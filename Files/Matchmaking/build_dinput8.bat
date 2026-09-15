@echo off
rem =====================================================================
rem  Rebuild dinput8.dll from dinput8_proxy.c
rem
rem  ⚠ THE SHIPPED DLL IS A ZIG BUILD, not Mingw-w64, whatever this file
rem  used to say. Verified 2026-09-15: rebuilding the then-current source with
rem
rem      python -m ziglang cc -target x86_64-windows-gnu -O2 -fms-extensions rem             -Wno-date-time -DNDEBUG -shared -o dinput8.dll dinput8_proxy.c
rem
rem  reproduces the shipped dinput8.dll with a BYTE-IDENTICAL .text -- only the
rem  PE timestamp (7 bytes of header), the debug directory in .rdata and
rem  .buildid differ. That is the check to run before trusting any rebuild.
rem
rem  pip install ziglang  gets the compiler. Mingw-w64 is NOT required and was
rem  never what built this; the block below is kept for anyone who has it.
rem
rem  ⚠ REBUILD GameModes\RoomMatchBoot\dinput8.dll TOO, from this same source
rem  with -DENABLE_BOOT_ROOMMATCH=1. It shadows this one when the room-match
rem  shortcut is used, so leaving it stale ships the fix to everyone EXCEPT the
rem  people using that shortcut.
rem
rem  Run this from this folder. Output lands here, next to the source, and
rem  the installer copies it to the game dir from "Files\Matchmaking".
rem =====================================================================
setlocal
cd /d "%~dp0"

where x86_64-w64-mingw32-gcc >nul 2>nul
if errorlevel 1 (
    echo.
    echo   x86_64-w64-mingw32-gcc is not on PATH.
    echo.
    echo   Install MSYS2 ^(https://www.msys2.org^) then:
    echo       pacman -S mingw-w64-x86_64-gcc
    echo   and add C:\msys64\mingw64\bin to PATH.
    echo.
    exit /b 1
)

echo Building dinput8.dll ...
x86_64-w64-mingw32-gcc ^
    -shared -O2 -municode -DNDEBUG ^
    -o dinput8.dll dinput8_proxy.c ^
    -Wl,--out-implib,dinput8_proxy.lib ^
    -static-libgcc ^
    -lkernel32 -luser32

if errorlevel 1 (
    echo.
    echo   BUILD FAILED -- dinput8.dll was NOT replaced.
    exit /b 1
)

echo.
echo   Built dinput8.dll
echo.
echo   Sanity check before shipping: launch the game with it in place and
echo   read patch_ranked.log next to the game exe. You should see a line
echo   for every patch, e.g.
echo.
echo       AIZEN_COUNTER: Pl20-only -- Kikon Counter now costs 5 flames only
echo.
echo   If a line instead says "(game updated?) -- skipped", the game build
echo   moved and that patch's RVAs need re-finding. The DLL verifies a byte
echo   signature at every site first, so a mismatch is a clean skip, never
echo   a crash.
echo.
endlocal
