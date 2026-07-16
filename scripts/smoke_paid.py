#!/usr/bin/env python3
"""Explicitly paid one-plan, one-image, one-video Qwen Cloud smoke test."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from videoforge.config import Settings
from videoforge.planner import DEMO_PROMPT
from videoforge.providers.qwen_cloud import QwenCloudProvider
from videoforge.schemas import ProjectInput, ProviderImageRequest, ProviderVideoRequest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-paid-calls",
        action="store_true",
        help="required acknowledgement that real media calls incur charges",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.confirm_paid_calls:
        print(
            "Refusing to call Qwen Cloud. Re-run with --confirm-paid-calls only "
            "when you explicitly intend to create one paid image and one paid video."
        )
        return 2

    settings = Settings.from_env(provider="qwen")
    provider = QwenCloudProvider(settings)
    project_id = f"paid-smoke-{int(time.time())}"
    output = Path("smoke-output") / project_id
    output.mkdir(parents=True, exist_ok=True)

    print("1/3 Qwen structured planning call…")
    plan = provider.create_production_plan(
        project_id,
        ProjectInput(
            title="Paid Smoke Test",
            storyPrompt=DEMO_PROMPT,
            genre="Psychological horror",
            visualStyle="Cinematic realism",
            targetDurationSeconds=9,
        ),
    )
    shot = plan.shots[0]

    print("2/3 Qwen image call (billable)…")
    image = provider.generate_image(
        ProviderImageRequest(
            project_id=project_id,
            shot_id=shot.id,
            prompt=shot.image_prompt,
            negative_prompt=plan.visual_bible.negative_prompt,
            seed=shot.image_seed,
        ),
        output / "shot-01.png",
    )
    if not image.get("remote_url"):
        raise RuntimeError("Qwen image call returned no remote first-frame URL")

    print("3/3 Wan 2.7 three-second video call (billable)…")
    video_request = ProviderVideoRequest(
        project_id=project_id,
        shot_id=shot.id,
        first_frame_url=image["remote_url"],
        prompt=shot.motion_prompt,
        negative_prompt=plan.visual_bible.negative_prompt,
        seed=shot.video_seed,
        duration_seconds=3,
    )
    submitted = provider.generate_video(video_request)
    while True:
        result = provider.get_video_task(submitted["task_id"])
        print(f"  task status: {result['task_status']}")
        if result["task_status"] == "SUCCEEDED":
            break
        if result["task_status"] in {"FAILED", "CANCELED", "UNKNOWN"}:
            raise RuntimeError(f"Wan task ended as {result['task_status']}")
        time.sleep(settings.poll_interval_seconds)
    provider.download_result(result["video_url"], output / "shot-01.mp4")
    print(f"Paid smoke completed. Outputs: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

