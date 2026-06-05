"""Database initialization and session helpers."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, text  # type: ignore[import]
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker  # type: ignore[import]


class Base(DeclarativeBase):
    """Base declarative class."""


_SESSION_FACTORY: sessionmaker[Session] | None = None
_DB_PATH: Path | None = None


def get_default_db_path() -> Path:
    return Path.cwd() / "insight.db"


def init_db(db_path: Path) -> None:
    """Initialize SQLite DB and tables."""
    global _SESSION_FACTORY, _DB_PATH
    _DB_PATH = Path(db_path)
    engine = create_engine(f"sqlite:///{_DB_PATH}", future=True)
    from ..domain.models import (  # noqa: F401
        ActivityRecord,
        AppSetting,
        CorrelationProject,
        EventBlock,
        PointAccount,
        PointLedgerEntry,
        Task,
    )

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        rec_cols = conn.execute(text("PRAGMA table_info(activity_records)")).fetchall()
        rec_col_map = {row[1]: row for row in rec_cols}
        need_rebuild_records = False
        if "mood_score" not in rec_col_map:
            need_rebuild_records = True
        # PRAGMA table_info: row[3] -> notnull (1/0)
        if "efficiency_score" in rec_col_map and int(rec_col_map["efficiency_score"][3]) == 1:
            need_rebuild_records = True
        if need_rebuild_records:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS activity_records_new ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "block_id INTEGER NOT NULL,"
                    "start_time DATETIME NOT NULL,"
                    "end_time DATETIME NOT NULL,"
                    "efficiency_score INTEGER NULL,"
                    "state_score INTEGER NULL,"
                    "mood_score INTEGER NULL,"
                    "tags VARCHAR(200) NULL,"
                    "note TEXT NULL,"
                    "created_at DATETIME NOT NULL,"
                    "updated_at DATETIME NOT NULL,"
                    "FOREIGN KEY(block_id) REFERENCES event_blocks(id)"
                    ")"
                )
            )
            has_mood = "mood_score" in rec_col_map
            mood_select = "mood_score" if has_mood else "NULL AS mood_score"
            conn.execute(
                text(
                    "INSERT INTO activity_records_new "
                    "(id, block_id, start_time, end_time, efficiency_score, state_score, mood_score, tags, note, created_at, updated_at) "
                    "SELECT id, block_id, start_time, end_time, efficiency_score, state_score, "
                    + mood_select
                    + ", tags, note, created_at, updated_at FROM activity_records"
                )
            )
            conn.execute(text("DROP TABLE activity_records"))
            conn.execute(text("ALTER TABLE activity_records_new RENAME TO activity_records"))
            conn.execute(text("PRAGMA foreign_keys=ON"))

        task_cols = conn.execute(text("PRAGMA table_info(tasks)")).fetchall()
        task_col_names = {row[1] for row in task_cols}
        if "block_id" not in task_col_names:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN block_id INTEGER REFERENCES event_blocks(id)"))

        cols = conn.execute(text("PRAGMA table_info(event_blocks)")).fetchall()
        col_names = {row[1] for row in cols}
        if "category" not in col_names:
            conn.execute(text("ALTER TABLE event_blocks ADD COLUMN category TEXT DEFAULT 'study_work' NOT NULL"))
        if "points_per_minute" not in col_names:
            conn.execute(text("ALTER TABLE event_blocks ADD COLUMN points_per_minute REAL DEFAULT 0 NOT NULL"))
        # Keep color consistent with fixed two categories.
        conn.execute(
            text(
                "UPDATE event_blocks SET color = CASE "
                "WHEN category = 'rest_entertainment' THEN '#3B82F6' "
                "ELSE '#DC2626' END"
            )
        )
        conn.execute(
            text(
                "INSERT INTO event_blocks(name, category, color, points_per_minute, is_active, created_at, updated_at) "
                "SELECT '睡觉', 'rest_entertainment', '#3B82F6', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
                "WHERE NOT EXISTS (SELECT 1 FROM event_blocks WHERE name='睡觉')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO event_blocks(name, category, color, points_per_minute, is_active, created_at, updated_at) "
                "SELECT '吃饭', 'rest_entertainment', '#3B82F6', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
                "WHERE NOT EXISTS (SELECT 1 FROM event_blocks WHERE name='吃饭')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO point_accounts(id, balance, updated_at) "
                "SELECT 1, 0, CURRENT_TIMESTAMP "
                "WHERE NOT EXISTS (SELECT 1 FROM point_accounts WHERE id = 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO app_settings(key, value, updated_at) "
                "SELECT 'points_enabled', '1', CURRENT_TIMESTAMP "
                "WHERE NOT EXISTS (SELECT 1 FROM app_settings WHERE key = 'points_enabled')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO app_settings(key, value, updated_at) "
                "SELECT 'sleep_start_before', '23:30', CURRENT_TIMESTAMP "
                "WHERE NOT EXISTS (SELECT 1 FROM app_settings WHERE key = 'sleep_start_before')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO app_settings(key, value, updated_at) "
                "SELECT 'sleep_wake_before', '08:00', CURRENT_TIMESTAMP "
                "WHERE NOT EXISTS (SELECT 1 FROM app_settings WHERE key = 'sleep_wake_before')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO app_settings(key, value, updated_at) "
                "SELECT 'sleep_bonus_delta', '20', CURRENT_TIMESTAMP "
                "WHERE NOT EXISTS (SELECT 1 FROM app_settings WHERE key = 'sleep_bonus_delta')"
            )
        )
    _SESSION_FACTORY = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_db_path() -> Path:
    if _DB_PATH is None:
        return get_default_db_path()
    return _DB_PATH


def get_session_factory() -> sessionmaker[Session]:
    if _SESSION_FACTORY is None:
        init_db(get_default_db_path())
    assert _SESSION_FACTORY is not None
    return _SESSION_FACTORY


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def now_utc() -> datetime:
    return datetime.utcnow()
