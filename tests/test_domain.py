from __future__ import annotations

import pytest
from pydantic import ValidationError

from videoforge.budget import enforce_budget, estimate_budget
from videoforge.cinematography import (
    cinematography_issues,
    framing_family,
    framing_visibility_contract,
    practical_motion_issues,
)
from videoforge.config import Settings
from videoforge.consistency import repair_plan_consistency, validate_plan_consistency
from videoforge.planner import DEMO_PROMPT, create_mock_plan, deterministic_seed
from videoforge.prompting import immutable_bible_text, prompt_hash
from videoforge.retry import is_retryable_error
from videoforge.schemas import ProductionPlan, ProductionStage, ProjectInput
from videoforge.state_machine import can_transition, require_transition


def plan() -> ProductionPlan:
    return create_mock_plan(
        "project-domain-test",
        ProjectInput(title="The Third Exposure", storyPrompt=DEMO_PROMPT),
    )


def test_production_plan_schema_and_shot_order() -> None:
    value = plan().model_dump(by_alias=True)
    value["shots"][1]["order"] = 3
    with pytest.raises(ValidationError, match="ordered consecutively"):
        ProductionPlan.model_validate(value)


def test_duration_above_five_is_rejected() -> None:
    value = plan().model_dump(by_alias=True)
    value["shots"][0]["durationSeconds"] = 6
    with pytest.raises(ValidationError):
        ProductionPlan.model_validate(value)


def test_prompt_compiler_reuses_immutable_bible_verbatim() -> None:
    production = plan()
    prefix = immutable_bible_text(production.visual_bible)
    assert all(shot.image_prompt.startswith(prefix + "\n") for shot in production.shots)
    assert all("SHOT_COMPOSITION:" in shot.image_prompt for shot in production.shots)
    assert all("SHOT_START_STATE:" in shot.image_prompt for shot in production.shots)
    assert all("SHOT_ACTION_AFTER_FIRST_FRAME:" in shot.image_prompt for shot in production.shots)
    assert all("SHOT_END_STATE_DO_NOT_SHOW_YET:" in shot.image_prompt for shot in production.shots)
    assert all("SHOT_PROP_STATE:" in shot.image_prompt for shot in production.shots)
    assert all("FRAME_VISIBILITY_CONTRACT:" in shot.image_prompt for shot in production.shots)
    assert len({shot.image_prompt for shot in production.shots}) == len(production.shots)


def test_motion_prompt_is_one_action_with_explicit_state_handoff() -> None:
    production = plan()
    first, second = production.shots[:2]
    assert f"ACTION: {first.subject_action}" in first.motion_prompt
    assert first.motion_prompt.count(first.subject_action) == 1
    assert "No additional gestures" in first.motion_prompt
    assert first.end_state == second.start_state
    assert practical_motion_issues(production) == []


def test_practical_motion_validator_rejects_poetic_or_multi_action_direction() -> None:
    production = plan()
    broken_first = production.shots[0].model_copy(
        update={
            "subject_action": (
                "Mara lifts the pillow while fabric rustles and dust motes drift through a light beam"
            ),
            "environment_motion": "Dust motes drift faintly.",
            "camera_motion": "Static with a micro-adjustment and rack focus.",
        }
    )
    broken = production.model_copy(
        update={"shots": [broken_first, *production.shots[1:]]}
    )
    issues = practical_motion_issues(broken)
    assert any("poetic, sonic, or micro-atmospheric" in issue for issue in issues)
    assert any("multiple actions" in issue for issue in issues)
    assert any("nonessential environment motion" in issue for issue in issues)
    assert any("impractical camera" in issue for issue in issues)


def test_visibility_contract_enforces_actual_crop_without_prescribing_order() -> None:
    detail = framing_visibility_contract(
        "Insert/detail", "Only the photograph and two fingertips"
    )
    pov = framing_visibility_contract("POV", "Her eyeline toward the footboard")
    assert "No face, head, torso, full body" in detail
    assert "Only the photograph and two fingertips" in detail
    assert "TRUE FIRST-PERSON POV" in pov
    assert "face, head, torso, and full body cannot appear" in pov


