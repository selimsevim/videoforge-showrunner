from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from videoforge.app import create_app
from videoforge.budget import estimate_budget
from videoforge.config import ROOT, Settings
from videoforge.db import Database
from videoforge.jobs import JobRunner
from videoforge.planner import DEMO_PROMPT, create_mock_plan
from videoforge.prompting import prompt_hash
from videoforge.providers.base import ProviderError
from videoforge.providers.mock import MockShowrunnerProvider
from videoforge.schemas import ProjectInput, ProviderImageRequest

from .conftest import wait


def approve_plan_and_storyboard(client: TestClient, app, project: dict) -> dict:
    project_id = project["id"]
    assert client.post(f"/api/projects/{project_id}/plan/approve", json={}).status_code == 200
    assert client.post(f"/api/projects/{project_id}/storyboard", json={}).status_code == 202
    project = wait(app, project_id)
    assert project["stage"] == "STORYBOARD_REVIEW"
    assert all(shot["assets"] for shot in project["shots"])
    for shot in project["shots"]:
        response = client.post(
            f"/api/shots/{shot['id']}/image/approve?project_id={project_id}", json={}
        )
        assert response.status_code == 200
    return client.get(f"/api/projects/{project_id}").json()


def test_complete_mock_workflow_persists_and_assembles(client, app, demo_project) -> None:
    project = approve_plan_and_storyboard(client, app, demo_project)
    project_id = project["id"]
    response = client.post(f"/api/projects/{project_id}/videos", json={})
    assert response.status_code == 202
    project = wait(app, project_id)
    assert project["stage"] == "VIDEO_REVIEW"
    assert all(any(asset["kind"] == "video" for asset in shot["assets"]) for shot in project["shots"])
    response = client.post(f"/api/projects/{project_id}/assemble", json={})
    assert response.status_code == 202
    project = wait(app, project_id, 30)
    assert project["stage"] == "COMPLETED"
    assert project["finalAssets"][0]["localUrl"].endswith(".mp4")
    refreshed = client.get(f"/api/projects/{project_id}").json()
    assert refreshed["finalAssets"][0]["id"] == project["finalAssets"][0]["id"]


def test_mock_consistency_check_does_not_regenerate(client, app, demo_project) -> None:
    project = approve_plan_and_storyboard(client, app, demo_project)
    before_jobs = len(project["jobs"])
    response = client.post(f"/api/projects/{project['id']}/consistency-check", json={})
    assert response.status_code == 200
    assert response.json()["characterConsistencyScore"] == 0.91
    after = client.get(f"/api/projects/{project['id']}").json()
    assert len(after["jobs"]) == before_jobs


def test_partial_video_failure_and_independent_retry(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "db.sqlite",
        asset_root=tmp_path / "assets",
        demo_asset_root=ROOT / "public" / "demo-assets",
        mock_delay_seconds=0,
        poll_interval_seconds=0,
    )
    provider = MockShowrunnerProvider(settings, fail_video_shot="shot-02")
    app = create_app(settings, provider)
    with TestClient(app) as client:
        project = client.post("/api/demo-project", json={}).json()
        project = approve_plan_and_storyboard(client, app, project)
        client.post(f"/api/projects/{project['id']}/videos", json={})
        project = wait(app, project["id"])
        assert project["stage"] == "PARTIALLY_COMPLETED"
        failed = [job for job in project["jobs"] if job["kind"] == "video" and job["status"] == "FAILED"]
        assert failed[0]["shotId"] == "shot-02"
        assert "approved storyboard image remains saved" in failed[0]["errorMessage"]
        provider.fail_video_shot = None
        response = client.post(
            f"/api/shots/shot-02/video/retry?project_id={project['id']}", json={}
        )
        assert response.status_code == 202
        project = wait(app, project["id"])
        assert project["stage"] == "VIDEO_REVIEW"
        shot = next(item for item in project["shots"] if item["id"] == "shot-02")
        assert any(asset["kind"] == "video" for asset in shot["assets"])


