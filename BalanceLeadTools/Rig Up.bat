@echo off
rem  Bring the two-client online test rig up on the PUBLIC patch: install pass
rem  with nothing running, then the Sandboxie box, then the host. All rig_up.ps1
rem  does; this is just the double-click front door for it.
rem
rem  Any argument is passed straight through, so
rem  "Rig Up.bat -Launcher 'Quick Launch Training Mode.py'" works the same as
rem  calling the script by hand.
rem
rem  On the public patch the boot mode rides in the dll the install pass puts
rem  down (GameModes\RoomMatchBoot\dinput8.dll), so there is no -Boot argument.
rem
rem  ⚠ Running this installs the public build over whatever is in the game
rem  folder: Script\ and Motion\ are mirrored with robocopy /MIR and
rem  dinput8.dll is overwritten.
rem
rem  Local convenience only -- gitignored on purpose. The rig itself, and the
rem  reasons for the order of its steps, live in BalanceLeadTools\rig_up.ps1
rem  and in DataChakka\guides\Nilsix researches\SELF_HOSTED_ONLINE_TEST_RIG.md
cd /d "%~dp0"
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0rig_up.ps1" %*
echo.
pause
