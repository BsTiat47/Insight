"""Custom week timeline widget with compressed night scale and 5-minute precision."""

from __future__ import annotations

import time as _time
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


@dataclass
class TimelineRecord:
    id: int
    block_id: int
    start_time: datetime
    end_time: datetime


class WeekTimelineWidget(QWidget):
    selectionChanged = Signal(datetime, datetime)
    recordMoved = Signal(list)  # list of (record_id, new_start_time, new_end_time)
    recordSelectionChanged = Signal(list)  # list of selected record IDs

    SNAP_SAME_DAY_MINUTES = 20   # strong vertical snap within same day
    SNAP_CROSS_DAY_MINUTES = 10  # weak horizontal alignment across days

    # High-contrast palette for per-event coloring within a day
    EVENT_PALETTE = [
        "#3B82F6",  # Blue
        "#EF4444",  # Red
        "#10B981",  # Emerald
        "#F59E0B",  # Amber
        "#8B5CF6",  # Violet
        "#EC4899",  # Pink
        "#06B6D4",  # Cyan
        "#F97316",  # Orange
        "#84CC16",  # Lime
        "#6366F1",  # Indigo
    ]

    def __init__(self, slot_minutes: int = 5, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._slot_minutes = slot_minutes
        self._selection_slot_minutes = 30
        self._week_start = date.today() - timedelta(days=date.today().weekday())
        self._records: list[TimelineRecord] = []
        self._block_names: dict[int, str] = {}
        self._block_colors: dict[int, str] = {}
        self._color_map: dict[int, str] = {}

        self._axis_width = 72
        self._header_height = 38
        self._night_minutes = 8 * 60
        self._day_minutes = 16 * 60

        # Range-drag selection state
        self._dragging = False
        self._anchor: tuple[int, int] | None = None  # (day_idx, minute)
        self._cursor: tuple[int, int] | None = None

        # Record selection & move/resize-drag state
        self._selected_ids: set[int] = set()
        self._drag_mode: str = "none"  # 'none' | 'select' | 'move' | 'resize_top' | 'resize_bottom'
        self._drag_start_y: float = 0.0
        self._move_offset_minutes: int = 0
        self._snapped_offset_minutes: int = 0
        self._move_original: dict[int, tuple[datetime, datetime]] = {}
        self._resize_record_id: int | None = None
        self._resize_orig_start: datetime | None = None
        self._resize_orig_end: datetime | None = None

        # AI suggestion preview
        self._ai_suggestion_events: list[dict] = []  # list of {block_name, start_dt, end_dt, note}

        self.setMouseTracking(True)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    @property
    def axis_width(self) -> int:
        return self._axis_width

    @property
    def right_padding(self) -> int:
        return 8

    def _timeline_heights(self) -> tuple[float, float]:
        # Fill remaining space dynamically; keep night compressed but readable.
        total = max(120.0, self.height() - self._header_height - 8.0)
        night_height = max(18.0, min(48.0, total * 0.12))
        day_height = max(80.0, total - night_height)
        return night_height, day_height

    def set_week_start(self, week_start: date) -> None:
        self._week_start = week_start
        self.update()

    def show_ai_thinking(self) -> None:
        """Show 'AI thinking' placeholder in the selection area."""
        self._ai_suggestion_events = [{"block_name": "思考中...", "start_dt": None, "end_dt": None, "_thinking": True}]
        self.update()

    def show_ai_suggestion(self, events: list[dict]) -> None:
        """Show a multi-event AI suggestion ghost preview. Each dict: block_name, start_dt, end_dt, note."""
        self._ai_suggestion_events = events
        self.update()

    def clear_ai_suggestion(self) -> None:
        """Remove the AI suggestion preview."""
        self._ai_suggestion_events = []
        self.update()

    def clear_selection(self) -> None:
        self._anchor = None
        self._cursor = None
        self._dragging = False
        self._selected_ids.clear()
        self._drag_mode = "none"
        self._move_offset_minutes = 0
        self._snapped_offset_minutes = 0
        self._move_original.clear()
        self._resize_record_id = None
        self._resize_orig_start = None
        self._resize_orig_end = None
        self.update()

    def selected_range(self) -> tuple[datetime, datetime] | None:
        if not self._anchor or not self._cursor:
            return None
        a_day, a_min = self._anchor
        b_day, b_min = self._cursor
        start_day, end_day = sorted([a_day, b_day])
        if (a_day, a_min) <= (b_day, b_min):
            start_min, end_min = a_min, b_min
        else:
            start_min, end_min = b_min, a_min
        start_dt = self._day_minute_to_datetime(start_day, start_min)
        end_dt = self._day_minute_to_datetime(end_day, end_min)
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(minutes=self._slot_minutes)
        return start_dt, end_dt

    def set_records(self, records: list, block_names: dict[int, str], block_colors: dict[int, str]) -> None:
        self._records = [
            TimelineRecord(id=r.id, block_id=r.block_id, start_time=r.start_time, end_time=r.end_time)  # type: ignore[attr-defined]
            for r in records
        ]
        self._block_names = block_names
        self._block_colors = block_colors
        self._selected_ids = {rid for rid in self._selected_ids if any(r.id == rid for r in self._records)}
        self._color_map = self._build_color_map()
        self.update()

    def _build_color_map(self) -> dict[int, str]:
        """Assign high-contrast palette colors to events per day, round-robin by time."""
        by_day: dict[date, list[TimelineRecord]] = {}
        for rec in self._records:
            day = rec.start_time.date()
            by_day.setdefault(day, []).append(rec)
        color_map: dict[int, str] = {}
        for day_recs in by_day.values():
            day_recs.sort(key=lambda r: r.start_time)
            for i, rec in enumerate(day_recs):
                color_map[rec.id] = self.EVENT_PALETTE[i % len(self.EVENT_PALETTE)]
        return color_map

    def _grid_rect(self) -> QRectF:
        night_height, day_height = self._timeline_heights()
        return QRectF(
            self._axis_width,
            self._header_height,
            max(100.0, self.width() - self._axis_width - 8),
            night_height + day_height,
        )

    def _day_col_width(self) -> float:
        return self._grid_rect().width() / 7.0

    def _minute_to_y(self, minute: int) -> float:
        minute = max(0, min(24 * 60, minute))
        grid_top = self._grid_rect().top()
        night_height, day_height = self._timeline_heights()
        if minute <= self._night_minutes:
            return grid_top + (minute / self._night_minutes) * night_height
        return grid_top + night_height + ((minute - self._night_minutes) / self._day_minutes) * day_height

    def _y_to_minute(self, y: float, *, slot: int | None = None) -> int:
        grid = self._grid_rect()
        night_height, day_height = self._timeline_heights()
        rel = max(0.0, min(grid.height(), y - grid.top()))
        if rel <= night_height:
            minute = int((rel / night_height) * self._night_minutes)
        else:
            minute = self._night_minutes + int(((rel - night_height) / day_height) * self._day_minutes)
        step = slot if slot is not None else self._slot_minutes
        snapped = int(round(minute / step) * step)
        return max(0, min(24 * 60, snapped))

    def _point_to_day_minute(self, point: QPoint, *, slot: int | None = None) -> tuple[int, int] | None:
        grid = self._grid_rect()
        if not grid.contains(point):
            return None
        day_idx = int((point.x() - grid.left()) / self._day_col_width())
        day_idx = max(0, min(6, day_idx))
        minute = self._y_to_minute(float(point.y()), slot=slot)
        return day_idx, minute

    def _day_minute_to_datetime(self, day_idx: int, minute: int) -> datetime:
        current_day = self._week_start + timedelta(days=day_idx)
        hour = minute // 60
        minute_part = minute % 60
        if minute >= 24 * 60:
            current_day += timedelta(days=1)
            hour = 0
            minute_part = 0
        return datetime.combine(current_day, time(hour=hour, minute=minute_part))

    def _records_at_point(self, point: QPoint) -> list[int]:
        """Return list of record IDs whose rendered rectangle contains the point."""
        grid = self._grid_rect()
        day_width = self._day_col_width()
        week_start_dt = datetime.combine(self._week_start, time.min)
        week_end_dt = week_start_dt + timedelta(days=7)
        seen: set[int] = set()
        result: list[int] = []

        for rec in self._records:
            if rec.id in seen:
                continue
            start = max(rec.start_time, week_start_dt)
            end = min(rec.end_time, week_end_dt)
            if end <= start:
                continue
            day_cursor = start.date()
            while day_cursor <= (end - timedelta(microseconds=1)).date():
                day_start = datetime.combine(day_cursor, time.min)
                day_end = day_start + timedelta(days=1)
                seg_start = max(start, day_start)
                seg_end = min(end, day_end)
                if seg_end > seg_start:
                    day_idx = (day_cursor - self._week_start).days
                    if 0 <= day_idx < 7:
                        start_min = int((seg_start - day_start).total_seconds() // 60)
                        end_min = int((seg_end - day_start).total_seconds() // 60)
                        x = grid.left() + day_idx * day_width + 2
                        y1 = self._minute_to_y(start_min)
                        y2 = self._minute_to_y(end_min)
                        rect = QRectF(x, y1, max(6.0, day_width - 4), max(2.0, y2 - y1))
                        if rect.contains(point):
                            seen.add(rec.id)
                            result.append(rec.id)
                day_cursor += timedelta(days=1)
        return result

    def _compute_snap(self, proposed_minutes: int) -> int:
        """Snap the move offset so dragged record edges align with other records' edges.

        Same-day snaps use a large threshold (strong vertical attraction).
        Cross-day snaps use a small threshold (weak horizontal alignment).
        Same-day always wins over cross-day.
        """
        if not self._move_original:
            return proposed_minutes

        same_day_best: int | None = None
        same_day_dist = self.SNAP_SAME_DAY_MINUTES + 1
        cross_day_best: int | None = None
        cross_day_dist = self.SNAP_CROSS_DAY_MINUTES + 1

        for rec_id, (orig_start, orig_end) in self._move_original.items():
            rec_day = orig_start.date()
            new_start_min = self._datetime_to_minute_in_day(orig_start) + proposed_minutes
            new_end_min = self._datetime_to_minute_in_day(orig_end) + proposed_minutes

            for other in self._records:
                if other.id in self._selected_ids:
                    continue
                other_start_min = self._datetime_to_minute_in_day(other.start_time)
                other_end_min = self._datetime_to_minute_in_day(other.end_time)
                other_day = other.start_time.date()
                is_same_day = (rec_day == other_day)
                threshold = self.SNAP_SAME_DAY_MINUTES if is_same_day else self.SNAP_CROSS_DAY_MINUTES

                edges = [
                    (new_start_min, other_end_min),     # dragged top vs other bottom
                    (new_start_min, other_start_min),   # dragged top vs other top
                    (new_end_min, other_start_min),     # dragged bottom vs other top
                    (new_end_min, other_end_min),       # dragged bottom vs other bottom
                ]
                for dragged_edge, target_edge in edges:
                    dist = abs(dragged_edge - target_edge)
                    if dist >= threshold:
                        continue
                    candidate = proposed_minutes - (dragged_edge - target_edge)
                    if is_same_day and dist < same_day_dist:
                        same_day_dist = dist
                        same_day_best = candidate
                    elif not is_same_day and dist < cross_day_dist:
                        cross_day_dist = dist
                        cross_day_best = candidate

        # Same-day snap always wins; fall back to cross-day
        best_snap = same_day_best if same_day_best is not None else cross_day_best
        if best_snap is not None:
            return int(round(best_snap / self._slot_minutes) * self._slot_minutes)
        return proposed_minutes

    def _datetime_to_minute_in_day(self, dt: datetime) -> int:
        """Convert a datetime to minutes since midnight."""
        return dt.hour * 60 + dt.minute

    def _record_edge_at_point(self, point: QPoint, record_id: int) -> str | None:
        """Return 'top' if point is near the top edge of the record's rect, 'bottom' if near bottom, else None."""
        grid = self._grid_rect()
        day_width = self._day_col_width()
        week_start_dt = datetime.combine(self._week_start, time.min)
        week_end_dt = week_start_dt + timedelta(days=7)
        EDGE_PX = 16  # pixels from edge to trigger resize

        for rec in self._records:
            if rec.id != record_id:
                continue
            start = max(rec.start_time, week_start_dt)
            end = min(rec.end_time, week_end_dt)
            if end <= start:
                continue
            day_cursor = start.date()
            while day_cursor <= (end - timedelta(microseconds=1)).date():
                day_start = datetime.combine(day_cursor, time.min)
                day_end_dt = day_start + timedelta(days=1)
                seg_start = max(start, day_start)
                seg_end = min(end, day_end_dt)
                if seg_end > seg_start:
                    day_idx = (day_cursor - self._week_start).days
                    if 0 <= day_idx < 7:
                        start_min = int((seg_start - day_start).total_seconds() // 60)
                        end_min = int((seg_end - day_start).total_seconds() // 60)
                        x = grid.left() + day_idx * day_width + 2
                        y1 = self._minute_to_y(start_min)
                        y2 = self._minute_to_y(end_min)
                        rect = QRectF(x, y1, max(6.0, day_width - 4), max(2.0, y2 - y1))
                        if rect.contains(point):
                            if abs(point.y() - y1) <= EDGE_PX:
                                return "top"
                            if abs(point.y() - y2) <= EDGE_PX:
                                return "bottom"
                            return "middle"
                day_cursor += timedelta(days=1)
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            point = event.position().toPoint()
            hit_ids = self._records_at_point(point)
            if hit_ids:
                ctrl_held = event.modifiers() & Qt.KeyboardModifier.ControlModifier
                if not ctrl_held:
                    self._selected_ids = set(hit_ids)
                else:
                    for rid in hit_ids:
                        if rid in self._selected_ids:
                            self._selected_ids.discard(rid)
                        else:
                            self._selected_ids.add(rid)

                # Check for edge resize on first hit record
                edge = self._record_edge_at_point(point, hit_ids[0]) if len(hit_ids) == 1 and not ctrl_held else None
                if edge == "top":
                    self._drag_mode = "resize_top"
                    self.setCursor(Qt.CursorShape.SizeVerCursor)
                    self._resize_record_id = hit_ids[0]
                    for rec in self._records:
                        if rec.id == hit_ids[0]:
                            self._resize_orig_start = rec.start_time
                            self._resize_orig_end = rec.end_time
                            break
                elif edge == "bottom":
                    self._drag_mode = "resize_bottom"
                    self.setCursor(Qt.CursorShape.SizeVerCursor)
                    self._resize_record_id = hit_ids[0]
                    for rec in self._records:
                        if rec.id == hit_ids[0]:
                            self._resize_orig_start = rec.start_time
                            self._resize_orig_end = rec.end_time
                            break
                else:
                    self._drag_mode = "move"
                    self._move_original = {}
                    for rid in self._selected_ids:
                        for rec in self._records:
                            if rec.id == rid:
                                self._move_original[rid] = (rec.start_time, rec.end_time)
                                break

                self._drag_start_y = float(point.y())
                self._move_offset_minutes = 0
                self._snapped_offset_minutes = 0
                self._dragging = False
                self._anchor = None
                self._cursor = None
                self.recordSelectionChanged.emit(list(self._selected_ids))
                self.update()
            else:
                # Click on empty space: range-select (30-min slots)
                self._selected_ids.clear()
                self._drag_mode = "select"
                self._move_offset_minutes = 0
                self._snapped_offset_minutes = 0
                self._move_original.clear()
                pos = self._point_to_day_minute(point, slot=self._selection_slot_minutes)
                if pos is not None:
                    self._dragging = True
                    self._anchor = pos
                    self._cursor = pos
                self.recordSelectionChanged.emit([])
                self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_mode in ("resize_top", "resize_bottom") and self._resize_record_id is not None:
            current_y = float(event.position().toPoint().y())
            current_min = self._y_to_minute(current_y)
            # Snap to 30-min boundaries for resize
            snapped_min = int(round(current_min / self._selection_slot_minutes) * self._selection_slot_minutes)
            snapped_min = max(0, min(24 * 60, snapped_min))

            # Update the record in-place for visual preview
            for rec in self._records:
                if rec.id == self._resize_record_id:
                    if self._drag_mode == "resize_top":
                        new_start = snapped_min
                        # Keep within bounds and ensure positive duration
                        end_min = self._datetime_to_minute_in_day(self._resize_orig_end)
                        if new_start < end_min - self._selection_slot_minutes:
                            rec.start_time = rec.start_time.replace(
                                hour=new_start // 60, minute=new_start % 60, second=0, microsecond=0)
                    else:  # resize_bottom
                        new_end = snapped_min
                        start_min = self._datetime_to_minute_in_day(self._resize_orig_start)
                        if new_end > start_min + self._selection_slot_minutes:
                            rec.end_time = rec.end_time.replace(
                                hour=new_end // 60, minute=new_end % 60, second=0, microsecond=0)
                    break
            self.update()

        elif self._drag_mode == "move" and self._move_original:
            current_y = float(event.position().toPoint().y())
            delta_y = current_y - self._drag_start_y
            start_min = self._y_to_minute(self._drag_start_y)
            current_min = self._y_to_minute(current_y)
            raw_offset = current_min - start_min
            raw_offset = int(round(raw_offset / self._slot_minutes) * self._slot_minutes)

            # Clamp: no record should go outside 00:00-24:00 of its day
            for orig_start, orig_end in self._move_original.values():
                start_min_of_day = self._datetime_to_minute_in_day(orig_start)
                end_min_of_day = self._datetime_to_minute_in_day(orig_end)
                if start_min_of_day + raw_offset < 0:
                    raw_offset = -start_min_of_day
                if end_min_of_day + raw_offset > 24 * 60:
                    raw_offset = 24 * 60 - end_min_of_day

            self._move_offset_minutes = raw_offset
            snapped = self._compute_snap(raw_offset)
            self._snapped_offset_minutes = snapped
            self.update()
        elif self._drag_mode == "select" and self._dragging and self._anchor is not None:
            pos = self._point_to_day_minute(event.position().toPoint(), slot=self._selection_slot_minutes)
            if pos is not None:
                self._cursor = pos
                self.update()
        elif self._drag_mode == "none":
            # Idle hover: show resize cursor when near edge of selected record
            point = event.position().toPoint()
            edge = None
            for rid in self._selected_ids:
                edge = self._record_edge_at_point(point, rid)
                if edge in ("top", "bottom"):
                    break
            if edge in ("top", "bottom"):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._drag_mode in ("resize_top", "resize_bottom"):
                if self._resize_record_id is not None:
                    for rec in self._records:
                        if rec.id == self._resize_record_id:
                            # Only emit if actually changed
                            if (rec.start_time != self._resize_orig_start or
                                    rec.end_time != self._resize_orig_end):
                                self.recordMoved.emit([(rec.id, rec.start_time, rec.end_time)])
                            else:
                                # Restore originals (no-op drag)
                                rec.start_time = self._resize_orig_start
                                rec.end_time = self._resize_orig_end
                            break
                self._drag_mode = "none"
                self._resize_record_id = None
                self._resize_orig_start = None
                self._resize_orig_end = None
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self.update()
            elif self._drag_mode == "move":
                offset = self._snapped_offset_minutes or self._move_offset_minutes
                if offset != 0 and self._move_original:
                    moves: list[tuple[int, datetime, datetime]] = []
                    for rec_id, (orig_start, orig_end) in self._move_original.items():
                        new_start = orig_start + timedelta(minutes=offset)
                        new_end = orig_end + timedelta(minutes=offset)
                        if new_end > new_start:
                            moves.append((rec_id, new_start, new_end))
                    if moves:
                        self.recordMoved.emit(moves)
                self._drag_mode = "none"
                self._move_offset_minutes = 0
                self._snapped_offset_minutes = 0
                self._move_original.clear()
                self.update()
            elif self._drag_mode == "select" and self._dragging and self._anchor and self._cursor:
                selected = self.selected_range()
                if selected is not None:
                    start_dt, end_dt = selected
                    self.selectionChanged.emit(start_dt, end_dt)
                self._dragging = False
                self._drag_mode = "none"
        super().mouseReleaseEvent(event)

    def _draw_background(self, painter: QPainter) -> None:
        grid = self._grid_rect()
        painter.fillRect(grid, QColor("#FFFFFF"))

        # Time-of-day background bands
        periods = [
            (0, 6 * 60, QColor(30, 58, 95, 18)),       # Night: 00:00-06:00 dark blue tint
            (6 * 60, 12 * 60, QColor(255, 228, 181, 35)), # Morning: 06:00-12:00 warm amber
            (12 * 60, 18 * 60, QColor(255, 240, 220, 30)), # Afternoon: 12:00-18:00 light warm
            (18 * 60, 24 * 60, QColor(200, 200, 230, 28)), # Evening: 18:00-24:00 soft lavender
        ]
        for start_min, end_min, color in periods:
            y1 = self._minute_to_y(start_min)
            y2 = self._minute_to_y(end_min)
            band_rect = QRectF(grid.left(), y1, grid.width(), max(1.0, y2 - y1))
            painter.fillRect(band_rect, color)

        day_width = self._day_col_width()
        for day in range(8):
            x = grid.left() + day * day_width
            pen = QPen(QColor("#D8E2F0"))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawLine(int(x), int(grid.top()), int(x), int(grid.bottom()))

        # 30-minute horizontal grid lines
        for minute in range(0, 24 * 60, 30):
            y = self._minute_to_y(minute)
            grid_pen = QPen(QColor(100, 120, 150, 40))
            grid_pen.setWidth(1)
            painter.setPen(grid_pen)
            painter.drawLine(int(grid.left()), int(y), int(grid.right()), int(y))

        # Day headers
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        painter.setPen(QColor("#334155"))
        for day in range(7):
            current_day = self._week_start + timedelta(days=day)
            x = grid.left() + day * day_width
            header_rect = QRectF(x, 2, day_width, self._header_height - 4)
            painter.drawText(
                header_rect,
                Qt.AlignmentFlag.AlignCenter,
                f"{weekdays[day]}\n{current_day.month:02d}-{current_day.day:02d}",
            )

        # Left axis labels: hourly scale, night merged visually.
        painter.setPen(QColor("#64748B"))
        painter.drawText(QRectF(2, self._minute_to_y(0) - 8, self._axis_width - 8, 16), "00:00")
        painter.drawText(QRectF(2, self._minute_to_y(8 * 60) - 8, self._axis_width - 8, 16), "08:00")
        for hour in range(9, 24):
            y = self._minute_to_y(hour * 60)
            painter.drawText(QRectF(2, y - 8, self._axis_width - 8, 16), f"{hour:02d}:00")

    def _draw_records(self, painter: QPainter) -> None:
        grid = self._grid_rect()
        day_width = self._day_col_width()
        week_start_dt = datetime.combine(self._week_start, time.min)
        week_end_dt = week_start_dt + timedelta(days=7)
        label_candidates: list[tuple[int, QRectF, str, QColor]] = []

        is_moving = self._drag_mode == "move" and self._move_original
        offset = self._snapped_offset_minutes or self._move_offset_minutes

        for rec in self._records:
            is_selected = rec.id in self._selected_ids
            start = max(rec.start_time, week_start_dt)
            end = min(rec.end_time, week_end_dt)
            if end <= start:
                continue

            # Apply move offset to selected records
            if is_moving and is_selected and rec.id in self._move_original:
                orig_start, orig_end = self._move_original[rec.id]
                start = max(orig_start + timedelta(minutes=offset), week_start_dt)
                end = min(orig_end + timedelta(minutes=offset), week_end_dt)

            day_cursor = start.date()
            while day_cursor <= (end - timedelta(microseconds=1)).date():
                day_start = datetime.combine(day_cursor, time.min)
                day_end = day_start + timedelta(days=1)
                seg_start = max(start, day_start)
                seg_end = min(end, day_end)
                if seg_end > seg_start:
                    day_idx = (day_cursor - self._week_start).days
                    if 0 <= day_idx < 7:
                        start_min = int((seg_start - day_start).total_seconds() // 60)
                        end_min = int((seg_end - day_start).total_seconds() // 60)
                        x = grid.left() + day_idx * day_width + 2
                        y1 = self._minute_to_y(start_min)
                        y2 = self._minute_to_y(end_min)
                        rect = QRectF(x, y1, max(6.0, day_width - 4), max(2.0, y2 - y1))
                        event_color = QColor(self._color_map.get(rec.id, "#b7c0cc"))
                        event_color.setAlpha(185)
                        painter.fillRect(rect, event_color)
                        if is_selected:
                            sel_pen = QPen(QColor("#2563EB"))
                            sel_pen.setWidth(2)
                            painter.setPen(sel_pen)
                            painter.drawRect(rect)
                            # Resize handles: small bars at top & bottom
                            handle_w = min(20.0, rect.width() * 0.4)
                            handle_x = rect.left() + (rect.width() - handle_w) / 2
                            handle_h = 3.0
                            painter.fillRect(QRectF(handle_x, rect.top() - 1, handle_w, handle_h), QColor("#2563EB"))
                            painter.fillRect(QRectF(handle_x, rect.bottom() - 2, handle_w, handle_h), QColor("#2563EB"))
                            painter.setPen(Qt.PenStyle.NoPen)
                        name = self._block_names.get(rec.block_id, f"#{rec.block_id}")
                        label_candidates.append((day_idx, rect, name, QColor("#ffffff")))
                day_cursor += timedelta(days=1)

        self._draw_non_overlapping_labels(painter, label_candidates)
        self._draw_snap_indicators(painter)

    def _draw_snap_indicators(self, painter: QPainter) -> None:
        """Draw snap guide lines — strong for same-day, subtle for cross-day."""
        if self._drag_mode != "move" or not self._move_original:
            return
        offset = self._snapped_offset_minutes
        if offset == self._move_offset_minutes:
            return  # not snapped

        grid = self._grid_rect()
        day_width = self._day_col_width()

        for rec_id, (orig_start, orig_end) in self._move_original.items():
            rec_day = orig_start.date()
            new_start_min = self._datetime_to_minute_in_day(orig_start) + offset
            new_end_min = self._datetime_to_minute_in_day(orig_end) + offset

            for edge_min in [new_start_min, new_end_min]:
                for other in self._records:
                    if other.id in self._selected_ids:
                        continue
                    other_day = other.start_time.date()
                    same_day = (rec_day == other_day)
                    threshold = self.SNAP_SAME_DAY_MINUTES if same_day else self.SNAP_CROSS_DAY_MINUTES
                    other_start = self._datetime_to_minute_in_day(other.start_time)
                    other_end = self._datetime_to_minute_in_day(other.end_time)
                    for target_min in [other_start, other_end]:
                        if abs(edge_min - target_min) <= threshold:
                            y = self._minute_to_y(target_min)
                            if same_day:
                                # Strong glow + bright line for same-day snap
                                glow_pen = QPen(QColor(255, 107, 0, 70))
                                glow_pen.setWidth(7)
                                painter.setPen(glow_pen)
                                painter.drawLine(int(grid.left()), int(y), int(grid.right()), int(y))
                                snap_pen = QPen(QColor("#FF6B00"))
                                snap_pen.setWidth(2)
                                snap_pen.setStyle(Qt.PenStyle.DashLine)
                                painter.setPen(snap_pen)
                                painter.drawLine(int(grid.left()), int(y), int(grid.right()), int(y))
                                dot_pen = QPen(QColor("#FF6B00"))
                                dot_pen.setWidth(4)
                                painter.setPen(dot_pen)
                                for d in range(7):
                                    dx = grid.left() + d * day_width + day_width / 2
                                    painter.drawPoint(int(dx), int(y))
                            else:
                                # Subtle thin line for cross-day alignment
                                cross_pen = QPen(QColor(150, 150, 180, 80))
                                cross_pen.setWidth(1)
                                cross_pen.setStyle(Qt.PenStyle.DotLine)
                                painter.setPen(cross_pen)
                                painter.drawLine(int(grid.left()), int(y), int(grid.right()), int(y))
                            break

    def _draw_non_overlapping_labels(
        self, painter: QPainter, label_candidates: list[tuple[int, QRectF, str, QColor]]
    ) -> None:
        if not label_candidates:
            return
        day_occupied: dict[int, list[QRectF]] = {i: [] for i in range(7)}
        fm = painter.fontMetrics()
        label_h = max(11.0, float(fm.height() + 2))
        sorted_labels = sorted(label_candidates, key=lambda x: (x[0], x[1].top()))

        for day_idx, block_rect, text, color in sorted_labels:
            # Default label position: top of the block.
            y = block_rect.top() + 1
            x = block_rect.left() + 2
            w = max(8.0, block_rect.width() - 4)
            label_rect = QRectF(x, y, w, label_h)

            # If overlaps existing labels in same day, move downward until free.
            while any(label_rect.intersects(prev) for prev in day_occupied[day_idx]):
                y += label_h + 1
                label_rect = QRectF(x, y, w, label_h)

            day_occupied[day_idx].append(label_rect)
            painter.setPen(color)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

    def _draw_selection(self, painter: QPainter) -> None:
        if not self._anchor or not self._cursor:
            return
        grid = self._grid_rect()
        day_width = self._day_col_width()
        a_day, a_min = self._anchor
        b_day, b_min = self._cursor
        left_day = min(a_day, b_day)
        right_day = max(a_day, b_day)
        top_min = min(a_min, b_min)
        bottom_min = max(a_min, b_min)
        x = grid.left() + left_day * day_width + 1
        w = (right_day - left_day + 1) * day_width - 2
        y1 = self._minute_to_y(top_min)
        y2 = self._minute_to_y(bottom_min)
        rect = QRectF(x, y1, w, max(2.0, y2 - y1))
        painter.fillRect(rect, QColor(59, 130, 246, 50))
        pen = QPen(QColor("#2563eb"))
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRect(rect)

    def _draw_ai_preview(self, painter: QPainter) -> None:
        """Draw multi-event AI suggestion ghost preview at ~75% opacity."""
        if not self._ai_suggestion_events:
            return
        self._draw_ai_preview_impl(painter)

    def _draw_ai_preview_impl(self, painter: QPainter) -> None:
        grid = self._grid_rect()
        day_width = self._day_col_width()
        week_start_dt = datetime.combine(self._week_start, time.min)
        week_end_dt = week_start_dt + timedelta(days=7)

        # "Thinking" state: show spinner-like indicator in selection area
        if self._ai_suggestion_events[0].get("_thinking"):
            if not self._anchor or not self._cursor:
                return
            a_day, a_min = self._anchor
            b_day, b_min = self._cursor
            left_day = min(a_day, b_day)
            right_day = max(a_day, b_day)
            top_min = min(a_min, b_min)
            bottom_min = max(a_min, b_min)
            x = grid.left() + left_day * day_width + 1
            w = (right_day - left_day + 1) * day_width - 2
            y1 = self._minute_to_y(top_min)
            y2 = self._minute_to_y(bottom_min)
            rect = QRectF(x, y1, w, max(2.0, y2 - y1))
            # Subtle pulsing fill
            pulse = int(30 + 15 * (_time.time() % 2.0))
            painter.fillRect(rect, QColor(59, 130, 246, pulse))
            dash_pen = QPen(QColor(59, 130, 246, 140))
            dash_pen.setWidth(2)
            dash_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(dash_pen)
            painter.drawRect(rect)
            painter.setPen(Qt.PenStyle.NoPen)
            # Centered text
            label = "🤖 AI 思考中..."
            fm = painter.fontMetrics()
            label_w = fm.horizontalAdvance(label) + 12
            label_h = fm.height() + 6
            label_x = x + (w - label_w) / 2
            label_y = y1 + (y2 - y1 - label_h) / 2
            if w > label_w and (y2 - y1) > label_h:
                label_bg = QRectF(label_x, label_y, label_w, label_h)
                painter.fillRect(label_bg, QColor(30, 30, 30, 180))
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(label_bg, Qt.AlignmentFlag.AlignCenter, label)
                painter.setPen(Qt.PenStyle.NoPen)
            return

        # Assign distinct preview colors per event
        preview_colors = [
            QColor(59, 130, 246),   # Blue
            QColor(16, 185, 129),   # Emerald
            QColor(245, 158, 11),   # Amber
            QColor(139, 92, 246),   # Violet
            QColor(236, 72, 153),   # Pink
            QColor(6, 182, 212),    # Cyan
        ]

        for ev_idx, ev in enumerate(self._ai_suggestion_events):
            start_dt = ev["start_dt"]
            end_dt = ev["end_dt"]
            block_name = ev["block_name"]
            color = preview_colors[ev_idx % len(preview_colors)]

            start = max(start_dt, week_start_dt)
            end = min(end_dt, week_end_dt)
            if end <= start:
                continue

            day_cursor = start.date()
            while day_cursor <= (end - timedelta(microseconds=1)).date():
                day_start = datetime.combine(day_cursor, time.min)
                day_end = day_start + timedelta(days=1)
                seg_start = max(start, day_start)
                seg_end = min(end, day_end)
                if seg_end > seg_start:
                    day_idx = (day_cursor - self._week_start).days
                    if 0 <= day_idx < 7:
                        start_min = int((seg_start - day_start).total_seconds() // 60)
                        end_min = int((seg_end - day_start).total_seconds() // 60)
                        x = grid.left() + day_idx * day_width + 2
                        y1 = self._minute_to_y(start_min)
                        y2 = self._minute_to_y(end_min)
                        rect = QRectF(x, y1, max(6.0, day_width - 4), max(2.0, y2 - y1))

                        # Ghost fill with per-event color
                        ghost_fill = QColor(color.red(), color.green(), color.blue(), 45)
                        painter.fillRect(rect, ghost_fill)

                        # Dashed border
                        dash_pen = QPen(QColor(color.red(), color.green(), color.blue(), 190))
                        dash_pen.setWidth(2)
                        dash_pen.setStyle(Qt.PenStyle.DashLine)
                        painter.setPen(dash_pen)
                        painter.drawRect(rect)
                        painter.setPen(Qt.PenStyle.NoPen)

                        # Label
                        label = f"🤖 {block_name}"
                        fm = painter.fontMetrics()
                        label_w = fm.horizontalAdvance(label) + 8
                        label_h = fm.height() + 4
                        label_x = x + (day_width - 4 - label_w) / 2
                        label_y = y1 + (y2 - y1 - label_h) / 2
                        if label_w < day_width - 8 and label_h < y2 - y1:
                            label_bg = QRectF(label_x, label_y, label_w, label_h)
                            painter.fillRect(label_bg, QColor(30, 30, 30, 180))
                            painter.setPen(QColor("#FFFFFF"))
                            painter.drawText(label_bg, Qt.AlignmentFlag.AlignCenter, label)
                            painter.setPen(Qt.PenStyle.NoPen)
                day_cursor += timedelta(days=1)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self._draw_background(painter)
        self._draw_records(painter)
        if self._anchor and self._cursor:
            self._draw_selection(painter)
        self._draw_ai_preview(painter)
        painter.end()
