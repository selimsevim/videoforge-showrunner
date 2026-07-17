from __future__ import annotations

import re

from .schemas import ProductionPlan, ShotPlan


_STATE_PATTERN = re.compile(
    r"^BODY:\s*(?P<body>.+?)\s*\|\s*HANDS:\s*(?P<hands>.+?)\s*"
    r"\|\s*PROP:\s*(?P<prop>.+?)\s*$",
    re.IGNORECASE,
)
_STATIC_REACTION_PATTERN = re.compile(
    r"\b(look\w*|stare\w*|watch\w*|hold\w*|remain\w*|wait\w*|"
    r"breathe\w*|exhale\w*|blink\w*)\b|"
    r"\b(turn\w*|shift\w*|move\w*)\b.{0,30}\b(head|eyes?|gaze)\b|"
    r"\b(head|eyes?|gaze)\b.{0,30}\b(turn\w*|shift\w*|move\w*)\b|"
    r"\b(tighten\w*|clench\w*|press\w*)\b.{0,30}\b(jaw|mouth|lips?)\b|"
    r"\b(jaw|mouth|lips?)\b.{0,30}\b(tighten\w*|clench\w*|press\w*)\b",
    re.IGNORECASE,
)


def _normalized(value: str) -> str:
    return value.strip().casefold().rstrip(".")


def _state_with_prop(state: str, prop: str) -> str:
    match = _STATE_PATTERN.fullmatch(state.strip())
    if not match:
        return state
    return (
        f"BODY: {match.group('body')} | HANDS: {match.group('hands')} | PROP: {prop}"
    )


def _observational_action(shot: ShotPlan, character_name: str) -> str:
    subject = character_name or "The subject"
    verbs = (
        "looks forward",
        "holds still",
        "watches without moving",
        "stares forward",
        "remains still",
        "waits without moving",
    )
    return f"{subject} {verbs[(shot.order - 1) % len(verbs)]}."


def repair_practical_motion(plan: ProductionPlan) -> ProductionPlan:
    """Repair bounded ledger contradictions without inventing new story action."""
    prop_description = plan.visual_bible.important_prop.strip().casefold()
    nonphysical_prop = prop_description.startswith(
        ("none", "no prop", "no physical prop")
    ) or ("shadow" in prop_description and "photograph" not in prop_description)
    fixed_visible_prop = not nonphysical_prop and bool(
        re.search(r"\b(mounted|fixed|built[- ]?in|attached|installed)\b", prop_description)
    )
    all_prop_states_absent = all(
        _normalized(shot.prop_state) in {"none", "absent", "no prop"}
        for shot in plan.shots
    )
    stable_prop_state = plan.visual_bible.important_prop.strip().rstrip(".")
    character_name = plan.visual_bible.character_identity.split(",", 1)[0].split()[0]
    repaired_shots: list[ShotPlan] = []
    for shot in plan.shots:
        updates: dict[str, str] = {}
        if nonphysical_prop:
            updates.update(
                {
                    "start_state": _state_with_prop(shot.start_state, "none"),
                    "end_state": _state_with_prop(shot.end_state, "none"),
                    "prop_state": "none",
                }
            )
        elif fixed_visible_prop and all_prop_states_absent:
            updates.update(
                {
                    "start_state": _state_with_prop(
                        shot.start_state, stable_prop_state
                    ),
                    "end_state": _state_with_prop(shot.end_state, stable_prop_state),
                    "prop_state": stable_prop_state,
                }
            )
        candidate = shot.model_copy(update=updates)
        if _normalized(candidate.start_state) == _normalized(candidate.end_state):
            action = candidate.subject_action
            if not _STATIC_REACTION_PATTERN.search(action):
                candidate = candidate.model_copy(
                    update={
                        "subject_action": _observational_action(
                            candidate, character_name
                        )
                    }
                )
        repaired_shots.append(candidate)
    return plan.model_copy(update={"shots": repaired_shots})


