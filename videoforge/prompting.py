from __future__ import annotations

import hashlib

from .cinematography import framing_visibility_contract
from .schemas import ShotPlan, VisualBible


def prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bible_blocks(bible: VisualBible) -> tuple[str, ...]:
    return (
        "CHARACTER_BIBLE: "
        f"{bible.character_identity}; {bible.face_and_hair}; {bible.wardrobe}",
        "ENVIRONMENT_BIBLE: "
        f"{bible.environment}; {bible.time_of_day}",
        "STYLE_BIBLE: "
        f"{bible.visual_style}; {bible.lighting}; colour palette: {bible.palette}",
        f"CAMERA_BIBLE: {bible.camera_language}",
    )


def prop_bible_text(bible: VisualBible) -> str:
    return (
        "PROP_BIBLE: "
        f"{bible.important_prop}. This defines design and hand-held scale only for a shot "
        "whose first-frame ledger explicitly makes the prop visible."
    )


def prop_is_absent(prop_state: str) -> bool:
    return prop_state.strip().casefold().rstrip(".") in {
        "none",
        "absent",
        "no prop",
    }


def immutable_bible_text(bible: VisualBible) -> str:
    return "\n".join(bible_blocks(bible))


def first_frame_target(shot: ShotPlan) -> str:
    """Choose only a subject that physically exists in the declared first frame."""
    prop_state = shot.prop_state.strip().casefold().rstrip(".")
    primary = shot.primary_subject.strip()
    primary_names_prop = any(
        token in primary.casefold()
        for token in ("polaroid", "photo", "photograph", "important prop")
    )
    if prop_state in {"none", "absent", "no prop"} and primary_names_prop:
        ledger_parts = shot.start_state.split("|")
        hands = next(
            (
                part.split(":", 1)[1].strip()
                for part in ledger_parts
                if part.strip().upper().startswith("HANDS:")
            ),
            "the declared hands",
        )
        return hands
    return primary or shot.subject_position


def compile_image_prompt(bible: VisualBible, shot: ShotPlan) -> str:
    target = first_frame_target(shot)
    absent_prop = prop_is_absent(shot.prop_state)
    optional_prop_bible = "" if absent_prop else f"\n{prop_bible_text(bible)}"
    prop_constraint = (
        "ABSENT_PROP_CONSTRAINT: No photograph, Polaroid, instant-photo border, card, "
        "paper, inset picture, or floating image may appear anywhere in this frame."
        if absent_prop
        else (
            "VISIBLE_PROP_CONSTRAINT: Keep the declared prop at realistic hand-held scale. "
            "Never enlarge it, duplicate it, float it, or render it as a graphic overlay."
        )
    )
    shot_blocks = (
        f"STORYBOARD_SHOT: {shot.id}; beat {shot.order}",
        f"SHOT_COMPOSITION: {shot.framing}; {shot.camera_angle}; {shot.subject_position}",
        f"SHOT_FIRST_FRAME_TARGET: {target}",
        f"SHOT_START_STATE: {shot.start_state}",
        f"SHOT_PROP_STATE_AT_START: {shot.prop_state}",
        (
            "SHOT_FIRST_FRAME_DIRECTION: Render only the declared composition, "
            "SHOT_START_STATE, and SHOT_PROP_STATE_AT_START."
        ),
        prop_constraint,
        "FRAME_VISIBILITY_CONTRACT: "
        + framing_visibility_contract(shot.framing, target),
        (
            "HARD_SHOT_CONSTRAINT: This keyframe is the first frame of a video. Render the "
            "exact SHOT_START_STATE immediately before any action begins. No future action "
            "or end state is included in this prompt; do not invent one. Do not "
            "default to a seated portrait. Preserve the "
            "locked character and room while making this shot visibly distinct from the "
            "other storyboard beats. SHOT_COMPOSITION overrides bible context visibility: "
            "anything declared off-screen must not appear. SHOT_PROP_STATE_AT_START is the "
            "only authority for prop presence and visibility. For an insert, detail, macro, or "
            "extreme close-up, show only the specified object or body region—no full face, "
            "full body, or wide room. If SHOT_PROP_STATE_AT_START says absent or not visible, do not "
            "render the important prop anywhere."
        ),
    )
    return (
        f"{immutable_bible_text(bible)}{optional_prop_bible}\n"
        + "\n".join(shot_blocks)
    )


def compile_motion_prompt(shot: ShotPlan) -> str:
    return " ".join(
        (
            f"FRAMING: {shot.framing} of {shot.primary_subject}.",
            f"START: {shot.start_state.rstrip('.')}.",
            f"ACTION: {shot.subject_action.rstrip('.')}.",
            f"END: {shot.end_state.rstrip('.')}.",
            f"CAMERA: {shot.camera_motion.rstrip('.')}.",
            "Perform the action once. No additional gestures, prop movement, particles, "
            "atmospheric effects, dialogue, or new objects.",
            "Preserve facial identity, wardrobe, prop design, lighting, and room geometry.",
        )
    )


def compile_shot(bible: VisualBible, shot: ShotPlan) -> ShotPlan:
    return shot.model_copy(
        update={
            "image_prompt": compile_image_prompt(bible, shot),
            "motion_prompt": compile_motion_prompt(shot),
        }
    )


def compile_all(bible: VisualBible, shots: list[ShotPlan]) -> list[ShotPlan]:
    return [compile_shot(bible, shot) for shot in shots]
