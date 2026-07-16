from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from videoforge.schemas import (
    ConsistencyReport,
    ProductionPlan,
    ProjectInput,
    ProviderImageRequest,
    ProviderVideoRequest,
    VisualBible,
)


class ProviderError(RuntimeError):
    def __init__(
        self, message: str, *, code: str = "PROVIDER_ERROR", retryable: bool = False
    ):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ShowrunnerProvider(ABC):
    name: str

    @abstractmethod
    def create_production_plan(
        self, project_id: str, project: ProjectInput
    ) -> ProductionPlan: ...

    @abstractmethod
    def inspect_storyboard(
        self,
        images: list[Path],
        bible: VisualBible,
        plan: ProductionPlan | None = None,
    ) -> ConsistencyReport: ...

    @abstractmethod
    def generate_image(
        self, request: ProviderImageRequest, output_path: Path
    ) -> dict[str, Any]: ...

    def reframe_existing_image(
        self, request: ProviderImageRequest, output_path: Path
    ) -> dict[str, Any]:
        raise ProviderError(
            "This provider cannot reframe an existing generated image",
            code="REFRAME_UNSUPPORTED",
        )

    @abstractmethod
    def generate_video(self, request: ProviderVideoRequest) -> dict[str, Any]: ...

    @abstractmethod
    def get_video_task(self, task_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def download_result(self, source: str, output_path: Path) -> str: ...
