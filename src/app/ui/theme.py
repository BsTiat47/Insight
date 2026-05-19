"""UI theme helpers for Insight."""

from __future__ import annotations


def app_stylesheet() -> str:
    return """
QWidget {
    background: #F4F7FB;
    color: #1F2937;
    font-size: 13px;
}

QMainWindow {
    background: #F4F7FB;
}

QLabel {
    color: #374151;
}

QListWidget {
    background: #EEF3FB;
    border: 1px solid #D9E2F2;
    border-radius: 12px;
    padding: 8px;
    outline: none;
}

QListWidget::item {
    border-radius: 10px;
    padding: 10px 12px;
    margin: 2px 0;
}

QListWidget::item:selected {
    background: #2F6FED;
    color: #FFFFFF;
}

QListWidget::item:hover:!selected {
    background: #DDE8FF;
}

QPushButton {
    background: #2F6FED;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 6px 12px;
}

QPushButton:hover {
    background: #245EDD;
}

QPushButton:pressed {
    background: #1E4FB8;
}

QPushButton:disabled {
    background: #AABAD6;
    color: #ECF1FA;
}

QPushButton#sleepButton {
    background: #E5E7EB;
    color: #374151;
}

QPushButton#sleepButton:hover {
    background: #D1D5DB;
}

QPushButton#sleepButton:pressed {
    background: #C4CAD3;
}

QPushButton#dangerButton {
    background: #E11D48;
}

QPushButton#dangerButton:hover {
    background: #BE123C;
}

QComboBox, QLineEdit, QDateTimeEdit, QTimeEdit, QSpinBox, QTextEdit {
    background: #FFFFFF;
    border: 1px solid #D3DCEB;
    border-radius: 8px;
    padding: 5px 8px;
}

QComboBox:focus, QLineEdit:focus, QDateTimeEdit:focus, QTimeEdit:focus, QSpinBox:focus, QTextEdit:focus {
    border: 1px solid #2F6FED;
}

QComboBox::drop-down {
    border: none;
    width: 22px;
}

QTableWidget {
    background: #FFFFFF;
    border: 1px solid #D3DCEB;
    border-radius: 10px;
    gridline-color: #EEF2F8;
    selection-background-color: #DCE8FF;
    selection-color: #1F2937;
}

QHeaderView::section {
    background: #F2F6FE;
    color: #334155;
    border: none;
    border-bottom: 1px solid #DCE5F2;
    padding: 8px 6px;
    font-weight: 600;
}

QMenu {
    background: #FFFFFF;
    border: 1px solid #D3DCEB;
    border-radius: 10px;
    padding: 6px;
}

QMenu::item {
    padding: 8px 12px;
    border-radius: 8px;
}

QMenu::item:selected {
    background: #E8F0FF;
}

QDialog {
    background: #F8FAFD;
}

QSplitter::handle {
    background: #DCE5F2;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background: #C7D3E8;
    border-radius: 5px;
    min-height: 24px;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QToolTip {
    background: #1F2937;
    color: #F9FAFB;
    border: 0;
    border-radius: 6px;
    padding: 6px 8px;
}
"""
