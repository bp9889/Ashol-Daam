@echo off
cd /d "%~dp0"
call ..\.venv\Scripts\activate
echo Checking for updates to the app's parts...
pip install -q --disable-pip-version-check -r requirements-local.txt
start http://localhost:8000
uvicorn app.main:app
