#!/usr/bin/env python3
"""Run a reproducible Qwen-Image 2.0 + Wan 2.7 multi-shot cloud test."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


IMAGE_MODEL = "qwen-image-2.0"
VIDEO_MODEL = "wan2.7-i2v"
SHARED_SINGAPORE_BASE = "https://dashscope-intl.aliyuncs.com/api/v1"

LOOK_BIBLE = {
    "subject": (
        "same woman, late 20s, short black bob, pale skin, narrow jaw, green "
        "trench coat, black trousers, silver signet ring on right hand, no hat, "
        "no glasses"
    ),
    "style": (
        "photorealistic, muted teal-and-amber grade, overcast daylight, soft key "
        "light from camera left, shallow depth of field, 50mm photographic lens, "
        "eye-level camera, realistic skin texture, restrained contrast, no text, "
        "no logos, no extra people"
    ),
    "scene": (
        "wet pavement outside a modern concrete cafe, soft reflections, light "
        "breeze, sparse background detail, cinematic realism"
    ),
    "negative": (
        "extra people, duplicate subject, text, logo, watermark, oversaturated "
        "colours, cartoon look, deformed hands, malformed fingers, blur, low "
        "resolution, bad anatomy"
    ),
}

SHOTS = [
    {
        "shot_id": "s01",
        "image_delta": (
            "medium shot, centred composition, woman standing still and looking "
            "slightly off-camera to the right"
        ),
        "video_delta": (
            "subtle head turn towards camera, coat hem fluttering lightly, fixed camera"
        ),
        "image_seed": 170700001,
        "video_seed": 170700101,
    },
    {
        "shot_id": "s02",
        "image_delta": (
            "medium close-up, three-quarter left profile, woman resting her hand "
            "on the cafe window frame"
        ),
        "video_delta": (
            "slow inhale, blink once, hand slides slightly on the window frame, "
            "slow push-in"
        ),
        "image_seed": 170700002,
        "video_seed": 170700102,
    },
    {
        "shot_id": "s03",
        "image_delta": (
            "medium shot, slight side profile, woman turning her shoulders "
            "towards the street"
        ),
        "video_delta": (
            "small shoulder turn and one step forward, hair moves gently in the "
            "breeze, camera tracks left slightly"
        ),
        "image_seed": 170700003,
        "video_seed": 170700103,
    },
]


def load_dotenv(path: Path) -> None:
    """Load a small, conventional .env file without adding a dependency."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def build_base_url() -> tuple[str, str]:
    override = os.environ.get("QWEN_BASE_URL", "").strip().rstrip("/")
    if override:
        parsed = urlparse(override)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("QWEN_BASE_URL must be a complete HTTPS URL")
        return override, "override"

    workspace = os.environ.get("QWEN_WORKSPACE_ID", "").strip()
    if workspace:
        if not re.fullmatch(r"[A-Za-z0-9-]+", workspace):
            raise ValueError("QWEN_WORKSPACE_ID contains unexpected characters")
        return (
            f"https://{workspace}.ap-southeast-1.maas.aliyuncs.com/api/v1",
            "workspace-specific Singapore endpoint",
        )
    return SHARED_SINGAPORE_BASE, "shared Singapore endpoint"


def get_api_key() -> tuple[str, str]:
    """Return the first supported API-key variable without exposing its value."""
    for name in ("DASHSCOPE_API_KEY", "QWEN_CLOUD_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value and not value.startswith("replace-with-"):
            return value, name
    return "", ""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def image_prompt(shot: dict[str, Any]) -> str:
    return ", ".join(
        [
            LOOK_BIBLE["subject"],
            LOOK_BIBLE["scene"],
            LOOK_BIBLE["style"],
            shot["image_delta"],
        ]
    )


def image_payload(shot: dict[str, Any], size: str) -> dict[str, Any]:
    return {
        "model": IMAGE_MODEL,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": image_prompt(shot)}],
                }
            ]
        },
        "parameters": {
            "negative_prompt": LOOK_BIBLE["negative"],
            "size": size,
            "n": 1,
            "prompt_extend": False,
            "watermark": False,
            "seed": shot["image_seed"],
        },
    }


def video_payload(
    shot: dict[str, Any], first_frame_url: str, duration: int
) -> dict[str, Any]:
    return {
        "model": VIDEO_MODEL,
        "input": {
            "prompt": shot["video_delta"],
            "negative_prompt": LOOK_BIBLE["negative"],
            "media": [{"type": "first_frame", "url": first_frame_url}],
        },
        "parameters": {
            "resolution": "720P",
            "duration": duration,
            "prompt_extend": False,
            "watermark": False,
            "seed": shot["video_seed"],
        },
    }


