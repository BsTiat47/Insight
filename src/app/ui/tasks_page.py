"""Tasks / todo management page."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..storage.database import session_scope
from ..storage.repositories import (
    complete_task,
    create_task,
    delete_task,
    list_tasks,
    update_task,
)

TASK_TYPE_LABELS = {"one_time": "一次性事项", "recurring": "长期事项"}


class TasksPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._editing_id: int | None = None

        # ── Form ──
        form_group = QGroupBox("新建/编辑待办事项")
        form_layout = QVBoxLayout(form_group)

        self.task_name = QLineEdit()
        self.task_name.setPlaceholderText("事项名称（例如：完成年度报告）")

        self.task_type_combo = QComboBox()
        self.task_type_combo.addItem("一次性事项", "one_time")
        self.task_type_combo.addItem("长期事项（每日安排）", "recurring")
        self.task_type_combo.currentIndexChanged.connect(self._on_type_changed)

        self.task_start_date = QDateEdit()
        self.task_start_date.setCalendarPopup(True)
        self.task_start_date.setSpecialValueText("无起始日期")
        self.task_start_date.setDate(date.today())
        self.task_start_check = QCheckBox("设置起始日期")
        self.task_start_check.toggled.connect(self._on_start_toggled)

        self.task_end_date = QDateEdit()
        self.task_end_date.setCalendarPopup(True)
        self.task_end_date.setDate(date.today() + timedelta(days=7))

        self.total_minutes_spin = QSpinBox()
        self.total_minutes_spin.setRange(1, 10000)
        self.total_minutes_spin.setSuffix(" 分钟")
        self.total_minutes_spin.setValue(60)

        self.daily_minutes_spin = QSpinBox()
        self.daily_minutes_spin.setRange(1, 1440)
        self.daily_minutes_spin.setSuffix(" 分钟/天")
        self.daily_minutes_spin.setValue(30)

        self.save_btn = QPushButton("保存事项")
        self.save_btn.clicked.connect(self._save_task)
        self.cancel_edit_btn = QPushButton("取消编辑")
        self.cancel_edit_btn.clicked.connect(self._cancel_edit)
        self.cancel_edit_btn.setVisible(False)

        form_layout.addWidget(QLabel("名称"))
        form_layout.addWidget(self.task_name)
        form_layout.addWidget(QLabel("类型"))
        form_layout.addWidget(self.task_type_combo)
        sr = QHBoxLayout()
        sr.addWidget(self.task_start_check)
        sr.addWidget(self.task_start_date)
        sr.addStretch()
        form_layout.addLayout(sr)
        form_layout.addWidget(QLabel("截止日期"))
        form_layout.addWidget(self.task_end_date)
        form_layout.addWidget(QLabel("所需时长"))
        form_layout.addWidget(self.total_minutes_spin)
        form_layout.addWidget(self.daily_minutes_spin)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.cancel_edit_btn)
        btn_row.addStretch()
        form_layout.addLayout(btn_row)

        # ── Task list ──
        self.task_list = QListWidget()
        self.task_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.task_list.currentRowChanged.connect(self._on_list_selection)

        list_btns = QHBoxLayout()
        self.edit_btn = QPushButton("编辑")
        self.edit_btn.clicked.connect(self._edit_selected)
        self.complete_btn = QPushButton("标记完成")
        self.complete_btn.clicked.connect(self._complete_selected)
        self.delete_btn = QPushButton("删除")
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.clicked.connect(self._delete_selected)
        list_btns.addWidget(self.edit_btn)
        list_btns.addWidget(self.complete_btn)
        list_btns.addWidget(self.delete_btn)
        list_btns.addStretch()

        # ── Root ──
        left = QVBoxLayout()
        left.addWidget(form_group)
        left.addStretch()

        right = QVBoxLayout()
        right.addWidget(QLabel("待办事项列表"))
        right.addWidget(self.task_list, stretch=1)
        right.addLayout(list_btns)

        root = QHBoxLayout(self)
        root.addLayout(left, stretch=2)
        root.addLayout(right, stretch=3)

        self._on_type_changed()
        self._on_start_toggled()
        self._load_tasks()

    def _on_type_changed(self) -> None:
        is_one_time = self.task_type_combo.currentData() == "one_time"
        self.total_minutes_spin.setVisible(is_one_time)
        self.daily_minutes_spin.setVisible(not is_one_time)

    def _on_start_toggled(self) -> None:
        self.task_start_date.setEnabled(self.task_start_check.isChecked())

    def _load_tasks(self) -> None:
        self.task_list.blockSignals(True)
        self.task_list.clear()
        with session_scope() as session:
            tasks = list_tasks(session, include_completed=False)
        for t in tasks:
            label = self._format_task(t)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, t.id)
            if t.is_completed:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.task_list.addItem(item)
        self.task_list.blockSignals(False)

    @staticmethod
    def _format_task(t) -> str:
        type_label = TASK_TYPE_LABELS.get(t.task_type, t.task_type)
        parts = [f"[{type_label}] {t.name}"]
        if t.start_date:
            parts.append(f"  从 {t.start_date.isoformat()}")
        parts.append(f"  截止 {t.end_date.isoformat()}")
        if t.task_type == "one_time" and t.total_minutes:
            hours = t.total_minutes // 60
            mins = t.total_minutes % 60
            parts.append(f"  共 {hours}h{mins}m" if hours else f"  共 {mins}m")
        elif t.task_type == "recurring" and t.daily_minutes:
            parts.append(f"  每天 {t.daily_minutes} 分钟")
        return "".join(parts)

    def _on_list_selection(self) -> None:
        """Show context actions when a task is selected (handled by buttons)."""
        pass

    def _edit_selected(self) -> None:
        item = self.task_list.currentItem()
        if item is None:
            return
        task_id = item.data(Qt.ItemDataRole.UserRole)
        with session_scope() as session:
            tasks = list_tasks(session, include_completed=True)
        t = next((tk for tk in tasks if tk.id == task_id), None)
        if t is None:
            return
        self._editing_id = t.id
        self.task_name.setText(t.name)
        idx = self.task_type_combo.findData(t.task_type)
        if idx >= 0:
            self.task_type_combo.setCurrentIndex(idx)
        if t.start_date:
            self.task_start_check.setChecked(True)
            self.task_start_date.setDate(t.start_date)
        else:
            self.task_start_check.setChecked(False)
        self.task_end_date.setDate(t.end_date)
        if t.total_minutes is not None:
            self.total_minutes_spin.setValue(t.total_minutes)
        if t.daily_minutes is not None:
            self.daily_minutes_spin.setValue(t.daily_minutes)
        self.save_btn.setText("更新事项")
        self.cancel_edit_btn.setVisible(True)
        self._on_type_changed()
        self._on_start_toggled()

    def _cancel_edit(self) -> None:
        self._editing_id = None
        self.task_name.clear()
        self.task_type_combo.setCurrentIndex(0)
        self.task_start_check.setChecked(False)
        self.task_end_date.setDate(date.today() + timedelta(days=7))
        self.total_minutes_spin.setValue(60)
        self.daily_minutes_spin.setValue(30)
        self.save_btn.setText("保存事项")
        self.cancel_edit_btn.setVisible(False)
        self._on_type_changed()
        self._on_start_toggled()

    def _save_task(self) -> None:
        name = self.task_name.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入事项名称。")
            return
        task_type = self.task_type_combo.currentData()
        end_date = self.task_end_date.date().toPython()
        start_date = self.task_start_date.date().toPython() if self.task_start_check.isChecked() else None
        if start_date and start_date > end_date:
            QMessageBox.warning(self, "提示", "起始日期不能晚于截止日期。")
            return

        total_minutes = self.total_minutes_spin.value() if task_type == "one_time" else None
        daily_minutes = self.daily_minutes_spin.value() if task_type == "recurring" else None

        with session_scope() as session:
            if self._editing_id is not None:
                update_task(
                    session, self._editing_id,
                    name=name, task_type=task_type, end_date=end_date,
                    start_date=start_date, total_minutes=total_minutes, daily_minutes=daily_minutes,
                )
            else:
                create_task(
                    session,
                    name=name, task_type=task_type, end_date=end_date,
                    start_date=start_date, total_minutes=total_minutes, daily_minutes=daily_minutes,
                )
        self._cancel_edit()
        self._load_tasks()

    def _complete_selected(self) -> None:
        item = self.task_list.currentItem()
        if item is None:
            return
        task_id = item.data(Qt.ItemDataRole.UserRole)
        with session_scope() as session:
            complete_task(session, task_id)
        self._load_tasks()

    def _delete_selected(self) -> None:
        item = self.task_list.currentItem()
        if item is None:
            return
        task_id = item.data(Qt.ItemDataRole.UserRole)
        confirm = QMessageBox.question(
            self, "确认删除", "确定要删除此待办事项吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        with session_scope() as session:
            delete_task(session, task_id)
        self._load_tasks()

    def refresh(self) -> None:
        self._load_tasks()
