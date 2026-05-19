"""Event blocks management page."""

from __future__ import annotations

from typing import Callable

from sqlalchemy.exc import IntegrityError
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..domain.models import EventBlock
from ..services.undo_stack import CreateBlockCmd, DeleteBlockCmd, UndoStack, UpdateBlockCmd, snapshot_from_block
from ..storage.database import session_scope
from ..storage.repositories import (
    BLOCK_CATEGORY_REST,
    BLOCK_CATEGORY_WORK,
    CATEGORY_COLOR_MAP,
    CATEGORY_LABEL_MAP,
    create_block,
    delete_block,
    list_blocks,
    update_block,
)


class BlocksPage(QWidget):
    def __init__(
        self,
        on_blocks_changed: Callable[[], None],
        parent: QWidget | None = None,
        undo_stack: UndoStack | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_blocks_changed = on_blocks_changed
        self._undo_stack = undo_stack
        self._selected_block_id: int | None = None
        self._selected_category = BLOCK_CATEGORY_WORK

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("方块名称")
        self.category_combo = QComboBox()
        self.category_combo.addItem(CATEGORY_LABEL_MAP[BLOCK_CATEGORY_WORK], BLOCK_CATEGORY_WORK)
        self.category_combo.addItem(CATEGORY_LABEL_MAP[BLOCK_CATEGORY_REST], BLOCK_CATEGORY_REST)
        self.category_combo.currentIndexChanged.connect(self.on_category_change)
        self.color_label = QLabel(CATEGORY_COLOR_MAP[self._selected_category])
        self.points_per_minute_input = QDoubleSpinBox()
        self.points_per_minute_input.setDecimals(2)
        self.points_per_minute_input.setRange(-100.0, 100.0)
        self.points_per_minute_input.setSingleStep(0.1)
        self.points_per_minute_input.setValue(0.0)

        self.add_btn = QPushButton("新增")
        self.add_btn.clicked.connect(self.add_block)
        self.update_btn = QPushButton("更新")
        self.update_btn.clicked.connect(self.update_selected_block)

        form = QHBoxLayout()
        form.setSpacing(8)
        form.addWidget(QLabel("名称"))
        form.addWidget(self.name_input)
        form.addWidget(QLabel("类型"))
        form.addWidget(self.category_combo)
        form.addWidget(QLabel("每分钟积分"))
        form.addWidget(self.points_per_minute_input)
        form.addWidget(self.color_label)
        form.addWidget(self.add_btn)
        form.addWidget(self.update_btn)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["名称", "类型", "每分钟积分", "操作"])
        self.table.itemSelectionChanged.connect(self.on_selection_change)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)
        root.addLayout(form)
        root.addWidget(self.table)
        self.table.verticalHeader().setVisible(False)

        self.refresh()

    def on_category_change(self) -> None:
        category = self.category_combo.currentData()
        if isinstance(category, str):
            self._selected_category = category
            self.color_label.setText(CATEGORY_COLOR_MAP.get(category, CATEGORY_COLOR_MAP[BLOCK_CATEGORY_WORK]))

    def refresh(self) -> None:
        with session_scope() as session:
            blocks = list_blocks(session, include_inactive=True)
        self.table.setRowCount(len(blocks))
        for row, block in enumerate(blocks):
            name_item = QTableWidgetItem(block.name)
            name_item.setData(32, block.id)  # Qt.UserRole
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(CATEGORY_LABEL_MAP.get(block.category, block.category)))
            self.table.setItem(row, 2, QTableWidgetItem(f"{block.points_per_minute:.2f}"))
            del_btn = QPushButton("删除")
            del_btn.setObjectName("dangerButton")
            del_btn.clicked.connect(lambda checked=False, bid=block.id: self.delete_block_by_id(bid))
            self.table.setCellWidget(row, 3, del_btn)

    def _current_block_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        name_item = self.table.item(row, 0)
        if name_item is None:
            return None
        value = name_item.data(32)
        return int(value) if value is not None else None

    def on_selection_change(self) -> None:
        block_id = self._current_block_id()
        if block_id is None:
            return
        self._selected_block_id = block_id
        self.name_input.setText(self.table.item(self.table.currentRow(), 0).text())
        category_label = self.table.item(self.table.currentRow(), 1).text()
        category = BLOCK_CATEGORY_WORK
        for key, label in CATEGORY_LABEL_MAP.items():
            if label == category_label:
                category = key
                break
        self._selected_category = category
        combo_idx = self.category_combo.findData(category)
        if combo_idx >= 0:
            self.category_combo.setCurrentIndex(combo_idx)
        points_text = self.table.item(self.table.currentRow(), 2).text()
        try:
            points_per_minute = float(points_text)
        except ValueError:
            points_per_minute = 0.0
        self.points_per_minute_input.setValue(points_per_minute)
        self.color_label.setText(CATEGORY_COLOR_MAP.get(category, CATEGORY_COLOR_MAP[BLOCK_CATEGORY_WORK]))

    def add_block(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入方块名称。")
            return
        try:
            with session_scope() as session:
                block = create_block(
                    session,
                    name=name,
                    category=self._selected_category,
                    points_per_minute=self.points_per_minute_input.value(),
                )
                snap = snapshot_from_block(block)
                bid = block.id
        except IntegrityError:
            QMessageBox.warning(self, "提示", "方块名称已存在。")
            return
        if self._undo_stack is not None:
            self._undo_stack.push(CreateBlockCmd(snap, bid))
        self.name_input.clear()
        self.points_per_minute_input.setValue(0.0)
        self.refresh()
        self._on_blocks_changed()

    def update_selected_block(self) -> None:
        if self._selected_block_id is None:
            QMessageBox.warning(self, "提示", "请先选择方块。")
            return
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入方块名称。")
            return
        try:
            with session_scope() as session:
                block = session.get(EventBlock, self._selected_block_id)
                if block is None:
                    QMessageBox.warning(self, "提示", "方块不存在。")
                    return
                before = snapshot_from_block(block)
                update_block(
                    session,
                    self._selected_block_id,
                    name=name,
                    category=self._selected_category,
                    points_per_minute=self.points_per_minute_input.value(),
                )
                after = snapshot_from_block(block)
        except IntegrityError:
            QMessageBox.warning(self, "提示", "方块名称已存在。")
            return
        if self._undo_stack is not None:
            self._undo_stack.push(UpdateBlockCmd(self._selected_block_id, before, after))
        self.refresh()
        self._on_blocks_changed()

    def delete_block_by_id(self, block_id: int) -> None:
        confirm = QMessageBox.question(self, "确认删除", "确认删除该方块吗？")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            with session_scope() as session:
                block = session.get(EventBlock, block_id)
                if block is None:
                    return
                snap = snapshot_from_block(block)
                delete_block(session, block_id)
            if self._undo_stack is not None:
                self._undo_stack.push(DeleteBlockCmd(snap))
        except ValueError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self.refresh()
        self._on_blocks_changed()