def test_fatal_paid_account_error_cancels_unsubmitted_video_jobs(tmp_path: Path) -> None:
    class BillingBlockedProvider(MockShowrunnerProvider):
        name = "qwen"

        def __init__(self, settings):
            super().__init__(settings)
            self.video_calls = 0

        def generate_video(self, request):
            self.video_calls += 1
            raise ProviderError(
                "Free-tier-only mode blocks paid inference.",
                code="ALLOCATION_QUOTA_FREE_TIER_ONLY",
            )

    settings = Settings(
        database_path=tmp_path / "db.sqlite",
        asset_root=tmp_path / "assets",
        demo_asset_root=ROOT / "public" / "demo-assets",
        provider="qwen",
        mock_delay_seconds=0,
        poll_interval_seconds=0,
        max_concurrent_video_tasks=1,
    )
    provider = BillingBlockedProvider(settings)
    app = create_app(settings, provider)
    with TestClient(app) as client:
        project = client.post("/api/recorded-demo", json={}).json()
        response = client.post(
            f"/api/projects/{project['id']}/videos",
            json={"confirmPaidCalls": True},
        )
        assert response.status_code == 202
        project = wait(app, project["id"])
        video_jobs = [
            job
            for job in project["jobs"]
            if job["kind"] == "video"
            and not job["payload"].get("recordedRehearsal")
        ]
        assert provider.video_calls == 1
        assert sum(job["status"] == "FAILED" for job in video_jobs) == 1
        assert all(
            job["status"] in {"FAILED", "CANCELLED"} for job in video_jobs
        )


def test_assembly_failure_preserves_individual_videos(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "db.sqlite",
        asset_root=tmp_path / "assets",
        demo_asset_root=ROOT / "public" / "demo-assets",
        mock_delay_seconds=0,
        poll_interval_seconds=0,
        ffmpeg_binary="definitely-not-ffmpeg",
    )
    app = create_app(settings, MockShowrunnerProvider(settings))
    with TestClient(app) as client:
        project = client.post("/api/demo-project", json={}).json()
        project = approve_plan_and_storyboard(client, app, project)
        client.post(f"/api/projects/{project['id']}/videos", json={})
        project = wait(app, project["id"])
        client.post(f"/api/projects/{project['id']}/assemble", json={})
        project = wait(app, project["id"])
        assert project["stage"] == "PARTIALLY_COMPLETED"
        assert all(any(asset["kind"] == "video" for asset in shot["assets"]) for shot in project["shots"])
        assert not project["finalAssets"]


def test_paid_provider_requires_explicit_media_confirmation(tmp_path: Path) -> None:
    class PaidMock(MockShowrunnerProvider):
        name = "qwen"

    settings = Settings(
        database_path=tmp_path / "db.sqlite",
        asset_root=tmp_path / "assets",
        demo_asset_root=ROOT / "public" / "demo-assets",
        provider="qwen",
        mock_delay_seconds=0,
    )
    app = create_app(settings, PaidMock(settings))
    with TestClient(app) as client:
        project = client.post("/api/demo-project", json={}).json()
        client.post(f"/api/projects/{project['id']}/plan/approve", json={})
        rejected = client.post(f"/api/projects/{project['id']}/storyboard", json={})
        assert rejected.status_code == 402
        accepted = client.post(
            f"/api/projects/{project['id']}/storyboard",
            json={"confirmPaidCalls": True},
        )
        assert accepted.status_code == 202


