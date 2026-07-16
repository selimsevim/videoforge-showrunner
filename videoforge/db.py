from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Iterable

from .schemas import JobStatus, ProductionPlan, ProductionStage, ProjectInput, utc_now
from .state_machine import require_transition


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    return json.loads(value)


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            story_prompt TEXT NOT NULL,
            genre TEXT NOT NULL,
            visual_style TEXT NOT NULL,
            aspect_ratio TEXT NOT NULL,
            target_duration_seconds INTEGER NOT NULL,
            shot_count INTEGER NOT NULL,
            stage TEXT NOT NULL,
            provider TEXT NOT NULL,
            plan_approved INTEGER NOT NULL DEFAULT 0,
            budget_json TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS production_plans (
            project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
            plan_json TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS shots (
            id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            order_index INTEGER NOT NULL,
            plan_json TEXT NOT NULL,
            image_approved INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (project_id, id)
        );
        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            shot_id TEXT,
            kind TEXT NOT NULL,
            local_path TEXT NOT NULL,
            local_url TEXT NOT NULL,
            remote_url TEXT,
            prompt_hash TEXT,
            sha256 TEXT,
            metadata_json TEXT NOT NULL,
            is_current INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS generation_jobs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            shot_id TEXT,
            kind TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            status TEXT NOT NULL,
            prompt TEXT,
            prompt_hash TEXT,
            negative_prompt TEXT,
            seed INTEGER,
            parameters_json TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            request_id TEXT,
            remote_task_id TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            error_code TEXT,
            error_message TEXT,
            started_at TEXT,
            completed_at TEXT,
            output_url TEXT,
            estimated_cost REAL,
            usage_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_requests (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            job_id TEXT,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            request_id TEXT,
            request_json TEXT NOT NULL,
            response_json TEXT,
            status_code INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS consistency_reports (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            phase TEXT NOT NULL,
            report_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_project ON generation_jobs(project_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON generation_jobs(status);
        CREATE INDEX IF NOT EXISTS idx_assets_project ON assets(project_id, shot_id, kind);
        """
        with self.connect() as connection:
            connection.executescript(schema)

    def create_project(self, data: ProjectInput, provider: str) -> dict[str, Any]:
        project_id = f"project-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO projects (
                    id, title, story_prompt, genre, visual_style, aspect_ratio,
                    target_duration_seconds, shot_count, stage, provider,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    data.title,
                    data.story_prompt,
                    data.genre,
                    data.visual_style,
                    data.aspect_ratio,
                    data.target_duration_seconds,
                    data.shot_count,
                    ProductionStage.DRAFT,
                    provider,
                    now,
                    now,
                ),
            )
        return self.get_project(project_id)

    def project_input(self, project_id: str) -> ProjectInput:
        row = self._project_row(project_id)
        return ProjectInput(
            title=row["title"],
            storyPrompt=row["story_prompt"],
            genre=row["genre"],
            visualStyle=row["visual_style"],
            aspectRatio=row["aspect_ratio"],
            targetDurationSeconds=row["target_duration_seconds"],
            shotCount=row["shot_count"],
        )

    def _project_row(self, project_id: str) -> sqlite3.Row:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if not row:
            raise KeyError(project_id)
        return row

    def set_stage(
        self, project_id: str, stage: ProductionStage | str, *, force: bool = False
    ) -> None:
        row = self._project_row(project_id)
        target = ProductionStage(stage)
        if not force:
            require_transition(row["stage"], target)
        with self.connect() as connection:
            connection.execute(
                "UPDATE projects SET stage = ?, updated_at = ? WHERE id = ?",
                (target, utc_now(), project_id),
            )

    def update_project(self, project_id: str, values: dict[str, Any]) -> dict[str, Any]:
        allowed = {"title", "story_prompt", "genre", "visual_style", "error_message"}
        filtered = {key: value for key, value in values.items() if key in allowed}
        if filtered:
            assignments = ", ".join(f"{key} = ?" for key in filtered)
            with self.connect() as connection:
                connection.execute(
                    f"UPDATE projects SET {assignments}, updated_at = ? WHERE id = ?",
                    (*filtered.values(), utc_now(), project_id),
                )
        return self.get_project(project_id)

    def save_plan(self, plan: ProductionPlan, budget: dict[str, Any]) -> None:
        now = utc_now()
        plan_data = plan.model_dump(by_alias=True)
        with self.connect() as connection:
            previous = {
                row["id"]: row["image_approved"]
                for row in connection.execute(
                    "SELECT id, image_approved FROM shots WHERE project_id = ?",
                    (plan.project_id,),
                )
            }
            existing = connection.execute(
                "SELECT version FROM production_plans WHERE project_id = ?",
                (plan.project_id,),
            ).fetchone()
            version = (existing["version"] + 1) if existing else 1
            connection.execute(
                """
                INSERT INTO production_plans(project_id, plan_json, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    plan_json=excluded.plan_json,
                    version=excluded.version,
                    updated_at=excluded.updated_at
                """,
                (plan.project_id, _json(plan_data), version, now, now),
            )
            connection.execute("DELETE FROM shots WHERE project_id = ?", (plan.project_id,))
            for shot in plan.shots:
                connection.execute(
                    """
                    INSERT INTO shots(
                        id, project_id, order_index, plan_json, image_approved,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        shot.id,
                        plan.project_id,
                        shot.order,
                        _json(shot.model_dump(by_alias=True)),
                        previous.get(shot.id, 0),
                        now,
                        now,
                    ),
                )
            connection.execute(
                """
                UPDATE projects SET title = ?, genre = ?, budget_json = ?,
                    plan_approved = 0, updated_at = ? WHERE id = ?
                """,
                (plan.title, plan.genre, _json(budget), now, plan.project_id),
            )

    def approve_plan(self, project_id: str) -> None:
        if not self.get_plan(project_id):
            raise ValueError("project has no production plan")
        with self.connect() as connection:
            connection.execute(
                "UPDATE projects SET plan_approved = 1, updated_at = ? WHERE id = ?",
                (utc_now(), project_id),
            )

    def get_plan(self, project_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT plan_json FROM production_plans WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return _loads(row["plan_json"]) if row else None

    def approve_image(self, project_id: str, shot_id: str, approved: bool = True) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE shots SET image_approved = ?, updated_at = ?
                WHERE project_id = ? AND id = ?
                """,
                (int(approved), utc_now(), project_id, shot_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(shot_id)

    def all_images_approved(self, project_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total, SUM(image_approved) AS approved
                FROM shots WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
        return bool(row["total"] and row["total"] == (row["approved"] or 0))

    def create_asset(
        self,
        *,
        project_id: str,
        shot_id: str | None,
        kind: str,
        local_path: str,
        local_url: str,
        remote_url: str | None = None,
        prompt_hash: str | None = None,
        sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        asset_id = f"asset-{uuid.uuid4().hex[:14]}"
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE assets SET is_current = 0
                WHERE project_id = ? AND shot_id IS ? AND kind = ?
                """,
                (project_id, shot_id, kind),
            )
            connection.execute(
                """
                INSERT INTO assets(
                    id, project_id, shot_id, kind, local_path, local_url,
                    remote_url, prompt_hash, sha256, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    project_id,
                    shot_id,
                    kind,
                    local_path,
                    local_url,
                    remote_url,
                    prompt_hash,
                    sha256,
                    _json(metadata or {}),
                    utc_now(),
                ),
            )
        return asset_id

    def latest_asset(self, project_id: str, shot_id: str | None, kind: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM assets
                WHERE project_id = ? AND shot_id IS ? AND kind = ? AND is_current = 1
                ORDER BY created_at DESC LIMIT 1
                """,
                (project_id, shot_id, kind),
            ).fetchone()
        return self._asset_dict(row) if row else None

    def create_job(
        self,
        *,
        project_id: str,
        shot_id: str | None,
        kind: str,
        provider: str,
        model: str,
        payload: dict[str, Any],
        prompt: str | None = None,
        prompt_hash: str | None = None,
        negative_prompt: str | None = None,
        seed: int | None = None,
        parameters: dict[str, Any] | None = None,
        estimated_cost: float | None = None,
        retry_count: int = 0,
    ) -> str:
        job_id = f"job-{uuid.uuid4().hex[:14]}"
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_jobs(
                    id, project_id, shot_id, kind, provider, model, status,
                    prompt, prompt_hash, negative_prompt, seed, parameters_json,
                    payload_json, retry_count, estimated_cost, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    project_id,
                    shot_id,
                    kind,
                    provider,
                    model,
                    JobStatus.QUEUED,
                    prompt,
                    prompt_hash,
                    negative_prompt,
                    seed,
                    _json(parameters or {}),
                    _json(payload),
                    retry_count,
                    estimated_cost,
                    now,
                    now,
                ),
            )
        return job_id

    def update_job(self, job_id: str, **values: Any) -> None:
        allowed = {
            "status",
            "request_id",
            "remote_task_id",
            "retry_count",
            "error_code",
            "error_message",
            "started_at",
            "completed_at",
            "output_url",
            "usage_json",
            "payload_json",
        }
        filtered = {key: value for key, value in values.items() if key in allowed}
        if not filtered:
            return
        for key in ("usage_json", "payload_json"):
            if key in filtered and not isinstance(filtered[key], str):
                filtered[key] = _json(filtered[key])
        assignments = ", ".join(f"{key} = ?" for key in filtered)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE generation_jobs SET {assignments}, updated_at = ? WHERE id = ?",
                (*filtered.values(), utc_now(), job_id),
            )

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if not row:
            raise KeyError(job_id)
        return self._job_dict(row)

    def incomplete_jobs(self) -> list[dict[str, Any]]:
        statuses = (
            JobStatus.QUEUED,
            JobStatus.GENERATING,
            JobStatus.POLLING,
            JobStatus.DOWNLOADING,
            JobStatus.VERIFYING,
        )
        placeholders = ",".join("?" for _ in statuses)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_jobs WHERE status IN ({placeholders})",
                statuses,
            ).fetchall()
        return [self._job_dict(row) for row in rows]

    def jobs_for_project(self, project_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM generation_jobs WHERE project_id = ?"
        parameters: list[Any] = [project_id]
        if kind:
            sql += " AND kind = ?"
            parameters.append(kind)
        sql += " ORDER BY created_at"
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._job_dict(row) for row in rows]

    def add_consistency_report(
        self, project_id: str, phase: str, report: dict[str, Any]
    ) -> str:
        report_id = f"report-{uuid.uuid4().hex[:14]}"
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO consistency_reports(id, project_id, phase, report_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (report_id, project_id, phase, _json(report), utc_now()),
            )
        return report_id

    def record_provider_request(
        self,
        *,
        project_id: str,
        job_id: str | None,
        provider: str,
        model: str,
        request_data: dict[str, Any],
        response_data: dict[str, Any] | None = None,
        request_id: str | None = None,
        status_code: int | None = None,
    ) -> str:
        record_id = f"request-{uuid.uuid4().hex[:14]}"
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO provider_requests(
                    id, project_id, job_id, provider, model, request_id,
                    request_json, response_json, status_code, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    project_id,
                    job_id,
                    provider,
                    model,
                    request_id,
                    _json(request_data),
                    _json(response_data) if response_data is not None else None,
                    status_code,
                    utc_now(),
                ),
            )
        return record_id

    def get_project(self, project_id: str) -> dict[str, Any]:
        row = self._project_row(project_id)
        with self.connect() as connection:
            shot_rows = connection.execute(
                "SELECT * FROM shots WHERE project_id = ? ORDER BY order_index",
                (project_id,),
            ).fetchall()
            asset_rows = connection.execute(
                "SELECT * FROM assets WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()
            report_rows = connection.execute(
                """
                SELECT * FROM consistency_reports WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
            request_rows = connection.execute(
                """
                SELECT * FROM provider_requests WHERE project_id = ?
                ORDER BY created_at
                """,
                (project_id,),
            ).fetchall()
        assets = [self._asset_dict(asset) for asset in asset_rows]
        shots = []
        for shot_row in shot_rows:
            shot = _loads(shot_row["plan_json"])
            shot["imageApproved"] = bool(shot_row["image_approved"])
            shot["assets"] = [
                asset
                for asset in assets
                if asset["shotId"] == shot_row["id"] and asset["isCurrent"]
            ]
            shots.append(shot)
        final_assets = [
            asset for asset in assets if asset["kind"] == "final" and asset["isCurrent"]
        ]
        return {
            "id": row["id"],
            "title": row["title"],
            "storyPrompt": row["story_prompt"],
            "genre": row["genre"],
            "visualStyle": row["visual_style"],
            "aspectRatio": row["aspect_ratio"],
            "targetDurationSeconds": row["target_duration_seconds"],
            "shotCount": row["shot_count"],
            "stage": row["stage"],
            "provider": row["provider"],
            "planApproved": bool(row["plan_approved"]),
            "budget": _loads(row["budget_json"]),
            "errorMessage": row["error_message"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "savedAt": row["updated_at"],
            "plan": self.get_plan(project_id),
            "shots": shots,
            "jobs": self.jobs_for_project(project_id),
            "finalAssets": final_assets,
            "consistencyReports": [
                {
                    "id": report["id"],
                    "phase": report["phase"],
                    "report": _loads(report["report_json"]),
                    "createdAt": report["created_at"],
                }
                for report in report_rows
            ],
            "providerRequests": [
                {
                    "id": request["id"],
                    "jobId": request["job_id"],
                    "provider": request["provider"],
                    "model": request["model"],
                    "requestId": request["request_id"],
                    "request": _loads(request["request_json"], {}),
                    "response": _loads(request["response_json"], {}),
                    "statusCode": request["status_code"],
                    "createdAt": request["created_at"],
                }
                for request in request_rows
            ],
        }

    def list_projects(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM projects ORDER BY updated_at DESC"
            ).fetchall()
        return [self.get_project(row["id"]) for row in rows]

    @staticmethod
    def _asset_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "projectId": row["project_id"],
            "shotId": row["shot_id"],
            "kind": row["kind"],
            "localPath": row["local_path"],
            "localUrl": row["local_url"],
            "remoteUrl": row["remote_url"],
            "promptHash": row["prompt_hash"],
            "sha256": row["sha256"],
            "metadata": _loads(row["metadata_json"], {}),
            "isCurrent": bool(row["is_current"]),
            "createdAt": row["created_at"],
        }

    @staticmethod
    def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "projectId": row["project_id"],
            "shotId": row["shot_id"],
            "kind": row["kind"],
            "provider": row["provider"],
            "model": row["model"],
            "status": row["status"],
            "prompt": row["prompt"],
            "promptHash": row["prompt_hash"],
            "negativePrompt": row["negative_prompt"],
            "seed": row["seed"],
            "parameters": _loads(row["parameters_json"], {}),
            "payload": _loads(row["payload_json"], {}),
            "requestId": row["request_id"],
            "remoteTaskId": row["remote_task_id"],
            "retryCount": row["retry_count"],
            "errorCode": row["error_code"],
            "errorMessage": row["error_message"],
            "startedAt": row["started_at"],
            "completedAt": row["completed_at"],
            "outputUrl": row["output_url"],
            "estimatedCost": row["estimated_cost"],
            "usage": _loads(row["usage_json"], {}),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
