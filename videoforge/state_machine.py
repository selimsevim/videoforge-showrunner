from __future__ import annotations

from .schemas import ProductionStage


ALLOWED_TRANSITIONS: dict[ProductionStage, set[ProductionStage]] = {
    ProductionStage.DRAFT: {ProductionStage.PLANNING, ProductionStage.CANCELLED},
    ProductionStage.PLANNING: {
        ProductionStage.PLAN_READY,
        ProductionStage.FAILED,
        ProductionStage.CANCELLED,
    },
    ProductionStage.PLAN_READY: {
        ProductionStage.STORYBOARD_GENERATING,
        ProductionStage.PLANNING,
        ProductionStage.CANCELLED,
    },
    ProductionStage.STORYBOARD_GENERATING: {
        ProductionStage.STORYBOARD_REVIEW,
        ProductionStage.PARTIALLY_COMPLETED,
        ProductionStage.FAILED,
        ProductionStage.CANCELLED,
    },
    ProductionStage.STORYBOARD_REVIEW: {
        ProductionStage.STORYBOARD_GENERATING,
        ProductionStage.VIDEO_GENERATING,
        ProductionStage.CANCELLED,
    },
    ProductionStage.VIDEO_GENERATING: {
        ProductionStage.VIDEO_REVIEW,
        ProductionStage.PARTIALLY_COMPLETED,
        ProductionStage.FAILED,
        ProductionStage.CANCELLED,
    },
    ProductionStage.VIDEO_REVIEW: {
        ProductionStage.VIDEO_GENERATING,
        ProductionStage.ASSEMBLING,
        ProductionStage.COMPLETED,
    },
    ProductionStage.ASSEMBLING: {
        ProductionStage.COMPLETED,
        ProductionStage.PARTIALLY_COMPLETED,
        ProductionStage.VIDEO_REVIEW,
    },
    ProductionStage.PARTIALLY_COMPLETED: {
        ProductionStage.STORYBOARD_GENERATING,
        ProductionStage.STORYBOARD_REVIEW,
        ProductionStage.VIDEO_GENERATING,
        ProductionStage.VIDEO_REVIEW,
        ProductionStage.ASSEMBLING,
        ProductionStage.CANCELLED,
    },
    ProductionStage.FAILED: {ProductionStage.PLANNING, ProductionStage.CANCELLED},
    # A completed cut may be reopened for a deliberate paid video pass while its
    # approved keyframes remain locked. This also makes the existing completed-shot
    # retry endpoint usable after final assembly.
    ProductionStage.COMPLETED: {
        ProductionStage.VIDEO_GENERATING,
        ProductionStage.ASSEMBLING,
    },
    ProductionStage.CANCELLED: set(),
}


def can_transition(current: ProductionStage | str, target: ProductionStage | str) -> bool:
    current_stage = ProductionStage(current)
    target_stage = ProductionStage(target)
    return current_stage == target_stage or target_stage in ALLOWED_TRANSITIONS[current_stage]


def require_transition(current: ProductionStage | str, target: ProductionStage | str) -> None:
    if not can_transition(current, target):
        raise ValueError(f"invalid production transition: {current} -> {target}")
