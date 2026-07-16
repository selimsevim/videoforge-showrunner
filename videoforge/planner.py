from __future__ import annotations

import hashlib

from .prompting import compile_all
from .schemas import Narrative, ProductionPlan, ProjectInput, ShotPlan, VisualBible


DEMO_PROMPT = (
    "A woman finds a Polaroid photograph of herself sleeping in her bedroom, "
    "but she lives alone."
)


def deterministic_seed(project_id: str, order: int, kind: str) -> int:
    digest = hashlib.sha256(f"{project_id}:{order}:{kind}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % (2**31 - 1)


def create_mock_plan(project_id: str, project: ProjectInput) -> ProductionPlan:
    horror_demo = any(
        word in project.story_prompt.lower()
        for word in ("photograph", "photo", "polaroid", "sleeping", "lives alone")
    )
    if horror_demo:
        title = project.title or "The Third Exposure"
        logline = (
            "Living alone, Mara finds a fresh Polaroid of herself asleep in the "
            "room where she is standing—and the photograph is not empty."
        )
        narrative = Narrative(
            setup="Mara discovers a Polaroid on the floor beside her bedroom window.",
            escalation="She lifts it and recognizes herself asleep in the same room.",
            resolution=(
                "A new silhouette appears inside the photograph as Mara turns "
                "toward the dark doorway."
            ),
        )
        bible = VisualBible(
            characterIdentity=(
                "Mara, a solitary woman in her early thirties, pale oval face, "
                "slender build, guarded expression"
            ),
            faceAndHair=(
                "chin-length straight black bob with blunt fringe, grey-green eyes, "
                "natural skin texture, no glasses"
            ),
            wardrobe=(
                "the same oversized charcoal-grey knit sweater and black lounge trousers"
            ),
            importantProp=(
                "one square white-bordered instant Polaroid with a slightly yellowed frame"
            ),
            environment=(
                "the same modest bedroom, unmade bed left of frame, tall window with "
                "sheer curtain, dark open doorway opposite the window, worn wooden floor"
            ),
            timeOfDay="blue hour before dawn",
            lighting=(
                "cold window light from camera left, one dim tungsten bedside lamp, "
                "doorway remains nearly black"
            ),
            palette="desaturated blue-grey, charcoal, faded cream, restrained amber",
            cameraLanguage=(
                "cinematic 50mm lens language, eye-level camera, shallow depth of field, "
                "restrained locked compositions, subtle film grain"
            ),
            visualStyle=project.visual_style,
            negativePrompt=(
                "extra people, duplicate subject, changed hairstyle, changed wardrobe, "
                "different room, extra photographs, text, logo, watermark, deformed hands, "
                "oversaturated colours, cartoon style, distorted face"
            ),
        )
        raw_shots = [
            dict(
                purpose="Establish — discovery",
                framing="medium-wide shot",
                angle="eye level",
                position="Mara stands right of centre beside the window",
                action="Mara crouches beside the Polaroid on the floor",
                end=(
                    "Mara crouches beside the Polaroid with her right hand above it; "
                    "her left hand rests on her knee"
                ),
                state="bedroom geometry is fully established; Polaroid lies face-up by her foot",
                env_motion="None.",
                camera="Static camera.",
                prop="Polaroid face-up on the floor, its image not yet readable",
                end_prop="Polaroid face-up on the floor, its image not yet readable",
                delta=(
                    "medium-wide establishing shot, Mara right of centre beside the window, "
                    "looking down at the single Polaroid on the floor, doorway visible deep "
                    "in background, restrained unease"
                ),
            ),
            dict(
                purpose="Escalate — recognition",
                framing="tight medium close-up",
                angle="slight over-shoulder angle",
                position="Mara fills the left half of frame; photograph held near her face",
                action="Mara lifts the Polaroid to eye level with her right hand",
                end=(
                    "Mara holds the Polaroid at eye level in her right hand; her left hand "
                    "rests on her knee"
                ),
                state="same bedroom falls softly out of focus behind her",
                env_motion="None.",
                camera="Slow push-in.",
                prop="Polaroid face-up on the floor, its image not yet readable",
                end_prop=(
                    "The same Polaroid is upright in her right hand and visibly shows Mara "
                    "asleep on the same bed"
                ),
                delta=(
                    "tight medium close-up from a slight over-shoulder angle, Mara crouched "
                    "with the single Polaroid still on the floor near her right hand"
                ),
            ),
            dict(
                purpose="Reveal — presence",
                framing="medium shot",
                angle="eye level",
                position="Mara foreground left; dark doorway occupies background right",
                action="Mara slowly turns her head toward the dark doorway",
                end=(
                    "Mara faces the dark doorway while holding the Polaroid at eye level "
                    "in her right hand"
                ),
                state="same room and lighting; doorway remains empty and nearly black",
                env_motion="None.",
                camera="Static camera.",
                prop=(
                    "The same Polaroid remains upright in her right hand and shows Mara "
                    "asleep on the same bed"
                ),
                end_prop=(
                    "The same Polaroid remains upright in her right hand and shows Mara "
                    "asleep on the same bed"
                ),
                delta=(
                    "medium shot, Mara foreground left turning toward the dark doorway, "
                    "holding the same Polaroid where a single indistinct silhouette is now "
                    "visible behind her sleeping self; the real doorway stays empty"
                ),
            ),
        ]
        intended = "quiet curiosity → intimate dread → lingering paranoia"
    else:
        title = project.title
        logline = (
            f"A solitary protagonist confronts an unsettling discovery: {project.story_prompt}"
        )
        narrative = Narrative(
            setup="The protagonist notices one impossible detail in a familiar room.",
            escalation="A closer look makes the personal implication undeniable.",
            resolution="A restrained final reveal changes the meaning of the discovery.",
        )
        bible = VisualBible(
            characterIdentity="one solitary adult protagonist with a calm, readable face",
            faceAndHair="short dark hair, natural skin texture, no eyewear",
            wardrobe="the same charcoal overshirt and black trousers in every shot",
            importantProp="one small weathered personal object with fixed design",
            environment="one quiet, sparsely furnished apartment room",
            timeOfDay="late overcast afternoon",
            lighting="soft window light from camera left with one practical lamp",
            palette="muted slate, charcoal, faded cream, restrained amber",
            cameraLanguage="eye-level 50mm lens, stable compositions, shallow focus",
            visualStyle=project.visual_style,
            negativePrompt=(
                "extra people, duplicate subject, wardrobe changes, location changes, "
                "extra props, text, logo, watermark, distorted anatomy"
            ),
        )
        raw_shots = [
            dict(
                purpose="Establish",
                framing="medium-wide shot",
                angle="eye level",
                position="protagonist slightly right of centre",
                action="The protagonist notices the object",
                end=(
                    "The protagonist looks at the object on the table with both hands "
                    "at their sides"
                ),
                state="room geography clearly established",
                env_motion="None.",
                camera="Static camera.",
                prop="object rests on a nearby table",
                end_prop="The object rests on the nearby table",
                delta="medium-wide discovery composition with the object clearly visible",
            ),
            dict(
                purpose="Escalate",
                framing="medium close-up",
                angle="eye level",
                position="protagonist centred with object in foreground",
                action="The protagonist lifts the object to eye level",
                end=(
                    "The protagonist holds the object at eye level in one hand; the other "
                    "hand remains at their side"
                ),
                state="same room softly out of focus",
                env_motion="None.",
                camera="Slow push-in.",
                prop="The object rests on the nearby table",
                end_prop="The same object is held carefully at eye level in one hand",
                delta="medium close-up emphasizing the hands and the unchanged object",
            ),
            dict(
                purpose="Reveal or resolve",
                framing="medium shot",
                angle="eye level",
                position="protagonist foreground left with negative space behind",
                action="The protagonist turns toward the source of the revelation",
                end=(
                    "The protagonist faces the source while holding the object at eye level"
                ),
                state="same room and fixed lighting",
                env_motion="None.",
                camera="Static camera.",
                prop="same object remains visible and unchanged",
                end_prop="The same object remains visible and unchanged",
                delta="medium final reveal composition with controlled negative space",
            ),
        ]
        intended = "curiosity → apprehension → uneasy recognition"

    if project.shot_count > 3:
        bridge_shots = []
        for index in range(project.shot_count - 3):
            bridge_shots.append(
                dict(
                    purpose=f"Bridge {index + 1} — deepen the implication",
                    framing="controlled medium close-up",
                    angle="eye level",
                    position="the same protagonist remains centred in the established room",
                    action=f"The protagonist moves one thumb to edge mark {index + 1}",
                    end=(
                        "The protagonist holds the same prop at eye level with one thumb "
                        f"resting at edge mark {index + 1}"
                    ),
                    state="the same environment and lighting remain unchanged",
                    env_motion="None.",
                    camera="Static camera.",
                    prop="the same important prop remains visible with unchanged design",
                    end_prop="The same important prop remains visible with unchanged design",
                    delta=(
                        "controlled bridge composition in the same room, preserving the "
                        "protagonist, wardrobe, prop design, light direction, and palette"
                    ),
                )
            )
        raw_shots = [raw_shots[0], raw_shots[1], *bridge_shots, raw_shots[2]]

    duration = max(
        2, min(5, round(project.target_duration_seconds / project.shot_count))
    )
    shots: list[ShotPlan] = []
    previous_end = ""
    for index, raw in enumerate(raw_shots[: project.shot_count], 1):
        start_state = previous_end or (
            f"BODY: {raw['position'].rstrip('.')}. | "
            "HANDS: Both hands are visible and still. | "
            f"PROP: {raw['prop'].rstrip('.')}"
        )
        end_state = (
            f"BODY: {raw['end'].rstrip('.')}. | "
            "HANDS: Both hands hold the completed action position. | "
            f"PROP: {raw['end_prop'].rstrip('.')}"
        )
        start_body = start_state.split("|", 1)[0].removeprefix("BODY:").strip()
        start_prop = start_state.rsplit("| PROP:", 1)[-1].strip()
        shots.append(
            ShotPlan(
                id=f"shot-{index:02d}",
                order=index,
                narrativePurpose=raw["purpose"],
                framing=raw["framing"],
                cameraAngle=raw["angle"],
                subjectPosition=start_body,
                primarySubject="the protagonist and the important prop",
                framingReason=(
                    "This framing clearly shows the named physical action and primary subject."
                ),
                startState=start_state,
                subjectAction=raw["action"],
                endState=end_state,
                environmentState=raw["state"],
                environmentMotion=raw["env_motion"],
                cameraMotion=raw["camera"],
                propState=start_prop,
                imageDelta=raw["delta"],
                imagePrompt="pending compilation",
                motionPrompt="pending compilation",
                durationSeconds=duration,
                imageSeed=deterministic_seed(project_id, index, "image"),
                videoSeed=deterministic_seed(project_id, index, "video"),
            )
        )
        previous_end = end_state
    shots = compile_all(bible, shots)
    return ProductionPlan(
        projectId=project_id,
        title=title,
        logline=logline,
        genre=project.genre,
        intendedEmotion=intended,
        narrative=narrative,
        visualBible=bible,
        shots=shots,
    )
