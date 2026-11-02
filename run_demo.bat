@echo off
rem Starts the AI Firewall API (port 8000) and the Security Console (port 3001), then opens the console.
rem Close the two black windows to stop everything.
cd /d %~dp0
rem Session state (exposure/taint, values the user typed, canaries) in SQLite: survives an API restart mid-demo.
set FIREWALL_STATE_DB=%~dp0data\firewall_state.sqlite
start "AI Firewall API" cmd /k ".venv\Scripts\python.exe -m uvicorn api.main:app --port 8000"
start "Security Console" cmd /k "cd frontend\security-console && npm run dev"
echo Waiting for the API to load the model (can take a minute or more)...
:wait_api
powershell -NoProfile -Command "try { (Invoke-WebRequest http://127.0.0.1:8000/docs -UseBasicParsing -TimeoutSec 2) | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  timeout /t 3 >nul
  goto wait_api
)
echo API is ready.
start http://127.0.0.1:3001
