"""Correlation project analysis service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.models import ActivityRecord, EventBlock
from ..storage.repositories import CorrelationProjectData, get_correlation_project

TARGET_LABELS = {
    "efficiency": "效率均值",
    "state": "状态均值",
    "mood": "心情均值",
}

SOURCE_LABELS = {
    "duration": "时长(分钟)",
    "frequency": "频次(条数)",
    "occurred": "是否发生",
}

TIME_RELATION_LAG = {
    "same_day": 0,
    "lag_1": 1,
    "lag_2": 2,
}

TIME_RELATION_LABEL = {
    "same_day": "同日(T)",
    "lag_1": "滞后1天(T+1)",
    "lag_2": "滞后2天(T+2)",
}


@dataclass
class CorrelationItemResult:
    source_name: str
    samples: int
    spearman: float
    direction: str
    strength: str
    explanation: str


@dataclass
class CorrelationProjectResult:
    project_id: int
    project_name: str
    target_label: str
    source_metric_label: str
    time_relation_label: str
    items: list[CorrelationItemResult]
    summary: str


def _rank(values: list[float]) -> list[float]:
    pairs = sorted(enumerate(values), key=lambda item: item[1])
    ranked = [0.0] * len(values)
    idx = 0
    while idx < len(pairs):
        end = idx
        while end + 1 < len(pairs) and pairs[end + 1][1] == pairs[idx][1]:
            end += 1
        avg_rank = (idx + end) / 2.0 + 1.0
        for j in range(idx, end + 1):
            ranked[pairs[j][0]] = avg_rank
        idx = end + 1
    return ranked


def _pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    num = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    den_x = sqrt(sum((v - mean_x) ** 2 for v in x))
    den_y = sqrt(sum((v - mean_y) ** 2 for v in y))
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def _spearman(x: list[float], y: list[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    return _pearson(_rank(x), _rank(y))


def _strength(value: float) -> str:
    abs_v = abs(value)
    if abs_v < 0.2:
        return "极弱"
    if abs_v < 0.4:
        return "较弱"
    if abs_v < 0.6:
        return "中等"
    if abs_v < 0.8:
        return "较强"
    return "很强"


def _direction(value: float) -> str:
    if value > 0:
        return "正相关"
    if value < 0:
        return "负相关"
    return "无明显方向"


def _parse_config(raw_config: str) -> tuple[str, list[int]]:
    try:
        data = json.loads(raw_config)
    except json.JSONDecodeError:
        return "duration", []
    source_type = str(data.get("source_type", "duration"))
    if source_type not in SOURCE_LABELS:
        source_type = "duration"
    block_ids = [int(v) for v in data.get("block_ids", []) if isinstance(v, (int, float, str))]
    return source_type, sorted(set(block_ids))


def _day_range(start: date, days: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(days)]


def analyze_project_by_id(session: Session, project_id: int) -> CorrelationProjectResult | None:
    project = get_correlation_project(session, project_id)
    if project is None or not project.is_active:
        return None
    project_data = CorrelationProjectData(
        id=project.id,
        name=project.name,
        days=project.days,
        time_relation=project.time_relation,
        target_variable=project.target_variable,
        source_config=project.source_config,
        is_active=project.is_active,
        updated_at=project.updated_at,
    )
    return analyze_project(session, project_data)


def analyze_project(session: Session, project: CorrelationProjectData) -> CorrelationProjectResult:
    lag_days = TIME_RELATION_LAG.get(project.time_relation, 0)
    source_metric, block_ids = _parse_config(project.source_config)
    today = datetime.now().date()
    start_day = today - timedelta(days=max(1, project.days) - 1)
    source_days = _day_range(start_day, max(1, project.days))
    end_day_for_query = today + timedelta(days=lag_days)

    stmt = (
        select(
            ActivityRecord.start_time,
            ActivityRecord.end_time,
            ActivityRecord.block_id,
            ActivityRecord.efficiency_score,
            ActivityRecord.state_score,
            ActivityRecord.mood_score,
            EventBlock.name,
        )
        .join(EventBlock, EventBlock.id == ActivityRecord.block_id)
        .where(
            ActivityRecord.start_time >= datetime.combine(start_day, datetime.min.time()),
            ActivityRecord.start_time < datetime.combine(end_day_for_query + timedelta(days=1), datetime.min.time()),
        )
    )
    rows = session.execute(stmt).all()

    # Daily target averages: value on day d
    target_sum: dict[date, float] = {}
    target_count: dict[date, int] = {}
    for row in rows:
        d = row.start_time.date()
        value = None
        if project.target_variable == "efficiency":
            value = row.efficiency_score
        elif project.target_variable == "state":
            value = row.state_score
        elif project.target_variable == "mood":
            value = row.mood_score
        if value is None:
            continue
        target_sum[d] = target_sum.get(d, 0.0) + float(value)
        target_count[d] = target_count.get(d, 0) + 1
    target_avg = {k: target_sum[k] / target_count[k] for k in target_sum if target_count.get(k, 0) > 0}

    block_name_map = {int(row.block_id): row.name for row in rows}
    selected_ids = block_ids if block_ids else sorted(block_name_map.keys())
    if not selected_ids:
        return CorrelationProjectResult(
            project_id=project.id,
            project_name=project.name,
            target_label=TARGET_LABELS.get(project.target_variable, "目标指标"),
            source_metric_label=SOURCE_LABELS[source_metric],
            time_relation_label=TIME_RELATION_LABEL.get(project.time_relation, "同日(T)"),
            items=[],
            summary="暂无可分析数据，请先创建相关事件记录。",
        )

    daily_values: dict[int, dict[date, float]] = {bid: {} for bid in selected_ids}
    combined_daily: dict[date, float] = {}
    for row in rows:
        bid = int(row.block_id)
        if bid not in daily_values:
            continue
        d = row.start_time.date()
        duration = max(0.0, (row.end_time - row.start_time).total_seconds() / 60.0)
        delta = 0.0
        if source_metric == "duration":
            delta = duration
        elif source_metric == "frequency":
            delta = 1.0
        elif source_metric == "occurred":
            delta = 1.0
        if source_metric == "occurred":
            daily_values[bid][d] = 1.0
            combined_daily[d] = 1.0
        else:
            daily_values[bid][d] = daily_values[bid].get(d, 0.0) + delta
            combined_daily[d] = combined_daily.get(d, 0.0) + delta

    results: list[CorrelationItemResult] = []

    def build_item(name: str, day_values: dict[date, float]) -> CorrelationItemResult | None:
        xs: list[float] = []
        ys: list[float] = []
        for source_day in source_days:
            target_day = source_day + timedelta(days=lag_days)
            target_value = target_avg.get(target_day)
            if target_value is None:
                continue
            xs.append(float(day_values.get(source_day, 0.0)))
            ys.append(float(target_value))
        sample_n = len(xs)
        rho = _spearman(xs, ys) if sample_n >= 2 else 0.0
        direction = _direction(rho)
        strength = _strength(rho)
        if sample_n < 2:
            note = "样本过少，无法形成稳定相关估计。"
        elif sample_n < 6:
            note = "样本偏少，结果仅用于调试观察。"
        else:
            note = "样本量可用于趋势参考。"
        explanation = (
            f"{TIME_RELATION_LABEL.get(project.time_relation, '同日(T)')}，"
            f"{direction}（{strength}），样本N={sample_n}。{note}"
        )
        return CorrelationItemResult(
            source_name=name,
            samples=sample_n,
            spearman=round(rho, 3),
            direction=direction,
            strength=strength,
            explanation=explanation,
        )

    combined_item = build_item("事件组合(全部)", combined_daily)
    if combined_item is not None:
        results.append(combined_item)
    for bid in selected_ids:
        label = block_name_map.get(bid, f"事件#{bid}")
        item = build_item(label, daily_values.get(bid, {}))
        if item is not None:
            results.append(item)

    results.sort(key=lambda item: abs(item.spearman), reverse=True)
    if results:
        top = results[0]
        summary = f"当前最强关系：{top.source_name} 与 {TARGET_LABELS.get(project.target_variable, '目标')} 的 Spearman={top.spearman:.3f}。"
    else:
        summary = "样本不足或数据缺失，暂无法得到稳定相关结果。"

    return CorrelationProjectResult(
        project_id=project.id,
        project_name=project.name,
        target_label=TARGET_LABELS.get(project.target_variable, "目标指标"),
        source_metric_label=SOURCE_LABELS[source_metric],
        time_relation_label=TIME_RELATION_LABEL.get(project.time_relation, "同日(T)"),
        items=results,
        summary=summary,
    )

