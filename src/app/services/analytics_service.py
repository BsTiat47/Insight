"""Statistics service for dashboard charts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.models import ActivityRecord, EventBlock
from ..storage.repositories import BLOCK_CATEGORY_REST, BLOCK_CATEGORY_WORK


@dataclass
class DailySeries:
    dates: list[str]
    frequency: list[int]
    avg_efficiency: list[float]
    avg_state: list[float]


@dataclass
class CategorySeries:
    dates: list[str]
    duration_minutes: list[float]
    frequency: list[int]
    avg_efficiency: list[float]
    avg_state: list[float]
    avg_mood: list[float]


@dataclass
class _DayAccumulator:
    duration_minutes: list[float]
    frequency: list[int]
    eff_sum: list[float]
    eff_count: list[int]
    state_sum: list[float]
    state_count: list[int]
    mood_sum: list[float]
    mood_count: list[int]


def _build_day_index(days: int) -> tuple[date, list[date], dict[date, int]]:
    start_day = datetime.now().date() - timedelta(days=days - 1)
    dates = [start_day + timedelta(days=i) for i in range(days)]
    return start_day, dates, {d: idx for idx, d in enumerate(dates)}


def _empty_accumulator(days: int) -> _DayAccumulator:
    return _DayAccumulator(
        duration_minutes=[0.0] * days,
        frequency=[0] * days,
        eff_sum=[0.0] * days,
        eff_count=[0] * days,
        state_sum=[0.0] * days,
        state_count=[0] * days,
        mood_sum=[0.0] * days,
        mood_count=[0] * days,
    )


def _accumulator_to_series(acc: _DayAccumulator, dates: list[date]) -> CategorySeries:
    days = len(dates)
    return CategorySeries(
        dates=[d.strftime("%m-%d") for d in dates],
        duration_minutes=[round(v, 2) for v in acc.duration_minutes],
        frequency=acc.frequency,
        avg_efficiency=[round(acc.eff_sum[i] / acc.eff_count[i], 2) if acc.eff_count[i] else 0.0 for i in range(days)],
        avg_state=[round(acc.state_sum[i] / acc.state_count[i], 2) if acc.state_count[i] else 0.0 for i in range(days)],
        avg_mood=[round(acc.mood_sum[i] / acc.mood_count[i], 2) if acc.mood_count[i] else 0.0 for i in range(days)],
    )


def build_daily_series(session: Session, days: int) -> DailySeries:
    start_day, dates, day_index = _build_day_index(days)
    stmt = (
        select(
            ActivityRecord.start_time,
            ActivityRecord.efficiency_score,
            ActivityRecord.state_score,
        )
        .where(ActivityRecord.start_time >= datetime.combine(start_day, datetime.min.time()))
    )
    rows = session.execute(stmt).all()

    frequency = [0] * days
    eff_sum = [0.0] * days
    eff_count = [0] * days
    state_sum = [0.0] * days
    state_count = [0] * days

    for row in rows:
        idx = day_index.get(row.start_time.date())
        if idx is None:
            continue
        frequency[idx] += 1
        if row.efficiency_score is not None:
            eff_sum[idx] += float(row.efficiency_score)
            eff_count[idx] += 1
        if row.state_score is not None:
            state_sum[idx] += float(row.state_score)
            state_count[idx] += 1

    return DailySeries(
        dates=[d.strftime("%m-%d") for d in dates],
        frequency=frequency,
        avg_efficiency=[round(eff_sum[i] / eff_count[i], 2) if eff_count[i] else 0.0 for i in range(days)],
        avg_state=[round(state_sum[i] / state_count[i], 2) if state_count[i] else 0.0 for i in range(days)],
    )


def _load_record_rows(session: Session, since: datetime, block_ids: list[int] | None = None) -> list:
    stmt = (
        select(
            ActivityRecord.start_time,
            ActivityRecord.end_time,
            ActivityRecord.efficiency_score,
            ActivityRecord.state_score,
            ActivityRecord.mood_score,
            ActivityRecord.block_id,
            EventBlock.category,
            EventBlock.name,
        )
        .join(EventBlock, EventBlock.id == ActivityRecord.block_id)
        .where(ActivityRecord.start_time >= since)
    )
    if block_ids:
        stmt = stmt.where(ActivityRecord.block_id.in_(block_ids))
    return session.execute(stmt).all()


def build_category_overview(session: Session, days: int) -> dict[str, CategorySeries]:
    since = datetime.now() - timedelta(days=days - 1)
    _, dates, day_index = _build_day_index(days)
    rows = _load_record_rows(session, since=since)

    accumulators = {
        BLOCK_CATEGORY_REST: _empty_accumulator(days),
        BLOCK_CATEGORY_WORK: _empty_accumulator(days),
    }

    for row in rows:
        if row.category not in accumulators:
            continue
        idx = day_index.get(row.start_time.date())
        if idx is None:
            continue
        acc = accumulators[row.category]
        acc.duration_minutes[idx] += max(0.0, (row.end_time - row.start_time).total_seconds() / 60.0)
        acc.frequency[idx] += 1
        if row.efficiency_score is not None:
            acc.eff_sum[idx] += float(row.efficiency_score)
            acc.eff_count[idx] += 1
        if row.state_score is not None:
            acc.state_sum[idx] += float(row.state_score)
            acc.state_count[idx] += 1
        if row.mood_score is not None:
            acc.mood_sum[idx] += float(row.mood_score)
            acc.mood_count[idx] += 1

    return {
        BLOCK_CATEGORY_REST: _accumulator_to_series(accumulators[BLOCK_CATEGORY_REST], dates),
        BLOCK_CATEGORY_WORK: _accumulator_to_series(accumulators[BLOCK_CATEGORY_WORK], dates),
    }


def build_custom_metrics(
    session: Session,
    days: int,
    block_ids: list[int],
) -> CategorySeries:
    since = datetime.now() - timedelta(days=days - 1)
    _, dates, day_index = _build_day_index(days)
    acc = _empty_accumulator(days)
    rows = _load_record_rows(session, since=since, block_ids=block_ids)

    for row in rows:
        idx = day_index.get(row.start_time.date())
        if idx is None:
            continue
        acc.duration_minutes[idx] += max(0.0, (row.end_time - row.start_time).total_seconds() / 60.0)
        acc.frequency[idx] += 1
        if row.efficiency_score is not None:
            acc.eff_sum[idx] += float(row.efficiency_score)
            acc.eff_count[idx] += 1
        if row.state_score is not None:
            acc.state_sum[idx] += float(row.state_score)
            acc.state_count[idx] += 1
        if row.mood_score is not None:
            acc.mood_sum[idx] += float(row.mood_score)
            acc.mood_count[idx] += 1

    return _accumulator_to_series(acc, dates)
