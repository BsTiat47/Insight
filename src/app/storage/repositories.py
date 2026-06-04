"""Repository helpers for blocks and records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from ..domain.models import ActivityRecord, AppSetting, CorrelationProject, EventBlock, PointAccount, PointLedgerEntry, Task
from .database import now_utc

BLOCK_CATEGORY_REST = "rest_entertainment"
BLOCK_CATEGORY_WORK = "study_work"

CATEGORY_COLOR_MAP = {
    BLOCK_CATEGORY_REST: "#3B82F6",  # blue
    BLOCK_CATEGORY_WORK: "#DC2626",  # red
}

CATEGORY_LABEL_MAP = {
    BLOCK_CATEGORY_REST: "休息/娱乐",
    BLOCK_CATEGORY_WORK: "学习/工作",
}


@dataclass
class BlockStats:
    block_name: str
    records_count: int
    total_minutes: int


@dataclass
class CorrelationProjectData:
    id: int
    name: str
    days: int
    time_relation: str
    target_variable: str
    source_config: str
    is_active: bool
    updated_at: datetime


@dataclass
class PointSettings:
    points_enabled: bool
    sleep_start_before: str
    sleep_wake_before: str
    sleep_bonus_delta: int


def list_blocks(session: Session, include_inactive: bool = True) -> list[EventBlock]:
    stmt: Select[tuple[EventBlock]] = select(EventBlock).order_by(EventBlock.name.asc())
    if not include_inactive:
        stmt = stmt.where(EventBlock.is_active.is_(True))
    return list(session.scalars(stmt).all())


def create_block(session: Session, name: str, category: str, points_per_minute: float = 0.0) -> EventBlock:
    color = CATEGORY_COLOR_MAP.get(category, CATEGORY_COLOR_MAP[BLOCK_CATEGORY_WORK])
    block = EventBlock(
        name=name.strip(),
        category=category,
        color=color,
        points_per_minute=float(points_per_minute),
        is_active=True,
    )
    session.add(block)
    session.flush()
    return block


def update_block(
    session: Session,
    block_id: int,
    name: str,
    category: str,
    points_per_minute: float | None = None,
) -> EventBlock:
    block = session.get(EventBlock, block_id)
    if block is None:
        raise ValueError("Block not found.")
    block.name = name.strip()
    block.category = category
    block.color = CATEGORY_COLOR_MAP.get(category, CATEGORY_COLOR_MAP[BLOCK_CATEGORY_WORK])
    if points_per_minute is not None:
        block.points_per_minute = float(points_per_minute)
    block.updated_at = now_utc()
    session.flush()
    return block


def set_block_active(session: Session, block_id: int, is_active: bool) -> None:
    block = session.get(EventBlock, block_id)
    if block is None:
        raise ValueError("Block not found.")
    block.is_active = is_active
    block.updated_at = now_utc()
    session.flush()


def delete_block(session: Session, block_id: int) -> None:
    block = session.get(EventBlock, block_id)
    if block is None:
        raise ValueError("Block not found.")
    used_count = session.scalar(select(func.count(ActivityRecord.id)).where(ActivityRecord.block_id == block_id)) or 0
    if used_count > 0:
        raise ValueError("该方块已有关联记录，不能删除。")
    session.delete(block)
    session.flush()


def create_record(
    session: Session,
    block_id: int,
    start_time: datetime,
    end_time: datetime,
    efficiency_score: int | None,
    state_score: int | None,
    mood_score: int | None,
    tags: str | None,
    note: str | None,
) -> ActivityRecord:
    record = ActivityRecord(
        block_id=block_id,
        start_time=start_time,
        end_time=end_time,
        efficiency_score=efficiency_score,
        state_score=state_score,
        mood_score=mood_score,
        tags=tags or None,
        note=note or None,
    )
    session.add(record)
    session.flush()
    return record


def update_record(
    session: Session,
    record_id: int,
    block_id: int,
    start_time: datetime,
    end_time: datetime,
    efficiency_score: int | None,
    state_score: int | None,
    mood_score: int | None,
    tags: str | None,
    note: str | None,
) -> ActivityRecord:
    record = session.get(ActivityRecord, record_id)
    if record is None:
        raise ValueError("Record not found.")
    record.block_id = block_id
    record.start_time = start_time
    record.end_time = end_time
    record.efficiency_score = efficiency_score
    record.state_score = state_score
    record.mood_score = mood_score
    record.tags = tags or None
    record.note = note or None
    record.updated_at = now_utc()
    session.flush()
    return record


def delete_record(session: Session, record_id: int) -> None:
    record = session.get(ActivityRecord, record_id)
    if record is None:
        return
    session.delete(record)
    session.flush()


def list_recent_records(session: Session, limit: int = 100) -> list[ActivityRecord]:
    stmt = select(ActivityRecord).order_by(ActivityRecord.start_time.desc()).limit(limit)
    return list(session.scalars(stmt).all())


def get_record_by_id(session: Session, record_id: int) -> ActivityRecord | None:
    return session.get(ActivityRecord, record_id)


def list_records_for_day(session: Session, day: datetime) -> list[ActivityRecord]:
    start = datetime(day.year, day.month, day.day)
    end = start + timedelta(days=1)
    stmt = (
        select(ActivityRecord)
        .where(ActivityRecord.start_time >= start, ActivityRecord.start_time < end)
        .order_by(ActivityRecord.start_time.asc())
    )
    return list(session.scalars(stmt).all())


def list_records_in_range(session: Session, start: datetime, end: datetime) -> list[ActivityRecord]:
    """Return records that overlap with [start, end)."""
    stmt = (
        select(ActivityRecord)
        .where(ActivityRecord.start_time < end, ActivityRecord.end_time > start)
        .order_by(ActivityRecord.start_time.asc())
    )
    return list(session.scalars(stmt).all())


def list_recent_blocks(session: Session, limit: int = 5) -> list[EventBlock]:
    stmt = (
        select(EventBlock)
        .join(ActivityRecord, ActivityRecord.block_id == EventBlock.id)
        .group_by(EventBlock.id)
        .order_by(func.max(ActivityRecord.start_time).desc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def block_summary(session: Session, days: int) -> list[BlockStats]:
    since = datetime.now() - timedelta(days=days - 1)
    duration_minutes = (
        (func.strftime("%s", ActivityRecord.end_time) - func.strftime("%s", ActivityRecord.start_time)) / 60
    )
    stmt = (
        select(
            EventBlock.name,
            func.count(ActivityRecord.id),
            func.coalesce(func.sum(duration_minutes), 0),
        )
        .join(ActivityRecord, ActivityRecord.block_id == EventBlock.id)
        .where(ActivityRecord.start_time >= since)
        .group_by(EventBlock.id)
        .order_by(func.count(ActivityRecord.id).desc())
    )
    rows = session.execute(stmt).all()
    return [BlockStats(block_name=name, records_count=count, total_minutes=int(total)) for name, count, total in rows]


def list_correlation_projects(session: Session, include_inactive: bool = False) -> list[CorrelationProjectData]:
    stmt = select(CorrelationProject).order_by(CorrelationProject.updated_at.desc())
    if not include_inactive:
        stmt = stmt.where(CorrelationProject.is_active.is_(True))
    rows = session.scalars(stmt).all()
    return [
        CorrelationProjectData(
            id=row.id,
            name=row.name,
            days=row.days,
            time_relation=row.time_relation,
            target_variable=row.target_variable,
            source_config=row.source_config,
            is_active=row.is_active,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


def get_correlation_project(session: Session, project_id: int) -> CorrelationProject | None:
    return session.get(CorrelationProject, project_id)


def create_correlation_project(
    session: Session,
    name: str,
    days: int,
    time_relation: str,
    target_variable: str,
    source_config: str,
    is_active: bool = True,
) -> CorrelationProject:
    project = CorrelationProject(
        name=name.strip(),
        days=days,
        time_relation=time_relation,
        target_variable=target_variable,
        source_config=source_config,
        is_active=is_active,
    )
    session.add(project)
    session.flush()
    return project


def update_correlation_project(
    session: Session,
    project_id: int,
    *,
    name: str | None = None,
    days: int | None = None,
    time_relation: str | None = None,
    target_variable: str | None = None,
    source_config: str | None = None,
    is_active: bool | None = None,
) -> CorrelationProject:
    project = session.get(CorrelationProject, project_id)
    if project is None:
        raise ValueError("Correlation project not found.")
    if name is not None:
        project.name = name.strip()
    if days is not None:
        project.days = days
    if time_relation is not None:
        project.time_relation = time_relation
    if target_variable is not None:
        project.target_variable = target_variable
    if source_config is not None:
        project.source_config = source_config
    if is_active is not None:
        project.is_active = is_active
    project.updated_at = now_utc()
    session.flush()
    return project


def delete_correlation_project(session: Session, project_id: int) -> None:
    project = session.get(CorrelationProject, project_id)
    if project is None:
        return
    session.delete(project)
    session.flush()


def _setting_get(session: Session, key: str, default: str) -> str:
    row = session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=default)
        session.add(row)
        session.flush()
        return default
    return row.value


def _setting_set(session: Session, key: str, value: str) -> None:
    row = session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
        session.add(row)
    else:
        row.value = value
        row.updated_at = now_utc()
    session.flush()


def get_points_settings(session: Session) -> PointSettings:
    enabled_raw = _setting_get(session, "points_enabled", "1")
    sleep_start_before = _setting_get(session, "sleep_start_before", "23:30")
    sleep_wake_before = _setting_get(session, "sleep_wake_before", "08:00")
    sleep_bonus_raw = _setting_get(session, "sleep_bonus_delta", "20")
    try:
        sleep_bonus = int(sleep_bonus_raw)
    except ValueError:
        sleep_bonus = 20
    return PointSettings(
        points_enabled=enabled_raw == "1",
        sleep_start_before=sleep_start_before,
        sleep_wake_before=sleep_wake_before,
        sleep_bonus_delta=sleep_bonus,
    )


def save_points_settings(
    session: Session,
    *,
    points_enabled: bool,
    sleep_start_before: str,
    sleep_wake_before: str,
    sleep_bonus_delta: int,
) -> PointSettings:
    _setting_set(session, "points_enabled", "1" if points_enabled else "0")
    _setting_set(session, "sleep_start_before", sleep_start_before)
    _setting_set(session, "sleep_wake_before", sleep_wake_before)
    _setting_set(session, "sleep_bonus_delta", str(int(sleep_bonus_delta)))
    return get_points_settings(session)


# ── AI settings ──────────────────────────────────────────────

@dataclass
class AISettings:
    enabled: bool = False
    api_url: str = "https://api.deepseek.com/v1/chat/completions"
    api_key: str = ""
    model: str = "deepseek-chat"
    system_prompt: str = ""


DEFAULT_AI_SYSTEM_PROMPT = (
    "你是一个个人日程助理。用户框选了一个时间段，你需要为其安排合理的活动。\n"
    "规则：\n"
    "1. 根据用户习惯和待办事项，将时间段拆分为连续的活动块。\n"
    "2. 连续无间隙：events的start_offset_minutes和end_offset_minutes必须首尾相连，覆盖整个时间段。\n"
    "3. 第一个event的start_offset_minutes必须为0，最后一个的end_offset_minutes必须等于总时长。\n\n"
    "示例（3小时的时间段）：\n"
    '{"events": [\n'
    '  {"block_name": "学习", "start_offset_minutes": 0, "end_offset_minutes": 90, "efficiency_score": 4, "state_score": 3, "mood_score": null, "note": "集中学习"},\n'
    '  {"block_name": "休息", "start_offset_minutes": 90, "end_offset_minutes": 105, "efficiency_score": null, "state_score": null, "mood_score": null, "note": "短暂休息"},\n'
    '  {"block_name": "学习", "start_offset_minutes": 105, "end_offset_minutes": 180, "efficiency_score": 3, "state_score": 3, "mood_score": null, "note": "继续学习"}\n'
    "]}\n"
    "只返回JSON，不要有其他内容。"
)


def get_ai_settings(session: Session) -> AISettings:
    return AISettings(
        enabled=_setting_get(session, "ai_enabled", "0") == "1",
        api_url=_setting_get(session, "ai_api_url", "https://api.deepseek.com/v1/chat/completions"),
        api_key=_setting_get(session, "ai_api_key", ""),
        model=_setting_get(session, "ai_model", "deepseek-chat"),
        system_prompt=_setting_get(session, "ai_system_prompt", DEFAULT_AI_SYSTEM_PROMPT),
    )


def save_ai_settings(
    session: Session,
    *,
    enabled: bool,
    api_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
) -> AISettings:
    _setting_set(session, "ai_enabled", "1" if enabled else "0")
    _setting_set(session, "ai_api_url", api_url)
    _setting_set(session, "ai_api_key", api_key)
    _setting_set(session, "ai_model", model)
    _setting_set(session, "ai_system_prompt", system_prompt)
    return get_ai_settings(session)


def get_point_account(session: Session) -> PointAccount:
    account = session.get(PointAccount, 1)
    if account is None:
        account = PointAccount(id=1, balance=0)
        session.add(account)
        session.flush()
    return account


def append_point_ledger(
    session: Session,
    *,
    delta: int,
    reason: str,
    ref_type: str | None = None,
    ref_id: int | None = None,
    note: str | None = None,
    created_at: datetime | None = None,
) -> PointLedgerEntry:
    account = get_point_account(session)
    account.balance += int(delta)
    account.updated_at = now_utc()
    entry = PointLedgerEntry(
        account_id=account.id,
        delta=int(delta),
        balance_after=account.balance,
        reason=reason,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note or None,
        created_at=created_at or now_utc(),
    )
    session.add(entry)
    session.flush()
    return entry


def sum_point_ledger_by_ref(session: Session, *, ref_type: str, ref_id: int) -> int:
    total = session.scalar(
        select(func.coalesce(func.sum(PointLedgerEntry.delta), 0)).where(
            PointLedgerEntry.ref_type == ref_type, PointLedgerEntry.ref_id == ref_id
        )
    )
    return int(total or 0)


def list_point_ledger(session: Session, limit: int = 200) -> list[PointLedgerEntry]:
    stmt = select(PointLedgerEntry).order_by(PointLedgerEntry.created_at.desc(), PointLedgerEntry.id.desc()).limit(limit)
    return list(session.scalars(stmt).all())


# ── Task CRUD ──────────────────────────────────────────────

def create_task(
    session: Session,
    *,
    name: str,
    task_type: str,
    end_date: date,
    start_date: date | None = None,
    total_minutes: int | None = None,
    daily_minutes: int | None = None,
) -> Task:
    task = Task(
        name=name,
        task_type=task_type,
        start_date=start_date,
        end_date=end_date,
        total_minutes=total_minutes,
        daily_minutes=daily_minutes,
    )
    session.add(task)
    session.flush()
    return task


def update_task(
    session: Session,
    task_id: int,
    *,
    name: str,
    task_type: str,
    end_date: date,
    start_date: date | None = None,
    total_minutes: int | None = None,
    daily_minutes: int | None = None,
    is_completed: bool = False,
) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")
    task.name = name
    task.task_type = task_type
    task.start_date = start_date
    task.end_date = end_date
    task.total_minutes = total_minutes
    task.daily_minutes = daily_minutes
    task.is_completed = is_completed
    task.updated_at = now_utc()
    session.flush()
    return task


def delete_task(session: Session, task_id: int) -> None:
    task = session.get(Task, task_id)
    if task is not None:
        session.delete(task)
        session.flush()


def complete_task(session: Session, task_id: int) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")
    task.is_completed = True
    task.updated_at = now_utc()
    session.flush()
    return task


def list_tasks(session: Session, *, include_completed: bool = False) -> list[Task]:
    stmt = select(Task).order_by(Task.is_completed.asc(), Task.end_date.asc(), Task.id.asc())
    if not include_completed:
        stmt = stmt.where(Task.is_completed == False)  # noqa: E712
    return list(session.scalars(stmt).all())
