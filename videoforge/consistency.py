from __future__ import annotations

from .prompting import compile_all, immutable_bible_text
from .schemas import ConsistencyReport, ConsistencyWarning, ProductionPlan


def validate_plan_consistency(plan: ProductionPlan) -> ConsistencyReport:
    warnings: list[ConsistencyWarning] = []
    prefix = immutable_bible_text(plan.visual_bible)
    for shot in plan.shots:
        if not shot.image_prompt.startswith(prefix):
            warnings.append(
                ConsistencyWarning(
                    shotId=shot.id,
                    field="visualBible",
                    expected="exact immutable shared bible prefix",
                    found="missing or paraphrased bible prefix",
                    severity="high",
                )
            )
        required_motion = (
            "Preserve facial identity, wardrobe, prop design, lighting, and room geometry."
        )
        if required_motion not in shot.motion_prompt:
            warnings.append(
                ConsistencyWarning(
                    shotId=shot.id,
                    field="stabilityConstraint",
                    expected=required_motion,
                    found=shot.motion_prompt,
                    severity="medium",
                )
            )
        if shot.duration_seconds > 5:
            warnings.append(
                ConsistencyWarning(
                    shotId=shot.id,
                    field="durationSeconds",
                    expected="at most 5 seconds",
                    found=str(shot.duration_seconds),
                    severity="high",
                )
            )
    return ConsistencyReport(approved=not warnings, warnings=warnings)


def repair_plan_consistency(plan: ProductionPlan) -> tuple[ProductionPlan, ConsistencyReport]:
    repaired = plan.model_copy(
        update={"shots": compile_all(plan.visual_bible, plan.shots)}
    )
    return repaired, validate_plan_consistency(repaired)


def mock_storyboard_report() -> ConsistencyReport:
    return ConsistencyReport(
        approved=True,
        warnings=[],
        characterConsistencyScore=0.91,
        environmentConsistencyScore=0.95,
        paletteConsistencyScore=0.94,
        propConsistencyScore=0.88,
        visibleDifferences=[
            "Minor facial-feature variation between the establishing and close shots.",
            "The Polaroid border appears fractionally warmer in shot 3.",
        ],
    )

