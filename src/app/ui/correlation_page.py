"""Correlation analysis page."""

from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..services.correlation_service import analyze_project_by_id
from ..storage.database import session_scope
from ..storage.repositories import (
    CATEGORY_LABEL_MAP,
    create_correlation_project,
    delete_correlation_project,
    list_blocks,
    list_correlation_projects,
)

RANGE_OPTIONS = [("周", 7), ("月", 30), ("半年", 182), ("一年", 365)]


class CorrelationPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.corr_project_name = QLineEdit()
        self.corr_project_name.setPlaceholderText("分析项目名称（例如：睡眠对次日效率）")
        self.corr_days_combo = QComboBox()
        for label, _days in RANGE_OPTIONS:
            self.corr_days_combo.addItem(label, _days)
        self.corr_days_combo.setCurrentIndex(1)

        self.corr_time_combo = QComboBox()
        self.corr_time_combo.addItem("同日(T)", "same_day")
        self.corr_time_combo.addItem("滞后1天(T+1)", "lag_1")
        self.corr_time_combo.addItem("滞后2天(T+2)", "lag_2")

        self.corr_target_combo = QComboBox()
        self.corr_target_combo.addItem("效率均值", "efficiency")
        self.corr_target_combo.addItem("状态均值", "state")
        self.corr_target_combo.addItem("心情均值", "mood")

        self.corr_source_combo = QComboBox()
        self.corr_source_combo.addItem("时长(分钟)", "duration")
        self.corr_source_combo.addItem("频次(条数)", "frequency")
        self.corr_source_combo.addItem("是否发生", "occurred")

        self.corr_block_list = QListWidget()
        self.corr_block_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)

        self.corr_create_btn = QPushButton("生成分析项目")
        self.corr_create_btn.clicked.connect(self.create_correlation_project_item)
        self.corr_delete_btn = QPushButton("删除项目")
        self.corr_delete_btn.setObjectName("dangerButton")
        self.corr_delete_btn.clicked.connect(self.delete_selected_correlation_project)
        self.corr_refresh_btn = QPushButton("刷新结果")
        self.corr_refresh_btn.clicked.connect(self.refresh_correlation)

        corr_form = QVBoxLayout()
        corr_form.addWidget(QLabel("项目名称"))
        corr_form.addWidget(self.corr_project_name)
        corr_form.addWidget(QLabel("分析范围"))
        corr_form.addWidget(self.corr_days_combo)
        corr_form.addWidget(QLabel("时间组合"))
        corr_form.addWidget(self.corr_time_combo)
        corr_form.addWidget(QLabel("目标变量"))
        corr_form.addWidget(self.corr_target_combo)
        corr_form.addWidget(QLabel("来源定义"))
        corr_form.addWidget(self.corr_source_combo)
        corr_form.addWidget(QLabel("事件组合"))
        corr_form.addWidget(self.corr_block_list, stretch=1)
        corr_form.addWidget(self.corr_create_btn)

        self.corr_project_list = QListWidget()
        self.corr_project_list.currentRowChanged.connect(lambda *_args: self.refresh_correlation())
        corr_project_col = QVBoxLayout()
        corr_project_col.addWidget(QLabel("分析项目"))
        corr_project_col.addWidget(self.corr_project_list, stretch=1)
        corr_project_col.addWidget(self.corr_refresh_btn)
        corr_project_col.addWidget(self.corr_delete_btn)

        self.corr_result_table = QTableWidget(0, 5)
        self.corr_result_table.setHorizontalHeaderLabels(["来源事件", "样本N", "Spearman", "方向/强度", "解释"])
        self.corr_result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.corr_result_table.verticalHeader().setVisible(False)
        self.corr_result_table.horizontalHeader().setStretchLastSection(True)

        self.corr_summary_label = QLabel("请选择或创建分析项目。")
        self.corr_summary_label.setWordWrap(True)

        corr_result_col = QVBoxLayout()
        corr_result_col.addWidget(QLabel("分析结果"))
        corr_result_col.addWidget(self.corr_result_table, stretch=1)
        corr_result_col.addWidget(self.corr_summary_label)

        root = QHBoxLayout(self)
        root.addLayout(corr_form, stretch=2)
        root.addLayout(corr_project_col, stretch=1)
        root.addLayout(corr_result_col, stretch=3)

        self.refresh()

    @staticmethod
    def _selected_days(combo: QComboBox) -> int:
        return int(combo.currentData() or 7)

    def _selected_correlation_block_ids(self) -> list[int]:
        ids: list[int] = []
        for i in range(self.corr_block_list.count()):
            item = self.corr_block_list.item(i)
            if item.isSelected():
                ids.append(int(item.data(32)))
        return ids

    def _reload_blocks(self) -> None:
        self.corr_block_list.clear()
        with session_scope() as session:
            blocks = list_blocks(session, include_inactive=False)
        for b in blocks:
            item = QListWidgetItem(f"{b.name}（{CATEGORY_LABEL_MAP.get(b.category, b.category)}）")
            item.setData(32, b.id)
            item.setSelected(True)
            self.corr_block_list.addItem(item)

    def load_correlation_projects(self, select_project_id: int | None = None) -> None:
        with session_scope() as session:
            projects = list_correlation_projects(session)
        self.corr_project_list.blockSignals(True)
        self.corr_project_list.clear()
        target_row = -1
        for row, project in enumerate(projects):
            item = QListWidgetItem(project.name)
            item.setData(32, project.id)
            self.corr_project_list.addItem(item)
            if select_project_id is not None and project.id == select_project_id:
                target_row = row
        if projects:
            self.corr_project_list.setCurrentRow(target_row if target_row >= 0 else 0)
        self.corr_project_list.blockSignals(False)

    def create_correlation_project_item(self) -> None:
        block_ids = self._selected_correlation_block_ids()
        if not block_ids:
            QMessageBox.information(self, "提示", "请至少选择一个来源事件。")
            return

        name = self.corr_project_name.text().strip() or f"关联分析项目 {self.corr_project_list.count() + 1}"
        source_config = json.dumps(
            {
                "source_type": str(self.corr_source_combo.currentData() or "duration"),
                "block_ids": block_ids,
            },
            ensure_ascii=False,
        )
        with session_scope() as session:
            project = create_correlation_project(
                session=session,
                name=name,
                days=self._selected_days(self.corr_days_combo),
                time_relation=str(self.corr_time_combo.currentData() or "same_day"),
                target_variable=str(self.corr_target_combo.currentData() or "efficiency"),
                source_config=source_config,
            )
            project_id = project.id
        self.corr_project_name.clear()
        self.load_correlation_projects(select_project_id=project_id)
        self.refresh_correlation()

    def delete_selected_correlation_project(self) -> None:
        item = self.corr_project_list.currentItem()
        if item is None:
            return
        project_id = int(item.data(32))
        with session_scope() as session:
            delete_correlation_project(session, project_id)
        self.load_correlation_projects()
        self.refresh_correlation()

    def refresh_correlation(self) -> None:
        item = self.corr_project_list.currentItem()
        if item is None:
            self.corr_result_table.setRowCount(0)
            self.corr_summary_label.setText("暂无分析项目，请先创建项目。")
            return
        project_id = int(item.data(32))
        with session_scope() as session:
            result = analyze_project_by_id(session, project_id)
        if result is None:
            self.corr_result_table.setRowCount(0)
            self.corr_summary_label.setText("项目不存在或已失效。")
            return

        self.corr_result_table.setRowCount(len(result.items))
        for row, entry in enumerate(result.items):
            self.corr_result_table.setItem(row, 0, QTableWidgetItem(entry.source_name))
            self.corr_result_table.setItem(row, 1, QTableWidgetItem(str(entry.samples)))
            self.corr_result_table.setItem(row, 2, QTableWidgetItem(f"{entry.spearman:.3f}"))
            self.corr_result_table.setItem(row, 3, QTableWidgetItem(f"{entry.direction}/{entry.strength}"))
            self.corr_result_table.setItem(row, 4, QTableWidgetItem(entry.explanation))
        self.corr_summary_label.setText(result.summary)

    def refresh(self) -> None:
        self._reload_blocks()
        self.load_correlation_projects()
        self.refresh_correlation()

