"""Record page: timeline-only main view, modal editor on demand."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Callable

from PySide6.QtCore import QDateTime, Qt, QTime, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTimeEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import IntegrityError

from ..domain.models import ActivityRecord
from ..services.points_service import apply_points_for_new_record, recalculate_points_for_record
from ..services.record_service import validate_scores, validate_time_range
from ..services.undo_stack import (
    BulkDeleteCmd,
    CreateRecordCmd,
    DeleteRecordCmd,
    RecordUndoSnapshot,
    UndoStack,
    UpdateRecordCmd,
    snapshot_from_record,
)
from ..storage.database import session_scope
from ..storage.repositories import (
    BLOCK_CATEGORY_REST,
    BLOCK_CATEGORY_WORK,
    CATEGORY_LABEL_MAP,
    create_block,
    create_record,
    delete_record,
    get_record_by_id,
    list_blocks,
    list_records_in_range,
    update_record,
)
from .undo_shortcuts import UndoRedoShortcutFilter
from .week_timeline_widget import WeekTimelineWidget

SCORE_NONE = "无"


class RecordEditorDialog(QDialog):
    def __init__(
        self,
        start_dt: datetime,
        end_dt: datetime,
        record_id: int | None = None,
        parent: QWidget | None = None,
        undo_stack: UndoStack | None = None,
    ) -> None:
        super().__init__(parent)
        self._record_id = record_id
        self._deleted = False
        self._undo_stack = undo_stack
        self._initial_snapshot: RecordUndoSnapshot | None = None
        self.setWindowTitle("编辑事件" if record_id is not None else "新建事件")
        self.resize(700, 280)

        self.block_combo = QComboBox()
        self.block_combo.setEditable(False)
        self.inline_block_btn = QPushButton("快速新增方块")
        self.inline_block_btn.clicked.connect(self.inline_create_block)

        self._start_date = start_dt.date()
        self._end_date = end_dt.date()
        self.start_date_label = QLabel(self._start_date.isoformat())
        self.end_date_label = QLabel(self._end_date.isoformat())
        self.start_time_edit = QTimeEdit(QTime(start_dt.hour, start_dt.minute))
        self.start_time_edit.setDisplayFormat("HH:mm")
        self.end_time_edit = QTimeEdit(QTime(end_dt.hour, end_dt.minute))
        self.end_time_edit.setDisplayFormat("HH:mm")

        self.efficiency_combo = self._build_score_combo()
        self.state_combo = self._build_score_combo()
        self.mood_combo = self._build_score_combo()
        self.note_input = QTextEdit()
        self.note_input.setFixedHeight(70)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("事件方块"))
        row1.addWidget(self.block_combo, stretch=2)
        row1.addWidget(self.inline_block_btn)
        row1.addWidget(QLabel("效率"))
        row1.addWidget(self.efficiency_combo)
        row1.addWidget(QLabel("状态"))
        row1.addWidget(self.state_combo)
        row1.addWidget(QLabel("心情"))
        row1.addWidget(self.mood_combo)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("开始日期"))
        row2.addWidget(self.start_date_label)
        row2.addWidget(QLabel("开始时间"))
        row2.addWidget(self.start_time_edit, stretch=1)
        row2.addWidget(QLabel("结束日期"))
        row2.addWidget(self.end_date_label)
        row2.addWidget(QLabel("结束时间"))
        row2.addWidget(self.end_time_edit, stretch=1)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("备注"))
        row3.addWidget(self.note_input, stretch=1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.on_accept)
        self.buttons.rejected.connect(self.reject)
        if self._record_id is not None:
            self.delete_btn = QPushButton("删除")
            self.delete_btn.clicked.connect(self.on_delete)
            self.buttons.addButton(self.delete_btn, QDialogButtonBox.ButtonRole.DestructiveRole)

        root = QVBoxLayout(self)
        root.addLayout(row1)
        root.addLayout(row2)
        root.addLayout(row3)
        root.addWidget(self.buttons)

        if self._undo_stack is not None:
            filt = UndoRedoShortcutFilter(self._undo_stack, self, self)
            self.note_input.installEventFilter(filt)

        self.refresh_blocks()
        if self._record_id is not None:
            self.load_existing_record(self._record_id)

    @staticmethod
    def _build_score_combo() -> QComboBox:
        combo = QComboBox()
        combo.addItem(SCORE_NONE, None)
        for score in range(1, 6):
            combo.addItem(str(score), score)
        combo.setCurrentIndex(0)
        return combo

    @staticmethod
    def _set_score_combo(combo: QComboBox, value: int | None) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setCurrentIndex(0)

    @property
    def deleted(self) -> bool:
        return self._deleted

    def refresh_blocks(self) -> None:
        current = self.block_combo.currentData()
        self.block_combo.blockSignals(True)
        self.block_combo.clear()
        with session_scope() as session:
            blocks = list_blocks(session, include_inactive=True)
        for b in blocks:
            suffix = "" if b.is_active else "（已停用）"
            self.block_combo.addItem(f"{b.name}{suffix}", b.id)
        if current is not None:
            idx = self.block_combo.findData(current)
            if idx >= 0:
                self.block_combo.setCurrentIndex(idx)
        self.block_combo.blockSignals(False)

    def inline_create_block(self) -> None:
        name, ok = QInputDialog.getText(self, "新增方块", "方块名称")
        if not ok or not name.strip():
            return
        category_text, ok = QInputDialog.getItem(
            self,
            "新增方块",
            "事件类型",
            [CATEGORY_LABEL_MAP[BLOCK_CATEGORY_WORK], CATEGORY_LABEL_MAP[BLOCK_CATEGORY_REST]],
            0,
            False,
        )
        if not ok or not category_text.strip():
            return
        category = BLOCK_CATEGORY_WORK if category_text == CATEGORY_LABEL_MAP[BLOCK_CATEGORY_WORK] else BLOCK_CATEGORY_REST
        try:
            with session_scope() as session:
                block = create_block(session, name=name, category=category)
                block_id = block.id
        except IntegrityError:
            QMessageBox.warning(self, "提示", "方块名称已存在。")
            return
        self.refresh_blocks()
        idx = self.block_combo.findData(block_id)
        if idx >= 0:
            self.block_combo.setCurrentIndex(idx)

    def load_existing_record(self, record_id: int) -> None:
        with session_scope() as session:
            rec = get_record_by_id(session, record_id)
        if rec is None:
            QMessageBox.warning(self, "提示", "记录不存在或已删除。")
            self.reject()
            return
        idx = self.block_combo.findData(rec.block_id)
        if idx >= 0:
            self.block_combo.setCurrentIndex(idx)
        self._start_date = rec.start_time.date()
        self._end_date = rec.end_time.date()
        self.start_date_label.setText(self._start_date.isoformat())
        self.end_date_label.setText(self._end_date.isoformat())
        self.start_time_edit.setTime(QTime(rec.start_time.hour, rec.start_time.minute))
        self.end_time_edit.setTime(QTime(rec.end_time.hour, rec.end_time.minute))
        self._set_score_combo(self.efficiency_combo, rec.efficiency_score)
        self._set_score_combo(self.state_combo, rec.state_score)
        self._set_score_combo(self.mood_combo, rec.mood_score)
        self.note_input.setPlainText(rec.note or "")
        self._initial_snapshot = snapshot_from_record(rec)

    def on_delete(self) -> None:
        if self._record_id is None:
            return
        snap: RecordUndoSnapshot | None = None
        with session_scope() as session:
            rec = get_record_by_id(session, self._record_id)
            if rec is None:
                return
            snap = snapshot_from_record(rec)
            rid = rec.id
            delete_record(session, self._record_id)
            recalculate_points_for_record(session, record_id=rid, new_record=None)
        if snap is not None and self._undo_stack is not None:
            self._undo_stack.push(DeleteRecordCmd(snap))
        self._deleted = True
        self.accept()

    def on_accept(self) -> None:
        block_id = self.block_combo.currentData()
        if block_id is None:
            QMessageBox.warning(self, "提示", "请先选择事件方块。")
            return
        start_time = self.start_time_edit.time().toPython()
        end_time = self.end_time_edit.time().toPython()
        start = datetime.combine(self._start_date, start_time)
        end = datetime.combine(self._end_date, end_time)
        efficiency = self.efficiency_combo.currentData()
        state = self.state_combo.currentData()
        mood = self.mood_combo.currentData()
        note = self.note_input.toPlainText().strip() or None
        try:
            validate_time_range(start, end)
            validate_scores(efficiency, state, mood)
        except ValueError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        new_snap: RecordUndoSnapshot | None = None
        new_id: int | None = None
        with session_scope() as session:
            if self._record_id is None:
                rec = create_record(session, block_id, start, end, efficiency, state, mood, None, note)
                apply_points_for_new_record(session, rec)
                new_snap = snapshot_from_record(rec)
                new_id = rec.id
            else:
                rec = update_record(session, self._record_id, block_id, start, end, efficiency, state, mood, None, note)
                recalculate_points_for_record(session, record_id=rec.id, new_record=rec)
                new_snap = snapshot_from_record(rec)
        if self._undo_stack is not None and new_snap is not None:
            if self._record_id is None and new_id is not None:
                self._undo_stack.push(CreateRecordCmd(new_snap, new_id))
            elif self._record_id is not None and self._initial_snapshot is not None:
                self._undo_stack.push(UpdateRecordCmd(self._record_id, self._initial_snapshot, new_snap))
        self.accept()


class SleepEditorDialog(QDialog):
    """Dedicated sleep editor with cross-day friendly datetime inputs."""

    def __init__(
        self,
        start_dt: datetime,
        end_dt: datetime,
        sleep_block_id: int,
        record_id: int | None = None,
        parent: QWidget | None = None,
        undo_stack: UndoStack | None = None,
    ) -> None:
        super().__init__(parent)
        self._record_id = record_id
        self._sleep_block_id = sleep_block_id
        self._deleted = False
        self._undo_stack = undo_stack
        self._initial_snapshot: RecordUndoSnapshot | None = None
        self.setWindowTitle("编辑睡眠" if record_id is not None else "记录睡眠")
        self.resize(620, 260)

        self.start_dt = QDateTimeEdit(QDateTime(start_dt))
        self.start_dt.setCalendarPopup(True)
        self.start_dt.setDisplayFormat("yyyy-MM-dd HH:mm")

        self.end_dt = QDateTimeEdit(QDateTime(end_dt))
        self.end_dt.setCalendarPopup(True)
        self.end_dt.setDisplayFormat("yyyy-MM-dd HH:mm")

        self.efficiency_combo = RecordEditorDialog._build_score_combo()
        self.state_combo = RecordEditorDialog._build_score_combo()
        self.mood_combo = RecordEditorDialog._build_score_combo()
        self.note_input = QTextEdit()
        self.note_input.setFixedHeight(64)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("入睡时间"))
        row1.addWidget(self.start_dt, stretch=2)
        row1.addWidget(QLabel("起床时间"))
        row1.addWidget(self.end_dt, stretch=2)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("效率"))
        row2.addWidget(self.efficiency_combo)
        row2.addWidget(QLabel("状态"))
        row2.addWidget(self.state_combo)
        row2.addWidget(QLabel("心情"))
        row2.addWidget(self.mood_combo)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("备注"))
        row3.addWidget(self.note_input, stretch=1)

        hint = QLabel("提示：睡眠可跨天记录（例如 23:40 -> 次日 07:30）。")
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.on_accept)
        self.buttons.rejected.connect(self.reject)
        if self._record_id is not None:
            self.delete_btn = QPushButton("删除")
            self.delete_btn.clicked.connect(self.on_delete)
            self.buttons.addButton(self.delete_btn, QDialogButtonBox.ButtonRole.DestructiveRole)

        root = QVBoxLayout(self)
        root.addWidget(hint)
        root.addLayout(row1)
        root.addLayout(row2)
        root.addLayout(row3)
        root.addWidget(self.buttons)

        if self._undo_stack is not None:
            filt = UndoRedoShortcutFilter(self._undo_stack, self, self)
            self.note_input.installEventFilter(filt)

        if self._record_id is not None:
            self.load_existing_record(self._record_id)

    def load_existing_record(self, record_id: int) -> None:
        with session_scope() as session:
            rec = get_record_by_id(session, record_id)
        if rec is None:
            QMessageBox.warning(self, "提示", "睡眠记录不存在或已删除。")
            self.reject()
            return
        self.start_dt.setDateTime(QDateTime(rec.start_time))
        self.end_dt.setDateTime(QDateTime(rec.end_time))
        RecordEditorDialog._set_score_combo(self.efficiency_combo, rec.efficiency_score)
        RecordEditorDialog._set_score_combo(self.state_combo, rec.state_score)
        RecordEditorDialog._set_score_combo(self.mood_combo, rec.mood_score)
        self.note_input.setPlainText(rec.note or "")
        self._initial_snapshot = snapshot_from_record(rec)

    def on_delete(self) -> None:
        if self._record_id is None:
            return
        snap: RecordUndoSnapshot | None = None
        with session_scope() as session:
            rec = get_record_by_id(session, self._record_id)
            if rec is None:
                return
            snap = snapshot_from_record(rec)
            rid = rec.id
            delete_record(session, self._record_id)
            recalculate_points_for_record(session, record_id=rid, new_record=None)
        if snap is not None and self._undo_stack is not None:
            self._undo_stack.push(DeleteRecordCmd(snap))
        self._deleted = True
        self.accept()

    def on_accept(self) -> None:
        start = self.start_dt.dateTime().toPython()
        end = self.end_dt.dateTime().toPython()
        efficiency = self.efficiency_combo.currentData()
        state = self.state_combo.currentData()
        mood = self.mood_combo.currentData()
        note = self.note_input.toPlainText().strip() or None
        try:
            validate_time_range(start, end)
            validate_scores(efficiency, state, mood)
        except ValueError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        new_snap: RecordUndoSnapshot | None = None
        new_id: int | None = None
        with session_scope() as session:
            if self._record_id is None:
                rec = create_record(session, self._sleep_block_id, start, end, efficiency, state, mood, None, note)
                apply_points_for_new_record(session, rec)
                new_snap = snapshot_from_record(rec)
                new_id = rec.id
            else:
                rec = update_record(
                    session,
                    self._record_id,
                    self._sleep_block_id,
                    start,
                    end,
                    efficiency,
                    state,
                    mood,
                    None,
                    note,
                )
                recalculate_points_for_record(session, record_id=rec.id, new_record=rec)
                new_snap = snapshot_from_record(rec)
        if self._undo_stack is not None and new_snap is not None:
            if self._record_id is None and new_id is not None:
                self._undo_stack.push(CreateRecordCmd(new_snap, new_id))
            elif self._record_id is not None and self._initial_snapshot is not None:
                self._undo_stack.push(UpdateRecordCmd(self._record_id, self._initial_snapshot, new_snap))
        self.accept()


class RecordPage(QWidget):
    def __init__(
        self,
        on_data_changed: Callable[[], None],
        parent: QWidget | None = None,
        undo_stack: UndoStack | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_data_changed = on_data_changed
        self._week_start = self._get_week_start(date.today())
        self._undo_stack = undo_stack

        self.week_title = QLabel()
        self.prev_week_btn = QPushButton("上一周")
        self.next_week_btn = QPushButton("下一周")
        self.today_week_btn = QPushButton("回到本周")
        self.prev_week_btn.clicked.connect(self.show_prev_week)
        self.next_week_btn.clicked.connect(self.show_next_week)
        self.today_week_btn.clicked.connect(self.show_current_week)

        self.ai_toggle = QCheckBox("AI 自动补全")
        self.ai_toggle.setChecked(self._load_ai_enabled())
        self.ai_toggle.toggled.connect(self._on_ai_toggled)

        week_controls = QHBoxLayout()
        week_controls.addWidget(self.prev_week_btn)
        week_controls.addWidget(self.next_week_btn)
        week_controls.addWidget(self.today_week_btn)
        week_controls.addWidget(self.week_title)
        week_controls.addStretch()
        week_controls.addWidget(self.ai_toggle)

        self.week_timeline = WeekTimelineWidget(slot_minutes=5)
        self.week_timeline.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.week_timeline.customContextMenuRequested.connect(self.open_timeline_menu)
        self.week_timeline.recordMoved.connect(self._on_records_moved)
        self.week_timeline.selectionChanged.connect(self._on_selection_for_ai)

        self._ai_suggestion: list[dict] | None = None  # list of {block_name, start_dt, end_dt, ...}

        self._tab_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Tab), self)
        self._tab_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._tab_shortcut.activated.connect(self._on_tab_accept_ai)

        self.sleep_buttons: list[QPushButton] = []
        sleep_row = QHBoxLayout()
        sleep_row.setSpacing(6)
        # Align sleep buttons with day columns in timeline.
        sleep_row.setContentsMargins(self.week_timeline.axis_width, 0, self.week_timeline.right_padding, 0)
        for i in range(7):
            btn = QPushButton("睡眠")
            btn.setObjectName("sleepButton")
            btn.clicked.connect(lambda checked=False, day_idx=i: self.open_sleep_for_day(day_idx))
            sleep_row.addWidget(btn, stretch=1)
            self.sleep_buttons.append(btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)
        root.addLayout(week_controls)
        root.addLayout(sleep_row)
        root.addWidget(self.week_timeline, stretch=1)

        self.refresh()

    @staticmethod
    def _get_week_start(target_day: date) -> date:
        return target_day - timedelta(days=target_day.weekday())

    def _refresh_week_title(self) -> None:
        end_day = self._week_start + timedelta(days=6)
        self.week_title.setText(f"{self._week_start.isoformat()} ~ {end_day.isoformat()}")

    def show_prev_week(self) -> None:
        self._week_start -= timedelta(days=7)
        self.refresh()

    def show_next_week(self) -> None:
        self._week_start += timedelta(days=7)
        self.refresh()

    def show_current_week(self) -> None:
        self._week_start = self._get_week_start(date.today())
        self.refresh()

    # ── AI suggestion ──

    @staticmethod
    def _load_ai_enabled() -> bool:
        try:
            with session_scope() as session:
                from ..storage.repositories import get_ai_settings
                return get_ai_settings(session).enabled
        except Exception:
            return False

    def _on_ai_toggled(self, checked: bool) -> None:
        try:
            with session_scope() as session:
                from ..storage.repositories import get_ai_settings, save_ai_settings
                s = get_ai_settings(session)
                save_ai_settings(session, enabled=checked, api_url=s.api_url,
                                 api_key=s.api_key, model=s.model, system_prompt=s.system_prompt)
        except Exception:
            pass

    def _on_selection_for_ai(self, start_dt: datetime, end_dt: datetime) -> None:
        """Trigger AI suggestion when user finishes a time-range selection."""
        if not self.ai_toggle.isChecked():
            return
        self.week_timeline.show_ai_thinking()
        self._ai_suggestion = None
        QTimer.singleShot(300, lambda: self._request_ai_suggestion(start_dt, end_dt))

    def _request_ai_suggestion(self, start_dt: datetime, end_dt: datetime) -> None:
        """Load DB context, then call API and display result."""
        from ..services.ai_service import AIContext, build_ai_context, call_ai_api

        ctx: AIContext | None = None
        try:
            with session_scope() as session:
                ctx = build_ai_context(session, start_dt, end_dt)
        except Exception:
            pass
        if ctx is None:
            self.week_timeline.clear_ai_suggestion()
            return

        try:
            result = call_ai_api(ctx, start_dt, end_dt)
        except Exception:
            result = None

        if result is not None and hasattr(result, 'events') and result.events:
            events_data: list[dict] = []
            for ev in result.events:
                events_data.append({
                    "block_name": ev.block_name,
                    "start_dt": start_dt + timedelta(minutes=ev.start_offset_minutes),
                    "end_dt": start_dt + timedelta(minutes=ev.end_offset_minutes),
                    "efficiency_score": ev.efficiency_score,
                    "state_score": ev.state_score,
                    "mood_score": ev.mood_score,
                    "note": ev.note,
                })
            self._ai_suggestion = events_data
            self.week_timeline.show_ai_suggestion(events_data)
        else:
            self.week_timeline.clear_ai_suggestion()

    def _on_tab_accept_ai(self) -> None:
        """Tab key: silently accept AI suggestion if available."""
        if self._ai_suggestion is not None:
            self._accept_ai_suggestion()

    def _accept_ai_suggestion(self) -> None:
        """Create records from the AI suggestion (multi-event batch)."""
        if self._ai_suggestion is None:
            QMessageBox.information(self, "提示", "没有AI建议可接受。")
            return
        events_data = self._ai_suggestion

        # Resolve block IDs
        with session_scope() as session:
            blocks = list_blocks(session, include_inactive=True)
        block_name_to_id: dict[str, int] = {b.name: b.id for b in blocks}

        missing = [ev["block_name"] for ev in events_data if ev["block_name"] not in block_name_to_id]
        if missing:
            QMessageBox.warning(self, "提示", f"未找到方块：{', '.join(missing)}，请先创建。")
            return

        # Batch create all events with undo support
        commands: list = []
        new_ids: list[int] = []
        with session_scope() as session:
            for ev in events_data:
                bid = block_name_to_id[ev["block_name"]]
                rec = create_record(
                    session, bid, ev["start_dt"], ev["end_dt"],
                    ev.get("efficiency_score"), ev.get("state_score"), ev.get("mood_score"),
                    None, ev.get("note"),
                )
                apply_points_for_new_record(session, rec)
                snap = snapshot_from_record(rec)
                commands.append(CreateRecordCmd(snap, rec.id))
                new_ids.append(rec.id)
        for cmd in commands:
            if self._undo_stack is not None:
                self._undo_stack.push(cmd)

        self.week_timeline.clear_ai_suggestion()
        self.week_timeline.clear_selection()
        self._ai_suggestion = None
        self.refresh()
        self._on_data_changed()

    def open_timeline_menu(self, pos) -> None:  # type: ignore[no-untyped-def]
        selected = self.week_timeline.selected_range()
        if selected is None:
            # Fallback: check if right-clicked on a record, use its time range
            hit_ids = self.week_timeline._records_at_point(pos)
            if hit_ids:
                for rec_data in self.week_timeline._records:
                    if rec_data.id == hit_ids[0]:
                        selected = (rec_data.start_time, rec_data.end_time)
                        break
        if selected is None:
            QMessageBox.information(self, "提示", "请先在时间轴框选一个时间范围，或右键点击已有事件。")
            return
        start_dt, end_dt = selected
        with session_scope() as session:
            hit_records = list_records_in_range(session, start_dt, end_dt)
            blocks = list_blocks(session, include_inactive=True)
        block_map = {b.id: b.name for b in blocks}

        menu = QMenu(self)
        if self._ai_suggestion is not None:
            names = " → ".join(ev["block_name"] for ev in self._ai_suggestion)
            ai_action = menu.addAction(f"🤖 接受AI建议：{names}")
        else:
            ai_action = None
        new_action = menu.addAction("新建事件")
        delete_all_action = menu.addAction(f"全部删除（框选范围内共 {len(hit_records)} 条）")
        delete_all_action.setEnabled(bool(hit_records))
        undo_action = menu.addAction("撤销 (Ctrl+Z)")
        undo_action.setEnabled(bool(self._undo_stack and self._undo_stack.can_undo()))
        redo_action = menu.addAction("重做 (Ctrl+Y)")
        redo_action.setEnabled(bool(self._undo_stack and self._undo_stack.can_redo()))
        menu.addSeparator()
        action_to_record_id: dict[QAction, int] = {}
        if hit_records:
            for rec in hit_records:
                name = block_map.get(rec.block_id, f"#{rec.block_id}")
                text = f"编辑: {name}  {rec.start_time.strftime('%m-%d %H:%M')} ~ {rec.end_time.strftime('%H:%M')}"
                action = menu.addAction(text)
                action_to_record_id[action] = rec.id

        chosen = menu.exec(self.week_timeline.mapToGlobal(pos))
        if chosen is None:
            return
        if ai_action is not None and chosen == ai_action:
            self._accept_ai_suggestion()
            return
        if chosen == new_action:
            self.open_editor(start_dt, end_dt, record_id=None)
            return
        if chosen == delete_all_action:
            self._bulk_delete_records_in_selection(hit_records)
            return
        if chosen == undo_action:
            self._menu_undo()
            return
        if chosen == redo_action:
            self._menu_redo()
            return
        record_id = action_to_record_id.get(chosen)
        if record_id is not None:
            with session_scope() as session:
                rec = get_record_by_id(session, record_id)
                blocks = {b.id: b.name for b in list_blocks(session, include_inactive=True)}
            if rec is not None and blocks.get(rec.block_id) == "睡觉":
                self.open_sleep_editor(start_dt, end_dt, record_id=record_id)
            else:
                self.open_editor(start_dt, end_dt, record_id=record_id)

    def _menu_undo(self) -> None:
        if not self._undo_stack:
            return
        try:
            self._undo_stack.undo()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "撤销失败", str(exc))

    def _menu_redo(self) -> None:
        if not self._undo_stack:
            return
        try:
            self._undo_stack.redo()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "重做失败", str(exc))

    def _bulk_delete_records_in_selection(self, hit_records: list[ActivityRecord]) -> None:
        if not hit_records:
            return
        confirm = QMessageBox.question(
            self,
            "确认全部删除",
            f"将删除框选范围内重叠的 {len(hit_records)} 条记录（含睡眠）。此操作用于调试，可用 Ctrl+Z 或多步撤销恢复。\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        record_ids = [rec.id for rec in hit_records]
        with session_scope() as session:
            batch: list[RecordUndoSnapshot] = []
            for rid in record_ids:
                rec = get_record_by_id(session, rid)
                if rec is None:
                    continue
                batch.append(snapshot_from_record(rec))
            if not batch:
                QMessageBox.information(self, "提示", "没有可删除的记录。")
                return
            for rid in record_ids:
                rec = get_record_by_id(session, rid)
                if rec is None:
                    continue
                delete_record(session, rid)
                recalculate_points_for_record(session, record_id=rid, new_record=None)
        if self._undo_stack is not None:
            self._undo_stack.push(BulkDeleteCmd(batch))
        self.refresh()
        self._on_data_changed()

    def open_editor(self, start_dt: datetime, end_dt: datetime, record_id: int | None) -> None:
        dlg = RecordEditorDialog(
            start_dt=start_dt,
            end_dt=end_dt,
            record_id=record_id,
            parent=self,
            undo_stack=self._undo_stack,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self._on_data_changed()

    def _ensure_sleep_block(self) -> int:
        with session_scope() as session:
            blocks = list_blocks(session, include_inactive=True)
            for b in blocks:
                if b.name == "睡觉":
                    return b.id
            block = create_block(session, name="睡觉", category=BLOCK_CATEGORY_REST)
            return block.id

    def open_sleep_for_day(self, day_idx: int) -> None:
        target_day = self._week_start + timedelta(days=day_idx)
        default_start = datetime.combine(target_day - timedelta(days=1), time(hour=23, minute=0))
        default_end = datetime.combine(target_day, time(hour=7, minute=30))
        self.open_sleep_editor(default_start, default_end, record_id=None)

    def open_sleep_editor(self, start_dt: datetime, end_dt: datetime, record_id: int | None) -> None:
        sleep_block_id = self._ensure_sleep_block()
        dlg = SleepEditorDialog(
            start_dt=start_dt,
            end_dt=end_dt,
            sleep_block_id=sleep_block_id,
            record_id=record_id,
            parent=self,
            undo_stack=self._undo_stack,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self._on_data_changed()

    def _on_records_moved(self, moves: list) -> None:
        """Handle recordMoved signal: update DB and push undo commands.

        moves: list of (record_id, new_start_time, new_end_time)
        """
        commands: list[UpdateRecordCmd] = []
        with session_scope() as session:
            for record_id, new_start, new_end in moves:
                rec = get_record_by_id(session, record_id)
                if rec is None:
                    continue
                before = snapshot_from_record(rec)
                after = RecordUndoSnapshot(
                    block_id=rec.block_id,
                    start_time=new_start,
                    end_time=new_end,
                    efficiency_score=rec.efficiency_score,
                    state_score=rec.state_score,
                    mood_score=rec.mood_score,
                    tags=rec.tags,
                    note=rec.note,
                )
                update_record(
                    session,
                    record_id,
                    block_id=rec.block_id,
                    start_time=new_start,
                    end_time=new_end,
                    efficiency_score=rec.efficiency_score,
                    state_score=rec.state_score,
                    mood_score=rec.mood_score,
                    tags=rec.tags,
                    note=rec.note,
                )
                commands.append(UpdateRecordCmd(record_id, before, after))
        for cmd in commands:
            if self._undo_stack is not None:
                self._undo_stack.push(cmd)
        self.refresh()
        self._on_data_changed()

    def refresh(self) -> None:
        self._refresh_week_title()
        for i, btn in enumerate(self.sleep_buttons):
            day = self._week_start + timedelta(days=i)
            btn.setText(f"{day.month:02d}-{day.day:02d} 前夜睡眠")
        self.week_timeline.set_week_start(self._week_start)
        range_start = datetime.combine(self._week_start, time.min)
        range_end = datetime.combine(self._week_start + timedelta(days=7), time.min)
        with session_scope() as session:
            week_records = list_records_in_range(session, range_start, range_end)
            blocks = list_blocks(session, include_inactive=True)
            block_map = {b.id: b.name for b in blocks}
            color_map = {b.id: b.color for b in blocks}
        self.week_timeline.set_records(week_records, block_map, color_map)
