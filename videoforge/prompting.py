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
        "PROP_BIBLE: "
        f"{bible.important_prop}. This defines its design and scale only; show it exactly "
        "where SHOT_PROP_STATE requires it.",
        "STYLE_BIBLE: "
        f"{bible.visual_style}; {bible.lighting}; colour palette: {bible.palette}",
        f"CAMERA_BIBLE: {bible.camera_language}",
    )


def immutable_bible_text(bible: VisualBible) -> str:
    return "\n".join(bible_blocks(bible))


def compile_image_prompt(bible: VisualBible, shot: ShotPlan) -> str:
    shot_blocks = (
        f"STORYBOARD_SHOT: {shot.id}; beat {shot.order}; {shot.narrative_purpose}",
        f"SHOT_COMPOSITION: {shot.framing}; {shot.camera_angle}; {shot.subject_position}",
        f"SHOT_PRIMARY_SUBJECT: {shot.primary_subject}",
        f"SHOT_FRAMING_REASON: {shot.framing_reason}",
        f"SHOT_START_STATE: {shot.start_state}",
        f"SHOT_ENVIRONMENT_STATE: {shot.environment_state}",
        f"SHOT_PROP_STATE_AT_START: {shot.prop_state}",
        (
            "SHOT_FIRST_FRAME_DIRECTION: Render only the declared composition, "
            "SHOT_START_STATE, and SHOT_PROP_STATE_AT_START."
        ),
        "FRAME_VISIBILITY_CONTRACT: "
        + framing_visibility_contract(shot.framing, shot.subject_position),
        (
            "HARD_SHOT_CONSTRAINT: This keyframe is the first frame of a video. Render the "
            "exact SHOT_START_STATE immediately before any action begins. No future action "
            "or end state is included in this prompt; do not invent one. Do not "
            "default to a seated portrait. Keep the "
            "important prop at realistic hand-held scale; never enlarge it. Preserve the "
            "locked character and room while making this shot visibly distinct from the "
            "other storyboard beats. SHOT_COMPOSITION overrides bible context visibility: "
            "anything declared off-screen must not appear. For an insert, detail, macro, or "
            "extreme close-up, show only the specified object or body region—no full face, "
            "full body, or wide room. If SHOT_PROP_STATE says absent or not visible, do not "
            "render the important prop anywhere."
        ),
    )
    return f"{immutable_bible_text(bible)}\n" + "\n".join(shot_blocks)


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
