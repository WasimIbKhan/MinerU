@echo off
REM Local addition (not upstream): launch the patched MinerU 4 API server from this
REM checkout's venv. Loopback only; never pass --remote (documents stay local).
REM basic = local small models, no VLM. Port and upload dir via MINERU_PORT /
REM MINERU_UPLOAD_DIR. Log: logs\mineru-api-<port>.log.
setlocal
set "ROOT=%~dp0"
if "%MINERU_PORT%"=="" set "MINERU_PORT=8011"
if "%MINERU_UPLOAD_DIR%"=="" set "MINERU_UPLOAD_DIR=%ROOT%uploads"
cd /d "%ROOT%"
if not exist logs mkdir logs
set "PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True"
"%ROOT%.venv\Scripts\mineru-api.exe" --host 127.0.0.1 --port %MINERU_PORT% --tier basic --no-advanced --upload-dir "%MINERU_UPLOAD_DIR%" >> "logs\mineru-api-%MINERU_PORT%.log" 2>&1
