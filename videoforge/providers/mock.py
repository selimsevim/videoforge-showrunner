from __future__ import annotations

import hashlib
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

from videoforge.config import Settings
from videoforge.consistency import mock_storyboard_report
from videoforge.planner import create_mock_plan
from videoforge.schemas import (
    ConsistencyReport,
    ProductionPlan,
    ProjectInput,
    ProviderImageRequest,
    ProviderVideoRequest,
    VisualBible,
)

from .base import ProviderError, ShowrunnerProvider


class MockShowrunnerProvider(ShowrunnerProvider):
    name = "mock"

    def __init__(
        self,
        settings: Settings,
        *,
        fail_video_shot: str | None = None,
        fail_image_shot: str | None = None,
    ):
        self.settings = settings
        self.fail_video_shot = fail_video_shot
        self.fail_image_shot = fail_image_shot

    def _pause(self, multiplier: float = 1.0) -> None:
        delay = self.settings.mock_delay_seconds * multiplier
        if delay > 0:
            time.sleep(delay)

    @staticmethod
    def _index(shot_id: str) -> str:
        try:
            return f"s{int(shot_id.rsplit('-', 1)[-1]):02d}"
        except ValueError as exc:
            raise ProviderError(f"invalid mock shot ID: {shot_id}") from exc

    def create_production_plan(
        self, project_id: str, project: ProjectInput
    ) -> ProductionPlan:
        self._pause(0.4)
        return create_mock_plan(project_id, project)

    def inspect_storyboard(
        self,
        images: list[Path],
        bible: VisualBible,
        plan: ProductionPlan | None = None,
    ) -> ConsistencyReport:
        if not images:
            raise ProviderError("No storyboard images are available for inspection")
        self._pause(0.3)
        return mock_storyboard_report()

    def generate_image(
        self, request: ProviderImageRequest, output_path: Path
    ) -> dict[str, Any]:
        if request.shot_id == self.fail_image_shot:
            raise ProviderError(
                f"Mock image failure for {request.shot_id}",
                code="MOCK_IMAGE_FAILURE",
            )
        self._pause()
        source = self.settings.demo_asset_root / f"{self._index(request.shot_id)}.png"
        if not source.is_file():
            raise ProviderError(f"Mock image asset is missing: {source}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        data = output_path.read_bytes()
        with Image.open(output_path) as image:
            width, height = image.size
        return {
            "request_id": f"mock-image-{uuid.uuid4().hex[:12]}",
            "remote_url": None,
            "local_path": str(output_path),
            "sha256": hashlib.sha256(data).hexdigest(),
            "usage": {"image_count": 1, "width": width, "height": height},
        }

    def generate_video(self, request: ProviderVideoRequest) -> dict[str, Any]:
        if request.shot_id == self.fail_video_shot:
            raise ProviderError(
                f"Shot {request.shot_id[-2:]} video generation failed because the mock "
                "provider rejected the input image. The approved storyboard image remains saved.",
                code="MOCK_VIDEO_REJECTED",
            )
        self._pause()
        task_id = f"mock:{request.shot_id}:{uuid.uuid4().hex[:12]}"
        return {
            "request_id": f"mock-video-{uuid.uuid4().hex[:12]}",
            "task_id": task_id,
            "task_status": "PENDING",
        }

    def get_video_task(self, task_id: str) -> dict[str, Any]:
        self._pause(1.2)
        parts = task_id.split(":")
        if len(parts) != 3 or parts[0] != "mock":
            raise ProviderError("Malformed mock video task ID")
        source = self.settings.demo_asset_root / f"{self._index(parts[1])}.mp4"
        if not source.is_file():
            raise ProviderError(f"Mock video asset is missing: {source}")
        return {
            "task_status": "SUCCEEDED",
            "video_url": str(source),
            "request_id": f"mock-result-{parts[2]}",
            "usage": {
                "video_count": 1,
                "duration": 5,
                "output_video_duration": 5,
                "SR": 720,
            },
        }

    def download_result(self, source: str, output_path: Path) -> str:
        self._pause(0.5)
        source_path = Path(source)
        if not source_path.is_file():
            raise ProviderError(f"Mock result does not exist: {source}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, output_path)
        return hashlib.sha256(output_path.read_bytes()).hexdigest()
