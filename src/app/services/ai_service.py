"""AI-powered event suggestion service (DeepSeek / OpenAI-compatible API)."""

from __future__ import annotations

import json
import socket
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from ..domain.models import ActivityRecord, EventBlock, Task
from ..storage.repositories import (
    AISettings,
    get_ai_settings,
    list_blocks,
    list_records_in_range,
    list_tasks,
)


@dataclass
class SuggestedEvent:
    block_name: str
    start_offset_minutes: int  # minutes from selection start
    end_offset_minutes: int    # minutes from selection start
    efficiency_score: int | None = None
    state_score: int | None = None
    mood_score: int | None = None
    note: str | None = None


@dataclass
class AISuggestion:
    events: list[SuggestedEvent]


WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

TIME_BLOCKS = [
    (0, 6, "凌晨"),
    (6, 9, "早晨"),
    (9, 12, "上午"),
    (12, 14, "中午"),
    (14, 18, "下午"),
    (18, 22, "晚上"),
    (22, 24, "深夜"),
]


def _build_pattern_summary(records, max_samples: int = 200) -> str:
    """Build a summary of long-term activity patterns from historical records."""
    if not records:
        return "（无历史记录）"

    # Aggregate by (weekday, time_block) -> list of block names
    pattern: dict[tuple[int, str], list[str]] = defaultdict(list)
    sample = records[-max_samples:]
    for rec in sample:
        wd = rec.start_time.weekday()
        hour = rec.start_time.hour
        # Block is eager-loaded, no lazy query needed
        block_name = rec.block.name if rec.block is not None else f"#{rec.block_id}"
        for start_h, end_h, label in TIME_BLOCKS:
            if start_h <= hour < end_h:
                pattern[(wd, label)].append(block_name)
                break

    # For each weekday+time_block, find the most common activity
    lines: list[str] = []
    for wd in range(7):
        day_lines = []
        for _, _, label in TIME_BLOCKS:
            entries = pattern.get((wd, label), [])
            if entries:
                # Count frequencies
                counts: dict[str, int] = {}
                for e in entries:
                    counts[e] = counts.get(e, 0) + 1
                top = sorted(counts.items(), key=lambda x: -x[1])[:3]
                top_str = "、".join(f"{name}({cnt}次)" for name, cnt in top)
                day_lines.append(f"  {label}: {top_str}")
        if day_lines:
            lines.append(f"{WEEKDAY_ZH[wd]}:\n" + "\n".join(day_lines))
    return "\n".join(lines) if lines else "（无显著模式）"


def _build_recent_summary(records, max_samples: int = 30) -> str:
    """Build a summary of recent records."""
    lines: list[str] = []
    for rec in records[-max_samples:]:
        name = rec.block.name if rec.block is not None else f"#{rec.block_id}"
        lines.append(
            f"{rec.start_time.strftime('%m-%d %a %H:%M')}-{rec.end_time.strftime('%H:%M')} {name}"
        )
    return "\n".join(lines) if lines else "（无近期记录）"


def _build_tasks_summary(tasks) -> str:
    """Build a summary of pending tasks."""
    if not tasks:
        return "（无待办事项）"
    lines: list[str] = []
    for t in tasks:
        if t.task_type == "one_time":
            lines.append(
                f"[一次性] {t.name} — 需 {t.total_minutes or '?'} 分钟"
                f"（截止 {t.end_date.isoformat()}）"
            )
        else:
            lines.append(
                f"[长期] {t.name} — 每天 {t.daily_minutes or '?'} 分钟"
                f"（截止 {t.end_date.isoformat()}）"
            )
    return "\n".join(lines)


def _load_records_eager(session: Session, since: datetime) -> list[ActivityRecord]:
    """Load records with eager-loaded block relationship to avoid N+1 queries."""
    from sqlalchemy import select as sa_select
    stmt = (
        sa_select(ActivityRecord)
        .options(joinedload(ActivityRecord.block))
        .where(ActivityRecord.start_time >= since)
        .order_by(ActivityRecord.start_time.asc())
    )
    return list(session.scalars(stmt).all())


@dataclass
class AIContext:
    """Pre-loaded context for AI API call — no DB access needed after construction."""
    settings: AISettings
    block_names: list[str]
    pattern_summary: str
    recent_summary: str
    tasks_summary: str
    user_prompt: str = ""


