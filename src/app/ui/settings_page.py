"""Settings page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ..storage.database import session_scope
from ..storage.repositories import (
    DEFAULT_AI_SYSTEM_PROMPT,
    get_ai_settings,
    get_points_settings,
    list_blocks,
    save_ai_settings,
    save_points_settings,
    update_block,
)


class SettingsPage(QWidget):
    def __init__(self, db_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db_label = QLabel(f"数据库路径：{db_path}")
        self.score_doc = QLabel(
            "评分说明：效率/状态/心情 1-5（可选）。\n"
            "积分说明：按事件时长 * 每分钟积分计算；可在此开关与配置睡眠奖励。"
        )
        # ── Points settings ──
        self.points_enabled_checkbox = QCheckBox("启用自动积分计算")
        self.block_combo = QComboBox()
        self.block_points_spin = QDoubleSpinBox()
        self.block_points_spin.setDecimals(2)
        self.block_points_spin.setRange(-100.0, 100.0)
        self.block_points_spin.setSingleStep(0.1)
        self.block_save_btn = QPushButton("保存方块每分钟积分")
        self.block_combo.currentIndexChanged.connect(self._sync_block_points_spin)
        self.block_save_btn.clicked.connect(self.save_block_points_rule)
        self.sleep_start_edit = QTimeEdit()
        self.sleep_start_edit.setDisplayFormat("HH:mm")
        self.sleep_wake_edit = QTimeEdit()
        self.sleep_wake_edit.setDisplayFormat("HH:mm")
        self.sleep_bonus_spin = QSpinBox()
        self.sleep_bonus_spin.setRange(-10000, 10000)
        self.sleep_bonus_spin.setSingleStep(1)
        self.save_btn = QPushButton("保存积分设置")
        self.save_btn.clicked.connect(self.save_points_config)

        # ── AI settings ──
        self.ai_enabled_checkbox = QCheckBox("启用AI自动补全（框选时间段时自动建议日程）")
        self.ai_api_url = QLineEdit()
        self.ai_api_url.setPlaceholderText("https://api.deepseek.com/v1/chat/completions")
        self.ai_api_key = QLineEdit()
        self.ai_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_api_key.setPlaceholderText("sk-...")
        self.ai_model = QLineEdit()
        self.ai_model.setPlaceholderText("deepseek-chat")
        self.ai_system_prompt = QLineEdit()
        self.ai_system_prompt.setPlaceholderText("默认系统提示词（可自定义）")
        self.ai_test_btn = QPushButton("测试连接")
        self.ai_test_btn.clicked.connect(self._test_ai_connection)
        self.ai_save_btn = QPushButton("保存AI设置")
        self.ai_save_btn.clicked.connect(self._save_ai_config)

        ai_group = QGroupBox("AI 自动补全设置（默认 DeepSeek API）")
        ai_layout = QVBoxLayout(ai_group)
        ai_layout.addWidget(self.ai_enabled_checkbox)
        ai_layout.addWidget(QLabel("API 地址"))
        ai_layout.addWidget(self.ai_api_url)
        ai_layout.addWidget(QLabel("API Key"))
        ai_layout.addWidget(self.ai_api_key)
        ai_layout.addWidget(QLabel("模型名称"))
        ai_layout.addWidget(self.ai_model)
        ai_layout.addWidget(QLabel("自定义系统提示词"))
        ai_layout.addWidget(self.ai_system_prompt)
        ai_btn_row = QHBoxLayout()
        ai_btn_row.addWidget(self.ai_test_btn)
        ai_btn_row.addWidget(self.ai_save_btn)
        ai_btn_row.addStretch()
        ai_layout.addLayout(ai_btn_row)

        # ── Layout ──
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        layout.addWidget(self.db_label)
        layout.addWidget(self.score_doc)
        layout.addWidget(self.points_enabled_checkbox)

        rule_row = QHBoxLayout()
        rule_row.addWidget(QLabel("方块积分规则"))
        rule_row.addWidget(self.block_combo, stretch=1)
        rule_row.addWidget(QLabel("每分钟积分"))
        rule_row.addWidget(self.block_points_spin)
        rule_row.addWidget(self.block_save_btn)
        layout.addLayout(rule_row)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("早睡阈值（入睡早于）"))
        row1.addWidget(self.sleep_start_edit)
        row1.addWidget(QLabel("早起阈值（起床早于）"))
        row1.addWidget(self.sleep_wake_edit)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("早睡早起奖励积分"))
        row2.addWidget(self.sleep_bonus_spin)
        row2.addStretch()
        layout.addLayout(row2)
        layout.addWidget(self.save_btn)
        layout.addWidget(ai_group)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

        self._block_items: list[tuple[int, str, str]] = []
        self._reload_block_rules()
        self._load_points_config()
        self._load_ai_config()

    def _load_points_config(self) -> None:
        with session_scope() as session:
            settings = get_points_settings(session)
        self.points_enabled_checkbox.setChecked(settings.points_enabled)
        self.sleep_start_edit.setTime(self._parse_time(settings.sleep_start_before, "23:30"))
        self.sleep_wake_edit.setTime(self._parse_time(settings.sleep_wake_before, "08:00"))
        self.sleep_bonus_spin.setValue(settings.sleep_bonus_delta)

    @staticmethod
    def _parse_time(raw: str, fallback: str) -> QTime:
        hhmm = raw or fallback
        parts = hhmm.split(":")
        if len(parts) != 2:
            parts = fallback.split(":")
        try:
            return QTime(int(parts[0]), int(parts[1]))
        except ValueError:
            fallback_parts = fallback.split(":")
            return QTime(int(fallback_parts[0]), int(fallback_parts[1]))

    def save_points_config(self) -> None:
        sleep_start = self.sleep_start_edit.time().toString("HH:mm")
        sleep_wake = self.sleep_wake_edit.time().toString("HH:mm")
        with session_scope() as session:
            save_points_settings(
                session,
                points_enabled=self.points_enabled_checkbox.isChecked(),
                sleep_start_before=sleep_start,
                sleep_wake_before=sleep_wake,
                sleep_bonus_delta=self.sleep_bonus_spin.value(),
            )
        QMessageBox.information(self, "提示", "积分设置已保存。")

    def _reload_block_rules(self) -> None:
        self._block_items = []
        self.block_combo.blockSignals(True)
        self.block_combo.clear()
        with session_scope() as session:
            blocks = list_blocks(session, include_inactive=True)
        for block in blocks:
            self.block_combo.addItem(f"{block.name} ({block.points_per_minute:.2f}/分钟)", block.id)
            self._block_items.append((block.id, block.name, block.category))
        self.block_combo.blockSignals(False)
        self._sync_block_points_spin()

    def _sync_block_points_spin(self) -> None:
        block_id = self.block_combo.currentData()
        if block_id is None:
            self.block_points_spin.setValue(0.0)
            return
        with session_scope() as session:
            blocks = list_blocks(session, include_inactive=True)
        target = next((b for b in blocks if b.id == int(block_id)), None)
        self.block_points_spin.setValue(float(target.points_per_minute) if target is not None else 0.0)

    def save_block_points_rule(self) -> None:
        block_id = self.block_combo.currentData()
        if block_id is None:
            QMessageBox.warning(self, "提示", "当前没有可配置的方块。")
            return
        target = next((item for item in self._block_items if item[0] == int(block_id)), None)
        if target is None:
            QMessageBox.warning(self, "提示", "方块不存在，请刷新后重试。")
            return
        with session_scope() as session:
            update_block(
                session,
                block_id=int(block_id),
                name=target[1],
                category=target[2],
                points_per_minute=self.block_points_spin.value(),
            )
        self._reload_block_rules()
        QMessageBox.information(self, "提示", "方块积分规则已保存。")

    # ── AI settings ──

    def _load_ai_config(self) -> None:
        with session_scope() as session:
            settings = get_ai_settings(session)
        self.ai_enabled_checkbox.setChecked(settings.enabled)
        self.ai_api_url.setText(settings.api_url)
        self.ai_api_key.setText(settings.api_key)
        self.ai_model.setText(settings.model)
        self.ai_system_prompt.setText(settings.system_prompt)

    def _save_ai_config(self) -> None:
        with session_scope() as session:
            save_ai_settings(
                session,
                enabled=self.ai_enabled_checkbox.isChecked(),
                api_url=self.ai_api_url.text().strip(),
                api_key=self.ai_api_key.text().strip(),
                model=self.ai_model.text().strip(),
                system_prompt=self.ai_system_prompt.text().strip() or DEFAULT_AI_SYSTEM_PROMPT,
            )
        QMessageBox.information(self, "提示", "AI 设置已保存。")

    def _test_ai_connection(self) -> None:
        from ..services.ai_service import test_connection
        from ..storage.repositories import AISettings

        settings = AISettings(
            enabled=True,
            api_url=self.ai_api_url.text().strip(),
            api_key=self.ai_api_key.text().strip(),
            model=self.ai_model.text().strip(),
        )
        self.ai_test_btn.setEnabled(False)
        self.ai_test_btn.setText("测试中...")
        result = test_connection(settings)
        self.ai_test_btn.setEnabled(True)
        self.ai_test_btn.setText("测试连接")
        if result == "ok":
            QMessageBox.information(self, "AI 连接测试", "连接成功！API 响应正常。")
        else:
            QMessageBox.warning(self, "AI 连接测试", f"连接失败：{result}")
