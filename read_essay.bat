@echo off
rem ===========================================================================
rem  Essay Reader - can be placed anywhere (Desktop, Start Menu, pinned taskbar)
rem  ASCII only + CRLF: cmd.exe requires this combination.
rem ===========================================================================
setlocal

rem ==== fixed script folder (so a desktop copy still works) ====
set "APPDIR=D:\??"

rem If APPDIR is wrong (e.g. you moved the project), fall back to this bat own folder
if not exist "%APPDIR%\read_essay.py" set "APPDIR=%~dp0"

if not exist "%APPDIR%\read_essay.py" (
  echo.
  echo [ERROR] read_essay.py not found.
  echo   Tried: %APPDIR%
  echo   Please edit this bat and fix the APPDIR line.
  echo.
  pause
  exit /b 1
)

chcp 65001 >nul 2>&1
cd /d "%APPDIR%"

set "PY=D:\python\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" read_essay.py
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo [Reader exited with code %RC%]
  pause
)

endlocal
exit /b 0
