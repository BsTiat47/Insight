"""Custom week timeline widget with compressed night scale and 5-minute precision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


@dataclass
class TimelineRecord:
    block_id: int
    start_time: datetime
    end_time: datetime


class WeekTimelineWidget(QWidget):
    selectionChanged = Signal(datetime, datetime)

    def __init__(self, slot_minutes: int = 5, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._slot_minutes = slot_minutes
        self._week_start = date.today() - timedelta(days=date.today().weekday())
        self._records: list[TimelineRecord] = []
        self._block_names: dict[int, str] = {}
        self._block_colors: dict[int, str] = {}

        self._axis_width = 72
        self._header_height = 38
        self._night_minutes = 8 * 60
        self._day_minutes = 16 * 60

        self._dragging = False
        self._anchor: tuple[int, int] | None = None  # (day_idx, minute)
        self._cursor: tuple[int, int] | None = None
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

    def clear_selection(self) -> None:
        self._anchor = None
        self._cursor = None
        self._dragging = False
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
            TimelineRecord(block_id=r.block_id, start_time=r.start_time, end_time=r.end_time)  # type: ignore[attr-defined]
            for r in records
        ]
        self._block_names = block_names
        self._block_colors = block_colors
        self.update()

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

    def _y_to_minute(self, y: float) -> int:
        grid = self._grid_rect()
        night_height, day_height = self._timeline_heights()
        rel = max(0.0, min(grid.height(), y - grid.top()))
        if rel <= night_height:
            minute = int((rel / night_height) * self._night_minutes)
        else:
            minute = self._night_minutes + int(((rel - night_height) / day_height) * self._day_minutes)
        snapped = int(round(minute / self._slot_minutes) * self._slot_minutes)
        return max(0, min(24 * 60, snapped))

    def _point_to_day_minute(self, point: QPoint) -> tuple[int, int] | None:
        grid = self._grid_rect()
        if not grid.contains(point):
            return None
        day_idx = int((point.x() - grid.left()) / self._day_col_width())
        day_idx = max(0, min(6, day_idx))
        minute = self._y_to_minute(float(point.y()))
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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self._point_to_day_minute(event.position().toPoint())
            if pos is not None:
                self._dragging = True
                self._anchor = pos
                self._cursor = pos
                self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and self._anchor is not None:
            pos = self._point_to_day_minute(event.position().toPoint())
            if pos is not None:
                self._cursor = pos
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging and self._anchor and self._cursor:
            selected = self.selected_range()
            if selected is not None:
                start_dt, end_dt = selected
                self.selectionChanged.emit(start_dt, end_dt)
        self._dragging = False
        super().mouseReleaseEvent(event)

    def _draw_background(self, painter: QPainter) -> None:
        grid = self._grid_rect()
        painter.fillRect(grid, QColor("#FFFFFF"))

        day_width = self._day_col_width()
        for day in range(8):
            x = grid.left() + day * day_width
            pen = QPen(QColor("#D8E2F0"))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawLine(int(x), int(grid.top()), int(x), int(grid.bottom()))

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

        for rec in self._records:
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
                        color = QColor(self._block_colors.get(rec.block_id, "#b7c0cc"))
                        fill = QColor(color.red(), color.green(), color.blue(), 165)
                        painter.fillRect(rect, fill)
                        name = self._block_names.get(rec.block_id, f"#{rec.block_id}")
                        label_candidates.append((day_idx, rect, name, QColor("#ffffff")))
                day_cursor += timedelta(days=1)

        self._draw_non_overlapping_labels(painter, label_candidates)

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

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self._draw_background(painter)
        self._draw_records(painter)
        self._draw_selection(painter)
        painter.end()
