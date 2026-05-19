"""Points calculation and ledger write helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from sqlalchemy.orm import Session

from ..domain.models import ActivityRecord, EventBlock
from ..storage.database import now_utc
from ..storage.repositories import (
    append_point_ledger,
    get_point_account,
    get_points_settings,
    sum_point_ledger_by_ref,
)

REASON_EVENT_MINUTES = "event_minutes"
REASON_SLEEP_BONUS = "sleep_bonus"
REASON_RECORD_RECALC = "record_recalc"
REASON_MANUAL_ADJUST = "manual_adjust"
REF_TYPE_ACTIVITY_RECORD = "activity_record"


@dataclass
class RecordSnapshot:
    id: int
    block_id: int
    start_time: datetime
    end_time: datetime


def snapshot_record(record: ActivityRecord) -> RecordSnapshot:
    return RecordSnapshot(
        id=record.id,
        block_id=record.block_id,
        start_time=record.start_time,
        end_time=record.end_time,
    )


def _duration_minutes(record: RecordSnapshot) -> int:
    seconds = int((record.end_time - record.start_time).total_seconds())
    if seconds <= 0:
        return 0
    return seconds // 60


def _parse_hhmm(value: str, fallback: str) -> time:
    raw = value or fallback
    try:
        parts = raw.split(":")
        return time(hour=int(parts[0]), minute=int(parts[1]))
    except Exception:
        fallback_parts = fallback.split(":")
        return time(hour=int(fallback_parts[0]), minute=int(fallback_parts[1]))


def _record_point_delta(block: EventBlock, record: RecordSnapshot) -> int:
    minutes = _duration_minutes(record)
    if minutes <= 0:
        return 0
    return int(round(minutes * float(block.points_per_minute)))


def _is_sleep_block(block: EventBlock) -> bool:
    return block.name.strip() == "睡觉"


def _sleep_bonus_delta(record: RecordSnapshot, block: EventBlock, settings_sleep_bonus_delta: int, sleep_start_before: str, sleep_wake_before: str) -> int:
    if not _is_sleep_block(block):
        return 0
    start_limit = _parse_hhmm(sleep_start_before, "23:30")
    wake_limit = _parse_hhmm(sleep_wake_before, "08:00")
    if record.start_time.time() <= start_limit and record.end_time.time() <= wake_limit:
        return int(settings_sleep_bonus_delta)
    return 0


def _apply_record_points(session: Session, record: RecordSnapshot) -> None:
    settings = get_points_settings(session)
    if not settings.points_enabled:
        return
    block = session.get(EventBlock, record.block_id)
    if block is None:
        return
    event_delta = _record_point_delta(block, record)
    if event_delta != 0:
        append_point_ledger(
            session,
            delta=event_delta,
            reason=REASON_EVENT_MINUTES,
            ref_type=REF_TYPE_ACTIVITY_RECORD,
            ref_id=record.id,
            note=f"{block.name} {event_delta:+d} 积分（按分钟）",
        )
    bonus_delta = _sleep_bonus_delta(
        record,
        block,
        settings_sleep_bonus_delta=settings.sleep_bonus_delta,
        sleep_start_before=settings.sleep_start_before,
        sleep_wake_before=settings.sleep_wake_before,
    )
    if bonus_delta != 0:
        append_point_ledger(
            session,
            delta=bonus_delta,
            reason=REASON_SLEEP_BONUS,
            ref_type=REF_TYPE_ACTIVITY_RECORD,
            ref_id=record.id,
            note=f"早睡早起奖励 {bonus_delta:+d}",
        )


def apply_points_for_new_record(session: Session, record: ActivityRecord) -> None:
    _apply_record_points(session, snapshot_record(record))


def recalculate_points_for_record(
    session: Session,
    *,
    record_id: int,
    new_record: ActivityRecord | None,
) -> None:
    existing_sum = sum_point_ledger_by_ref(session, ref_type=REF_TYPE_ACTIVITY_RECORD, ref_id=record_id)
    if existing_sum != 0:
        append_point_ledger(
            session,
            delta=-existing_sum,
            reason=REASON_RECORD_RECALC,
            ref_type=REF_TYPE_ACTIVITY_RECORD,
            ref_id=record_id,
            note="记录更新/删除，回滚旧积分",
            created_at=now_utc(),
        )
    if new_record is not None:
        _apply_record_points(session, snapshot_record(new_record))


def manual_adjust_points(session: Session, delta: int, note: str | None) -> None:
    if delta == 0:
        return
    append_point_ledger(
        session,
        delta=delta,
        reason=REASON_MANUAL_ADJUST,
        note=note or "手动调整",
    )


def get_current_balance(session: Session) -> int:
    account = get_point_account(session)
    return int(account.balance)
