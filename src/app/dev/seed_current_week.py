"""Seed random records for the current week."""

from __future__ import annotations

import argparse
import random
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select

from ..domain.models import ActivityRecord, EventBlock
from ..storage.database import get_default_db_path, init_db, session_scope
from ..storage.repositories import (
    BLOCK_CATEGORY_REST,
    BLOCK_CATEGORY_WORK,
    create_block,
    create_record,
)


def _week_start(today: date) -> date:
    return today - timedelta(days=today.weekday())


def _ensure_blocks() -> list[EventBlock]:
    with session_scope() as session:
        blocks = list(session.scalars(select(EventBlock).where(EventBlock.is_active.is_(True))).all())
        if blocks:
            return blocks
        defaults = [
            ("专注工作", BLOCK_CATEGORY_WORK),
            ("学习", BLOCK_CATEGORY_WORK),
            ("休息", BLOCK_CATEGORY_REST),
            ("吃饭", BLOCK_CATEGORY_REST),
            ("运动", BLOCK_CATEGORY_REST),
        ]
        for name, category in defaults:
            create_block(session, name=name, category=category)
        return list(session.scalars(select(EventBlock).where(EventBlock.is_active.is_(True))).all())


def seed_current_week(seed: int | None = None, clear_existing: bool = True) -> int:
    rng = random.Random(seed)
    start_day = _week_start(date.today())
    end_day = start_day + timedelta(days=7)

    blocks = _ensure_blocks()
    if not blocks:
        return 0

    total_created = 0
    with session_scope() as session:
        if clear_existing:
            session.execute(
                delete(ActivityRecord).where(
                    ActivityRecord.start_time >= datetime.combine(start_day, time.min),
                    ActivityRecord.start_time < datetime.combine(end_day, time.min),
                )
            )

        for day_idx in range(7):
            day = start_day + timedelta(days=day_idx)
            event_count = rng.randint(5, 9)
            cursor_minutes = rng.randint(7 * 60, 9 * 60)  # 07:00 - 09:00

            for _ in range(event_count):
                block = rng.choice(blocks)
                duration = rng.choice([25, 30, 40, 50, 60, 75, 90])
                gap = rng.randint(5, 25)
                start_dt = datetime.combine(day, time.min) + timedelta(minutes=cursor_minutes)
                end_dt = start_dt + timedelta(minutes=duration)
                if end_dt >= datetime.combine(day, time(23, 30)):
                    break

                create_record(
                    session=session,
                    block_id=block.id,
                    start_time=start_dt,
                    end_time=end_dt,
                    efficiency_score=rng.randint(2, 5),
                    state_score=rng.randint(1, 5),
                    mood_score=rng.randint(1, 5),
                    tags=None,
                    note="自动生成(调试)",
                )
                total_created += 1
                cursor_minutes += duration + gap

    return total_created


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed random records for current week.")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible data.")
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Do not clear records in current week before seeding.",
    )
    args = parser.parse_args()

    init_db(get_default_db_path())
    created = seed_current_week(seed=args.seed, clear_existing=not args.keep_existing)
    print(f"Seeded current week records: {created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