def test_recorded_demo_is_instant_and_never_calls_paid_provider(tmp_path: Path) -> None:
    class NoCallPaidProvider(MockShowrunnerProvider):
        name = "qwen"

        def create_production_plan(self, project_id, project):
            raise AssertionError("recorded demo must not call the planning provider")

        def generate_image(self, request, output_path):
            raise AssertionError("recorded demo must not call the image provider")

        def generate_video(self, request):
            raise AssertionError("recorded demo must not call the video provider")

    settings = Settings(
        database_path=tmp_path / "db.sqlite",
        asset_root=tmp_path / "assets",
        demo_asset_root=ROOT / "public" / "demo-assets",
        provider="qwen",
        mock_delay_seconds=0,
    )
    app = create_app(settings, NoCallPaidProvider(settings))
    with TestClient(app) as client:
        response = client.post("/api/recorded-demo", json={})
        assert response.status_code == 201
        project = response.json()

        assert project["stage"] == "COMPLETED"
        assert project["provider"] == "qwen"
        assert project["planApproved"] is True
        assert len(project["shots"]) == 6
        assert len(project["jobs"]) == 13
        assert all(job["status"] == "COMPLETED" for job in project["jobs"])
        assert all(job["payload"]["recordedRehearsal"] is True for job in project["jobs"])
        assert all(job["promptHash"] == prompt_hash(job["prompt"]) for job in project["jobs"])
        image_jobs = [job for job in project["jobs"] if job["kind"] == "image"]
        video_jobs = [job for job in project["jobs"] if job["kind"] == "video"]
        assembly_jobs = [job for job in project["jobs"] if job["kind"] == "assembly"]
        assert len(image_jobs) == 6
        assert len(video_jobs) == 6
        assert len(assembly_jobs) == 1
        assert project["budget"]["imageCalls"] == 5
        handoff_job = next(job for job in image_jobs if job["shotId"] == "shot-02")
        assert handoff_job["provider"] == "local"
        assert handoff_job["model"] == "continuity-crop"
        assert handoff_job["estimatedCost"] is None
        assert handoff_job["payload"]["continuitySourceShotId"] == "shot-01"
        assert all(job["provider"] == "qwen" for job in video_jobs)
        assert all(job["model"] == "wan2.7-i2v" for job in video_jobs)
        assert all(job["estimatedCost"] is not None for job in video_jobs)
        assert assembly_jobs[0]["provider"] == "local"
        assert assembly_jobs[0]["estimatedCost"] is None
        assert all(
            job["payload"]["recordedProviderPromptHash"]
            == next(
                shot["assets"][0]["metadata"]["recordedProviderPromptHash"]
                for shot in project["shots"]
                if shot["id"] == job["shotId"]
            )
            for job in image_jobs
        )
        assert all("FRAME_VISIBILITY_CONTRACT" in shot["imagePrompt"] for shot in project["shots"])
        assert all("ACTION:" in shot["motionPrompt"] for shot in project["shots"])
        assert all(shot["imageApproved"] is True for shot in project["shots"])
        assert all(len(shot["assets"]) == 2 for shot in project["shots"])
        assert all(
            {asset["kind"] for asset in shot["assets"]} == {"image", "video"}
            for shot in project["shots"]
        )
        assert all(
            Path(asset["localPath"]).is_file()
            for shot in project["shots"]
            for asset in shot["assets"]
        )
        assert len(project["finalAssets"]) == 1
        assert Path(project["finalAssets"][0]["localPath"]).is_file()
        assert project["finalAssets"][0]["metadata"]["actualProviderClips"] is True
        handoff_asset = next(
            asset
            for shot in project["shots"]
            if shot["id"] == "shot-02"
            for asset in shot["assets"]
            if asset["kind"] == "image"
        )
        assert handoff_asset["metadata"]["derivedFromShotId"] == "shot-01"
        assert all(
            next(
                asset for asset in shot["assets"] if asset["kind"] == "video"
            )["metadata"]["actualProviderGeneration"]
            is True
            for shot in project["shots"]
        )

        reopened = client.post("/api/recorded-demo", json={})
        assert reopened.status_code == 201
        assert reopened.json()["id"] == project["id"]
        assert len(client.get("/api/projects").json()) == 1

        persisted = client.get(f"/api/projects/{project['id']}").json()
        assert persisted["title"] == "The Shadow — recorded Qwen rehearsal"
        assert [shot["imageSeed"] for shot in persisted["shots"]] == [
            1777431065,
            1777431065,
            1777954710,
            1777954710,
            1777535794,
            1777535794,
        ]


def test_health_and_config_never_expose_api_key(client, monkeypatch) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "secret-value")
    health = client.get("/api/health").json()
    config = client.get("/api/config").json()
    assert health["status"] == "ok"
    assert "secret-value" not in str(health)
    assert "secret-value" not in str(config)


def test_provider_failure_returns_structured_api_error(tmp_path: Path) -> None:
    class FailingPlanner(MockShowrunnerProvider):
        def create_production_plan(self, project_id, project):
            raise ProviderError(
                "The provider plan failed validation.",
                code="PLAN_VALIDATION_FAILED",
            )

    settings = Settings(
        database_path=tmp_path / "db.sqlite",
        asset_root=tmp_path / "assets",
        demo_asset_root=ROOT / "public" / "demo-assets",
        mock_delay_seconds=0,
    )
    app = create_app(settings, FailingPlanner(settings))
    with TestClient(app) as client:
        response = client.post("/api/demo-project", json={})
    assert response.status_code == 502
    assert response.json() == {
        "detail": "The provider plan failed validation.",
        "code": "PLAN_VALIDATION_FAILED",
        "retryable": False,
    }


