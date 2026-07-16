@echo off
REM TrustTrace — Windows quickstart. Double-click or run from a terminal.
echo ============================================================
echo TrustTrace Windows quickstart
echo ============================================================
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found on PATH. Install Python 3.11+ from python.org.
  pause & exit /b 1
)
echo [1/3] Creating virtual environment (.venv) ...
if not exist ".venv" ( python -m venv .venv )
echo [2/3] Installing dependencies ...
call .venv\Scripts\python.exe -m pip install --upgrade pip
call .venv\Scripts\pip.exe install -r requirements.txt
echo [3/3] Running tests (expect 78 passed) ...
call .venv\Scripts\python.exe -m pytest tests\ -q
echo.
echo ============================================================
echo Ready. Next:
echo   Backend  : .venv\Scripts\uvicorn backend.main:app --reload --port 8000
echo              then open http://127.0.0.1:8000/docs
echo   Dashboard: cd dashboard ^&^& npm install ^&^& npm run dev
echo   Mobile   : cd mobile ^&^& npm install ^&^& npx expo start
echo   Guide    : README_WINDOWS.md   Real models: docs\REAL_MODELS_SETUP.md
echo ============================================================
pause
