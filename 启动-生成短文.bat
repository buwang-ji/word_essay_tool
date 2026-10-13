@echo off
rem ===========================================================================
rem  Shanbay Daily Essay - double click to run
rem  ASCII only + CRLF: cmd.exe needs this exact combination to parse reliably.
rem ===========================================================================
setlocal

rem ==== fixed script folder (so a desktop copy still works) ====
set "APPDIR=D:\??"
if not exist "%APPDIR%\shanbay_daily_essay.py" set "APPDIR=%~dp0"


set "PY=D:\python\python.exe"
if not exist "%PY%" set "PY=python"
set "ARGS=--tab review"

echo ======================================================================
echo   Shanbay Daily Essay Generator
echo ======================================================================
echo.
echo   Which word list do you want?
echo.
echo     [1] Today REVIEW words    (default)
echo     [2] Today NEW words
echo     [3] Today TASK (new + review)
echo     [4] Quit
echo.
set "SEL="
set /p "SEL=Type 1, 2, 3 or 4 then press Enter: "

if "%SEL%"=="1" set "ARGS=--tab review"
if "%SEL%"=="2" set "ARGS=--tab new"
if "%SEL%"=="3" set "ARGS=--tab all"
if "%SEL%"=="4" goto :quit

echo.
echo ======================================================================
echo   Command: "%PY%" shanbay_daily_essay.py %ARGS%
echo ----------------------------------------------------------------------
echo   1. Open shanbay, collect today words automatically (paging included)
echo   2. Generate essays with DeepSeek API (2 essays per day)
echo   3. Save them and open in VS Code automatically
echo.
echo   Takes about 2-5 minutes. Please keep this window open.
echo ======================================================================
echo.

"%PY%" shanbay_daily_essay.py %ARGS%
set "RC=%ERRORLEVEL%"

echo.
echo ======================================================================
if not "%RC%"=="0" (
  echo   [FAILED] exit code %RC% - please screenshot the messages above.
) else (
  echo   [DONE] Essays generated and opened in VS Code.
)
echo ======================================================================
echo.
echo Press any key to close this window...
pause >nul
endlocal
exit /b 0

:quit
echo.
echo Cancelled. Nothing was run.
timeout /t 2 >nul
endlocal
exit /b 0

