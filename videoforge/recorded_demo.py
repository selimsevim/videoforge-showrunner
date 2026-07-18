from __future__ import annotations

from dataclasses import dataclass

from .prompting import compile_all
from .schemas import Narrative, ProductionPlan, ShotPlan, VisualBible


RECORDED_DEMO_PROMPT = (
    "A woman enters her room in the dark and sees a shadow moving independently."
)


@dataclass(frozen=True)
class RecordedFrame:
    shot_id: str
    filename: str
    model: str
    seed: int
    retry_count: int
    prompt_hash: str


RECORDED_FRAMES = (
    RecordedFrame(
        "shot-01",
        "shot-01.png",
        "qwen-image-2.0",
        1777431065,
        0,
        "5e0f43a2c00b4c2edcc7fd763fef83117c1f6351cf4e3d15f963870900a32429",
    ),
    RecordedFrame(
        "shot-02",
        "shot-02.png",
        "qwen-image-2.0-pro",
        1777535794,
        1,
        "bc083a02858be2bac2da78cb73b0b3d9fd6b8e0b81d89a7cbdac1e56205e14ee",
    ),
    RecordedFrame(
        "shot-03",
        "shot-03.png",
        "qwen-image-2.0-pro",
        1777954710,
        5,
        "e607016635ab4ce360b42de59fb7b24f6ad1ce620a101d08a13564e3450e185d",
    ),
    RecordedFrame(
        "shot-04",
        "shot-04.png",
        "qwen-image-2.0-pro",
        1777954710,
        5,
        "262e0131bb9169a456aab1ca26786eb206361437d4c13c438459f71803b1b473",
    ),
    RecordedFrame(
        "shot-05",
        "shot-05.png",
        "qwen-image-2.0-pro",
        1777535794,
        1,
        "05734549d0473a32c3b31a1430453d642d891c84075f14fc9e054a314cf6653e",
    ),
    RecordedFrame(
        "shot-06",
        "shot-06.png",
        "qwen-image-2.0-pro",
        1777535794,
        1,
        "39a15ca6f8416f2cf9ba485ae072168a3c12d6894e8c42e7569b102458b9393e",
    ),
)


