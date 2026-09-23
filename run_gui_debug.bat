@echo off
REM Debug launcher: console window + pause, so any Python traceback or
REM crash message stays visible instead of vanishing with pythonw.exe.
setlocal
set SCRIPT_DIR=%~dp0
for /d %%A in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_*") do (
  for /d %%B in ("%%A\ffmpeg-*") do set "PATH=%%B\bin;%PATH%"
)
"%SCRIPT_DIR%.venv-win\Scripts\python.exe" "%SCRIPT_DIR%app\gui\main.py"
echo.
echo === exited with errorlevel %errorlevel% ===
pause