def framing_family(framing: str) -> str:
    """Classify free-form LLM coverage without prescribing a shot order."""
    value = re.sub(r"[-_]", " ", framing.lower())
    if any(token in value for token in ("insert", "detail", "macro", "extreme close")):
        return "detail"
    if any(token in value for token in ("over the shoulder", "over-the-shoulder", "ots")):
        return "over-shoulder"
    if any(token in value for token in ("point of view", "pov", "subjective")):
        return "pov"
    if "medium close" in value:
        return "close"
    if "medium" in value:
        return "medium"
    if "close" in value:
        return "close"
    if any(token in value for token in ("wide", "master", "full room", "establish")):
        return "wide"
    return "other"


def framing_visibility_contract(framing: str, subject_position: str) -> str:
    """Translate free-form LLM coverage into a strict, order-independent crop contract."""
    family = framing_family(framing)
    target = subject_position.strip()
    physical_photo_target = bool(
        re.search(r"\b(polaroid|photo|photograph|print)\b", target, re.IGNORECASE)
    )
    reflection_target = bool(
        re.search(r"\b(tv|television|screen|mirror|reflection)\b", target, re.IGNORECASE)
    )
    shadow_target = bool(re.search(r"\bshadow\b", target, re.IGNORECASE))
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
            (
                "SHADOW CLOSE-UP. Fill the frame with the declared shadow and only the matching "
                "wall surface. The live person, face, body, TV, furniture, door, window, and room "
                "overview must remain completely outside the frame."
            )
            if shadow_target
            else (
                "CLOSE-UP. The named face, hands, or object must dominate the frame. Never show a "
                "full body or a readable wide room. If the shot direction says no face, the face "
                "and head must be completely outside the frame."
            )
        ),
        "detail": (
            (
                "PHYSICAL PHOTO DETAIL. The single hand-sized print must dominate the frame with "
                "correct perspective and contact with its supporting surface or declared fingers. "
                "A narrow area of supporting surface and declared fingertips may remain visible. "
                "No live face, live head, live torso, full body, bed-wide composition, window, or "
                "room overview may appear outside the print. A face or body printed inside the "
                "physical photograph is part of the prop and is explicitly allowed."
            )
            if physical_photo_target
            else (
                "PHYSICAL SCREEN/REFLECTION DETAIL. The declared TV, screen, or mirror surface "
                "fills the frame edge to edge. No live person or room context may appear outside "
                "that surface. A figure or hand visible only inside the declared optical reflection "
                "is part of the target and is explicitly allowed."
            )
            if reflection_target
            else (
                "INSERT/DETAIL. Fill the entire frame with only the named object, texture, or body "
                "region. A person may appear only as the explicitly named partial body region, such "
                "as fingertips. No face, head, torso, full body, bed-wide composition, window, or "
                "room overview may be visible."
            )
        ),
        "over-shoulder": (
            "SINGLE-SUBJECT OVER-THE-SHOULDER. Show one live person only: the near shoulder/back "
            "occupies one frame edge while the eyeline target controls the rest of the image. "
            "Do not add a second live person, a frontal double, or a face-to-face two-shot. A "
            "person printed inside a physical photograph is prop content, not a second live "
            "person. A reflection of the same subject inside a declared mirror or TV is an optical "
            "image, not a second live person. Do not substitute a profile medium shot, frontal "
            "portrait, or full-body view."
            + (
                " For a TV or mirror reflection, make this a tight two-plane composition: the "
                "near back/shoulder fills roughly the left quarter, the fixed glass and optical "
                "reflection fill roughly the right two-thirds, and only a narrow wall gap may "
                "separate them. Exclude the bed, window, door, and room overview."
                if reflection_target
                else ""
            )
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

    for shot, family in zip(plan.shots, families):
        if family == "pov" and re.search(
            r"\b(reflection|mirror)\b",
            " ".join((shot.primary_subject, shot.framing_reason, shot.image_delta)),
            re.IGNORECASE,
        ):
            issues.append(
                f"{shot.id} POV puts the observer's reflection in frame, contradicting the "
                "no-observer POV visibility contract; choose a non-POV framing or a target "
                "visible directly from the observer's eyes"
            )

    run = 1
    for previous, current in zip(families, families[1:]):
        run = run + 1 if current == previous else 1
        if run > 2:
            issues.append("more than two adjacent shots repeat the same framing family")
            break

    actions = [shot.subject_action.strip().lower() for shot in plan.shots]
    if len(set(actions)) < max(3, len(plan.shots) - 1):
        issues.append("subject actions repeat instead of progressing the story")
    deltas = [shot.image_delta.strip().lower() for shot in plan.shots]
    if len(set(deltas)) != len(deltas):
        issues.append("two or more image directions are duplicates")
    issues.extend(practical_motion_issues(plan))
    return issues


def practical_motion_issues(plan: ProductionPlan) -> list[str]:
    """Reject poetic motion prose that cannot be executed as one clear screen action."""
    issues: list[str] = []
    sensory_banned = re.compile(
        r"\b(audibly|rustl\w*|dust motes?|light beam|atmosphere|"
        r"imperceptibly|micro[- ]?adjust\w*|rack focus|focus shift|breath catches?)\b",
        re.IGNORECASE,
    )
    internal_motion_banned = re.compile(
        r"\b(recognition|realiz\w*|remember\w*|cognitive|dissonance)\b",
        re.IGNORECASE,
    )
    self_changing_prop = re.compile(
        r"\b(emerg\w*|develop\w*|materializ\w*|appear\w*|morph\w*|transform\w*)\b",
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
    allowed_camera = {
        "static camera",
        "slow push-in",
        "slow pull-back",
        "slow pan left",
        "slow pan right",
        "slow tilt up",
        "slow tilt down",
        "slow rise",
        "slow lower",
    }
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
        operational_direction = " ".join(
            (
                shot.framing_reason,
                shot.start_state,
                shot.subject_action,
                shot.end_state,
                shot.environment_state,
                shot.environment_motion,
                shot.camera_motion,
                shot.prop_state,
                shot.image_delta,
            )
        )
        executable_direction = " ".join(
            (
                shot.start_state,
                shot.subject_action,
                shot.end_state,
                shot.environment_motion,
                shot.camera_motion,
            )
        )
        forbidden_match = (
            sensory_banned.search(operational_direction)
            or internal_motion_banned.search(executable_direction)
            or self_changing_prop.search(executable_direction)
        )
        if forbidden_match:
            issues.append(
                f"{shot.id} contains poetic, sonic, or micro-atmospheric motion "
                f"({forbidden_match.group(0)})"
            )
        if complex_connectors.search(shot.subject_action):
            issues.append(f"{shot.id} combines multiple actions instead of one physical action")
        if len(re.findall(r"\band\b", shot.subject_action, re.IGNORECASE)) > 1:
            issues.append(f"{shot.id} chains more than one coordinated physical movement")
        if shot.subject_action.strip().casefold().rstrip(".") in (
            shot.start_state + " " + shot.end_state
        ).casefold():
            issues.append(
                f"{shot.id} repeats subjectAction inside a state instead of describing positions"
            )
        if _normalized(shot.environment_motion) != "none":
            issues.append(f"{shot.id} adds nonessential environment motion")
        if camera_banned.search(shot.camera_motion) or _normalized(
            shot.camera_motion
        ) not in allowed_camera:
            issues.append(f"{shot.id} uses an impractical camera or focus instruction")

        start_match = _STATE_PATTERN.fullmatch(shot.start_state.strip())
        end_match = _STATE_PATTERN.fullmatch(shot.end_state.strip())
        if not start_match:
            issues.append(
                f"{shot.id} startState must use BODY: ... | HANDS: ... | PROP: ..."
            )
        if not end_match:
            issues.append(
                f"{shot.id} endState must use BODY: ... | HANDS: ... | PROP: ..."
            )
        if start_match:
            if _normalized(shot.subject_position) != _normalized(start_match.group("body")):
                issues.append(
                    f"{shot.id} subjectPosition must exactly equal startState BODY"
                )
            if _normalized(shot.prop_state) != _normalized(start_match.group("prop")):
                issues.append(f"{shot.id} propState must exactly equal startState PROP")
        if start_match and end_match:
            start_prop = _normalized(start_match.group("prop"))
            end_prop = _normalized(end_match.group("prop"))
            absent_values = {"none", "absent", "no prop"}
            if (start_prop in absent_values) != (end_prop in absent_values):
                visibility_action = re.compile(
                    r"\b(reveal\w*|uncover\w*|expose\w*|hide\w*|conceal\w*|remove\w*)\b|"
                    r"\b(pull\w*|lift\w*|take\w*|slide\w*)\b.{0,40}"
                    r"\b(from|under|beneath|behind|off[- ]?screen|into view)\b|"
                    r"\blift\w*\b.{0,20}\b(pillow|blanket|sweater|duvet|cloth|cover|book)\b",
                    re.IGNORECASE,
                )
                if not visibility_action.search(shot.subject_action):
                    issues.append(
                        f"{shot.id} makes the prop appear or disappear without an explicit "
                        "uncovering or removal action"
                    )
            start_hands = _normalized(start_match.group("hands"))
            end_hands = _normalized(end_match.group("hands"))
            prop_terms = re.compile(r"\b(polaroid|photo|photograph|object|prop)\b")
            pickup_action = re.compile(
                r"\b(pick\w*|lift\w*|take\w*|grasp\w*|hold\w*|pull\w*)\b"
                r".{0,30}\b(polaroid|photo|photograph|object|prop)\b",
                re.IGNORECASE,
            )
            if (
                not prop_terms.search(start_hands)
                and prop_terms.search(end_hands)
                and not pickup_action.search(shot.subject_action)
            ):
                issues.append(
                    f"{shot.id} ends with the prop in hand without explicitly picking it up"
                )
            right_holds = re.compile(
                r"\bright\b.{0,35}\b(hold\w*|grip\w*)\b.{0,35}"
                r"\b(polaroid|photo|photograph|object|prop)\b",
                re.IGNORECASE,
            )
            left_holds = re.compile(
                r"\bleft\b.{0,35}\b(hold\w*|grip\w*)\b.{0,35}"
                r"\b(polaroid|photo|photograph|object|prop)\b",
                re.IGNORECASE,
            )
            transfer_action = re.compile(
                r"\b(transfer\w*|pass\w*|switch\w*|move\w*)\b.{0,35}\bhand\b|"
                r"\bhand\b.{0,35}\b(transfer\w*|pass\w*|switch\w*|move\w*)\b",
                re.IGNORECASE,
            )
            changes_holding_side = (
                right_holds.search(start_hands) and left_holds.search(end_hands)
            ) or (
                left_holds.search(start_hands) and right_holds.search(end_hands)
            )
            if changes_holding_side and not transfer_action.search(shot.subject_action):
                issues.append(
                    f"{shot.id} transfers the prop between hands without naming that action"
                )
        if _normalized(shot.start_state) == _normalized(
            shot.end_state
        ) and not _STATIC_REACTION_PATTERN.search(shot.subject_action):
            issues.append(f"{shot.id} action does not create a new physical endState")

    for previous, current in zip(plan.shots, plan.shots[1:]):
        if (
            previous.end_state.strip().casefold()
            != current.start_state.strip().casefold()
        ):
            issues.append(
                f"{previous.id} endState must exactly equal {current.id} startState"
            )
    return issues
