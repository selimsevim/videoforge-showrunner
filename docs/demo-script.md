# Recording-ready demo narrative

This route uses the six winning images from a completed live Qwen Cloud rehearsal. It
adds clearly labeled local editorial animatics for the six shots and final cut, loads
locally, makes no provider call, and spends no credits. Keep the server in normal Qwen
mode so the separate live production path remains real.

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

## 1:25–1:55 — Show the control system

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

## 1:55–2:35 — Production and final cut

Return to **Storyboard**, then click **View six shot clips**. Play one or two five-second
clips to show the shot order and pacing, then click **View assembled preview** and play
the 30-second cut. The page labels these as local editorial animatics: the visuals are
the real Qwen keyframes with a restrained push-in, not claimed Wan character motion.

“Opening this rehearsal made zero calls. In a new production, storyboard and video calls
start only after explicit confirmation. Jobs run independently, are persisted in SQLite,
and can be retried shot by shot without discarding successful frames.”

Do not click **Regenerate image** during the recording unless you intend to make a paid
Qwen call.

## 2:35–3:00 — Close

“VideoForge makes Qwen behave like a production team: plan the story, lock the world,
choose the lens for each beat, approve the evidence, and animate only what survived the
human checkpoint. It is a film workflow—not six unrelated generations.”

## Live fallback

If the network is slow, remain in the recorded rehearsal. Its six keyframes are the exact
saved output of the live run; its clips are local editorial animatics, not mock Qwen API
responses. If you demonstrate live generation, create a separate project so the
recording-ready rehearsal stays unchanged.