def test_storyboard_image_calls_are_serialized(tmp_path: Path) -> None:
    class ConcurrencyProbe(MockShowrunnerProvider):
        def __init__(self, settings: Settings):
            super().__init__(settings)
            self.lock = threading.Lock()
            self.active = 0
            self.peak = 0

        def generate_image(self, request, output_path):
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            try:
                time.sleep(0.05)
                return super().generate_image(request, output_path)
            finally:
                with self.lock:
                    self.active -= 1

    settings = Settings(
        database_path=tmp_path / "db.sqlite",
        asset_root=tmp_path / "assets",
        demo_asset_root=ROOT / "public" / "demo-assets",
        mock_delay_seconds=0,
        max_concurrent_image_tasks=1,
    )
    provider = ConcurrencyProbe(settings)
    app = create_app(settings, provider)
    with TestClient(app) as client:
        project = client.post("/api/demo-project", json={}).json()
        client.post(f"/api/projects/{project['id']}/plan/approve", json={})
        response = client.post(f"/api/projects/{project['id']}/storyboard", json={})
        assert response.status_code == 202
        wait(app, project["id"])
    assert provider.peak == 1


def test_framing_failure_retry_gets_corrective_prompt(tmp_path: Path) -> None:
    class FramingFailureOnce(MockShowrunnerProvider):
        def __init__(self, settings: Settings):
            super().__init__(settings)
            self.failed = False

        def generate_image(self, request, output_path):
            if request.shot_id == "shot-02" and not self.failed:
                self.failed = True
                raise ProviderError(
                    "Generated shot-02 violates its close framing contract and cannot be "
                    "corrected by cropping: full person and room visible",
                    code="FRAMING_VALIDATION_FAILED",
                )
            return super().generate_image(request, output_path)

    settings = Settings(
        database_path=tmp_path / "db.sqlite",
        asset_root=tmp_path / "assets",
        demo_asset_root=ROOT / "public" / "demo-assets",
        mock_delay_seconds=0,
    )
    app = create_app(settings, FramingFailureOnce(settings))
    with TestClient(app) as client:
        project = client.post("/api/demo-project", json={}).json()
        project_id = project["id"]
        client.post(f"/api/projects/{project_id}/plan/approve", json={})
        client.post(f"/api/projects/{project_id}/storyboard", json={})
        project = wait(app, project_id)
        failed = [
            job
            for job in project["jobs"]
            if job["shotId"] == "shot-02" and job["status"] == "FAILED"
        ]
        assert failed[-1]["errorCode"] == "FRAMING_VALIDATION_FAILED"
        response = client.post(
            f"/api/shots/shot-02/image/regenerate?project_id={project_id}", json={}
        )
        assert response.status_code == 202
        project = wait(app, project_id)
        retries = [
            job
            for job in project["jobs"]
            if job["shotId"] == "shot-02" and job["retryCount"] == 1
        ]
        assert retries[-1]["status"] == "COMPLETED"
        assert "RETRY_CORRECTION" in retries[-1]["prompt"]
        assert retries[-1]["parameters"]["correctiveFramingRetry"] is True


def test_queued_job_is_recovered_after_runner_restart(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "db.sqlite",
        asset_root=tmp_path / "assets",
        demo_asset_root=ROOT / "public" / "demo-assets",
        mock_delay_seconds=0,
        poll_interval_seconds=0,
    )
    database = Database(settings.database_path)
    project = database.create_project(
        ProjectInput(title="Recovery", storyPrompt=DEMO_PROMPT), "mock"
    )
    plan = create_mock_plan(project["id"], database.project_input(project["id"]))
    database.save_plan(
        plan, estimate_budget(plan, settings).model_dump(by_alias=True)
    )
    shot = plan.shots[0]
    request = ProviderImageRequest(
        project_id=project["id"],
        shot_id=shot.id,
        prompt=shot.image_prompt,
        negative_prompt=plan.visual_bible.negative_prompt,
        seed=shot.image_seed,
    )
    job_id = database.create_job(
        project_id=project["id"],
        shot_id=shot.id,
        kind="image",
        provider="mock",
        model="qwen-image-2.0",
        payload=request.model_dump(),
    )
    runner = JobRunner(database, MockShowrunnerProvider(settings), settings)
    try:
        runner.recover_incomplete_jobs()
        runner.wait_for_project(project["id"])
        assert database.get_job(job_id)["status"] == "COMPLETED"
        assert database.latest_asset(project["id"], shot.id, "image") is not None
    finally:
        runner.shutdown()
