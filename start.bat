@echo off
cd /d "%~dp0"
call ..\.venv\Scripts\activate
echo Checking for updates to the app's parts...
pip install -q --disable-pip-version-check -r requirements-local.txt
rem If an older copy is still running, it keeps the port busy and you'd see old code.
netstat -ano | findstr ":8000 " | findstr LISTENING >nul && (
  echo.
  echo Asol Dam is already running in another window. Close that window first, then run this again.
  pause
  exit /b
)
start http://localhost:8000
rem --reload: picks up code changes by itself, no restart needed
uvicorn app.main:app --reload
