@echo off
rem Start the Audit Workbench (serves the built SPA + API on port 8000).
setlocal
cd /d "%~dp0"

rem Replay mode: answer every model call from the workspace's recorded calls.
rem No model access is needed and nothing leaves this machine. Steps that were
rem never performed with a live model fail instead. See docs/demo-script.md.
rem Remove "rem " from the next line to turn it on; put it back to go live.
rem set "LLM_REPLAY=on"

if /i "%LLM_REPLAY%"=="on" echo Replay mode is ON: model calls are answered from recordings.
uv run --no-project uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
