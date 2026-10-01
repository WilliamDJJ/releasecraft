@echo off
setlocal
where pyw >nul 2>nul
if errorlevel 1 goto use_pythonw
start "" pyw -3 "%~dp0Releasecraft.pyw" %*
exit /b 0
:use_pythonw
where pythonw >nul 2>nul
if errorlevel 1 goto missing_python
start "" pythonw "%~dp0Releasecraft.pyw" %*
exit /b 0
:missing_python
echo Python 3.11+ with Tcl/Tk is required. Install Python, then double-click this launcher again.
pause
exit /b 2
