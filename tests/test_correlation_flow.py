from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from pathlib import Path

from src.app.services.correlation_service import analyze_project_by_id
from src.app.storage.database import init_db, session_scope
from src.app.storage.repositories import (
    BLOCK_CATEGORY_REST,
    BLOCK_CATEGORY_WORK,
    create_block,
    create_correlation_project,
    create_record,
    delete_correlation_project,
    list_correlation_projects,
)


def test_correlation_project_crud_and_analysis(tmp_path: Path) -> None:
    db_path = tmp_path / "test_correlation.db"
    init_db(db_path)

    with session_scope() as session:
        sleep = create_block(session, "睡觉_测试", BLOCK_CATEGORY_REST)
        work = create_block(session, "学习_测试", BLOCK_CATEGORY_WORK)

        start_day = datetime.now().date() - timedelta(days=14)
        for idx in range(12):
            day = start_day + timedelta(days=idx)
            sleep_minutes = 480 if idx % 2 == 0 else 300
            sleep_start = datetime.combine(day, time(hour=0, minute=0))
            sleep_end = sleep_start + timedelta(minutes=sleep_minutes)
            create_record(session, sleep.id, sleep_start, sleep_end, None, None, None, None, None)

            # Next-day work efficiency follows sleep pattern (for lag-1 positive relation).
            work_day = day + timedelta(days=1)
            work_start = datetime.combine(work_day, time(hour=9, minute=0))
            work_end = work_start + timedelta(minutes=120)
            efficiency = 5 if sleep_minutes >= 480 else 2
            create_record(session, work.id, work_start, work_end, efficiency, 3, 3, None, None)

        project = create_correlation_project(
            session=session,
            name="睡眠与次日效率",
            days=14,
            time_relation="lag_1",
            target_variable="efficiency",
            source_config=json.dumps({"source_type": "duration", "block_ids": [sleep.id]}, ensure_ascii=False),
        )
        project_id = project.id

    with session_scope() as session:
        projects = list_correlation_projects(session)
        assert any(p.id == project_id for p in projects)

        result = analyze_project_by_id(session, project_id)
        assert result is not None
        assert result.items
        assert result.items[0].samples >= 6
        assert result.items[0].spearman > 0

        delete_correlation_project(session, project_id)
        projects_after_delete = list_correlation_projects(session)
        assert all(p.id != project_id for p in projects_after_delete)

