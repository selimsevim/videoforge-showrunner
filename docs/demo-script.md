# Three-minute hackathon demo

## 0:00–0:25 — The problem

“Text-to-video is impressive one clip at a time, but a film is a continuity problem. Three independent prompts produce three different actors, sets, and camera systems. VideoForge turns Qwen Cloud into an AI showrunner.”

Show the Concept screen. Use the default prompt:

> A woman finds a Polaroid photograph of herself sleeping in her bedroom, but she lives alone.

Click **Load demo project**.

## 0:25–1:05 — The plan

Show the three-beat story, intended emotional progression, and immutable visual bible. Expand the shot list.

Point out:

- one character and one bedroom;
- the exact same sweater, Polaroid, light direction, palette, and camera language;
- distinct establish, recognize, and reveal functions;
- deterministic seeds;
- image prompts compiled from one shared bible;
- motion-only video prompts.

“Nothing free-form flows directly into paid generation. Pydantic validates the plan and the consistency guardian repairs prompt drift.”

Click **Approve Plan & Generate Storyboard**.

## 1:05–1:45 — The human checkpoint

As the three mock keyframes complete, explain that real mode uses `qwen-image-2.0`, `prompt_extend=false`, fixed 16:9 framing, and one output per shot.

Approve each image. Run the consistency check and show the scores/differences.

“The model advises; the filmmaker decides. A score never silently spends credits.”

Click **Generate Videos**.

## 1:45–2:25 — Production

Show persisted per-shot states: queued, generating, polling, downloading, verifying, completed. Play an individual clip.

Point out the approved source keyframe, motion-only prompt, 720P resolution, seed, H.264/30fps/duration verification, and independent retry control.

“Wan is not asked to recast the scene. It is asked to animate this exact frame.”

## 2:25–3:00 — Final cut and proof

Click **Assemble Final Preview**. Toggle between the assembled preview and individual shots. Show models, cost estimate, retries, generation time, and downloads.

Close with:

“VideoForge makes generation constrained, inspectable, recoverable, and collaborative. It uses Qwen for decisions, Qwen Image for the locked world, Wan for motion, and a human for approval—the minimum viable production studio, not another prompt box.”