def validate_payloads(shots: list[dict[str, Any]], size: str, duration: int) -> None:
    match = re.fullmatch(r"(\d+)\*(\d+)", size)
    if not match:
        raise ValueError("--image-size must use WIDTH*HEIGHT format")
    width, height = map(int, match.groups())
    pixels = width * height
    if pixels < 512 * 512 or pixels > 2048 * 2048:
        raise ValueError("image pixel count must be between 512*512 and 2048*2048")
    if not 2 <= duration <= 15:
        raise ValueError("Wan 2.7 duration must be between 2 and 15 seconds")
    if len(LOOK_BIBLE["negative"]) > 500:
        raise ValueError("negative prompt exceeds the documented 500-character limit")
    for shot in shots:
        payload = image_payload(shot, size)
        content = payload["input"]["messages"][0]["content"]
        if len(content) != 1 or not content[0].get("text"):
            raise ValueError(f"invalid image prompt for {shot['shot_id']}")
        media = video_payload(shot, "https://example.invalid/first-frame.png", duration)[
            "input"
        ]["media"]
        if media != [
            {"type": "first_frame", "url": "https://example.invalid/first-frame.png"}
        ]:
            raise ValueError(f"invalid video media for {shot['shot_id']}")


class ModelStudioClient:
    def __init__(self, api_key: str, base_url: str, max_attempts: int = 6):
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max_attempts
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "qwen-multishot-test/1.0",
            }
        )

    def request_json(
        self, method: str, url: str, *, async_call: bool = False, **kwargs: Any
    ) -> dict[str, Any]:
        headers = dict(kwargs.pop("headers", {}))
        if async_call:
            headers["X-DashScope-Async"] = "enable"
        wait_seconds = 2.0
        last_error = "unknown error"

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.session.request(
                    method, url, headers=headers, timeout=(20, 180), **kwargs
                )
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                retryable = True
            else:
                retryable = response.status_code in {429, 500, 502, 503, 504}
                if response.status_code < 400:
                    try:
                        data = response.json()
                    except ValueError as exc:
                        raise RuntimeError(
                            f"{method} {url} returned invalid JSON"
                        ) from exc
                    if data.get("code"):
                        raise RuntimeError(
                            f"{method} {url} failed: {data.get('code')}: "
                            f"{data.get('message', 'no message')}"
                        )
                    return data
                last_error = (
                    f"HTTP {response.status_code}: {response.text[:2000].strip()}"
                )
                if not retryable:
                    raise RuntimeError(f"{method} {url} failed: {last_error}")

            if attempt == self.max_attempts:
                break
            jitter = random.uniform(0, 1.0)
            time.sleep(wait_seconds + jitter)
            wait_seconds = min(wait_seconds * 2, 32)

        raise RuntimeError(
            f"{method} {url} exhausted {self.max_attempts} attempts: {last_error}"
        )

    def generate_image(
        self, shot: dict[str, Any], size: str, output_path: Path
    ) -> dict[str, Any]:
        url = f"{self.base_url}/services/aigc/multimodal-generation/generation"
        prompt = image_prompt(shot)
        data = self.request_json("POST", url, json=image_payload(shot, size))
        try:
            image_url = data["output"]["choices"][0]["message"]["content"][0][
                "image"
            ]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"unexpected image response: {json.dumps(data)[:2000]}") from exc
        image_sha = self.download(image_url, output_path)
        return {
            "request_id": data.get("request_id"),
            "prompt": prompt,
            "prompt_sha256": sha256_text(prompt),
            "image_url": image_url,
            "image_path": str(output_path),
            "image_sha256": image_sha,
            "width": data.get("usage", {}).get("width"),
            "height": data.get("usage", {}).get("height"),
            "image_seed": shot["image_seed"],
        }

    def submit_video(
        self, shot: dict[str, Any], first_frame_url: str, duration: int
    ) -> dict[str, Any]:
        url = f"{self.base_url}/services/aigc/video-generation/video-synthesis"
        data = self.request_json(
            "POST",
            url,
            async_call=True,
            json=video_payload(shot, first_frame_url, duration),
        )
        try:
            task_id = data["output"]["task_id"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"unexpected video response: {json.dumps(data)[:2000]}") from exc
        prompt = shot["video_delta"]
        return {
            "request_id": data.get("request_id"),
            "task_id": task_id,
            "task_status": data.get("output", {}).get("task_status"),
            "prompt": prompt,
            "prompt_sha256": sha256_text(prompt),
            "video_seed": shot["video_seed"],
        }

    def poll_video(
        self, task_id: str, poll_interval: float, poll_timeout: float
    ) -> dict[str, Any]:
        url = f"{self.base_url}/tasks/{task_id}"
        deadline = time.monotonic() + poll_timeout
        last_status = None
        while time.monotonic() < deadline:
            data = self.request_json("GET", url)
            status = data.get("output", {}).get("task_status", "UNKNOWN")
            if status != last_status:
                print(f"  task {task_id}: {status}", flush=True)
                last_status = status
            if status == "SUCCEEDED":
                return data
            if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                raise RuntimeError(
                    f"video task {task_id} ended as {status}: {json.dumps(data)[:2000]}"
                )
            time.sleep(poll_interval)
        raise TimeoutError(f"video task {task_id} exceeded {poll_timeout:.0f}s")

    def download(self, url: str, output_path: Path) -> str:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_suffix(output_path.suffix + ".part")
        digest = hashlib.sha256()
        with requests.get(url, stream=True, timeout=(20, 300)) as response:
            response.raise_for_status()
            with temp_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
                        digest.update(chunk)
        temp_path.replace(output_path)
        return digest.hexdigest()


