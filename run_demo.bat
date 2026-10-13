@echo off
rem Starts the AI Firewall API (port 8000) and the Security Console (port 3001), then opens the console.
rem Close the two black windows to stop everything.
cd /d %~dp0
start "AI Firewall API" cmd /k ".venv\Scripts\python.exe -m uvicorn api.main:app --port 8000"
start "Security Console" cmd /k "cd frontend\security-console && npm run dev"
echo Waiting for the API to load the model (about 30 seconds)...
timeout /t 30 >nul
start http://127.0.0.1:3001
