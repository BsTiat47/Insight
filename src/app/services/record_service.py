"""Record validation and timer state helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class TimerState:
    running: bool = False
    started_at: datetime | None = None


def _validate_optional_score(score: int | None, label: str) -> None:
    if score is None:
        return
    if score < 1 or score > 5:
        raise ValueError(f"{label}评分必须在 1 到 5 之间，或选择无。")


def validate_scores(efficiency: int | None, state: int | None, mood: int | None) -> None:
    _validate_optional_score(efficiency, "效率")
    _validate_optional_score(state, "状态")
    _validate_optional_score(mood, "心情")


def validate_time_range(start_time: datetime, end_time: datetime) -> None:
    if end_time <= start_time:
        raise ValueError("结束时间必须晚于开始时间。")
