"""Statistics dashboard page."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QLineSeries,
    QValueAxis,
)
from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..services.analytics_service import CategorySeries, build_category_overview, build_custom_metrics
from ..storage.database import session_scope
from ..storage.repositories import (
    BLOCK_CATEGORY_REST,
    BLOCK_CATEGORY_WORK,
    CATEGORY_LABEL_MAP,
    list_blocks,
)

RANGE_OPTIONS = [("周", 7), ("月", 30), ("半年", 182), ("一年", 365)]


@dataclass
class ViewConfig:
    view_id: str
    title: str
    kind: str  # category | custom
    category: str | None
    block_ids: list[int]
    metrics: dict[str, bool]


class StatsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._removed_view_ids: set[str] = set()
        self._custom_views: list[ViewConfig] = []

        self.tabs = QTabWidget()
        self.overview_tab = QWidget()
        self.custom_tab = QWidget()
        self.tabs.addTab(self.overview_tab, "默认统计视图")
        self.tabs.addTab(self.custom_tab, "自定义图表")

        self.range_combo = QComboBox()
        for label, _days in RANGE_OPTIONS:
            self.range_combo.addItem(label, _days)
        self.range_combo.currentIndexChanged.connect(self.refresh_overview)

        self.overview_list = QListWidget()
        self.overview_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.overview_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.overview_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.overview_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.overview_list.setSpacing(8)
        self.overview_list.verticalScrollBar().setSingleStep(12)
        self.overview_list.model().rowsMoved.connect(lambda *_args: self._sync_order_from_list())  # type: ignore[arg-type]

        self._card_cache: dict[str, tuple[QGroupBox, QLabel, QChartView]] = {}
        self._item_by_view_id: dict[str, QListWidgetItem] = {}
        self._view_order: list[str] = []
        self._handle_map: dict[QWidget, str] = {}
        self._canvas_map: dict[QWidget, str] = {}
        self._drag_anchor: QPoint | None = None
        self._drag_view_id: str | None = None
        self._render_queue: list[str] = []
        self._render_generation = 0
        self._category_data_cache: dict[str, CategorySeries] = {}
        self._active_views: dict[str, ViewConfig] = {}
        self._current_days = 7

        range_row = QHBoxLayout()
        range_row.addStretch()
        range_row.addWidget(QLabel("统计范围"))
        range_row.addWidget(self.range_combo)

        overview_layout = QVBoxLayout(self.overview_tab)
        overview_layout.setContentsMargins(2, 2, 2, 2)
        overview_layout.setSpacing(6)
        overview_layout.addWidget(self.overview_list, stretch=1)
        overview_layout.addLayout(range_row)

        self.custom_title_input = QLineEdit()
        self.custom_title_input.setPlaceholderText("图表名称（例如：学习效率追踪）")

        self.custom_range_combo = QComboBox()
        for label, _days in RANGE_OPTIONS:
            self.custom_range_combo.addItem(label, _days)
        self.custom_range_combo.setCurrentIndex(0)

        self.block_list = QListWidget()
        self.block_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)

        self.metric_duration = QCheckBox("时长(柱状)")
        self.metric_duration.setChecked(True)
        self.metric_frequency = QCheckBox("频次(折线)")
        self.metric_frequency.setChecked(True)
        self.metric_efficiency = QCheckBox("效率均值(折线)")
        self.metric_efficiency.setChecked(True)
        self.metric_state = QCheckBox("状态均值(折线)")
        self.metric_state.setChecked(True)
        self.metric_mood = QCheckBox("心情均值(折线)")
        self.metric_mood.setChecked(True)
        self.render_custom_btn = QPushButton("生成自定义图表")
        self.render_custom_btn.clicked.connect(self.render_custom_chart)
        self.save_custom_btn = QPushButton("保存到默认统计视图")
        self.save_custom_btn.clicked.connect(self.save_custom_view)

        controls_group = QGroupBox("图表配置")
        controls_layout = QVBoxLayout(controls_group)
        controls_layout.addWidget(QLabel("图表名称"))
        controls_layout.addWidget(self.custom_title_input)
        controls_layout.addWidget(QLabel("选择事件"))
        controls_layout.addWidget(self.block_list, stretch=1)
        controls_layout.addWidget(QLabel("指标"))
        controls_layout.addWidget(self.metric_duration)
        controls_layout.addWidget(self.metric_frequency)
        controls_layout.addWidget(self.metric_efficiency)
        controls_layout.addWidget(self.metric_state)
        controls_layout.addWidget(self.metric_mood)
        range_cfg = QHBoxLayout()
        range_cfg.addWidget(QLabel("范围"))
        range_cfg.addWidget(self.custom_range_combo)
        controls_layout.addLayout(range_cfg)
        controls_layout.addWidget(self.render_custom_btn)
        controls_layout.addWidget(self.save_custom_btn)

        self.custom_chart = QChart()
        self.custom_chart.setBackgroundBrush(QBrush(QColor("#FFFFFF")))
        self.custom_chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        self.custom_chart_view = QChartView(self.custom_chart)
        self.custom_chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.custom_chart_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        custom_layout = QHBoxLayout(self.custom_tab)
        custom_layout.addWidget(controls_group, stretch=0)
        custom_layout.addWidget(self.custom_chart_view, stretch=1)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)
        root.addWidget(self.tabs)

        self._reload_blocks()
        QTimer.singleShot(0, self._initial_render)

    def _initial_render(self) -> None:
        self.refresh_overview()
        self.render_custom_chart()

    def refresh(self) -> None:
        self._reload_blocks()
        self.refresh_overview()
        self.render_custom_chart()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._resize_cards()

    def _reload_blocks(self) -> None:
        self.block_list.clear()
        with session_scope() as session:
            blocks = list_blocks(session, include_inactive=False)
        for b in blocks:
            item = QListWidgetItem(f"{b.name}（{CATEGORY_LABEL_MAP.get(b.category, b.category)}）")
            item.setData(32, b.id)
            item.setSelected(True)
            self.block_list.addItem(item)

    def _selected_days(self, combo: QComboBox) -> int:
        return int(combo.currentData() or 7)

    @staticmethod
    def _compute_max(values: list[float]) -> float:
        valid = [v for v in values if v]
        return max(valid) if valid else 0.0

    def _plot_series(self, chart_view: QChartView, series: CategorySeries, title: str, bar_color: str, metrics: dict[str, bool]) -> None:
        chart = chart_view.chart()
        chart.removeAllSeries()
        for axis in chart.axes():
            chart.removeAxis(axis)

        x = list(range(len(series.dates)))
        if not x:
            chart.setTitle(title)
            return

        # X axis with sparse labels to avoid overlap
        axis_x = QBarCategoryAxis()
        step = max(1, len(x) // 10)
        tick_set = set(x[::step])
        labels = [series.dates[i] if i in tick_set else "" for i in x]
        axis_x.append(labels)
        axis_x.setLabelsColor(QColor("#64748B"))
        axis_x.setGridLineVisible(False)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)

        # Left Y axis
        axis_left = QValueAxis()
        axis_left.setLabelsColor(QColor("#64748B"))
        axis_left.setGridLineVisible(True)
        axis_left.setGridLineColor(QColor("#E2E8F0"))
        axis_left.setLabelFormat("%.0f")
        chart.addAxis(axis_left, Qt.AlignmentFlag.AlignLeft)

        # Right Y axis (conditional)
        has_right = any(metrics.get(k, True) for k in ["efficiency", "state", "mood"])
        axis_right = None
        if has_right:
            axis_right = QValueAxis()
            axis_right.setLabelsColor(QColor("#64748B"))
            axis_right.setGridLineVisible(False)
            axis_right.setLabelFormat("%.1f")
            axis_right.setRange(0, 5.0)
            chart.addAxis(axis_right, Qt.AlignmentFlag.AlignRight)

        max_left = 0.0

        # Bar: duration
        if metrics.get("duration", True):
            bar_set = QBarSet("时长")
            bar_color_q = QColor(bar_color)
            bar_set.setColor(bar_color_q)
            bar_set.setBorderColor(bar_color_q)
            for v in series.duration_minutes:
                bar_set.append(v)
            bar_series = QBarSeries()
            bar_series.append(bar_set)
            bar_series.setBarWidth(0.6)
            chart.addSeries(bar_series)
            bar_series.attachAxis(axis_x)
            bar_series.attachAxis(axis_left)
            if series.duration_minutes:
                max_left = max(max_left, max(series.duration_minutes))

        # Line: frequency (left axis)
        if metrics.get("frequency", True):
            line = QLineSeries()
            line.setName("频次")
            line.setPen(QPen(QColor("#334155"), 2))
            line.setPointsVisible(True)
            for i, v in enumerate(series.frequency):
                line.append(i, float(v))
            chart.addSeries(line)
            line.attachAxis(axis_x)
            line.attachAxis(axis_left)
            if series.frequency:
                max_left = max(max_left, float(max(series.frequency)))

        axis_left.setRange(0, max(1.0, max_left * 1.15))

        # Lines: right-axis metrics
        right_config = [
            ("efficiency", "效率均值", "#DC2626"),
            ("state", "状态均值", "#0EA5A4"),
            ("mood", "心情均值", "#8B5CF6"),
        ]
        max_right = 0.0
        if axis_right:
            for key, name, color in right_config:
                if not metrics.get(key, True):
                    continue
                vals = getattr(series, f"avg_{key}")
                line = QLineSeries()
                line.setName(name)
                line.setPen(QPen(QColor(color), 2))
                line.setPointsVisible(True)
                for i, v in enumerate(vals):
                    line.append(i, float(v))
                chart.addSeries(line)
                line.attachAxis(axis_x)
                line.attachAxis(axis_right)
                if vals:
                    max_right = max(max_right, max(vals))
            axis_right.setRange(0, max(1.0, max_right * 1.15))

        chart.setTitle(title)
        chart.legend().setVisible(True)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)

    def _base_views(self) -> list[ViewConfig]:
        return [
            ViewConfig(
                view_id="base_rest",
                title="休息/娱乐",
                kind="category",
                category=BLOCK_CATEGORY_REST,
                block_ids=[],
                metrics={"duration": True, "frequency": True, "efficiency": True, "state": True, "mood": True},
            ),
            ViewConfig(
                view_id="base_work",
                title="学习/工作",
                kind="category",
                category=BLOCK_CATEGORY_WORK,
                block_ids=[],
                metrics={"duration": True, "frequency": True, "efficiency": True, "state": True, "mood": True},
            ),
        ]

    def _ensure_card(self, view_id: str) -> tuple[QGroupBox, QLabel, QChartView]:
        if view_id in self._card_cache:
            return self._card_cache[view_id]
        card = QGroupBox()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        title_row = QHBoxLayout()
        drag_handle = QLabel("⠿")
        drag_handle.setToolTip("拖拽排序")
        drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        drag_handle.installEventFilter(self)
        self._handle_map[drag_handle] = view_id
        title_label = QLabel("")
        del_btn = QPushButton("删除")
        del_btn.setObjectName("dangerButton")
        del_btn.clicked.connect(lambda checked=False, vid=view_id: self._delete_view(vid))
        title_row.addWidget(drag_handle)
        title_row.addWidget(title_label)
        title_row.addStretch()
        title_row.addWidget(del_btn)
        card_layout.addLayout(title_row)

        chart = QChart()
        chart.setBackgroundBrush(QBrush(QColor("#FFFFFF")))
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        chart_view = QChartView(chart)
        chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        chart_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        chart_view.installEventFilter(self)
        self._canvas_map[chart_view] = view_id
        card_layout.addWidget(chart_view)
        self._card_cache[view_id] = (card, title_label, chart_view)
        return self._card_cache[view_id]

    def _ensure_item(self, view_id: str) -> QListWidgetItem:
        if view_id in self._item_by_view_id:
            return self._item_by_view_id[view_id]
        item = QListWidgetItem()
        item.setData(32, view_id)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )
        self.overview_list.addItem(item)
        self._item_by_view_id[view_id] = item
        card, _label, _chart_view = self._ensure_card(view_id)
        self.overview_list.setItemWidget(item, card)
        return item

    def _delete_view(self, view_id: str) -> None:
        if view_id.startswith("custom_"):
            self._custom_views = [v for v in self._custom_views if v.view_id != view_id]
        else:
            self._removed_view_ids.add(view_id)
        self.refresh_overview()

    def _remove_item(self, view_id: str) -> None:
        item = self._item_by_view_id.pop(view_id, None)
        if item is None:
            return
        row = self.overview_list.row(item)
        if row >= 0:
            self.overview_list.takeItem(row)
        card_tuple = self._card_cache.pop(view_id, None)
        if card_tuple:
            chart_view = card_tuple[2]
            self._canvas_map.pop(chart_view, None)
            card_tuple[0].deleteLater()
        stale_handles = [w for w, vid in self._handle_map.items() if vid == view_id]
        for w in stale_handles:
            self._handle_map.pop(w, None)

    def _sync_order_from_list(self) -> None:
        new_order: list[str] = []
        for row in range(self.overview_list.count()):
            item = self.overview_list.item(row)
            view_id = item.data(32)
            if isinstance(view_id, str):
                new_order.append(view_id)
        if new_order:
            self._view_order = new_order

    def eventFilter(self, watched, event):  # type: ignore[override]
        # Handle drag sorting via dedicated handle so chart canvas won't block dragging.
        if watched in self._handle_map:
            vid = self._handle_map[watched]
            if event.type() == QEvent.Type.MouseButtonPress:
                self._drag_anchor = event.globalPosition().toPoint()
                self._drag_view_id = vid
                watched.setCursor(Qt.CursorShape.ClosedHandCursor)
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_anchor and self._drag_view_id == vid:
                delta = event.globalPosition().toPoint() - self._drag_anchor
                if delta.manhattanLength() >= QApplication.startDragDistance():
                    item = self._item_by_view_id.get(vid)
                    if item is not None:
                        self.overview_list.setCurrentItem(item)
                        self.overview_list.startDrag(Qt.DropAction.MoveAction)
                    self._drag_anchor = None
                    self._drag_view_id = None
                    watched.setCursor(Qt.CursorShape.OpenHandCursor)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_anchor = None
                self._drag_view_id = None
                watched.setCursor(Qt.CursorShape.OpenHandCursor)
                return True

        # Smooth wheel scrolling when cursor is on chart canvas.
        if watched in self._canvas_map and event.type() == QEvent.Type.Wheel:
            bar = self.overview_list.verticalScrollBar()
            delta = event.angleDelta().y()
            bar.setValue(bar.value() - int(delta / 3))
            return True
        return super().eventFilter(watched, event)

    def _resize_cards(self) -> None:
        viewport_h = max(200, self.overview_list.viewport().height())
        target_h = max(280, int(viewport_h * 0.48))
        for view_id, item in self._item_by_view_id.items():
            card, _label, chart_view = self._card_cache[view_id]
            chart_view.setMinimumHeight(target_h)
            item.setSizeHint(QSize(self.overview_list.viewport().width() - 12, target_h + 72))
            card.setMinimumHeight(target_h + 48)

    def _selected_block_ids(self) -> list[int]:
        ids: list[int] = []
        for i in range(self.block_list.count()):
            item = self.block_list.item(i)
            if item.isSelected():
                ids.append(int(item.data(32)))
        return ids

    def _current_metrics(self) -> dict[str, bool]:
        return {
            "duration": self.metric_duration.isChecked(),
            "frequency": self.metric_frequency.isChecked(),
            "efficiency": self.metric_efficiency.isChecked(),
            "state": self.metric_state.isChecked(),
            "mood": self.metric_mood.isChecked(),
        }

    def refresh_overview(self) -> None:
        days = self._selected_days(self.range_combo)
        with session_scope() as session:
            category_data = build_category_overview(session, days=days)
        self._current_days = days

        views = [v for v in self._base_views() if v.view_id not in self._removed_view_ids] + self._custom_views
        active: dict[str, ViewConfig] = {v.view_id: v for v in views}
        self._active_views = active
        self._category_data_cache = category_data

        # Update order with additions/removals.
        if not self._view_order:
            self._view_order = [v.view_id for v in views]
        else:
            self._view_order = [vid for vid in self._view_order if vid in active] + [
                vid for vid in active if vid not in self._view_order
            ]

        # Remove inactive items from list.
        for vid in list(self._item_by_view_id.keys()):
            if vid not in active:
                self._remove_item(vid)

        # Ensure all active items exist.
        for vid in self._view_order:
            self._ensure_item(vid)

        # Enforce list order.
        for row, vid in enumerate(self._view_order):
            item = self._item_by_view_id[vid]
            current_row = self.overview_list.row(item)
            if current_row != row and current_row >= 0:
                taken = self.overview_list.takeItem(current_row)
                self.overview_list.insertItem(row, taken)
                self.overview_list.setItemWidget(taken, self._card_cache[vid][0])

        # Render charts incrementally to keep UI responsive.
        self._render_generation += 1
        generation = self._render_generation
        self._render_queue = list(self._view_order)
        QTimer.singleShot(0, lambda gen=generation: self._render_next_overview_card(gen))
        self._resize_cards()

    def _render_next_overview_card(self, generation: int) -> None:
        if generation != self._render_generation or not self._render_queue:
            return

        vid = self._render_queue.pop(0)
        view = self._active_views[vid]
        card, title_label, chart_view = self._card_cache[vid]
        title_label.setText(view.title)
        if view.kind == "category" and view.category is not None:
            series = self._category_data_cache[view.category]
            bar_color = "#60A5FA" if view.category == BLOCK_CATEGORY_REST else "#F87171"
            self._plot_series(chart_view, series, view.title, bar_color, view.metrics)
        else:
            with session_scope() as session:
                series = build_custom_metrics(session, days=self._current_days, block_ids=view.block_ids)
            self._plot_series(chart_view, series, view.title, "#3B82F6", view.metrics)
        card.show()

        if self._render_queue:
            QTimer.singleShot(0, lambda gen=generation: self._render_next_overview_card(gen))

    def render_custom_chart(self) -> None:
        selected_ids = self._selected_block_ids()
        days = self._selected_days(self.custom_range_combo)
        with session_scope() as session:
            series = build_custom_metrics(session, days=days, block_ids=selected_ids)
        metrics = self._current_metrics()

        chart = self.custom_chart_view.chart()
        chart.removeAllSeries()
        for axis in chart.axes():
            chart.removeAxis(axis)
        if not any(metrics.values()):
            chart.setTitle("请至少选择一个指标")
            return
        self._plot_series(self.custom_chart_view, series, "自定义统计预览", "#3B82F6", metrics)

    def save_custom_view(self) -> None:
        selected_ids = self._selected_block_ids()
        if not selected_ids:
            return
        name = self.custom_title_input.text().strip() or f"自定义图表 {len(self._custom_views) + 1}"
        cfg = ViewConfig(
            view_id=f"custom_{uuid4().hex[:8]}",
            title=name,
            kind="custom",
            category=None,
            block_ids=selected_ids,
            metrics=self._current_metrics(),
        )
        self._custom_views.append(cfg)
        self._view_order.append(cfg.view_id)
        self.refresh_overview()
