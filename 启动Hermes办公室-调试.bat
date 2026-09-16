@echo off
chcp 65001 >nul
title Hermes 办公室（调试模式 · 保留控制台看日志）
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [!] 没有专用环境，请先执行一次：
  echo     uv venv .venv
  echo     uv pip install --python .venv\Scripts\python.exe pywebview pythonnet
  pause
  exit /b 1
)

echo ============================================
echo   Hermes 办公室
echo   关闭窗口即退出；本控制台会显示日志
echo ============================================
echo.
".venv\Scripts\python.exe" hermes_office_app.py %*
echo.
echo [退出] 程序已结束。按任意键关闭。
pause >nul
