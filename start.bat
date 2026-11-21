@echo off
rem Kilowise: one double-click to install, build if needed, and open the app.
rem   start.bat          sync, then serve (builds the app data first if it is missing)
rem   start.bat build    sync, rebuild from data\raw, then serve
rem Close this window (or press Ctrl+C) to stop the website.
setlocal
title Kilowise
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo uv is not installed. Install it once with:
  echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 ^| iex"
  echo then open a new window and run start.bat again.
  pause
  exit /b 1
)

echo [1/3] Installing or updating dependencies...
rem --inexact keeps optional packages (the chat model's PyTorch group) if they are installed
uv sync --inexact
if errorlevel 1 goto :fail

rem Use the fine-tuned chat model only if its packages are already installed (no surprise download)
set "GROUP="
uv run --no-sync python -c "import torch, peft" >nul 2>nul
if not errorlevel 1 if exist "models\chat-lora\adapter_model.safetensors" set "GROUP=--group finetune"

if /i "%~1"=="build" (
  echo [2/3] Rebuilding the app data...
  uv run --no-sync greenledger build
  if errorlevel 1 goto :fail
) else (
  echo [2/3] Using the existing app data ^(run "start.bat build" after changing data or code^).
)

echo [3/3] Starting Kilowise. Your browser opens by itself.
if defined GROUP (echo       Chat: fine-tuned model) else (echo       Chat: retrieval only ^(install with: uv sync --group finetune^))
echo       Close this window to stop the website.
echo.
uv run --no-sync %GROUP% greenledger serve
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo Something went wrong (see the messages above). If the port is busy, close the other Kilowise window first.
pause
exit /b 1