def test_consistency_guardian_repairs_paraphrased_prompt() -> None:
    production = plan()
    broken = production.model_copy(
        update={
            "shots": [
                production.shots[0].model_copy(update={"image_prompt": "different wardrobe"}),
                *production.shots[1:],
            ]
        }
    )
    assert not validate_plan_consistency(broken).approved
    repaired, report = repair_plan_consistency(broken)
    assert report.approved
    assert repaired.shots[0].image_prompt.startswith(immutable_bible_text(repaired.visual_bible))


def test_seed_generation_is_deterministic_and_distinct() -> None:
    assert deterministic_seed("p", 1, "image") == deterministic_seed("p", 1, "image")
    assert deterministic_seed("p", 1, "image") != deterministic_seed("p", 1, "video")
    assert deterministic_seed("p", 1, "image") != deterministic_seed("p", 2, "image")


def test_prompt_hash_is_stable() -> None:
    assert prompt_hash("locked prompt") == prompt_hash("locked prompt")
    assert prompt_hash("locked prompt") != prompt_hash("locked prompt ")
    assert len(prompt_hash("locked prompt")) == 64


@pytest.mark.parametrize("code", [429, "500", "TIMEOUT", "CONNECTION"])
def test_retry_classification_allows_transport_failures(code) -> None:
    assert is_retryable_error(code)


@pytest.mark.parametrize("code", [401, "INVALID_API_KEY", "DATA_INSPECTION_FAILED", "MODEL_NOT_FOUND"])
def test_retry_classification_blocks_permanent_failures(code) -> None:
    assert not is_retryable_error(code)


def test_budget_estimate_and_limits() -> None:
    production = plan()
    settings = Settings(max_shots=3, max_video_duration_seconds=5)
    enforce_budget(production, settings)
    estimate = estimate_budget(production, settings)
    assert estimate.image_calls == 3
    assert estimate.video_calls == 3
    assert estimate.video_seconds == 15
    assert estimate.estimated_cost_cny > 0
    with pytest.raises(ValueError, match="MAX_SHOTS"):
        enforce_budget(production, Settings(max_shots=2, default_shots=2))


def test_state_machine_transitions() -> None:
    assert can_transition(ProductionStage.DRAFT, ProductionStage.PLANNING)
    assert can_transition(ProductionStage.STORYBOARD_REVIEW, ProductionStage.VIDEO_GENERATING)
    assert not can_transition(ProductionStage.DRAFT, ProductionStage.COMPLETED)
    with pytest.raises(ValueError, match="invalid production transition"):
        require_transition(ProductionStage.DRAFT, ProductionStage.COMPLETED)


def test_internal_planner_supports_six_shots() -> None:
    production = create_mock_plan(
        "project-six-shot",
        ProjectInput(
            title="Six-shot internal test",
            storyPrompt=DEMO_PROMPT,
            shotCount=6,
            targetDurationSeconds=30,
        ),
    )
    assert len(production.shots) == 6
    assert [shot.order for shot in production.shots] == [1, 2, 3, 4, 5, 6]
    assert all(shot.duration_seconds == 5 for shot in production.shots)


def test_cinematography_validator_requires_variety_without_fixed_order() -> None:
    production = create_mock_plan(
        "project-six-shot-grammar",
        ProjectInput(
            title="Six-shot grammar test",
            storyPrompt=DEMO_PROMPT,
            shotCount=6,
            targetDurationSeconds=30,
        ),
    )
    assert cinematography_issues(production)
    framings = [
        "tight facial close-up",
        "wide room master",
        "macro insert detail",
        "over-the-shoulder medium close-up",
        "medium profile",
        "subjective POV",
    ]
    varied = production.model_copy(
        update={
            "shots": [
                shot.model_copy(
                    update={
                        "framing": framings[index],
                        "subject_action": f"progressive action {index}",
                        "prop_state": f"progressive prop state {index}",
                        "image_delta": f"unique visual direction {index}",
                    }
                )
                for index, shot in enumerate(production.shots)
            ]
        }
    )
    assert framing_family(varied.shots[0].framing) == "close"
    assert framing_family(varied.shots[1].framing) == "wide"
    assert cinematography_issues(varied) == []
