from __future__ import annotations

import hashlib
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .assembly import probe_media, verify_video
from .budget import enforce_budget, estimate_budget
from .cinematography import framing_family, repair_practical_motion
from .config import Settings
from .consistency import repair_plan_consistency
from .db import Database
from .jobs import JobRunner
from .planner import DEMO_PROMPT
from .prompting import (
    compile_framing_retry_correction,
    compile_image_prompt,
    first_frame_image_direction,
    first_frame_target,
    prompt_hash,
    should_reset_reference_for_retry,
    should_use_set_plate_for_retry,
)
from .providers import (
    MockShowrunnerProvider,
    ProviderError,
    QwenCloudProvider,
    ShowrunnerProvider,
)
from .recorded_demo import (
    RECORDED_ANIMATIC_MODEL,
    RECORDED_DEMO_PROMPT,
    RECORDED_DEMO_TITLE,
    RECORDED_FINAL_FILENAME,
    RECORDED_FRAMES,
    create_recorded_demo_plan,
)
from .retry import attempt_seed
from .schemas import (
    GenerationConfirmation,
    JobStatus,
    ProductionPlan,
    ProductionStage,
    ProjectInput,
    ProjectPatch,
    ProviderImageRequest,
    ProviderVideoRequest,
    utc_now,
)


ACTIVE_JOB_STATUSES = {
    JobStatus.QUEUED,
    JobStatus.GENERATING,
    JobStatus.POLLING,
    JobStatus.DOWNLOADING,
    JobStatus.VERIFYING,
}


def _provider(settings: Settings) -> ShowrunnerProvider:
    if settings.provider == "qwen":
        return QwenCloudProvider(settings)
    return MockShowrunnerProvider(settings)


