# Consistency strategy

VideoForge's governing rule is: **lock the world in images first; ask the video model only to animate those images.**

## Immutable visual bible

The Visual Director separates continuity into fixed blocks:

- `CHARACTER_BIBLE`: identity, face, hair, wardrobe
- `ENVIRONMENT_BIBLE`: room, time of day, prop design
- `STYLE_BIBLE`: visual medium, lighting, palette
- `CAMERA_BIBLE`: lens and composition language
- `NEGATIVE_BIBLE`: exclusions sent as the provider negative prompt

`immutable_bible_text()` serializes the first four blocks once. Every image prompt is compiled as:

```text
CHARACTER_BIBLE: ...
ENVIRONMENT_BIBLE: ...
STYLE_BIBLE: ...
CAMERA_BIBLE: ...
SHOT_IMAGE_DELTA: ...
```

The prefix is byte-identical across all shots. The consistency guardian detects a missing or paraphrased prefix and recompiles it before the plan is shown or saved.

## Motion-only video prompts

Wan receives the approved keyframe plus:

```text
SUBJECT_MOTION. ENVIRONMENT_MOTION. CAMERA_MOTION.
Preserve facial identity, wardrobe, prop design, lighting, and room geometry.
```

The video prompt does not redescribe the actor or set. Every shot has one restrained subject action, one subtle environment motion, and one simple camera instruction.

## Human gates

The plan is editable before image calls. Every keyframe must then be approved before videos can start. Consistency inspection returns scores and visible differences, but it never regenerates automatically.

## Technical verification

Every MP4 is checked for H.264, 720P geometry, approximately 30 fps, and ≤5.2 second duration. These checks prove delivery compliance; they are separate from subjective continuity.

## Known failure modes

- Fine facial structure and jewelry can drift between independently generated keyframes.
- Negative prompts do not guarantee that background figures are absent.
- Expired remote image URLs cannot seed a new Wan task; the local image remains saved, but a real provider keyframe must be regenerated or uploaded.
- A high automated consistency score is evidence, not creative authority. The user remains the final approver.

