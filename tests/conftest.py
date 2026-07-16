from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videoforge.app import create_app
from videoforge.config import ROOT, Settings
from videoforge.providers.mock import MockShowrunnerProvider


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "videoforge.db",
        asset_root=tmp_path / "assets",
        demo_asset_root=ROOT / "public" / "demo-assets",
        mock_delay_seconds=0,
        poll_interval_seconds=0,
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings, MockShowrunnerProvider(settings))


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def demo_project(client: TestClient) -> dict:
    response = client.post("/api/demo-project", json={})
    assert response.status_code == 201
    return response.json()


def wait(app, project_id: str, timeout: float = 15) -> dict:
    app.state.runner.wait_for_project(project_id, timeout)
    return app.state.database.get_project(project_id)

