"""Executable entry for PyInstaller (project root must be on sys.path)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.main import main

if __name__ == "__main__":
    raise SystemExit(main())