def create_recorded_demo_plan(project_id: str) -> ProductionPlan:
    """Rebuild the approved plan from the recorded July 2026 Qwen rehearsal."""

    bible = VisualBible(
        characterIdentity="Elena, late 20s, sharp-featured, tired eyes, no jewelry",
        faceAndHair=(
            "Shoulder-length dark brown hair, slightly tangled, parted left, no makeup"
        ),
        wardrobe="Gray cotton sleep shirt (mid-thigh), black knit shorts, bare feet",
        importantProp=(
            "A cracked, unpowered 55-inch flat-screen TV mounted on the wall "
            "opposite the door"
        ),
        environment=(
            "Small urban bedroom: white walls, single window with closed blinds, "
            "unmade twin bed against left wall, dresser against right wall, door on rear wall"
        ),
        timeOfDay="Late night",
        lighting=(
            "Single weak source: cool blue streetlight seeping under the door, casting "
            "a long horizontal gradient across floor and lower wall; rest of room in deep shadow"
        ),
        palette="Desaturated cool grays, charcoal blacks, muted steel blue highlights",
        cameraLanguage=(
            "Precise, anchored framing; no handheld; slow camera moves only when the "
            "subject's attention shifts decisively"
        ),
        visualStyle=(
            "Cinematic realism — shallow depth of field only in close-ups; textures "
            "visible (fabric weave, wall texture, TV glass)"
        ),
        negativePrompt=(
            "no text, no logos, no lens flare, no motion blur, no CGI, no blood, no "
            "monsters, no supernatural glow, no floating objects"
        ),
    )
    still = (
        "BODY: standing just inside doorway, facing room center, weight on left foot | "
        "HANDS: right hand withdrawn, fingers slightly curled, left hand still at side | "
        "PROP: none"
    )
    forward = (
        "BODY: standing just inside doorway, weight shifted forward onto both feet, "
        "chin tilted down 10 degrees | HANDS: right hand withdrawn, fingers slightly "
        "curled, left hand still at side | PROP: none"
    )
    downcast = forward.replace(
        "chin tilted down 10 degrees |", "chin tilted down 10 degrees, eyes downcast |"
    )
    rows = (
        dict(
            purpose="Establish — the dark room",
            framing="Wide master shot",
            angle="Eye-level, slightly high to include the door frame",
            position="standing just inside doorway, facing room center, weight on left foot",
            target="Elena entering her bedroom",
            reason="Establishes the door, bed, dresser, TV, and the room's fixed geography.",
            start=(
                "BODY: standing just inside doorway, facing room center, weight on left foot | "
                "HANDS: relaxed at sides, palms inward | PROP: none"
            ),
            action="She reaches forward and flicks the wall switch up with her right index finger.",
            end=still,
            environment=(
                "Room fully dark except for a narrow band of cool blue light across the "
                "floor and baseboard, originating under the door."
            ),
            delta=(
                "Wide view: doorway open behind Elena, unmade bed left, dresser right, "
                "black TV centered on far wall, blue light stripe across floor."
            ),
            seed=1777431065,
            video_seed=9430,
        ),
        dict(
            purpose="Discover — her attention shifts",
            framing="Medium shot, eye-level",
            angle="Slightly angled right to show the wall behind her left shoulder",
            position="standing just inside doorway, facing room center, weight on left foot",
            target="Elena turning her head toward the far wall",
            reason="Keeps her face and eyeline readable while preserving the wall as her target.",
            start=still,
            action="She turns her head sharply left and fixes her eyes on the far wall.",
            end=still,
            environment=(
                "The same room and lighting; a tall human-shaped shadow stretches up the "
                "wall beside the TV."
            ),
            delta=(
                "Medium shot: Elena in profile, eyes fixed on the far wall where a tall "
                "shadow falls beside the black TV."
            ),
            seed=1777535794,
            video_seed=3857,
        ),
        dict(
            purpose="Inspect — the impossible shadow",
            framing="Close-up on wall shadow",
            angle="Eye-level, perpendicular to the wall",
            position="Elena is completely off-screen",
            target="The raised-hand shadow on the wall",
            reason="Removes the actor and room overview so the autonomous shadow owns the frame.",
            start=still,
            action="The shadow holds one hand raised while Elena remains off-screen.",
            end=still,
            environment=(
                "Only the wall texture and the elongated raised-hand shadow are visible."
            ),
            delta=(
                "Tight actor-free detail: wall texture and a crisp human shadow with its "
                "right hand raised; no face, body, bed, window, or room overview."
            ),
            seed=1777954710,
            video_seed=2108,
        ),
        dict(
            purpose="Recognize — the TV becomes a mirror",
            framing="Tight over-the-shoulder shot",
            angle="Slightly low over Elena's right shoulder toward the TV",
            position="Elena's near shoulder and hair occupy one edge of frame",
            target="Elena's reflection in the cracked black TV screen",
            reason="Juxtaposes her lowered hands with the raised shadow inside one eyeline.",
            start=still,
            action="She takes one small step forward and lowers her chin toward the reflection.",
            end=forward,
            environment=(
                "The cracked TV glass acts as a dark mirror; Elena's faint reflection keeps "
                "both hands lowered."
            ),
            delta=(
                "Tight over-shoulder composition: one near shoulder at frame edge; cracked "
                "black TV fills the view and reflects Elena with both hands down."
            ),
            seed=1777954710,
            video_seed=7369,
        ),
        dict(
            purpose="Dread — she understands",
            framing="Tight close-up on Elena's face",
            angle="Eye-level, centered",
            position="Only Elena's face and upper neck fill the frame",
            target="Elena's face registering the realization",
            reason="Pauses the visual investigation for one clean, readable emotional beat.",
            start=forward,
            action="She presses her lips together and lowers her eyes without blinking.",
            end=downcast,
            environment="The bedroom falls fully out of focus behind her.",
            delta=(
                "Tight face close-up: Elena's eyes lowered and lips pressed; no full body "
                "or readable room geography."
            ),
            seed=1777535794,
            video_seed=5216,
        ),
        dict(
            purpose="Reveal — the shadow is not hers",
            framing="Insert detail on TV reflection",
            angle="Perpendicular to the TV screen, tight frame",
            position="Elena appears only as a faint reflection in the glass",
            target="The cracked TV reflection with a raised shadow hand",
            reason="Ends on physical evidence: her hands are down, but the reflected shadow is raised.",
            start=downcast,
            action="Elena remains still as the raised shadow hand holds in the reflection.",
            end=downcast,
            environment="Only cracked black TV glass and the layered reflection are visible.",
            delta=(
                "Full-frame insert of cracked black TV glass: Elena's faint reflection has "
                "both hands lowered while a distinct shadow hand is raised, palm forward."
            ),
            seed=1777535794,
            video_seed=6813,
        ),
    )
    shots = [
        ShotPlan(
            id=f"shot-{order:02d}",
            order=order,
            narrativePurpose=row["purpose"],
            framing=row["framing"],
            cameraAngle=row["angle"],
            subjectPosition=row["position"],
            primarySubject=row["target"],
            framingReason=row["reason"],
            startState=row["start"],
            subjectAction=row["action"],
            endState=row["end"],
            environmentState=row["environment"],
            environmentMotion="None.",
            cameraMotion="Static camera.",
            propState="none",
            imageDelta=row["delta"],
            imagePrompt="pending compilation",
            motionPrompt="pending compilation",
            durationSeconds=5,
            imageSeed=row["seed"],
            videoSeed=row["video_seed"],
        )
        for order, row in enumerate(rows, 1)
    ]
    return ProductionPlan(
        projectId=project_id,
        title="The Shadow — recorded Qwen rehearsal",
        logline=(
            "A woman enters her dark bedroom and sees a shadow moving independently—"
            "then realizes it is not hers."
        ),
        genre="Psychological horror",
        intendedEmotion=(
            "Dread through physical dissonance: her body remains still while the shadow "
            "betrays agency."
        ),
        narrative=Narrative(
            setup=(
                "Elena enters her bedroom at night. The light switch fails, but the room's "
                "geography is clear in a thin strip of streetlight."
            ),
            escalation=(
                "Her gaze leads us from the room to an actor-free shadow detail, then into "
                "the cracked TV that reflects her real posture."
            ),
            resolution=(
                "After one close-up registers her realization, the TV insert proves the "
                "raised shadow hand cannot belong to her."
            ),
        ),
        visualBible=bible,
        shots=compile_all(bible, shots),
    )
