# Windows Packaging Guide

## 1) Prepare environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pyinstaller
```

## 2) Build executable

```powershell
pyinstaller --name Insight --windowed --onefile src/app/main.py
```

Output executable:

- `dist/Insight.exe`

## 3) One-command build

You can also run:

```powershell
.\scripts\build.ps1
```

## 4) Smoke test checklist

- App opens successfully.
- Can create event block.
- Can create overlapping records.
- Stats page renders 7-day and 30-day charts.
- App restart keeps data.
