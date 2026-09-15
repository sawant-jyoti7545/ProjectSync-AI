@echo off
REM ProjectSync AI - everyday startup
REM Use this AFTER you've already run setup.bat once.
REM Double-click this file to activate the existing environment and start the server.

cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo Virtual environment not found. Please run setup.bat first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
cd backend
echo Starting ProjectSync AI backend...
echo Open http://127.0.0.1:8000/health and http://127.0.0.1:8000/docs once it's running.
echo Press CTRL+C to stop.
echo.
python -m uvicorn main:app --reload

pause
