from __future__ import annotations

import re

from .schemas import ProductionPlan


def framing_family(framing: str) -> str:
    """Classify free-form LLM coverage without prescribing a shot order."""
    value = re.sub(r"[-_]", " ", framing.lower())
    if any(token in value for token in ("insert", "detail", "macro", "extreme close")):
        return "detail"
    if any(token in value for token in ("over the shoulder", "over-the-shoulder", "ots")):
        return "over-shoulder"
    if any(token in value for token in ("point of view", "pov", "subjective")):
        return "pov"
    if "close" in value:
        return "close"
    if any(token in value for token in ("wide", "master", "full room", "establish")):
        return "wide"
    if "medium" in value:
        return "medium"
    return "other"


def framing_visibility_contract(framing: str, subject_position: str) -> str:
    """Translate free-form LLM coverage into a strict, order-independent crop contract."""
    family = framing_family(framing)
    target = subject_position.strip()
    contracts = {
        "wide": (
            "WIDE/MASTER. Show the spatial geography and the subject within it. The room may "
            "be visible, but its architecture must match the continuity reference exactly."
        ),
        "medium": (
            "MEDIUM. Crop the principal subject approximately head-to-waist or to the named "
            "action area. Do not fall back to a full-body wide master."
        ),
        "close": (
            "CLOSE-UP. The named face, hands, or object must dominate the frame. Never show a "
            "full body or a readable wide room. If the shot direction says no face, the face "
            "and head must be completely outside the frame."
        ),
        "detail": (
            "INSERT/DETAIL. Fill the entire frame with only the named object, texture, or body "
            "region. A person may appear only as the explicitly named partial body region, such "
            "as fingertips. No face, head, torso, full body, bed-wide composition, window, or "
            "room overview may be visible."
        ),
        "over-shoulder": (
            "OVER-THE-SHOULDER. A near shoulder/back may occupy one frame edge while the eyeline "
            "target controls the rest of the image. Do not substitute a profile medium shot, "
            "frontal portrait, or full-body view."
        ),
        "pov": (
            "TRUE FIRST-PERSON POV. The camera is exactly the observer's eyes. The observer's "
            "face, head, torso, and full body cannot appear; show their hands only when the shot "
            "explicitly names them. Do not substitute an external view of the observer."
        ),
        "other": (
            "OBEY THE DECLARED FRAME. The named visual subject and crop must dominate; do not "
            "fall back to the continuity reference's camera position."
        ),
    }
    return f"{contracts[family]} Declared on-screen target: {target}"


def cinematography_issues(plan: ProductionPlan) -> list[str]:
    """Return coverage/story-continuity problems while allowing any creative order."""
    if len(plan.shots) < 3:
        return []

    families = [framing_family(shot.framing) for shot in plan.shots]
    issues: list[str] = []
    required_variety = min(4, len(plan.shots))
    if len(set(families)) < required_variety:
        issues.append(
            f"coverage uses only {len(set(families))} framing families; use at least "
            f"{required_variety} story-motivated families"
        )
    if not any(family == "wide" for family in families):
        issues.append("the sequence never establishes spatial geography with a wide/master shot")
    if not any(family in {"close", "detail", "pov"} for family in families):
        issues.append("the sequence has no intimate reaction, detail, or point-of-view coverage")

    run = 1
    for previous, current in zip(families, families[1:]):
        run = run + 1 if current == previous else 1
        if run > 2:
            issues.append("more than two adjacent shots repeat the same framing family")
            break

    actions = [shot.subject_action.strip().lower() for shot in plan.shots]
    if len(set(actions)) < max(3, len(plan.shots) - 1):
        issues.append("subject actions repeat instead of progressing the story")
    prop_states = [shot.prop_state.strip().lower() for shot in plan.shots]
    required_prop_states = min(3, len(plan.shots))
    if len(set(prop_states)) < required_prop_states:
        issues.append(
            "prop state or placement does not establish at least "
            f"{required_prop_states} meaningful sequence states"
        )
    deltas = [shot.image_delta.strip().lower() for shot in plan.shots]
    if len(set(deltas)) != len(deltas):
        issues.append("two or more image directions are duplicates")
    issues.extend(practical_motion_issues(plan))
    return issues


def practical_motion_issues(plan: ProductionPlan) -> list[str]:
    """Reject poetic motion prose that cannot be executed as one clear screen action."""
    issues: list[str] = []
    banned = re.compile(
        r"\b(audibly|faintly|rustl\w*|dust motes?|light beam|recognition|realiz\w*|"
        r"remember\w*|cognitive|dissonance|atmosphere|imperceptibly|micro[- ]?adjust\w*|"
        r"rack focus|focus shift|breath catches?)\b",
        re.IGNORECASE,
    )
    complex_connectors = re.compile(
        r"\b(while|then|after|before|simultaneously|as she|as he|as they)\b|[;—]",
        re.IGNORECASE,
    )
    camera_banned = re.compile(
        r"\b(rack focus|focus shift|micro|settle|orbit|shake|handheld|zoom)\b",
        re.IGNORECASE,
    )

    for shot in plan.shots:
        missing = [
            name
            for name, value in (
                ("primarySubject", shot.primary_subject),
                ("framingReason", shot.framing_reason),
                ("startState", shot.start_state),
                ("endState", shot.end_state),
            )
            if not value.strip()
        ]
        if missing:
            issues.append(f"{shot.id} is missing practical fields: {', '.join(missing)}")
        if len(shot.subject_action.split()) > 18:
            issues.append(f"{shot.id} subjectAction exceeds 18 words")
        if banned.search(
            " ".join(
                (shot.subject_action, shot.environment_motion, shot.camera_motion)
            )
        ):
            issues.append(f"{shot.id} contains poetic, sonic, or micro-atmospheric motion")
        if complex_connectors.search(shot.subject_action):
            issues.append(f"{shot.id} combines multiple actions instead of one physical action")
        if shot.subject_action.strip().casefold().rstrip(".") in (
            shot.start_state + " " + shot.end_state
        ).casefold():
            issues.append(
                f"{shot.id} repeats subjectAction inside a state instead of describing positions"
            )
        if shot.environment_motion.strip().lower().rstrip(".") not in {
            "none",
            "room remains still",
            "environment remains still",
        }:
            issues.append(f"{shot.id} adds nonessential environment motion")
        if camera_banned.search(shot.camera_motion):
            issues.append(f"{shot.id} uses an impractical camera or focus instruction")

    for previous, current in zip(plan.shots, plan.shots[1:]):
        if (
            previous.end_state.strip().casefold()
            != current.start_state.strip().casefold()
        ):
            issues.append(
                f"{previous.id} endState must exactly equal {current.id} startState"
            )
    return issues
