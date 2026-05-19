@echo off
setlocal

set "PROJECT_DIR=%~dp0"
pushd "%PROJECT_DIR%"

if exist ".venv\Scripts\pythonw.exe" (
  ".venv\Scripts\pythonw.exe" -m src.app.main
  popd
  endlocal
  exit /b 0
)

if not exist ".venv\Scripts\python.exe" (
  echo [Insight] 未找到 .venv\Scripts\pythonw.exe / python.exe
  echo 请先在项目目录安装依赖后再启动。
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m src.app.main
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo.
  echo [Insight] 进程退出码: %EXITCODE%
  pause
)

popd
endlocal
