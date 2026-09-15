@echo off
cd /d "%~dp0"

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0ClaudeGauge.pyw"
    exit /b
)

where python >nul 2>nul
if %errorlevel%==0 (
    start "" python "%~dp0ClaudeGauge.pyw"
    exit /b
)

echo.
echo   Python not found / Python ne nayden.
echo   https://www.python.org/downloads/
echo   Set checkbox: Add python.exe to PATH
echo.
pause
