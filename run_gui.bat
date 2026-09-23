@echo off
REM Shonan_Lite GUI launcher (Windows dev environment).
REM Launches app/gui/main.py with the .venv-win interpreter, no console window.
REM
REM Explorer's own PATH is fixed at logon time and does not pick up newly
REM installed tools (pip/winget/etc.) until logoff/logon, so a desktop-icon
REM launch of this batch file would not see e.g. a freshly winget-installed
REM ffmpeg. Prepend its known install location directly (no external process
REM calls, to avoid any script-blocking security software) as a fallback.
setlocal
set SCRIPT_DIR=%~dp0
for /d %%A in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_*") do (
  for /d %%B in ("%%A\ffmpeg-*") do set "PATH=%%B\bin;%PATH%"
)
start "" "%SCRIPT_DIR%.venv-win\Scripts\pythonw.exe" "%SCRIPT_DIR%app\gui\main.py"
