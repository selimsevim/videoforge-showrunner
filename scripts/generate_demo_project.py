#!/usr/bin/env python3
from __future__ import annotations

from videoforge.budget import estimate_budget
from videoforge.config import Settings
from videoforge.consistency import repair_plan_consistency
from videoforge.db import Database
from videoforge.planner import DEMO_PROMPT, create_mock_plan
from videoforge.schemas import ProductionStage, ProjectInput


def main() -> int:
    settings = Settings.from_env()
    database = Database(settings.database_path)
    project = database.create_project(
        ProjectInput(
            title="The Third Exposure",
            storyPrompt=DEMO_PROMPT,
            genre="Psychological horror",
            visualStyle="Cinematic realism",
        ),
        "mock",
    )
    plan, report = repair_plan_consistency(
        create_mock_plan(project["id"], database.project_input(project["id"]))
    )
    database.save_plan(
        plan, estimate_budget(plan, settings).model_dump(by_alias=True)
    )
    database.add_consistency_report(
        project["id"], "preflight", report.model_dump(by_alias=True)
    )
    database.set_stage(project["id"], ProductionStage.PLAN_READY, force=True)
    print(project["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

