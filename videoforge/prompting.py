from __future__ import annotations

import hashlib
import re

from .cinematography import framing_family, framing_visibility_contract
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


def _context_mentions_absent_physical_prop(
    value: str, bible: VisualBible, absent_prop: bool
) -> bool:
    if not absent_prop:
        return False
    description = bible.important_prop.strip().casefold()
    if description.startswith(("none", "no prop", "no physical prop")) or (
        "shadow" in description and "photograph" not in description
    ):
        return False
    ignored = {
        "important",
        "physical",
        "realistic",
        "single",
        "small",
        "large",
        "white",
        "black",
        "visible",
        "partially",
        "slightly",
        "handheld",
        "yellowed",
    }
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", description)
        if len(token) >= 4 and token not in ignored
    }
    context_tokens = set(re.findall(r"[a-z0-9]+", value.casefold()))
    return bool(tokens & context_tokens)


def immutable_bible_text(bible: VisualBible) -> str:
    return "\n".join(bible_blocks(bible))


def first_frame_target(shot: ShotPlan) -> str:
    """Choose only a subject that physically exists in the declared first frame."""
    prop_state = shot.prop_state.strip().casefold().rstrip(".")
    primary = re.sub(r"[*_`]", "", shot.primary_subject).strip()
    primary = re.sub(
        r"\s+\b(entering|turning|looking|watching|holding|lifting|raising|lowering|"
        r"reaching|registering|showing|moving|stepping|taking|walking|revealing)\b.*$",
        "",
        primary,
        flags=re.IGNORECASE,
    ).strip(" ,:;-–—")
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


def first_frame_image_direction(shot: ShotPlan) -> str:
    """Compile a static composition note without leaking the future action."""
    return (
        f"{shot.framing}; {shot.camera_angle}; frame {first_frame_target(shot)}. "
        "This is the still first frame before the subject action begins."
    )


def compile_image_prompt(bible: VisualBible, shot: ShotPlan) -> str:
    target = first_frame_target(shot)
    absent_prop = prop_is_absent(shot.prop_state)
    family = framing_family(shot.framing)
    fixed_installed_prop = bool(
        re.search(
            r"\b(mounted|fixed|built[- ]?in|attached|installed)\b",
            bible.important_prop,
            re.IGNORECASE,
        )
    )
    ignored_prop_words = {
        "cracked",
        "unpowered",
        "inch",
        "flat",
        "mounted",
        "fixed",
        "built",
        "attached",
        "installed",
        "wall",
        "opposite",
        "realistic",
        "the",
        "and",
        "with",
        "from",
    }
    prop_words = {
        token
        for token in re.findall(r"[a-z0-9]+", bible.important_prop.casefold())
        if len(token) >= 3 and token not in ignored_prop_words
    }
    target_words = set(re.findall(r"[a-z0-9]+", target.casefold()))
    prop_alias_targeted = any(
        re.search(pattern, bible.important_prop, re.IGNORECASE)
        and re.search(pattern, target, re.IGNORECASE)
        for pattern in (
            r"\b(tv|television|screen)\b",
            r"\b(mirror|reflection)\b",
            r"\b(photo|photograph|polaroid|print)\b",
            r"\b(clock|painting|picture|shelf|lamp)\b",
        )
    )
    fixed_prop_offscreen = (
        fixed_installed_prop
        and family in {"close", "detail", "pov"}
        and not (prop_alias_targeted or bool(prop_words & target_words))
    )
    rendered_prop_absent = absent_prop or fixed_prop_offscreen
    optional_prop_bible = (
        "" if rendered_prop_absent else f"\n{prop_bible_text(bible)}"
    )
    image_start_state = (
        shot.start_state.rsplit("| PROP:", 1)[0].rstrip()
        if rendered_prop_absent
        else shot.start_state
    )
    prop_constraint = (
        "EMPTY_FRAME_CONSTRAINT: Keep every visible furniture surface bare. Add no loose "
        "objects, graphic elements, or inset imagery."
        if absent_prop
        else (
            "OFFSCREEN_FIXED_PROP_CONSTRAINT: The installed set fixture remains unchanged in "
            "continuity but must stay entirely outside this frame."
            if fixed_prop_offscreen
            else (
                "VISIBLE_PROP_CONSTRAINT: Keep the declared prop at realistic hand-held scale. "
                "Never enlarge it, duplicate it, float it, or render it as a graphic overlay."
            )
        )
    )
    context_blocks = tuple(
        block
        for label, value in (
            ("SHOT_ENVIRONMENT_STATE_AT_START", shot.environment_state),
            ("SHOT_IMAGE_DIRECTION", first_frame_image_direction(shot)),
        )
        if not _context_mentions_absent_physical_prop(value, bible, absent_prop)
        for block in (f"{label}: {value}",)
    )
    shot_blocks = (
        f"STORYBOARD_SHOT: {shot.id}; beat {shot.order}",
        f"SHOT_COMPOSITION: {shot.framing}; {shot.camera_angle}; {shot.subject_position}",
        f"SHOT_FIRST_FRAME_TARGET: {target}",
        f"SHOT_START_STATE: {image_start_state}",
        *context_blocks,
        (
            "SHOT_SURFACE_STATE: Every visible furniture surface is bare and empty."
            if absent_prop
            else (
                "SHOT_OFFSCREEN_CONTINUITY: The installed set fixture is outside this crop."
                if fixed_prop_offscreen
                else f"SHOT_PROP_STATE_AT_START: {shot.prop_state}"
            )
        ),
        (
            "SHOT_FIRST_FRAME_DIRECTION: Render only the declared composition, "
            "SHOT_START_STATE, SHOT_ENVIRONMENT_STATE_AT_START, SHOT_IMAGE_DIRECTION, "
            "and the declared visible surface or prop state."
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
            "anything declared off-screen must not appear. The declared surface or prop state "
            "is the only authority for object presence and visibility. For an insert, detail, macro, or "
            "extreme close-up, show only the specified object or body region—no full face, "
            "full body, or wide room. When surfaces are declared empty, keep them empty."
        ),
    )
    return (
        f"{immutable_bible_text(bible)}{optional_prop_bible}\n"
        + "\n".join(shot_blocks)
    )