def ffprobe_json(path: Path) -> dict[str, Any]:
    if not shutil.which("ffprobe"):
        return {"ffprobe_missing": True}
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=format_name,duration:stream=codec_name,width,height,avg_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def write_outputs(records: list[dict[str, Any]], log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    manifest = log_dir / "manifest.jsonl"
    manifest.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    (log_dir / "summary.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def parse_frame_rate(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    numerator, _, denominator = value.partition("/")
    try:
        return float(numerator) / float(denominator or 1)
    except (ValueError, ZeroDivisionError):
        return None


def technical_checks(probe: dict[str, Any], requested_duration: int) -> dict[str, Any]:
    streams = probe.get("streams", [])
    video = next((item for item in streams if item.get("width")), {})
    duration_text = probe.get("format", {}).get("duration")
    try:
        duration = float(duration_text)
    except (TypeError, ValueError):
        duration = None
    fps = parse_frame_rate(video.get("avg_frame_rate"))
    checks = {
        "codec_h264": video.get("codec_name") == "h264",
        "resolution_720p": video.get("height") == 720 or video.get("width") == 720,
        "fps_about_30": fps is not None and abs(fps - 30.0) <= 0.1,
        "duration_within_tolerance": (
            duration is not None and duration <= requested_duration + 0.2
        ),
    }
    return {"duration_seconds": duration, "fps": fps, "checks": checks}


def write_report(
    records: list[dict[str, Any]], path: Path, run_id: str, endpoint_kind: str
) -> None:
    lines = [
        f"# Qwen/Wan run {run_id}",
        "",
        f"- Models: `{IMAGE_MODEL}` + `{VIDEO_MODEL}`",
        f"- Endpoint: {endpoint_kind}",
        f"- Shots: {len(records)}",
        "",
        "| Shot | Status | Image | Video | Duration | FPS | Technical checks |",
        "|---|---|---|---|---:|---:|---|",
    ]
    for record in records:
        image_ok = "yes" if record.get("image") else "no"
        video_ok = "yes" if record.get("video_result") else "no"
        technical = record.get("video_result", {}).get("technical", {})
        duration = technical.get("duration_seconds")
        fps = technical.get("fps")
        checks = technical.get("checks", {})
        check_text = (
            ", ".join(f"{key}={'pass' if value else 'FAIL'}" for key, value in checks.items())
            or "n/a"
        )
        lines.append(
            f"| {record['shot_id']} | {record.get('status', 'unknown')} | {image_ok} | "
            f"{video_ok} | {duration if duration is not None else 'n/a'} | "
            f"{round(fps, 3) if fps is not None else 'n/a'} | {check_text} |"
        )
    failures = [record for record in records if record.get("status") == "failed"]
    lines.extend(["", "## Failures", ""])
    if failures:
        lines.extend(
            f"- `{record['shot_id']}`: {record.get('error', 'unknown error')}"
            for record in failures
        )
    else:
        lines.append("- None")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def dry_run(
    shots: list[dict[str, Any]], base_url: str, run_root: Path, size: str, duration: int
) -> None:
    request_dir = run_root / "request_payloads"
    request_dir.mkdir(parents=True, exist_ok=True)
    for shot in shots:
        shot_id = shot["shot_id"]
        (request_dir / f"{shot_id}-image.json").write_text(
            json.dumps(image_payload(shot, size), indent=2) + "\n", encoding="utf-8"
        )
        placeholder = f"https://example.invalid/{shot_id}.png"
        (request_dir / f"{shot_id}-video.json").write_text(
            json.dumps(video_payload(shot, placeholder, duration), indent=2) + "\n",
            encoding="utf-8",
        )
    metadata = {
        "mode": "dry-run",
        "base_url": base_url,
        "image_endpoint": f"{base_url}/services/aigc/multimodal-generation/generation",
        "video_endpoint": f"{base_url}/services/aigc/video-generation/video-synthesis",
        "shots": [shot["shot_id"] for shot in shots],
        "ffprobe_available": bool(shutil.which("ffprobe")),
        "validated": True,
    }
    (run_root / "dry-run-summary.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2))


def run_pipeline(args: argparse.Namespace) -> Path:
    load_dotenv(Path(args.env_file))
    selected = [shot for shot in SHOTS if shot["shot_id"] in args.shots]
    validate_payloads(selected, args.image_size, args.video_duration)
    base_url, endpoint_kind = build_base_url()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_root = Path(args.output_root).resolve() / run_id
    image_dir = run_root / "images"
    video_dir = run_root / "videos"
    log_dir = run_root / "logs"
    for directory in (image_dir, video_dir, log_dir):
        directory.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        dry_run(
            selected, base_url, run_root, args.image_size, args.video_duration
        )
        return run_root

    api_key, api_key_source = get_api_key()
    if not api_key:
        raise RuntimeError(
            "DASHSCOPE_API_KEY/QWEN_CLOUD_API_KEY is missing. Put a Singapore "
            "Model Studio key in .env or export it in the shell. Do not paste "
            "the key into logs."
        )

    print(f"Run directory: {run_root}")
    print(f"Endpoint: {endpoint_kind}")
    print(f"Credential source: {api_key_source}")
    print(f"Shots: {', '.join(shot['shot_id'] for shot in selected)}")
    client = ModelStudioClient(api_key, base_url)
    records: list[dict[str, Any]] = [
        {"shot_id": shot["shot_id"], "status": "pending"} for shot in selected
    ]

    try:
        # Generate and save all first frames before starting the asynchronous jobs.
        for shot, record in zip(selected, records):
            print(f"Generating image {shot['shot_id']}...", flush=True)
            record["image"] = client.generate_image(
                shot, args.image_size, image_dir / f"{shot['shot_id']}.png"
            )
            record["status"] = "image_succeeded"
            write_outputs(records, log_dir)

        # Submit all video jobs first so their processing overlaps.
        for shot, record in zip(selected, records):
            print(f"Submitting video {shot['shot_id']}...", flush=True)
            record["video_submit"] = client.submit_video(
                shot, record["image"]["image_url"], args.video_duration
            )
            record["status"] = "video_submitted"
            write_outputs(records, log_dir)

        for shot, record in zip(selected, records):
            task_id = record["video_submit"]["task_id"]
            print(f"Waiting for video {shot['shot_id']}...", flush=True)
            done = client.poll_video(task_id, args.poll_interval, args.poll_timeout)
            try:
                video_url = done["output"]["video_url"]
            except (KeyError, TypeError) as exc:
                raise RuntimeError(
                    f"successful task {task_id} had no video_url: {json.dumps(done)[:2000]}"
                ) from exc
            video_path = video_dir / f"{shot['shot_id']}.mp4"
            video_sha = client.download(video_url, video_path)
            probe = ffprobe_json(video_path)
            record["video_result"] = {
                "task_id": task_id,
                "request_id": done.get("request_id"),
                "video_url": video_url,
                "video_path": str(video_path),
                "video_sha256": video_sha,
                "usage": done.get("usage", {}),
                "ffprobe": probe,
                "technical": technical_checks(probe, args.video_duration),
            }
            record["status"] = "ok"
            write_outputs(records, log_dir)
    except Exception as exc:
        current = next(
            (record for record in records if record.get("status") != "ok"), records[-1]
        )
        current["status"] = "failed"
        current["error"] = f"{type(exc).__name__}: {exc}"
        write_outputs(records, log_dir)
        write_report(records, log_dir / "report.md", run_id, endpoint_kind)
        raise

    write_report(records, log_dir / "report.md", run_id, endpoint_kind)
    return run_root


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and write request payloads without calling the API",
    )
    parser.add_argument(
        "--shots",
        nargs="+",
        choices=[shot["shot_id"] for shot in SHOTS],
        default=[shot["shot_id"] for shot in SHOTS],
        help="shots to run (default: all three)",
    )
    parser.add_argument("--env-file", default=".env", help="credential env file")
    parser.add_argument("--output-root", default="runs", help="run output directory")
    parser.add_argument("--image-size", default="1920*1080")
    parser.add_argument("--video-duration", type=int, default=5)
    parser.add_argument("--poll-interval", type=float, default=15.0)
    parser.add_argument("--poll-timeout", type=float, default=1800.0)
    return parser.parse_args(argv)


def main() -> int:
    try:
        run_root = run_pipeline(parse_args())
    except (ValueError, RuntimeError, TimeoutError, requests.RequestException) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Completed: {run_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
