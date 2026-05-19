"""Points page with manual adjustment and ledger history."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..services.points_service import get_current_balance, manual_adjust_points
from ..services.undo_stack import ManualPointsAdjustCmd, UndoStack
from ..storage.database import session_scope
from ..storage.repositories import list_point_ledger

from .undo_shortcuts import UndoRedoShortcutFilter


_REASON_LABELS = {
    "event_minutes": "事件时长积分",
    "sleep_bonus": "早睡早起奖励",
    "record_recalc": "记录重算回滚",
    "manual_adjust": "手动调整",
}


class PointsPage(QWidget):
    def __init__(self, undo_stack: UndoStack | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._undo_stack = undo_stack
        self.balance_label = QLabel()
        self.balance_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.delta_input = QSpinBox()
        self.delta_input.setRange(-100000, 100000)
        self.delta_input.setValue(0)
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("备注（可选）")
        self.adjust_btn = QPushButton("执行手动增减")
        self.adjust_btn.clicked.connect(self.apply_manual_adjust)

        action_row = QHBoxLayout()
        action_row.addWidget(QLabel("积分变动"))
        action_row.addWidget(self.delta_input)
        action_row.addWidget(QLabel("备注"))
        action_row.addWidget(self.note_input, stretch=1)
        action_row.addWidget(self.adjust_btn)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["时间", "变动", "余额", "来源", "备注"])
        self.table.verticalHeader().setVisible(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.addWidget(self.balance_label)
        root.addLayout(action_row)
        root.addWidget(self.table, stretch=1)

        if self._undo_stack is not None:
            filt = UndoRedoShortcutFilter(self._undo_stack, self, self)
            self.note_input.installEventFilter(filt)

        self.refresh()

    def apply_manual_adjust(self) -> None:
        delta = int(self.delta_input.value())
        if delta == 0:
            QMessageBox.warning(self, "提示", "变动值不能为 0。")
            return
        note = self.note_input.text().strip() or None
        with session_scope() as session:
            manual_adjust_points(session, delta, note)
        if self._undo_stack is not None:
            self._undo_stack.push(ManualPointsAdjustCmd(delta, note))
        self.delta_input.setValue(0)
        self.note_input.clear()
        self.refresh()

    def refresh(self) -> None:
        with session_scope() as session:
            balance = get_current_balance(session)
            rows = list_point_ledger(session, limit=300)
        self.balance_label.setText(f"当前积分余额：{balance}")
        self.table.setRowCount(len(rows))
        for idx, row in enumerate(rows):
            self.table.setItem(idx, 0, QTableWidgetItem(row.created_at.strftime("%Y-%m-%d %H:%M")))
            self.table.setItem(idx, 1, QTableWidgetItem(f"{row.delta:+d}"))
            self.table.setItem(idx, 2, QTableWidgetItem(str(row.balance_after)))
            source = _REASON_LABELS.get(row.reason, row.reason)
            self.table.setItem(idx, 3, QTableWidgetItem(source))
            self.table.setItem(idx, 4, QTableWidgetItem(row.note or ""))
