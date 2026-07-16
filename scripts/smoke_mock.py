#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from videoforge.app import create_app
from videoforge.config import ROOT, Settings
from videoforge.providers.mock import MockShowrunnerProvider


def main() -> int:
    with TemporaryDirectory(prefix="videoforge-smoke-") as directory:
        root = Path(directory)
        settings = Settings(
            database_path=root / "videoforge.db",
            asset_root=root / "assets",
            demo_asset_root=ROOT / "public" / "demo-assets",
            mock_delay_seconds=0,
            poll_interval_seconds=0,
        )
        app = create_app(settings, MockShowrunnerProvider(settings))
        with TestClient(app) as client:
            project = client.post("/api/demo-project", json={}).json()
            project_id = project["id"]
            client.post(f"/api/projects/{project_id}/plan/approve", json={}).raise_for_status()
            client.post(f"/api/projects/{project_id}/storyboard", json={}).raise_for_status()
            app.state.runner.wait_for_project(project_id)
            project = client.get(f"/api/projects/{project_id}").json()
            for shot in project["shots"]:
                client.post(
                    f"/api/shots/{shot['id']}/image/approve?project_id={project_id}",
                    json={},
                ).raise_for_status()
            client.post(f"/api/projects/{project_id}/videos", json={}).raise_for_status()
            app.state.runner.wait_for_project(project_id)
            client.post(f"/api/projects/{project_id}/assemble", json={}).raise_for_status()
            app.state.runner.wait_for_project(project_id, 30)
            project = client.get(f"/api/projects/{project_id}").json()
            print(
                f"mock smoke: stage={project['stage']} shots={len(project['shots'])} "
                f"final_assets={len(project['finalAssets'])}"
            )
            return 0 if project["stage"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

