@echo off
REM Launch MinerU FastAPI on 127.0.0.1:8001 using the local venv.
REM Active log: logs\mineru-api.log (rotated to timestamped file on restart).
REM Retention: rotated logs deleted after 14 days, capped at 30 files.

setlocal
set "ROOT=%~dp0"
set "ACTIVE=mineru-api.log"
cd /d "%ROOT%"

if not exist logs mkdir logs

REM Rotate previous active log
if exist "logs\%ACTIVE%" (
    for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set "TODAY=%%c-%%b-%%a"
    for /f "tokens=1-2 delims=: " %%a in ("%time%") do set "NOW=%%a-%%b"
    move /y "logs\%ACTIVE%" "logs\mineru-api.%TODAY%_%NOW%.log" > nul 2>&1
)

REM --- Retention cleanup ---
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$active = '%ACTIVE%';" ^
  "$logs = Get-ChildItem 'logs' -Filter '*.log' -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne $active };" ^
  "$logs | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } | Remove-Item -Force -ErrorAction SilentlyContinue;" ^
  "Get-ChildItem 'logs' -Filter '*.log' -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne $active } | Sort-Object LastWriteTime -Descending | Select-Object -Skip 30 | Remove-Item -Force -ErrorAction SilentlyContinue"

call "%ROOT%.venv\Scripts\activate.bat"
"%ROOT%.venv\Scripts\mineru-api.exe" --host 0.0.0.0 --port 8001 >> "logs\%ACTIVE%" 2>&1