def compile_framing_retry_correction(shot: ShotPlan, failure_message: str) -> str:
    """Turn a rejected frame diagnostic into a bounded composition correction."""
    target = first_frame_target(shot)
    diagnostic = " ".join(failure_message.split())
    if ":" in diagnostic:
        diagnostic = diagnostic.rsplit(":", 1)[-1].strip()
    diagnostic = diagnostic[:500].rstrip()
    return "\n".join(
        (
            "RETRY_CORRECTION: The previous generated image was rejected by framing "
            "validation. Discard its camera placement and do not repeat its composition.",
            f"REJECTED_FRAME_DIAGNOSTIC: {diagnostic}",
            (
                f"RETRY_COMPOSITION_TARGET: Create a new {shot.framing} of exactly {target}. "
                "The continuity reference controls identity, set design, wardrobe, and lighting "
                "only; it does not control camera position, crop, or visible context."
            ),
            "RETRY_FRAME_VISIBILITY_CONTRACT: "
            + framing_visibility_contract(shot.framing, target),
        )
    )


def should_reset_reference_for_retry(
    shot: ShotPlan, retry_count: int, error_code: str | None
) -> bool:
    """Drop the wide edit reference for late actor-free insert retries.

    Qwen's edit model can preserve a wide master too literally even when a close
    framing contract excludes the actor and room. A late shadow insert is safer as
    a bible-locked text-to-image composition because it contains no identity-bearing
    face, body, wardrobe, or movable prop.
    """
    if error_code not in {"FRAMING_VALIDATION_FAILED", "CROP", "CROPPING"}:
        return False
    if retry_count < 2:
        return False
    target = first_frame_target(shot)
    return (
        framing_family(shot.framing) in {"close", "detail"}
        and bool(re.search(r"\bshadow\b", target, re.IGNORECASE))
    )


def should_use_set_plate_for_retry(
    shot: ShotPlan, retry_count: int, error_code: str | None
) -> bool:
    """Use an actor-free crop of the master when OTS edits keep duplicating a person."""
    if error_code not in {"FRAMING_VALIDATION_FAILED", "CROP", "CROPPING"}:
        return False
    target = first_frame_target(shot)
    return (
        retry_count >= 2
        and framing_family(shot.framing) == "over-shoulder"
        and bool(
            re.search(
                r"\b(tv|television|screen|mirror|reflection)\b",
                target,
                re.IGNORECASE,
            )
        )
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