def build_ai_context(session: Session, start_dt: datetime, end_dt: datetime) -> AIContext | None:
    """Gather all DB data on the main thread. Returns None if AI is disabled."""
    settings = get_ai_settings(session)
    if not settings.enabled or not settings.api_key:
        return None

    blocks = list_blocks(session, include_inactive=False)
    block_names = [b.name for b in blocks]
    three_months_ago = datetime.now() - timedelta(days=90)
    long_term = _load_records_eager(session, three_months_ago)[-300:]
    two_weeks_ago = datetime.now() - timedelta(days=14)
    recent = [r for r in long_term if r.start_time >= two_weeks_ago]
    tasks = list_tasks(session, include_completed=False)

    weekday = WEEKDAY_ZH[start_dt.weekday()]
    slot_duration = int((end_dt - start_dt).total_seconds() // 60)

    user_prompt = (
        f"=== 当前选择 ===\n"
        f"时间段: {weekday} {start_dt.strftime('%H:%M')} 到 {end_dt.strftime('%H:%M')}\n"
        f"总时长: {slot_duration} 分钟\n"
        f"可用活动类型: {', '.join(block_names)}\n\n"
        f"=== 长期习惯模式（按星期几+时段统计） ===\n"
        f"{_build_pattern_summary(long_term)}\n\n"
        f"=== 近期活动记录 ===\n"
        f"{_build_recent_summary(recent)}\n\n"
        f"=== 待完成事项 ===\n"
        f"{_build_tasks_summary(tasks)}\n\n"
        f"请将以上 {slot_duration} 分钟拆分为多个连续活动块，填满整个时间段。"
        f"最后一个event的end_offset_minutes必须等于{slot_duration}。"
        f"优先安排截止日期临近的待办事项。"
    )

    return AIContext(
        settings=settings,
        block_names=block_names,
        pattern_summary=_build_pattern_summary(long_term),
        recent_summary=_build_recent_summary(recent),
        tasks_summary=_build_tasks_summary(tasks),
        user_prompt=user_prompt,
    )


def call_ai_api(ctx: AIContext, start_dt: datetime, end_dt: datetime) -> AISuggestion | None:
    """Pure HTTP call — no DB access. Safe to run from any thread."""
    from ..storage.repositories import DEFAULT_AI_SYSTEM_PROMPT
    # Always use the built-in multi-event prompt to ensure correct behavior
    system_prompt = DEFAULT_AI_SYSTEM_PROMPT
    payload = {
        "model": ctx.settings.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": ctx.user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
    }

    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(5)
    try:
        req = urllib.request.Request(
            ctx.settings.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {ctx.settings.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    finally:
        socket.setdefaulttimeout(old_timeout)

    try:
        content = body["choices"][0]["message"]["content"]
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
            if content.endswith("```"):
                content = content[:-3]
        data = json.loads(content)
    except (json.JSONDecodeError, KeyError, IndexError):
        return None

    raw_events = data.get("events", [])
    if not raw_events or not isinstance(raw_events, list):
        if data.get("block_name"):
            raw_events = [{
                "block_name": data["block_name"],
                "start_offset_minutes": 0,
                "end_offset_minutes": int((end_dt - start_dt).total_seconds() // 60),
                "efficiency_score": data.get("efficiency_score"),
                "state_score": data.get("state_score"),
                "mood_score": data.get("mood_score"),
                "note": data.get("note"),
            }]
        else:
            return None

    def _clamp_score(val) -> int | None:
        if val is None: return None
        try:
            v = int(val)
            return max(1, min(5, v))
        except (ValueError, TypeError):
            return None

    events: list[SuggestedEvent] = []
    for ev in raw_events:
        name = ev.get("block_name", "")
        if not name or name not in ctx.block_names:
            continue
        events.append(SuggestedEvent(
            block_name=name,
            start_offset_minutes=int(ev.get("start_offset_minutes", 0)),
            end_offset_minutes=int(ev.get("end_offset_minutes", 0)),
            efficiency_score=_clamp_score(ev.get("efficiency_score")),
            state_score=_clamp_score(ev.get("state_score")),
            mood_score=_clamp_score(ev.get("mood_score")),
            note=ev.get("note"),
        ))

    return AISuggestion(events=events) if events else None


def suggest_event(session: Session, start_dt: datetime, end_dt: datetime) -> AISuggestion | None:
    """Convenience: build context + call API in one call (used by test_connection path)."""
    ctx = build_ai_context(session, start_dt, end_dt)
    if ctx is None:
        return None
    return call_ai_api(ctx, start_dt, end_dt)


def test_connection(settings: AISettings) -> str:
    """Test the AI API connection. Returns "ok" or an error message."""
    if not settings.api_key:
        return "请先填写 API Key"

    payload = {
        "model": settings.model,
        "messages": [
            {"role": "user", "content": "回复OK"},
        ],
        "temperature": 0,
        "max_tokens": 16,
    }
    try:
        req = urllib.request.Request(
            settings.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            json.loads(resp.read().decode("utf-8"))
        return "ok"
    except Exception as exc:
        return str(exc)
