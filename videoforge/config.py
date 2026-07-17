from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from qwen_multishot_test import load_dotenv


ROOT = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, str(default)))


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    database_path: Path = ROOT / "data" / "videoforge.db"
    asset_root: Path = ROOT / "data" / "assets"
    demo_asset_root: Path = ROOT / "public" / "demo-assets"
    web_root: Path = ROOT / "web"
    provider: str = "qwen"
    qwen_text_model: str = "qwen-plus"
    qwen_vision_model: str = "qwen3-vl-plus"
    qwen_image_model: str = "qwen-image-2.0"
    qwen_image_edit_model: str = "qwen-image-2.0-pro"
    qwen_video_model: str = "wan2.7-i2v"
    qwen_region: str = "ap-southeast-1"
    max_shots: int = 6
    default_shots: int = 6
    max_video_duration_seconds: int = 5
    max_project_retries: int = 4
    max_concurrent_image_tasks: int = 1
    max_concurrent_video_tasks: int = 2
    mock_delay_seconds: float = 0.18
    poll_interval_seconds: float = 15.0
    image_cost_cny: float = 0.256873
    video_cost_cny_per_second_720p: float = 0.733924
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"

    @property
    def real_mode(self) -> bool:
        return self.provider == "qwen"

    @classmethod
    def from_env(cls, env_file: Path | None = None, **overrides: object) -> "Settings":
        load_dotenv(env_file or ROOT / ".env")
        values: dict[str, object] = {
            "database_path": Path(
                os.environ.get("VIDEOFORGE_DATABASE", ROOT / "data" / "videoforge.db")
            ),
            "asset_root": Path(
                os.environ.get("VIDEOFORGE_ASSET_ROOT", ROOT / "data" / "assets")
            ),
            "demo_asset_root": Path(
                os.environ.get(
                    "VIDEOFORGE_DEMO_ASSETS", ROOT / "public" / "demo-assets"
                )
            ),
            "provider": os.environ.get("SHOWRUNNER_PROVIDER", "qwen").lower(),
            "qwen_text_model": os.environ.get("QWEN_TEXT_MODEL", "qwen-plus"),
            "qwen_vision_model": os.environ.get("QWEN_VISION_MODEL", "qwen3-vl-plus"),
            "qwen_image_model": os.environ.get("QWEN_IMAGE_MODEL", "qwen-image-2.0"),
            "qwen_image_edit_model": os.environ.get(
                "QWEN_IMAGE_EDIT_MODEL", "qwen-image-2.0-pro"
            ),
            "qwen_video_model": os.environ.get("QWEN_VIDEO_MODEL", "wan2.7-i2v"),
            "qwen_region": os.environ.get("QWEN_REGION", "ap-southeast-1"),
            "max_shots": _int("MAX_SHOTS", 6),
            "default_shots": _int("DEFAULT_SHOTS", 6),
            "max_video_duration_seconds": _int("MAX_VIDEO_DURATION_SECONDS", 5),
            "max_project_retries": _int("MAX_PROJECT_RETRIES", 4),
            "max_concurrent_image_tasks": _int("MAX_CONCURRENT_IMAGE_TASKS", 1),
            "max_concurrent_video_tasks": _int("MAX_CONCURRENT_VIDEO_TASKS", 2),
            "mock_delay_seconds": _float("MOCK_DELAY_SECONDS", 0.18),
            "poll_interval_seconds": _float("QWEN_POLL_INTERVAL_SECONDS", 15.0),
            "image_cost_cny": _float("QWEN_IMAGE_COST_CNY", 0.256873),
            "video_cost_cny_per_second_720p": _float(
                "QWEN_VIDEO_COST_CNY_PER_SECOND_720P", 0.733924
            ),
            "ffmpeg_binary": os.environ.get("FFMPEG_BINARY", "ffmpeg"),
            "ffprobe_binary": os.environ.get("FFPROBE_BINARY", "ffprobe"),
        }
        values.update(overrides)
        settings = cls(**values)
        if settings.provider not in {"mock", "qwen"}:
            raise ValueError("SHOWRUNNER_PROVIDER must be 'mock' or 'qwen'")
        if not 1 <= settings.default_shots <= settings.max_shots <= 6:
            raise ValueError("shot limits must satisfy 1 <= DEFAULT_SHOTS <= MAX_SHOTS <= 6")
        if settings.max_concurrent_image_tasks < 1:
            raise ValueError("MAX_CONCURRENT_IMAGE_TASKS must be at least 1")
        if settings.max_concurrent_video_tasks < 1:
            raise ValueError("MAX_CONCURRENT_VIDEO_TASKS must be at least 1")
        return settings
