@echo off
REM ProjectSync AI - one-time setup
REM Double-click this file (or run it in PowerShell/CMD) from inside the
REM ProjectSync-AI folder. It creates the virtual environment, installs
REM all backend dependencies, creates your .env file, and starts the server.

echo ============================================
echo   ProjectSync AI - First-time setup
echo ============================================

cd /d "%~dp0"

echo.
echo [1/5] Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo.
    echo ERROR: Could not create virtual environment. Is Python installed and on PATH?
    echo Try running: python --version
    pause
    exit /b 1
)

echo.
echo [2/5] Activating virtual environment...
call venv\Scripts\activate.bat

echo.
echo [3/5] Installing backend dependencies (this can take a minute)...
cd backend
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: pip install failed. Check the messages above.
    pause
    exit /b 1
)

echo.
echo [4/5] Creating .env file from template...
if not exist ".env" (
    copy .env.example .env
) else (
    echo .env already exists, skipping.
)

echo.
echo [5/5] Starting the backend server...
echo Once it's running, open http://127.0.0.1:8000/health and http://127.0.0.1:8000/docs in your browser.
echo Press CTRL+C in this window to stop the server.
echo.
python -m uvicorn main:app --reload

pause
