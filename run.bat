@echo off
rem Start the Audit Workbench (serves the built SPA + API on port 8000).
setlocal
cd /d "%~dp0"

rem Replay mode: answer every model call from recorded calls instead of a model.
rem No model access is needed and nothing leaves this machine. Steps that were
rem never performed with a live model fail instead. See docs/demo-script.md.
rem Remove "rem " from BOTH lines below to turn it on; put it back to go live.
rem The second line names the recording: Procurement as built on 18 Nov 2026.
rem set "LLM_REPLAY=on"
rem set "LLM_REPLAY_SOURCE=Workspaces\recordings\procurement.db"

if /i "%LLM_REPLAY%"=="on" echo Replay mode is ON: model calls are answered from "%LLM_REPLAY_SOURCE%".
uv run --no-project uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
