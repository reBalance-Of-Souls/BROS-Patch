@echo off
rem Quick Boot Training (2026-11-25), to record combo trials: Training straight from the title logo, no Character
rem Select. Ichigo (Awakened) vs Ichigo (Awakened) on the Grid Stage; Display Settings: Display Gauges On, the five
rem others Off; Framedata Off. Training Settings > Status > Awakened (Self / Opponent) takes a side back to Normal.
rem = the launcher's Quick Launch Training (update included) + BROS_QUICKBOOT=1, read by replay.dll.
setlocal
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo   Python was not found on this PC. Start the launcher once, then try again.
  pause
  exit /b 1
)
set BROS_QUICKBOOT=1
%PY% "Bleach Rebirth of Souls Community Patch.py" --quick "ReBalance of Souls V2.0" --boot training
if errorlevel 1 pause
