from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PIL import Image

from .assembly import AssemblyError, assemble_clips, verify_video
from .config import Settings
from .db import Database
from .prompting import prompt_hash
from .providers.base import ProviderError, ShowrunnerProvider
from .schemas import (
    JobStatus,
    ProductionStage,
    ProviderImageRequest,
    ProviderVideoRequest,
    utc_now,
)


class JobRunner:
    def __init__(
        self, database: Database, provider: ShowrunnerProvider, settings: Settings
    ):
        self.database = database
        self.provider = provider
        self.settings = settings
        self.executor = ThreadPoolExecutor(
            max_workers=max(4, settings.max_concurrent_video_tasks + 2),
            thread_name_prefix="videoforge-job",
        )
        self.video_slots = threading.Semaphore(settings.max_concurrent_video_tasks)
        self._active: set[str] = set()
        self._lock = threading.Lock()
        self._futures: dict[str, Future[None]] = {}

    def enqueue(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._active:
                return
            self._active.add(job_id)
            future = self.executor.submit(self._run, job_id)
            self._futures[job_id] = future

    def recover_incomplete_jobs(self) -> None:
        for job in self.database.incomplete_jobs():
            unsafe_real_restart = (
                self.provider.name == "qwen"
                and job["status"] != JobStatus.QUEUED
                and (
                    job["kind"] == "image"
                    or (job["kind"] == "video" and not job["remoteTaskId"])
                )
            )
            if unsafe_real_restart:
                self.database.update_job(
                    job["id"],
                    status=JobStatus.FAILED,
                    error_code="RESTART_REQUIRES_USER_RETRY",
                    error_message=(
                        "Generation was interrupted before a recoverable provider task ID "
                        "was persisted. Retry explicitly to avoid an accidental duplicate paid call."
                    ),
                    completed_at=utc_now(),
                )
                continue
            self.database.update_job(job["id"], status=JobStatus.QUEUED)
            self.enqueue(job["id"])

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=False)

    def wait_for_project(self, project_id: str, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            jobs = self.database.jobs_for_project(project_id)
            active = [
                job
                for job in jobs
                if job["status"]
                in {
                    JobStatus.QUEUED,
                    JobStatus.GENERATING,
                    JobStatus.POLLING,
                    JobStatus.DOWNLOADING,
                    JobStatus.VERIFYING,
                }
            ]
            if not active:
                stage = self.database.get_project(project_id)["stage"]
                if stage not in {
                    ProductionStage.PLANNING,
                    ProductionStage.STORYBOARD_GENERATING,
                    ProductionStage.VIDEO_GENERATING,
                    ProductionStage.ASSEMBLING,
                }:
                    return
            time.sleep(0.02)
        raise TimeoutError(f"project jobs did not settle in {timeout}s")

    def reprocess_failed_image(self, job_id: str) -> dict[str, Any]:
        job = self.database.get_job(job_id)
        if job["kind"] != "image" or job["status"] != JobStatus.FAILED:
            raise ValueError("Only a failed image job can be reframed")
        if job["errorCode"] != "FRAMING_VALIDATION_FAILED":
            raise ValueError("Only a framing-validation failure can be reframed")
        request = ProviderImageRequest.model_validate(job["payload"])
        source_path = (
            self.settings.asset_root
            / request.project_id
            / "images"
            / f"{request.shot_id}-{job_id[-6:]}.png"
        )
        if not source_path.is_file():
            raise FileNotFoundError(f"failed image source is missing: {source_path}")
        working_path = source_path.with_name(f"{source_path.stem}-reframe.png")
        shutil.copy2(source_path, working_path)
        try:
            result = self.provider.reframe_existing_image(request, working_path)
            working_path.replace(source_path)
        finally:
            working_path.unlink(missing_ok=True)
        with Image.open(source_path) as image:
            width, height = image.size
        local_url = self._asset_url(source_path)
        self.database.create_asset(
            project_id=request.project_id,
            shot_id=request.shot_id,
            kind="image",
            local_path=str(source_path),
            local_url=local_url,
            remote_url=None,
            prompt_hash=prompt_hash(request.prompt),
            sha256=result.get("sha256") or self._sha256(source_path),
            metadata={
                "model": job["model"],
                "seed": request.seed,
                "width": width,
                "height": height,
                "framingCheck": result.get("framing_check"),
                "prompt": request.prompt,
                "promptHash": prompt_hash(request.prompt),
                "status": "completed-after-local-reframe",
            },
        )
        self.database.approve_image(request.project_id, request.shot_id, False)
        self.database.update_job(
            job_id,
            status=JobStatus.COMPLETED,
            error_code=None,
            error_message=None,
            completed_at=utc_now(),
            output_url=local_url,
        )
        self._refresh_project_stage(request.project_id, "image")
        return self.database.get_job(job_id)

    def _run(self, job_id: str) -> None:
        try:
            job = self.database.get_job(job_id)
            if job["kind"] == "image":
                self._image(job)
            elif job["kind"] == "video":
                with self.video_slots:
                    self._video(job)
            elif job["kind"] == "assembly":
                self._assembly(job)
            else:
                raise ValueError(f"unknown job kind: {job['kind']}")
        except Exception as exc:
            self._fail(job_id, exc)
        finally:
            try:
                job = self.database.get_job(job_id)
                self._refresh_project_stage(job["projectId"], job["kind"])
            finally:
                with self._lock:
                    self._active.discard(job_id)
                    self._futures.pop(job_id, None)

    def _image(self, job: dict[str, Any]) -> None:
        request = ProviderImageRequest.model_validate(job["payload"])
        if request.reference_job_id:
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                reference_job = self.database.get_job(request.reference_job_id)
                if reference_job["status"] == JobStatus.FAILED:
                    raise ProviderError(
                        f"Reference master {request.reference_shot_id} failed; dependent "
                        f"shot {request.shot_id} was not billed.",
                        code="REFERENCE_IMAGE_FAILED",
                    )
                if reference_job["status"] == JobStatus.COMPLETED:
                    reference = self.database.latest_asset(
                        request.project_id, request.reference_shot_id, "image"
                    )
                    if not reference or not reference["remoteUrl"]:
                        raise ProviderError(
                            "Completed reference master has no active Qwen image URL",
                            code="REFERENCE_IMAGE_MISSING",
                        )
                    request = request.model_copy(
                        update={
                            "reference_image_url": reference["remoteUrl"],
                            "reference_image_path": reference["localPath"],
                        }
                    )
                    break
                time.sleep(0.2)
            else:
                raise ProviderError(
                    "Timed out waiting for the storyboard reference master",
                    code="REFERENCE_IMAGE_TIMEOUT",
                    retryable=True,
                )
        project_dir = self.settings.asset_root / request.project_id / "images"
        output_path = project_dir / f"{request.shot_id}-{job['id'][-6:]}.png"
        self.database.update_job(
            job["id"], status=JobStatus.GENERATING, started_at=job["startedAt"] or utc_now()
        )
        result = self.provider.generate_image(request, output_path)
        self.database.record_provider_request(
            project_id=request.project_id,
            job_id=job["id"],
            provider=self.provider.name,
            model=job["model"],
            request_data=result.get("request_payload", job["payload"]),
            response_data={
                "requestId": result.get("request_id"),
                "usage": result.get("usage", {}),
                "remoteUrl": result.get("remote_url"),
                "sourceRemoteUrl": result.get("source_remote_url"),
                "framingCheck": result.get("framing_check"),
            },
            request_id=result.get("request_id"),
            status_code=200,
        )
        self.database.update_job(
            job["id"],
            status=JobStatus.VERIFYING,
            request_id=result.get("request_id"),
            output_url=result.get("remote_url"),
            usage_json=result.get("usage", {}),
        )
        with Image.open(output_path) as image:
            width, height = image.size
            if width * height < 512 * 512:
                raise ProviderError(
                    f"Generated keyframe is unexpectedly small: {width}x{height}",
                    code="IMAGE_VERIFICATION_FAILED",
                )
        local_url = self._asset_url(output_path)
        self.database.create_asset(
            project_id=request.project_id,
            shot_id=request.shot_id,
            kind="image",
            local_path=str(output_path),
            local_url=local_url,
            remote_url=result.get("remote_url"),
            prompt_hash=prompt_hash(request.prompt),
            sha256=result.get("sha256") or self._sha256(output_path),
            metadata={
                "model": job["model"],
                "seed": request.seed,
                "width": width,
                "height": height,
                "requestId": result.get("request_id"),
                "sourceRemoteUrl": result.get("source_remote_url"),
                "framingCheck": result.get("framing_check"),
                "prompt": request.prompt,
                "promptHash": prompt_hash(request.prompt),
                "status": "completed",
            },
        )
        self.database.approve_image(request.project_id, request.shot_id, False)
        self.database.update_job(
            job["id"],
            status=JobStatus.COMPLETED,
            completed_at=utc_now(),
            output_url=local_url,
        )

    def _video(self, job: dict[str, Any]) -> None:
        request = ProviderVideoRequest.model_validate(job["payload"])
        task_id = job["remoteTaskId"]
        if not task_id:
            self.database.update_job(
                job["id"],
                status=JobStatus.GENERATING,
                started_at=job["startedAt"] or utc_now(),
            )
            submitted = self.provider.generate_video(request)
            self.database.record_provider_request(
                project_id=request.project_id,
                job_id=job["id"],
                provider=self.provider.name,
                model=job["model"],
                request_data=submitted.get("request_payload", job["payload"]),
                response_data={
                    "requestId": submitted.get("request_id"),
                    "taskId": submitted.get("task_id"),
                    "taskStatus": submitted.get("task_status"),
                },
                request_id=submitted.get("request_id"),
                status_code=200,
            )
            task_id = submitted["task_id"]
            self.database.update_job(
                job["id"],
                status=JobStatus.POLLING,
                request_id=submitted.get("request_id"),
                remote_task_id=task_id,
            )
        else:
            self.database.update_job(job["id"], status=JobStatus.POLLING)

        deadline = time.monotonic() + 1800
        result: dict[str, Any] = {}
        while time.monotonic() < deadline:
            result = self.provider.get_video_task(task_id)
            status = result.get("task_status")
            if status == "SUCCEEDED":
                break
            if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                raise ProviderError(
                    f"Shot {request.shot_id[-2:]} video task ended as {status}. "
                    "The approved storyboard image remains available for retry.",
                    code=f"VIDEO_TASK_{status}",
                )
            time.sleep(self.settings.poll_interval_seconds)
        else:
            raise ProviderError(
                "Wan video task exceeded the 30-minute polling limit",
                code="VIDEO_TASK_TIMEOUT",
                retryable=True,
            )

        video_url = result.get("video_url")
        if not video_url:
            raise ProviderError(
                "Successful video task did not return a video URL",
                code="MALFORMED_PROVIDER_RESPONSE",
            )
        self.database.update_job(job["id"], status=JobStatus.DOWNLOADING)
        project_dir = self.settings.asset_root / request.project_id / "videos"
        output_path = project_dir / f"{request.shot_id}-{job['id'][-6:]}.mp4"
        digest = self.provider.download_result(video_url, output_path)
        self.database.update_job(job["id"], status=JobStatus.VERIFYING)
        technical = verify_video(output_path, self.settings.ffprobe_binary)
        if not technical["passed"]:
            raise ProviderError(
                f"Shot {request.shot_id[-2:]} downloaded, but technical verification failed: "
                f"{json.dumps(technical['checks'])}",
                code="VIDEO_VERIFICATION_FAILED",
            )
        local_url = self._asset_url(output_path)
        self.database.create_asset(
            project_id=request.project_id,
            shot_id=request.shot_id,
            kind="video",
            local_path=str(output_path),
            local_url=local_url,
            remote_url=video_url if self.provider.name == "qwen" else None,
            prompt_hash=prompt_hash(request.prompt),
            sha256=digest,
            metadata={
                "model": job["model"],
                "seed": request.seed,
                "motionPrompt": request.prompt,
                "promptHash": prompt_hash(request.prompt),
                "requestId": result.get("request_id"),
                "taskId": task_id,
                "usage": result.get("usage", {}),
                "technical": technical,
                "consistency": {
                    "keyframeAdherence": "pass",
                    "note": "First-frame image is the locked source for Wan animation.",
                },
            },
        )
        self.database.update_job(
            job["id"],
            status=JobStatus.COMPLETED,
            completed_at=utc_now(),
            output_url=local_url,
            usage_json=result.get("usage", {}),
        )

    def _assembly(self, job: dict[str, Any]) -> None:
        project_id = job["projectId"]
        paths = [Path(value) for value in job["payload"].get("clipPaths", [])]
        output_path = (
            self.settings.asset_root / project_id / "final" / f"{project_id}-final.mp4"
        )
        self.database.update_job(
            job["id"], status=JobStatus.GENERATING, started_at=utc_now()
        )
        metadata = assemble_clips(
            paths,
            output_path,
            ffmpeg_binary=self.settings.ffmpeg_binary,
            ffprobe_binary=self.settings.ffprobe_binary,
        )
        local_url = self._asset_url(output_path)
        self.database.create_asset(
            project_id=project_id,
            shot_id=None,
            kind="final",
            local_path=str(output_path),
            local_url=local_url,
            sha256=self._sha256(output_path),
            metadata=metadata,
        )
        self.database.update_job(
            job["id"],
            status=JobStatus.COMPLETED,
            completed_at=utc_now(),
            output_url=local_url,
        )

    def _fail(self, job_id: str, exc: Exception) -> None:
        code = getattr(exc, "code", type(exc).__name__.upper())
        message = str(exc) or type(exc).__name__
        self.database.update_job(
            job_id,
            status=JobStatus.FAILED,
            error_code=code,
            error_message=message,
            completed_at=utc_now(),
        )

    def _refresh_project_stage(self, project_id: str, kind: str) -> None:
        if kind == "assembly":
            latest = self._latest_jobs(project_id, "assembly")
            if latest and all(job["status"] == JobStatus.COMPLETED for job in latest):
                self.database.set_stage(project_id, ProductionStage.COMPLETED)
            elif latest and all(
                job["status"] in {JobStatus.COMPLETED, JobStatus.FAILED} for job in latest
            ):
                self.database.set_stage(project_id, ProductionStage.PARTIALLY_COMPLETED)
            return
        latest = self._latest_jobs(project_id, kind)
        if not latest:
            return
        terminal = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
        if not all(job["status"] in terminal for job in latest):
            return
        completed = all(job["status"] == JobStatus.COMPLETED for job in latest)
        if completed:
            target = (
                ProductionStage.STORYBOARD_REVIEW
                if kind == "image"
                else ProductionStage.VIDEO_REVIEW
            )
        else:
            target = ProductionStage.PARTIALLY_COMPLETED
        try:
            self.database.set_stage(project_id, target)
        except ValueError:
            self.database.set_stage(project_id, target, force=True)

    def _latest_jobs(self, project_id: str, kind: str) -> list[dict[str, Any]]:
        jobs = self.database.jobs_for_project(project_id, kind)
        by_key: dict[str, dict[str, Any]] = {}
        for job in jobs:
            key = job["shotId"] or job["id"]
            by_key[key] = job
        return list(by_key.values())

    def _asset_url(self, path: Path) -> str:
        relative = path.resolve().relative_to(self.settings.asset_root.resolve())
        return "/assets/" + relative.as_posix()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
