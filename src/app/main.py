"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QFont, QIcon  # type: ignore[import]
from PySide6.QtWidgets import QApplication  # type: ignore[import]

from .storage.database import get_default_db_path, init_db
from .ui.main_window import MainWindow
from .ui.theme import app_stylesheet


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(app_stylesheet())
    icon_path = Path.cwd() / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    db_path = get_default_db_path()
    init_db(db_path)
    window = MainWindow(db_path=db_path)
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
