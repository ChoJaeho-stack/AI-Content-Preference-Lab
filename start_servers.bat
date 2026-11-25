@echo off
setlocal
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
start "AI CONTENT LAB local servers" /min powershell.exe -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0logs\run-local-servers.ps1"
echo Server startup requested. The launcher reuses healthy local servers and writes diagnostics to logs\spring-local.log and logs\fastapi-local.err.log.
endlocal
