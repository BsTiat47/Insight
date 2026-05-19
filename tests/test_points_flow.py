from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from src.app.services.points_service import apply_points_for_new_record, manual_adjust_points, recalculate_points_for_record
from src.app.storage.database import init_db, session_scope
from src.app.storage.repositories import (
    BLOCK_CATEGORY_REST,
    BLOCK_CATEGORY_WORK,
    create_block,
    create_record,
    get_point_account,
    get_points_settings,
    list_point_ledger,
    list_blocks,
    save_points_settings,
    update_record,
)


def test_points_are_calculated_by_minutes_and_manual_adjust(tmp_path: Path) -> None:
    init_db(tmp_path / "test_points.db")
    with session_scope() as session:
        writing = create_block(session, "写作", BLOCK_CATEGORY_WORK, points_per_minute=2.0)
        start = datetime(2026, 5, 9, 10, 0)
        end = start + timedelta(minutes=30)
        rec = create_record(session, writing.id, start, end, None, None, None, None, None)
        apply_points_for_new_record(session, rec)
        manual_adjust_points(session, -5, "兑换奖励")

        account = get_point_account(session)
        assert account.balance == 55  # 30*2 - 5
        ledger = list_point_ledger(session, limit=10)
        assert len(ledger) >= 2
        assert any(item.delta == -5 for item in ledger)


def test_points_can_be_disabled(tmp_path: Path) -> None:
    init_db(tmp_path / "test_points_disable.db")
    with session_scope() as session:
        settings = get_points_settings(session)
        save_points_settings(
            session,
            points_enabled=False,
            sleep_start_before=settings.sleep_start_before,
            sleep_wake_before=settings.sleep_wake_before,
            sleep_bonus_delta=settings.sleep_bonus_delta,
        )
        study = create_block(session, "学习", BLOCK_CATEGORY_WORK, points_per_minute=3.0)
        start = datetime(2026, 5, 9, 9, 0)
        end = start + timedelta(minutes=20)
        rec = create_record(session, study.id, start, end, None, None, None, None, None)
        apply_points_for_new_record(session, rec)

        account = get_point_account(session)
        assert account.balance == 0
        assert list_point_ledger(session, limit=10) == []


def test_sleep_bonus_and_recalculate(tmp_path: Path) -> None:
    init_db(tmp_path / "test_sleep_bonus.db")
    with session_scope() as session:
        save_points_settings(
            session,
            points_enabled=True,
            sleep_start_before="23:30",
            sleep_wake_before="08:00",
            sleep_bonus_delta=12,
        )
        sleep_block = next((b for b in list_blocks(session, include_inactive=True) if b.name == "睡觉"), None)
        assert sleep_block is not None
        sleep_block.points_per_minute = 1.0
        start = datetime(2026, 5, 8, 23, 0)
        end = datetime(2026, 5, 9, 7, 20)
        rec = create_record(session, sleep_block.id, start, end, None, None, None, None, None)
        apply_points_for_new_record(session, rec)
        assert get_point_account(session).balance == 512  # 500 + 12

        updated = update_record(
            session,
            rec.id,
            sleep_block.id,
            datetime(2026, 5, 9, 0, 30),
            datetime(2026, 5, 9, 9, 0),
            None,
            None,
            None,
            None,
            None,
        )
        recalculate_points_for_record(session, record_id=rec.id, new_record=updated)
        assert get_point_account(session).balance == 510  # old 512 rollback, new 510 (no bonus)
