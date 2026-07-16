from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


class AssemblyError(RuntimeError):
    pass


def probe_media(path: Path, ffprobe_binary: str = "ffprobe") -> dict[str, Any]:
    if not shutil.which(ffprobe_binary):
        raise AssemblyError(f"ffprobe binary is unavailable: {ffprobe_binary}")
    command = [
        ffprobe_binary,
        "-v",
        "error",
        "-show_entries",
        "format=format_name,duration:stream=codec_name,width,height,avg_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        raise AssemblyError(
            f"ffprobe failed for {path.name}: {result.stderr.strip()[:1000]}"
        )
    return json.loads(result.stdout)


def verify_video(path: Path, ffprobe_binary: str = "ffprobe") -> dict[str, Any]:
    probe = probe_media(path, ffprobe_binary)
    stream = next((item for item in probe.get("streams", []) if item.get("width")), {})
    duration_value = probe.get("format", {}).get("duration")
    try:
        duration = float(duration_value)
    except (TypeError, ValueError):
        duration = None
    fps_value = stream.get("avg_frame_rate", "0/0")
    try:
        numerator, denominator = fps_value.split("/", 1)
        fps = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        fps = None
    checks = {
        "codecH264": stream.get("codec_name") == "h264",
        "resolution720p": stream.get("height") == 720 or stream.get("width") == 720,
        "fpsAbout30": fps is not None and abs(fps - 30) <= 0.1,
        "durationAtMost5_2": duration is not None and duration <= 5.2,
    }
    return {
        "width": stream.get("width"),
        "height": stream.get("height"),
        "codec": stream.get("codec_name"),
        "fps": fps,
        "durationSeconds": duration,
        "checks": checks,
        "passed": all(checks.values()),
        "ffprobe": probe,
    }


def assemble_clips(
    clips: list[Path],
    output_path: Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
) -> dict[str, Any]:
    if len(clips) < 1:
        raise AssemblyError("No completed clips are available for assembly")
    if not shutil.which(ffmpeg_binary):
        raise AssemblyError(f"FFmpeg binary is unavailable: {ffmpeg_binary}")
    for clip in clips:
        if not clip.is_file():
            raise AssemblyError(f"Clip is missing: {clip}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = output_path.parent / ".assembly"
    work.mkdir(parents=True, exist_ok=True)
    normalized: list[Path] = []
    filter_value = (
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,fps=30,format=yuv420p"
    )
    for index, clip in enumerate(clips, 1):
        target = work / f"normalized-{index:02d}.mp4"
        command = [
            ffmpeg_binary,
            "-y",
            "-v",
            "error",
            "-i",
            str(clip),
            "-map",
            "0:v:0",
            "-vf",
            filter_value,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "19",
            "-an",
            str(target),
        ]
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode:
            raise AssemblyError(
                f"FFmpeg normalization failed for shot {index}: "
                f"{result.stderr.strip()[:1200]}"
            )
        normalized.append(target)

    concat_file = work / "concat.txt"
    concat_file.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in normalized),
        encoding="utf-8",
    )
    command = [
        ffmpeg_binary,
        "-y",
        "-v",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(output_path),
    ]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        raise AssemblyError(f"FFmpeg final assembly failed: {result.stderr.strip()[:1200]}")
    probe = probe_media(output_path, ffprobe_binary)
    return {
        "clipCount": len(clips),
        "normalization": "1280x720, 30fps, H.264, silent",
        "probe": probe,
    }

