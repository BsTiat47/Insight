param(
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

Write-Host "Creating virtual environment..."
& $PythonExe -m venv .venv

Write-Host "Activating virtual environment..."
. .\.venv\Scripts\Activate.ps1

Write-Host "Installing dependencies..."
pip install -r requirements.txt
pip install pyinstaller

Write-Host "Building executable..."
$iconArg = @()
if (Test-Path "icon.ico") {
    $iconArg = @("--icon", "icon.ico")
}
elseif (Test-Path "icon.png") {
    # PyInstaller on Windows prefers .ico; PNG may work depending on toolchain version.
    $iconArg = @("--icon", "icon.png")
}
& pyinstaller @iconArg --name Insight --windowed --onefile run_insight.py

Write-Host "Build complete. Output: dist/Insight.exe"
