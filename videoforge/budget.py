from __future__ import annotations

from .config import Settings
from .schemas import BudgetEstimate, ProductionPlan


def estimate_budget(plan: ProductionPlan, settings: Settings) -> BudgetEstimate:
    image_calls = len(plan.shots)
    video_calls = len(plan.shots)
    video_seconds = sum(shot.duration_seconds for shot in plan.shots)
    cost = (
        image_calls * settings.image_cost_cny
        + video_seconds * settings.video_cost_cny_per_second_720p
    )
    return BudgetEstimate(
        imageCalls=image_calls,
        videoCalls=video_calls,
        videoSeconds=video_seconds,
        resolution="720P",
        estimatedCostCny=round(cost, 6),
    )


def enforce_budget(plan: ProductionPlan, settings: Settings) -> None:
    if len(plan.shots) > settings.max_shots:
        raise ValueError(f"project exceeds MAX_SHOTS={settings.max_shots}")
    for shot in plan.shots:
        if shot.duration_seconds > settings.max_video_duration_seconds:
            raise ValueError(
                f"{shot.id} exceeds MAX_VIDEO_DURATION_SECONDS="
                f"{settings.max_video_duration_seconds}"
            )

