# Recording-ready demo narrative

This route uses the six winning images from a completed live Qwen Cloud rehearsal. It
loads locally, makes no provider call, spends no credits, and opens directly at the
storyboard. Keep the server in normal Qwen mode so the production path remains real.

## Before recording

1. Run `npm start` and open `http://127.0.0.1:8000`.
2. Click **Start another** if an older project is already open.
3. Start the recording on the Concept screen.
4. Click **Open recorded Qwen demo**. The six-shot storyboard should appear immediately.

## 0:00–0:25 — The premise

“A film is not six pretty images. It is one world, revealed through six deliberate
camera decisions. VideoForge turns a story prompt into a controllable production.”

Point to the project prompt:

> A woman enters her room in the dark and sees a shadow moving independently.

“For this recording I am opening a completed live Qwen rehearsal, so we can inspect the
result immediately instead of watching a generation queue. The normal buttons still use
the real paid Qwen production path and explicit approval gates.”

Click **Open recorded Qwen demo**.

## 0:25–1:25 — Read the storyboard as a scene

Scroll through the six frames and narrate the cut:

1. **Establish — the dark room.** “The wide master gives us the bedroom, door, bed,
   dresser, TV, Elena, and the fixed blue light direction.”
2. **Discover — her attention shifts.** “The medium shot tells us where she looks. We
   move closer because the story has moved from space to attention.”
3. **Inspect — the impossible shadow.** “Now the actor disappears. The close detail is
   genuinely about the evidence: wall texture and one raised shadow hand.”
4. **Recognize — the TV becomes a mirror.** “The tight over-shoulder connects Elena's
   eyeline to the cracked TV. Her real posture and the impossible shadow share one frame.”
5. **Dread — she understands.** “A face close-up pauses the investigation for one simple,
   readable reaction.”
6. **Reveal — the shadow is not hers.** “The final TV insert supplies physical proof:
   Elena's hands are lowered, but the reflected shadow hand is raised.”

“The order is not a fixed wide-medium-close template. Qwen chooses shot size from the
narrative job of each beat. Here the sequence contracts from room, to gaze, to evidence,
then uses reflection and reaction to complete the reveal.”

## 1:25–2:10 — Show the control system

Open one prompt preview, then click **Edit prompt** to show the plan.

Point out:

- the immutable character, room, wardrobe, prop, light, palette, and camera bible;
- a different primary subject and framing reason for every shot;
- first-frame state separated from the physical action;
- image visibility contracts that prevent a close-up from falling back to a full person;
- motion prompts containing one action and one static camera instruction;
- recorded model, seed, retry, and prompt-hash metadata.

“The prompt is compiled like a call sheet. Shared facts remain fixed; only the shot's
composition and physical beat change.”

## 2:10–2:40 — Human checkpoints and production

Return to **Storyboard**. Approve one image if you want to demonstrate the checkpoint.
Do not click **Regenerate image** or **Generate videos** during the recording unless you
intend to make paid Qwen calls.

“Opening this rehearsal made zero calls. In a new production, storyboard and video calls
start only after explicit confirmation. Jobs run independently, are persisted in SQLite,
and can be retried shot by shot without discarding successful frames.”

## 2:40–3:00 — Close

“VideoForge makes Qwen behave like a production team: plan the story, lock the world,
choose the lens for each beat, approve the evidence, and animate only what survived the
human checkpoint. It is a film workflow—not six unrelated generations.”

## Live fallback

If the network is slow, remain in the recorded rehearsal. It is the exact saved output of
the live run, not mock media. If you do demonstrate live generation, create a separate
project so the recording-ready rehearsal stays unchanged.
