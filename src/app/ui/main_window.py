"""Main window with left navigation."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from ..services.undo_stack import UndoStack

from .blocks_page import BlocksPage
from .points_page import PointsPage
from .record_page import RecordPage
from .settings_page import SettingsPage
from .tasks_page import TasksPage


class MainWindow(QMainWindow):
    def __init__(self, db_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Insight")
        self.resize(1200, 800)

        self._undo_stack = UndoStack(max_size=200, on_changed=self.refresh_all)

        self.nav = QListWidget()
        self.nav.setFixedWidth(180)
        self.nav.setObjectName("sideNav")
        for item in ["记录", "统计", "积分", "待办", "关联性分析", "方块管理", "设置"]:
            QListWidgetItem(item, self.nav)

        self.stack = QStackedWidget()
        self.record_page = RecordPage(on_data_changed=self.refresh_all, undo_stack=self._undo_stack)
        self.stats_page = None
        self.points_page = PointsPage(undo_stack=self._undo_stack)
        self.tasks_page = TasksPage()
        self.correlation_page = None
        self._stats_placeholder = QLabel("统计页首次打开时加载...")
        self._stats_placeholder.setAlignment(Qt.AlignCenter)
        self._corr_placeholder = QLabel("关联性分析页首次打开时加载...")
        self._corr_placeholder.setAlignment(Qt.AlignCenter)
        self.blocks_page = BlocksPage(on_blocks_changed=self.refresh_all, undo_stack=self._undo_stack)
        self.settings_page = SettingsPage(db_path=db_path)

        self.stack.addWidget(self.record_page)        # 0
        self.stack.addWidget(self._stats_placeholder)  # 1
        self.stack.addWidget(self.points_page)         # 2
        self.stack.addWidget(self.tasks_page)          # 3
        self.stack.addWidget(self._corr_placeholder)   # 4
        self.stack.addWidget(self.blocks_page)         # 5
        self.stack.addWidget(self.settings_page)       # 6

        self.nav.currentRowChanged.connect(self.on_nav_changed)
        self.nav.setCurrentRow(0)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        layout.addWidget(self.nav)
        layout.addWidget(self.stack, stretch=1)
        layout.setAlignment(Qt.AlignTop)
        self.setCentralWidget(root)

        undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        undo_shortcut.activated.connect(self._shortcut_undo)
        redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        redo_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        redo_shortcut.activated.connect(self._shortcut_redo)

        # Warm up stats page after first screen is responsive.
        QTimer.singleShot(800, self._ensure_stats_page)

    def _shortcut_undo(self) -> None:
        try:
            self._undo_stack.undo()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "撤销失败", str(exc))

    def _shortcut_redo(self) -> None:
        try:
            self._undo_stack.redo()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "重做失败", str(exc))

    def refresh_all(self) -> None:
        self.record_page.refresh()
        if self.stats_page is not None:
            self.stats_page.refresh()
        self.points_page.refresh()
        self.tasks_page.refresh()
        if self.correlation_page is not None:
            self.correlation_page.refresh()
        self.blocks_page.refresh()

    def _ensure_stats_page(self) -> None:
        if self.stats_page is not None:
            return
        from .stats_page import StatsPage

        self.stats_page = StatsPage()
        self.stack.removeWidget(self._stats_placeholder)
        self._stats_placeholder.deleteLater()
        self.stack.insertWidget(1, self.stats_page)

    def on_nav_changed(self, index: int) -> None:
        if index == 1:
            self._ensure_stats_page()
        elif index == 4:
            self._ensure_correlation_page()
        self.stack.setCurrentIndex(index)

    def _ensure_correlation_page(self) -> None:
        if self.correlation_page is not None:
            return
        from .correlation_page import CorrelationPage

        self.correlation_page = CorrelationPage()
        self.stack.removeWidget(self._corr_placeholder)
        self._corr_placeholder.deleteLater()
        self.stack.insertWidget(4, self.correlation_page)
