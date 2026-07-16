from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProductionStage(StrEnum):
    DRAFT = "DRAFT"
    PLANNING = "PLANNING"
    PLAN_READY = "PLAN_READY"
    STORYBOARD_GENERATING = "STORYBOARD_GENERATING"
    STORYBOARD_REVIEW = "STORYBOARD_REVIEW"
    VIDEO_GENERATING = "VIDEO_GENERATING"
    VIDEO_REVIEW = "VIDEO_REVIEW"
    ASSEMBLING = "ASSEMBLING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    CANCELLED = "CANCELLED"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    GENERATING = "GENERATING"
    POLLING = "POLLING"
    DOWNLOADING = "DOWNLOADING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ProjectInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1, max_length=120)
    story_prompt: str = Field(alias="storyPrompt", min_length=8, max_length=2000)
    genre: str = Field(default="Psychological horror", max_length=80)
    visual_style: str = Field(alias="visualStyle", default="Cinematic realism")
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = Field(
        alias="aspectRatio", default="16:9"
    )
    target_duration_seconds: int = Field(
        alias="targetDurationSeconds", default=15, ge=6, le=30
    )
    shot_count: int = Field(alias="shotCount", default=3, ge=1, le=6)


class Narrative(BaseModel):
    setup: str = Field(min_length=3, max_length=600)
    escalation: str = Field(min_length=3, max_length=600)
    resolution: str = Field(min_length=3, max_length=600)


class VisualBible(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    character_identity: str = Field(alias="characterIdentity", min_length=3)
    face_and_hair: str = Field(alias="faceAndHair", min_length=3)
    wardrobe: str = Field(min_length=3)
    important_prop: str = Field(alias="importantProp", min_length=3)
    environment: str = Field(min_length=3)
    time_of_day: str = Field(alias="timeOfDay", min_length=2)
    lighting: str = Field(min_length=3)
    palette: str = Field(min_length=3)
    camera_language: str = Field(alias="cameraLanguage", min_length=3)
    visual_style: str = Field(alias="visualStyle", min_length=3)
    negative_prompt: str = Field(alias="negativePrompt", min_length=3, max_length=500)


class ShotPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(pattern=r"^shot-\d{2}$")
    order: int = Field(ge=1, le=6)
    narrative_purpose: str = Field(alias="narrativePurpose", min_length=3)
    framing: str = Field(min_length=2)
    camera_angle: str = Field(alias="cameraAngle", min_length=2)
    subject_position: str = Field(alias="subjectPosition", min_length=2)
    primary_subject: str = Field(alias="primarySubject", default="")
    framing_reason: str = Field(alias="framingReason", default="")
    start_state: str = Field(alias="startState", default="")
    subject_action: str = Field(alias="subjectAction", min_length=3)
    end_state: str = Field(alias="endState", default="")
    environment_state: str = Field(alias="environmentState", min_length=3)
    environment_motion: str = Field(alias="environmentMotion", min_length=3)
    camera_motion: str = Field(alias="cameraMotion", min_length=3)
    prop_state: str = Field(alias="propState", min_length=3)
    image_delta: str = Field(alias="imageDelta", min_length=3)
    image_prompt: str = Field(alias="imagePrompt", min_length=3)
    motion_prompt: str = Field(alias="motionPrompt", min_length=3)
    duration_seconds: int = Field(alias="durationSeconds", ge=2, le=5)
    image_seed: int = Field(alias="imageSeed", ge=0, le=2**31 - 1)
    video_seed: int = Field(alias="videoSeed", ge=0, le=2**31 - 1)


class ProductionPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(alias="projectId", min_length=8)
    title: str = Field(min_length=1, max_length=120)
    logline: str = Field(min_length=8, max_length=500)
    genre: str
    intended_emotion: str = Field(alias="intendedEmotion", min_length=3)
    narrative: Narrative
    visual_bible: VisualBible = Field(alias="visualBible")
    shots: list[ShotPlan] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def validate_shot_order(self) -> "ProductionPlan":
        expected = list(range(1, len(self.shots) + 1))
        actual = [shot.order for shot in self.shots]
        if actual != expected:
            raise ValueError(f"shots must be ordered consecutively; expected {expected}")
        if len({shot.id for shot in self.shots}) != len(self.shots):
            raise ValueError("shot IDs must be unique")
        return self


class ConsistencyWarning(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    shot_id: str = Field(alias="shotId")
    field: str
    expected: str
    found: str
    severity: Literal["low", "medium", "high"]


class ConsistencyReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    approved: bool
    warnings: list[ConsistencyWarning] = Field(default_factory=list)
    character_consistency_score: float | None = Field(
        alias="characterConsistencyScore", default=None, ge=0, le=1
    )
    environment_consistency_score: float | None = Field(
        alias="environmentConsistencyScore", default=None, ge=0, le=1
    )
    palette_consistency_score: float | None = Field(
        alias="paletteConsistencyScore", default=None, ge=0, le=1
    )
    prop_consistency_score: float | None = Field(
        alias="propConsistencyScore", default=None, ge=0, le=1
    )
    visible_differences: list[str] = Field(
        alias="visibleDifferences", default_factory=list
    )


class GenerationConfirmation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    confirm_paid_calls: bool = Field(alias="confirmPaidCalls", default=False)


class BudgetEstimate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    image_calls: int = Field(alias="imageCalls")
    video_calls: int = Field(alias="videoCalls")
    video_seconds: int = Field(alias="videoSeconds")
    resolution: str
    estimated_cost_cny: float = Field(alias="estimatedCostCny")


class AssetRecord(BaseModel):
    id: str
    project_id: str = Field(alias="projectId")
    shot_id: str | None = Field(alias="shotId", default=None)
    kind: Literal["image", "video", "final"]
    local_url: str = Field(alias="localUrl")
    remote_url: str | None = Field(alias="remoteUrl", default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApiError(BaseModel):
    detail: str
    code: str | None = None


class ProjectPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    story_prompt: str | None = Field(alias="storyPrompt", default=None, min_length=8)
    genre: str | None = None
    visual_style: str | None = Field(alias="visualStyle", default=None)


class ProviderImageRequest(BaseModel):
    project_id: str
    shot_id: str
    prompt: str
    negative_prompt: str
    seed: int
    size: str = "1920*1080"
    reference_shot_id: str | None = None
    reference_job_id: str | None = None
    reference_image_url: str | None = None
    framing: str | None = None
    subject_position: str | None = None
    image_delta: str | None = None


class ProviderVideoRequest(BaseModel):
    project_id: str
    shot_id: str
    first_frame_url: str
    prompt: str
    negative_prompt: str
    seed: int
    duration_seconds: int = Field(ge=2, le=5)
    resolution: str = "720P"
