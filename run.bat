@echo off
cd /d "%~dp0"
if not exist .venv (
  echo Membuat virtual env...
  python -m venv .venv
  call .venv\Scripts\activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate
)
if not exist .env copy .env.example .env >nul
start "" http://localhost:8765
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
pause
