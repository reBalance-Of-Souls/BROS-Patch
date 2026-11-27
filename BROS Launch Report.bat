@echo off
rem BROS Launch Report (session mv, 2026-11-17; the same file in the Dev launcher and the public one).
rem Double-click it after a start that did not work. It only READS: nothing on the PC is changed and nothing is
rem sent anywhere. It writes one zip on the Desktop (BROS_Launch_Reports_<date>.zip) for the player to send to the
rem patch team by hand: a fresh snapshot of the PC and the game folder, what Windows recorded in the last 30
rem minutes, the last launch reports and the launcher's console logs (launcher\launch_report.py --collect).
setlocal
cd /d "%~dp0"
echo.
echo   BROS Launch Report -- what happened when the game was started
echo   It only reads. Nothing is sent by itself. It makes one zip on your Desktop.
echo.
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo   Python was not found on this PC. Start the launcher once, then try again.
  echo.
  pause
  exit /b 1
)
%PY% -B "launcher\launch_report.py" --collect
echo.
if not defined BROS_LAUNCH_REPORT_NOBOX pause
