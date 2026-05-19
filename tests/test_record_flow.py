from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from src.app.services.analytics_service import build_daily_series
from src.app.storage.database import init_db, session_scope
from src.app.storage.repositories import (
    BLOCK_CATEGORY_REST,
    BLOCK_CATEGORY_WORK,
    block_summary,
    create_block,
    create_record,
    list_recent_records,
)


def test_overlap_records_are_persisted_and_counted(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    init_db(db_path)

    with session_scope() as session:
        writing = create_block(session, "写文章", BLOCK_CATEGORY_WORK)
        coffee = create_block(session, "喝咖啡", BLOCK_CATEGORY_REST)

        start = datetime.now() - timedelta(hours=1)
        end = datetime.now()

        # Overlap is allowed by design: two records in same time range.
        create_record(session, writing.id, start, end, 4, 4, 4, "focus", "main task")
        create_record(session, coffee.id, start, end, 3, None, None, "drink", "context task")

    with session_scope() as session:
        records = list_recent_records(session)
        assert len(records) == 2

        series = build_daily_series(session, days=7)
        assert sum(series.frequency) >= 2

        summary = block_summary(session, days=7)
        names = {s.block_name for s in summary}
        assert "写文章" in names
        assert "喝咖啡" in names
