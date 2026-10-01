@echo off
setlocal
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Run install.cmd first.
  exit /b 2
)
"%~dp0.venv\Scripts\python.exe" -m releasecraft %*
exit /b %errorlevel%
