"""Qt helpers so Ctrl+Z / Ctrl+Y trigger app-wide undo/redo first."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QMessageBox, QWidget

from ..services.undo_stack import UndoStack


class UndoRedoShortcutFilter(QObject):
    """When focus is in a text field, prefer global undo/redo if available."""

    def __init__(self, undo_stack: UndoStack, parent_widget: QWidget, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._undo_stack = undo_stack
        self._parent_widget = parent_widget

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.KeyPress:
            if event.matches(QKeySequence.StandardKey.Undo):
                if self._undo_stack.can_undo():
                    try:
                        self._undo_stack.undo()
                    except Exception as exc:  # noqa: BLE001
                        QMessageBox.warning(self._parent_widget, "撤销失败", str(exc))
                    return True
                return False
            if event.matches(QKeySequence.StandardKey.Redo):
                if self._undo_stack.can_redo():
                    try:
                        self._undo_stack.redo()
                    except Exception as exc:  # noqa: BLE001
                        QMessageBox.warning(self._parent_widget, "重做失败", str(exc))
                    return True
                return False
        return False