def create_app(
    settings: Settings | None = None, provider: ShowrunnerProvider | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.asset_root.mkdir(parents=True, exist_ok=True)
    settings.demo_asset_root.mkdir(parents=True, exist_ok=True)
    database = Database(settings.database_path)
    selected_provider = provider or _provider(settings)
    mock_runtime = isinstance(selected_provider, MockShowrunnerProvider)
    runner = JobRunner(database, selected_provider, settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        runner.recover_incomplete_jobs()
        yield
        runner.shutdown()

    app = FastAPI(
        title="VideoForge Showrunner",
        version="0.1.0",
        description="Agentic keyframe-first short-film production workspace",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.provider = selected_provider
    app.state.runner = runner

    app.mount("/assets", StaticFiles(directory=settings.asset_root), name="assets")
    if mock_runtime:
        app.mount(
            "/demo-assets",
            StaticFiles(directory=settings.demo_asset_root),
            name="demo-assets",
        )
    app.mount("/static", StaticFiles(directory=settings.web_root), name="static")

    @app.exception_handler(KeyError)
    async def not_found(_: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Resource not found: {exc.args[0]}", "code": "NOT_FOUND"},
        )

    @app.exception_handler(ValueError)
    async def invalid_state(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "code": "INVALID_STATE"},
        )

    @app.exception_handler(ProviderError)
    async def provider_failure(_: Request, exc: ProviderError) -> JSONResponse:
        return JSONResponse(
            status_code=503 if exc.retryable else 502,
            content={
                "detail": str(exc),
                "code": exc.code,
                "retryable": exc.retryable,
            },
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(settings.web_root / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "videoforge-showrunner",
            "provider": selected_provider.name,
            "database": "sqlite",
            "assetStorage": str(settings.asset_root),
        }

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return {
            "provider": selected_provider.name,
            "realMode": selected_provider.name == "qwen",
            "models": {
                "text": settings.qwen_text_model,
                "vision": settings.qwen_vision_model,
                "image": settings.qwen_image_model,
                "imageEdit": settings.qwen_image_edit_model,
                "video": settings.qwen_video_model,
            },
            "limits": {
                "maxShots": settings.max_shots,
                "defaultShots": settings.default_shots,
                "maxVideoDurationSeconds": settings.max_video_duration_seconds,
                "maxProjectRetries": settings.max_project_retries,
                "maxConcurrentImageTasks": settings.max_concurrent_image_tasks,
                "maxConcurrentVideoTasks": settings.max_concurrent_video_tasks,
            },
            "pricing": {
                "currency": "CNY",
                "image": settings.image_cost_cny,
                "videoSecond720p": settings.video_cost_cny_per_second_720p,
            },
        }

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectInput) -> dict[str, Any]:
        if body.shot_count > settings.max_shots:
            raise ValueError(f"shot count exceeds MAX_SHOTS={settings.max_shots}")
        return database.create_project(body, selected_provider.name)

    if mock_runtime:

        @app.post("/api/demo-project", status_code=201)
        def demo_project() -> dict[str, Any]:
            project = database.create_project(
                ProjectInput(
                    title="The Third Exposure",
                    storyPrompt=DEMO_PROMPT,
                    genre="Psychological horror",
                    visualStyle="Cinematic realism",
                    aspectRatio="16:9",
                    targetDurationSeconds=15,
                    shotCount=3,
                ),
                selected_provider.name,
            )
            return _create_plan(project["id"])

    @app.post("/api/recorded-demo", status_code=201)
    def recorded_demo() -> dict[str, Any]:
        """Open a complete, locally replayable snapshot of a live Qwen rehearsal.

        The endpoint performs local database and file operations only. It never invokes
        the active provider and cannot start a paid generation job.
        """

        image_sources = {
            frame.shot_id: settings.demo_asset_root / "shadow-rehearsal" / frame.filename
            for frame in RECORDED_FRAMES
        }
        video_sources = {
            frame.shot_id: (
                settings.demo_asset_root
                / "shadow-rehearsal"
                / "videos"
                / frame.video_filename
            )
            for frame in RECORDED_FRAMES
        }
        final_source = (
            settings.demo_asset_root / "shadow-rehearsal" / RECORDED_FINAL_FILENAME
        )
        missing = [
            str(source)
            for source in (*image_sources.values(), *video_sources.values(), final_source)
            if not source.is_file()
        ]
        if missing:
            raise FileNotFoundError(f"Recorded demo media is missing: {', '.join(missing)}")

        # The button is safe to use repeatedly during a presentation. Reopen the same
        # complete local snapshot instead of filling the database with duplicate demos.
        for candidate in database.list_projects():
            candidate_assets = [
                asset
                for shot in candidate["shots"]
                for asset in shot.get("assets", [])
            ]
            has_all_shot_media = all(
                any(asset["kind"] == kind for asset in shot.get("assets", []))
                for shot in candidate["shots"]
                for kind in ("image", "video")
            )
            current_media = candidate_assets + candidate.get("finalAssets", [])
            if (
                candidate["title"] == RECORDED_DEMO_TITLE
                and candidate["stage"] == ProductionStage.COMPLETED
                and len(candidate["shots"]) == len(RECORDED_FRAMES)
                and has_all_shot_media
                and candidate.get("finalAssets")
                and all(Path(asset["localPath"]).is_file() for asset in current_media)
            ):
                return candidate

        project = database.create_project(
            ProjectInput(
                title=RECORDED_DEMO_TITLE,
                storyPrompt=RECORDED_DEMO_PROMPT,
                genre="Psychological horror",
                visualStyle="Cinematic realism",
                aspectRatio="16:9",
                targetDurationSeconds=30,
                shotCount=6,
            ),
            "qwen",
        )
        project_id = project["id"]
        plan = create_recorded_demo_plan(project_id)
        budget = estimate_budget(plan, settings)
        database.save_plan(plan, budget.model_dump(by_alias=True))
        database.approve_plan(project_id)

        shot_by_id = {shot.id: shot for shot in plan.shots}
        image_output_dir = settings.asset_root / project_id / "images"
        video_output_dir = settings.asset_root / project_id / "videos"
        final_output_dir = settings.asset_root / project_id / "final"
        image_output_dir.mkdir(parents=True, exist_ok=True)
        video_output_dir.mkdir(parents=True, exist_ok=True)
        final_output_dir.mkdir(parents=True, exist_ok=True)
        completed_at = utc_now()
        for frame in RECORDED_FRAMES:
            image_source = image_sources[frame.shot_id]
            image_output = image_output_dir / frame.filename
            shutil.copy2(image_source, image_output)
            image_url = f"/assets/{project_id}/images/{frame.filename}"
            shot = shot_by_id[frame.shot_id]
            compiled_prompt_hash = prompt_hash(shot.image_prompt)
            image_job_id = database.create_job(
                project_id=project_id,
                shot_id=frame.shot_id,
                kind="image",
                provider="qwen",
                model=frame.model,
                payload={
                    "recordedRehearsal": True,
                    "source": "live-qwen-run-2026-07-17",
                    "recordedProviderPromptHash": frame.prompt_hash,
                },
                prompt=shot.image_prompt,
                prompt_hash=compiled_prompt_hash,
                negative_prompt=plan.visual_bible.negative_prompt,
                seed=frame.seed,
                parameters={"size": "1920*1080", "recorded": True},
                estimated_cost=settings.image_cost_cny,
                retry_count=frame.retry_count,
            )
            database.update_job(
                image_job_id,
                status=JobStatus.COMPLETED,
                started_at=completed_at,
                completed_at=completed_at,
                output_url=image_url,
                usage_json={"source": "recorded-live-qwen-rehearsal"},
            )
            database.create_asset(
                project_id=project_id,
                shot_id=frame.shot_id,
                kind="image",
                local_path=str(image_output),
                local_url=image_url,
                prompt_hash=frame.prompt_hash,
                sha256=hashlib.sha256(image_output.read_bytes()).hexdigest(),
                metadata={
                    "source": "recorded-live-qwen-rehearsal",
                    "model": frame.model,
                    "seed": frame.seed,
                    "winningRetry": frame.retry_count,
                    "recordedProviderPromptHash": frame.prompt_hash,
                },
            )
            database.approve_image(project_id, frame.shot_id)

            video_source = video_sources[frame.shot_id]
            video_output = video_output_dir / frame.video_filename
            shutil.copy2(video_source, video_output)
            video_url = f"/assets/{project_id}/videos/{frame.video_filename}"
            technical = verify_video(video_output, settings.ffprobe_binary)
            video_prompt_hash = prompt_hash(shot.motion_prompt)
            video_job_id = database.create_job(
                project_id=project_id,
                shot_id=frame.shot_id,
                kind="video",
                provider="local",
                model=RECORDED_ANIMATIC_MODEL,
                payload={
                    "recordedRehearsal": True,
                    "source": "local-editorial-animatic",
                    "basedOnLiveQwenKeyframe": True,
                },
                prompt=shot.motion_prompt,
                prompt_hash=video_prompt_hash,
                negative_prompt=plan.visual_bible.negative_prompt,
                seed=shot.video_seed,
                parameters={
                    "durationSeconds": shot.duration_seconds,
                    "resolution": "720P",
                    "motion": "subtle 2.5% editorial push-in",
                    "recorded": True,
                },
            )
            database.update_job(
                video_job_id,
                status=JobStatus.COMPLETED,
                started_at=completed_at,
                completed_at=completed_at,
                output_url=video_url,
                usage_json={"source": "local-editorial-animatic", "paidCalls": 0},
            )
            database.create_asset(
                project_id=project_id,
                shot_id=frame.shot_id,
                kind="video",
                local_path=str(video_output),
                local_url=video_url,
                prompt_hash=video_prompt_hash,
                sha256=hashlib.sha256(video_output.read_bytes()).hexdigest(),
                metadata={
                    "source": "local-editorial-animatic",
                    "model": RECORDED_ANIMATIC_MODEL,
                    "editorialOnly": True,
                    "basedOnLiveQwenKeyframe": True,
                    "technical": technical,
                },
            )

        final_output = final_output_dir / RECORDED_FINAL_FILENAME
        shutil.copy2(final_source, final_output)
        final_url = f"/assets/{project_id}/final/{RECORDED_FINAL_FILENAME}"
        assembly_prompt = (
            "Concatenate the six five-second editorial animatic clips in shot order."
        )
        assembly_job_id = database.create_job(
            project_id=project_id,
            shot_id=None,
            kind="assembly",
            provider="local",
            model="ffmpeg",
            payload={
                "recordedRehearsal": True,
                "source": "local-editorial-animatic",
                "clipCount": len(RECORDED_FRAMES),
            },
            prompt=assembly_prompt,
            prompt_hash=prompt_hash(assembly_prompt),
            parameters={"resolution": "1280x720", "fps": 30, "audio": False},
        )
        database.update_job(
            assembly_job_id,
            status=JobStatus.COMPLETED,
            started_at=completed_at,
            completed_at=completed_at,
            output_url=final_url,
            usage_json={"source": "local-ffmpeg-assembly", "paidCalls": 0},
        )
        database.create_asset(
            project_id=project_id,
            shot_id=None,
            kind="final",
            local_path=str(final_output),
            local_url=final_url,
            prompt_hash=prompt_hash(assembly_prompt),
            sha256=hashlib.sha256(final_output.read_bytes()).hexdigest(),
            metadata={
                "source": "local-editorial-animatic",
                "model": "ffmpeg",
                "editorialOnly": True,
                "clipCount": len(RECORDED_FRAMES),
                "probe": probe_media(final_output, settings.ffprobe_binary),
            },
        )

        database.set_stage(project_id, ProductionStage.COMPLETED, force=True)
        return database.get_project(project_id)

    @app.get("/api/projects")
    def list_projects() -> list[dict[str, Any]]:
        return database.list_projects()

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        return database.get_project(project_id)

    @app.patch("/api/projects/{project_id}")
    def patch_project(project_id: str, body: ProjectPatch) -> dict[str, Any]:
        values = body.model_dump(exclude_none=True)
        return database.update_project(project_id, values)

    def _create_plan(project_id: str) -> dict[str, Any]:
        project = database.get_project(project_id)
        if any(job["status"] in ACTIVE_JOB_STATUSES for job in project["jobs"]):
            raise ValueError("Cannot re-plan while generation jobs are active")
        database.set_stage(project_id, ProductionStage.PLANNING)
        try:
            plan = selected_provider.create_production_plan(
                project_id, database.project_input(project_id)
            )
            plan = repair_practical_motion(plan)
            plan, report = repair_plan_consistency(plan)
            enforce_budget(plan, settings)
            budget = estimate_budget(plan, settings)
            database.save_plan(plan, budget.model_dump(by_alias=True))
            database.add_consistency_report(
                project_id, "preflight", report.model_dump(by_alias=True)
            )
            database.record_provider_request(
                project_id=project_id,
                job_id=None,
                provider=selected_provider.name,
                model=settings.qwen_text_model if selected_provider.name == "qwen" else "mock-planner",
                request_data=database.project_input(project_id).model_dump(by_alias=True),
                response_data=plan.model_dump(by_alias=True),
                status_code=200,
            )
            database.set_stage(project_id, ProductionStage.PLAN_READY)
            return database.get_project(project_id)
        except Exception as exc:
            database.update_project(project_id, {"error_message": str(exc)})
            database.set_stage(project_id, ProductionStage.FAILED, force=True)
            raise

    @app.post("/api/projects/{project_id}/plan")
    def create_plan(project_id: str) -> dict[str, Any]:
        return _create_plan(project_id)

    @app.patch("/api/projects/{project_id}/plan")
    def patch_plan(project_id: str, body: ProductionPlan) -> dict[str, Any]:
        if body.project_id != project_id:
            raise ValueError("production plan projectId does not match route project ID")
        repaired, report = repair_plan_consistency(repair_practical_motion(body))
        enforce_budget(repaired, settings)
        budget = estimate_budget(repaired, settings)
        database.save_plan(repaired, budget.model_dump(by_alias=True))
        database.add_consistency_report(
            project_id, "preflight-edit", report.model_dump(by_alias=True)
        )
        database.set_stage(project_id, ProductionStage.PLAN_READY, force=True)
        return database.get_project(project_id)

    @app.post("/api/projects/{project_id}/plan/approve")
    def approve_plan(project_id: str) -> dict[str, Any]:
        project = database.get_project(project_id)
        if project["stage"] != ProductionStage.PLAN_READY:
            raise ValueError("The plan can only be approved from PLAN_READY")
        database.approve_plan(project_id)
        return database.get_project(project_id)

    def _require_paid_confirmation(body: GenerationConfirmation) -> None:
        if selected_provider.name == "qwen" and not body.confirm_paid_calls:
            raise HTTPException(
                status_code=402,
                detail=(
                    "This action starts paid Qwen Cloud media generation. Set "
                    "confirmPaidCalls=true after explicit user confirmation."
                ),
            )

    def _reference_master(project: dict[str, Any]) -> dict[str, Any]:
        return next(
            (
                shot
                for shot in project["shots"]
                if framing_family(shot["framing"]) == "wide"
            ),
            project["shots"][0],
        )

    def _image_job(
        project: dict[str, Any],
        shot: dict[str, Any],
        retry: int = 0,
        *,
        reference_shot_id: str | None = None,
        reference_job_id: str | None = None,
        reference_image_url: str | None = None,
        reference_image_path: str | None = None,
        retry_error_code: str | None = None,
        retry_error_message: str | None = None,
        continuity_reference_mode: str | None = None,
    ) -> str:
        plan = repair_practical_motion(ProductionPlan.model_validate(project["plan"]))
        planned_shot = next(item for item in plan.shots if item.id == shot["id"])
        prompt = compile_image_prompt(plan.visual_bible, planned_shot)
        framing_failure_codes = {
            "FRAMING_VALIDATION_FAILED",
            # Compatibility with jobs created before framing codes were preserved.
            "CROP",
            "CROPPING",
        }
        if (
            retry_error_code in framing_failure_codes
            and retry_error_message
        ):
            prompt += "\n" + compile_framing_retry_correction(
                planned_shot, retry_error_message
            )
        request = ProviderImageRequest(
            project_id=project["id"],
            shot_id=shot["id"],
            prompt=prompt,
            negative_prompt=plan.visual_bible.negative_prompt,
            seed=attempt_seed(shot["imageSeed"], retry),
            size="1920*1080",
            reference_shot_id=reference_shot_id,
            reference_job_id=reference_job_id,
            reference_image_url=reference_image_url,
            reference_image_path=reference_image_path,
            continuity_reference_mode=continuity_reference_mode,
            framing=planned_shot.framing,
            subject_position=planned_shot.subject_position,
            framing_target=first_frame_target(planned_shot),
            image_delta=first_frame_image_direction(planned_shot),
        )
        return database.create_job(
            project_id=project["id"],
            shot_id=shot["id"],
            kind="image",
            provider=selected_provider.name,
            model=(
                settings.qwen_image_edit_model
                if selected_provider.name == "qwen"
                and (reference_job_id or reference_image_url)
                else settings.qwen_image_model
            ),
            payload=request.model_dump(),
            prompt=request.prompt,
            prompt_hash=prompt_hash(request.prompt),
            negative_prompt=request.negative_prompt,
            seed=request.seed,
            parameters={
                "size": request.size,
                "prompt_extend": False,
                "n": 1,
                "referenceShotId": reference_shot_id,
                "baseSeed": shot["imageSeed"],
                "attemptSeed": request.seed,
                "retryReasonCode": retry_error_code,
                "correctiveFramingRetry": retry_error_code in framing_failure_codes,
                "continuityReferenceMode": continuity_reference_mode
                or (
                    "master-image"
                    if reference_job_id or reference_image_url
                    else "none"
                ),
            },
            estimated_cost=settings.image_cost_cny,
            retry_count=retry,
        )

    @app.post("/api/projects/{project_id}/storyboard", status_code=202)
    def generate_storyboard(
        project_id: str, body: GenerationConfirmation = Body(default_factory=GenerationConfirmation)
    ) -> dict[str, Any]:
        _require_paid_confirmation(body)
        project = database.get_project(project_id)
        if not project["planApproved"]:
            raise ValueError("Approve the production plan before generating storyboard images")
        active_images = [
            job
            for job in project["jobs"]
            if job["kind"] == "image" and job["status"] in ACTIVE_JOB_STATUSES
        ]
        if active_images:
            raise ValueError("Storyboard generation is already in progress")
        database.set_stage(project_id, ProductionStage.STORYBOARD_GENERATING)
        if selected_provider.name == "qwen":
            master = _reference_master(project)
            master_job_id = _image_job(project, master)
            job_ids = [master_job_id]
            for shot in project["shots"]:
                if shot["id"] == master["id"]:
                    continue
                job_ids.append(
                    _image_job(
                        project,
                        shot,
                        reference_shot_id=master["id"],
                        reference_job_id=master_job_id,
                    )
                )
        else:
            job_ids = [_image_job(project, shot) for shot in project["shots"]]
        for job_id in job_ids:
            runner.enqueue(job_id)
        return {"projectId": project_id, "jobIds": job_ids, "status": "accepted"}

    def _shot(project: dict[str, Any], shot_id: str) -> dict[str, Any]:
        shot = next((item for item in project["shots"] if item["id"] == shot_id), None)
        if not shot:
            raise KeyError(shot_id)
        return shot

    @app.post("/api/shots/{shot_id}/image/regenerate", status_code=202)
    def regenerate_image(
        shot_id: str,
        project_id: str,
        body: GenerationConfirmation = Body(default_factory=GenerationConfirmation),
    ) -> dict[str, Any]:
        _require_paid_confirmation(body)
        project = database.get_project(project_id)
        shot = _shot(project, shot_id)
        attempts = [
            job
            for job in project["jobs"]
            if job["kind"] == "image" and job["shotId"] == shot_id
        ]
        if any(job["status"] in ACTIVE_JOB_STATUSES for job in attempts):
            raise ValueError(f"{shot_id} already has an image job in the queue")
        retries = max((job["retryCount"] for job in attempts), default=-1) + 1
        if retries > settings.max_project_retries:
            raise ValueError(
                f"{shot_id} reached MAX_PROJECT_RETRIES={settings.max_project_retries}"
            )
        database.set_stage(project_id, ProductionStage.STORYBOARD_GENERATING)
        master = _reference_master(project)
        plan = repair_practical_motion(ProductionPlan.model_validate(project["plan"]))
        planned_shot = next(item for item in plan.shots if item.id == shot_id)
        previous_error_code = attempts[-1]["errorCode"] if attempts else None
        reset_reference = should_reset_reference_for_retry(
            planned_shot, retries, previous_error_code
        )
        use_set_plate = should_use_set_plate_for_retry(
            planned_shot, retries, previous_error_code
        )
        reference_url = None
        reference_path = None
        reference_shot_id = None
        if (
            selected_provider.name == "qwen"
            and shot["id"] != master["id"]
            and not reset_reference
        ):
            reference = database.latest_asset(project_id, master["id"], "image")
            if not reference or not reference["remoteUrl"]:
                raise ValueError("The continuity master must be regenerated first")
            reference_url = reference["remoteUrl"]
            reference_path = reference["localPath"]
            reference_shot_id = master["id"]
        job_id = _image_job(
            project,
            shot,
            retries,
            reference_shot_id=reference_shot_id,
            reference_image_url=reference_url,
            reference_image_path=reference_path,
            retry_error_code=previous_error_code,
            retry_error_message=attempts[-1]["errorMessage"] if attempts else None,
            continuity_reference_mode=(
                "bible-only-composition-reset"
                if reset_reference
                else ("set-plate-composition-reset" if use_set_plate else None)
            ),
        )
        runner.enqueue(job_id)
        return {"projectId": project_id, "jobId": job_id, "status": "accepted"}

    @app.post("/api/shots/{shot_id}/image/approve")
    def approve_image(shot_id: str, project_id: str) -> dict[str, Any]:
        project = database.get_project(project_id)
        _shot(project, shot_id)
        if not database.latest_asset(project_id, shot_id, "image"):
            raise ValueError(f"{shot_id} has no generated keyframe to approve")
        database.approve_image(project_id, shot_id, True)
        return database.get_project(project_id)

    @app.post("/api/jobs/{job_id}/image/reframe")
    def reframe_failed_image(job_id: str) -> dict[str, Any]:
        return runner.reprocess_failed_image(job_id)

    def _video_job(project: dict[str, Any], shot: dict[str, Any], retry: int = 0) -> str:
        plan = ProductionPlan.model_validate(project["plan"])
        image = database.latest_asset(project["id"], shot["id"], "image")
        if not image:
            raise ValueError(f"{shot['id']} has no approved image")
        # Send the exact locally reviewed frame. Qwen-hosted source URLs can expire, and a
        # visibility-safe crop must not silently revert to the uncropped cloud source.
        first_frame = image["localPath"]
        request = ProviderVideoRequest(
            project_id=project["id"],
            shot_id=shot["id"],
            first_frame_url=first_frame,
            prompt=shot["motionPrompt"],
            negative_prompt=plan.visual_bible.negative_prompt,
            seed=shot["videoSeed"],
            duration_seconds=shot["durationSeconds"],
            resolution="720P",
        )
        return database.create_job(
            project_id=project["id"],
            shot_id=shot["id"],
            kind="video",
            provider=selected_provider.name,
            model=settings.qwen_video_model,
            payload=request.model_dump(),
            prompt=request.prompt,
            prompt_hash=prompt_hash(request.prompt),
            negative_prompt=request.negative_prompt,
            seed=request.seed,
            parameters={
                "duration": request.duration_seconds,
                "resolution": request.resolution,
                "prompt_extend": False,
            },
            estimated_cost=(
                request.duration_seconds * settings.video_cost_cny_per_second_720p
            ),
            retry_count=retry,
        )

    @app.post("/api/projects/{project_id}/videos", status_code=202)
    def generate_videos(
        project_id: str, body: GenerationConfirmation = Body(default_factory=GenerationConfirmation)
    ) -> dict[str, Any]:
        _require_paid_confirmation(body)
        project = database.get_project(project_id)
        if not database.all_images_approved(project_id):
            raise ValueError("Approve every storyboard image before generating videos")
        active = [
            job
            for job in project["jobs"]
            if job["kind"] == "video" and job["status"] in ACTIVE_JOB_STATUSES
        ]
        if active:
            raise ValueError("Video generation is already in progress")
        database.set_stage(project_id, ProductionStage.VIDEO_GENERATING)
        job_ids = [_video_job(project, shot) for shot in project["shots"]]
        for job_id in job_ids:
            runner.enqueue(job_id)
        return {"projectId": project_id, "jobIds": job_ids, "status": "accepted"}

    @app.post("/api/shots/{shot_id}/video/retry", status_code=202)
    def retry_video(
        shot_id: str,
        project_id: str,
        body: GenerationConfirmation = Body(default_factory=GenerationConfirmation),
    ) -> dict[str, Any]:
        _require_paid_confirmation(body)
        project = database.get_project(project_id)
        shot = _shot(project, shot_id)
        attempts = [
            job
            for job in project["jobs"]
            if job["kind"] == "video" and job["shotId"] == shot_id
        ]
        if not attempts or attempts[-1]["status"] not in {
            JobStatus.FAILED,
            JobStatus.COMPLETED,
        }:
            raise ValueError("Only a failed or completed video generation can be retried")
        retries = attempts[-1]["retryCount"] + 1
        if retries > settings.max_project_retries:
            raise ValueError(
                f"{shot_id} reached MAX_PROJECT_RETRIES={settings.max_project_retries}"
            )
        database.set_stage(project_id, ProductionStage.VIDEO_GENERATING)
        job_id = _video_job(project, shot, retries)
        runner.enqueue(job_id)
        return {"projectId": project_id, "jobId": job_id, "status": "accepted"}

    @app.post("/api/projects/{project_id}/consistency-check")
    def consistency_check(project_id: str) -> dict[str, Any]:
        project = database.get_project(project_id)
        plan = ProductionPlan.model_validate(project["plan"])
        paths = []
        for shot in project["shots"]:
            image = database.latest_asset(project_id, shot["id"], "image")
            if not image:
                raise ValueError("Generate all storyboard images before consistency inspection")
            paths.append(Path(image["localPath"]))
        report = selected_provider.inspect_storyboard(paths, plan.visual_bible, plan)
        database.add_consistency_report(
            project_id, "storyboard", report.model_dump(by_alias=True)
        )
        return report.model_dump(by_alias=True)

    @app.post("/api/projects/{project_id}/assemble", status_code=202)
    def assemble(project_id: str) -> dict[str, Any]:
        project = database.get_project(project_id)
        clip_paths = []
        for shot in project["shots"]:
            video = database.latest_asset(project_id, shot["id"], "video")
            if not video:
                raise ValueError(
                    "All individual shots must be complete before final assembly"
                )
            clip_paths.append(video["localPath"])
        database.set_stage(project_id, ProductionStage.ASSEMBLING)
        job_id = database.create_job(
            project_id=project_id,
            shot_id=None,
            kind="assembly",
            provider="local-ffmpeg",
            model="ffmpeg",
            payload={"clipPaths": clip_paths},
            parameters={"resolution": "1280x720", "fps": 30, "audio": False},
        )
        runner.enqueue(job_id)
        return {"projectId": project_id, "jobId": job_id, "status": "accepted"}

    @app.get("/api/projects/{project_id}/jobs")
    def project_jobs(project_id: str) -> list[dict[str, Any]]:
        database.get_project(project_id)
        return database.jobs_for_project(project_id)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return database.get_job(job_id)

    return app


app = create_app()
