# =====================================================================
#  rig_up.ps1 -- bring the two-client online test rig up, in order,
#                on the PUBLIC patch.
#
#  Two full clients on one machine playing each other in a room match: one
#  normal, one inside a Sandboxie box on a second Steam account. It is how an
#  online-only bug gets reproduced without a partner.
#
#  The reasoning behind every step is in
#      DataChakka/guides/Nilsix researches/SELF_HOSTED_ONLINE_TEST_RIG.md
#  Read that before changing anything here; this file encodes decisions, it
#  does not explain them.
#
#      .\rig_up.ps1
#      .\rig_up.ps1 -Launcher 'Quick Launch Training Mode.py'
#      .\rig_up.ps1 -Report C:\x.txt
#
#  ⚠ THIS INSTALLS THE PUBLIC BUILD OVER WHATEVER IS IN THE GAME FOLDER.
#  The launcher mirrors Script/ and Motion/ with robocopy /MIR and overwrites
#  dinput8.dll. If you were on a dev-environment build, it is gone until you run
#  a dev launcher again.
#
#  ⚠ Needs BalanceLeadTools\DevToken.txt to exist in this checkout. Without it
#  the launcher does `git reset --hard origin/main` + `git clean -fd -e Json`
#  on its way up and discards any local work in this repo first.
# =====================================================================
param(
    [string]$Launcher = 'Quick Launch Room Match.py',
    [string]$Report   = (Join-Path $env:TEMP 'bros_rig_report.txt')
)

$ErrorActionPreference = 'Continue'

$repo   = Split-Path -Parent $PSScriptRoot
$py     = (Get-Command py -ErrorAction SilentlyContinue).Source
if (-not $py -or (Get-Item $py).Length -eq 0) {
    # ⚠ NOT "python": C:\...\WindowsApps\python.exe is a zero-byte App Execution
    # Alias and Sandboxie refuses it with System Error Code 1920. Any real
    # interpreter will do.
    $py = 'C:\Users\PC\AppData\Local\Python\pythoncore-3.14-64\python.exe'
}
$G      = (Get-Content (Join-Path $repo 'Json\config.json') | ConvertFrom-Json).GAME_PATH
$sbie   = 'C:\Program Files\Sandboxie-Plus\Start.exe'
$hlog   = Join-Path $G 'patch_ranked.log'
$blog   = 'C:\Sandbox\PC\BROS2\drive\D\SteamLibrary\steamapps\common\BLEACH Rebirth of Souls\patch_ranked.log'
$bsteam = 'C:\Sandbox\PC\BROS2\drive\C\Program Files (x86)\Steam\logs\connection_log.txt'

"rig up (public patch)  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Set-Content $Report
function Say($t) { "  $t" | Add-Content $Report; Write-Output "  $t" }

function Session($path) {
    $t = Get-Content $path -Tail 600 -ErrorAction SilentlyContinue
    if (-not $t) { return @() }
    $i = ($t | Select-String 'loaded INTO GAME' | Select-Object -Last 1).LineNumber
    if (-not $i) { return @() }
    return $t[($i-1)..($t.Count-1)]
}
function RoomCode($path) {
    $s = Session $path
    if (-not $s) { return $null }
    $m = $s | Select-String 'match code' | Select-Object -Last 1
    if ($m) { return $m.ToString().Trim() } else { return $null }
}
function KillClients {
    Stop-Process -Name BLEACH_Rebirth_of_Souls -Force -ErrorAction SilentlyContinue
    $d = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $d -and (Get-Process BLEACH_Rebirth_of_Souls -ErrorAction SilentlyContinue)) {
        Start-Sleep -Seconds 2
    }
    Start-Sleep -Seconds 4     # let Windows release the dll handle
}
function RunLauncher($tag) {
    $o = "$Report.$tag.out"
    # ⚠ BROS_LAUNCHER_RELAUNCHED=1 suppresses the launcher's one-shot self
    # re-exec after a pull that changed something. Left on, that re-exec starts a
    # SECOND client, and Steam will not run one account's game twice, so one of
    # the pair quits and the rig comes up with a single client. Measured
    # 2026-09-15. The cost is that a run which pulls an update installs it with
    # the old launcher code; for a rig that determinism is what you want.
    $env:BROS_LAUNCHER_RELAUNCHED = '1'
    $p = Start-Process $py -ArgumentList "`"$repo\$Launcher`"" -WorkingDirectory $repo `
                       -RedirectStandardOutput $o -RedirectStandardError "$o.err" `
                       -PassThru -NoNewWindow
    $p.WaitForExit(240000) | Out-Null
    $s = (Get-Content $o -ErrorAction SilentlyContinue) -join ' | '
    if ($s) { Say "launcher: $s" }
}

if (-not (Test-Path (Join-Path $repo 'BalanceLeadTools\DevToken.txt'))) {
    Say "REFUSING: no BalanceLeadTools\DevToken.txt in this checkout."
    Say "  Without it the launcher runs 'git reset --hard origin/main' and"
    Say "  'git clean -fd -e Json' before starting, which would discard local work."
    exit 1
}

KillClients

# ---- 1. install, with NOTHING running --------------------------------------
# Separate on purpose: with the box up, the launcher CANNOT write dinput8.dll
# ("Permission denied"), which is harmless when the file on disk is already the
# one you want and silently runs the OLD loader when it is not.
#
# ⚠ On the public patch this step is also what selects the boot mode. Unlike the
# dev environment, which picks it at runtime from BROS_BOOT_MODE, the public
# launchers install a frozen per-mode loader -- GameModes\RoomMatchBoot\dinput8.dll,
# built from the one canonical source with -DENABLE_BOOT_ROOMMATCH=1 -- which
# SHADOWS Files\Matchmaking\dinput8.dll. So the mode rides in the installed dll,
# steps 3 and 4 need no environment variable, and after any dll change you must
# close both clients and redo this step.
"=== install pass ===" | Add-Content $Report
RunLauncher 'install'
$d = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $d -and -not (Get-Process BLEACH_Rebirth_of_Souls -ErrorAction SilentlyContinue)) {
    Start-Sleep -Seconds 3
}
Start-Sleep -Seconds 15
$state = Join-Path $G 'launcher_patch_state.json'
if (Test-Path $state) { Say "version : $((Get-Content $state | ConvertFrom-Json).version)" }
Say "code    : $(Get-Content (Join-Path $G 'patch_ranked.txt') -ErrorAction SilentlyContinue)"
KillClients
Say "install client closed"

# ---- 2. boxed Steam --------------------------------------------------------
# Test for the STATE (up and logged on), never for the transition. Launching
# steam.exe into a box that already holds one does nothing and writes nothing,
# so waiting for a new logon line waits forever.
"=== boxed Steam ===" | Add-Content $Report
$logged = (Test-Path $bsteam) -and
          ((Get-Content $bsteam | Select-String "RecvMsgClientLogOnResponse.*'OK'").Count -gt 0)
if ((@(Get-Process steam -ErrorAction SilentlyContinue).Count -ge 2) -and $logged) {
    Say "already up and logged on -- reused"
} else {
    $before = if (Test-Path $bsteam) {
        (Get-Content $bsteam | Select-String "RecvMsgClientLogOnResponse.*'OK'").Count } else { 0 }
    Start-Process $sbie -ArgumentList '/box:BROS2', 'C:\Program Files (x86)\Steam\steam.exe'
    $d = (Get-Date).AddMinutes(6); $logged = $false
    while ((Get-Date) -lt $d) {
        Start-Sleep -Seconds 10
        if (Test-Path $bsteam) {
            if ((Get-Content $bsteam | Select-String "RecvMsgClientLogOnResponse.*'OK'").Count -gt $before) {
                $logged = $true; break
            }
        }
    }
}
if (-not $logged) { Say "FAIL: boxed Steam never logged on"; exit 1 }
Say ((Get-Content $bsteam | Select-String "RecvMsgClientLogOnResponse.*'OK'" | Select-Object -Last 1).ToString().Trim())

# ---- 3. the BOX, first, and wait for it to REACH THE ROOM -------------------
# The exe directly. NEVER a launcher: Sandboxie is copy-on-write, and a launcher
# in the box forks the whole install (564 MB, measured) after which the two
# clients silently run different data, a different dll and different lobby codes.
#
# ⚠ Wait for the box's own "match code ... loaded" line, not for its process to
# appear. The process shows up in seconds and the client can take minutes to
# finish booting -- and a boxed client that initialises next to an already
# running host makes the host quit, cleanly, with no crash line and no Windows
# record. Waiting on the process plus a fixed sleep is what produced exactly
# that on 2026-09-15: box process at 15:16:14, host already loaded at 15:15:53,
# host gone.
"=== box (first) ===" | Add-Content $Report
$boxBefore = RoomCode $blog
Start-Process $sbie -ArgumentList '/box:BROS2', (Join-Path $G 'BLEACH_Rebirth_of_Souls.exe') -WorkingDirectory $G
$d = (Get-Date).AddMinutes(8); $boxCode = $null
while ((Get-Date) -lt $d) {
    Start-Sleep -Seconds 10
    $c = RoomCode $blog
    if ($c -and $c -ne $boxBefore) { $boxCode = $c; break }
}
if (-not $boxCode) { Say "FAIL: the boxed client never reached the room"; exit 1 }
Say "box  code : $boxCode"
$boxPid = (@(Get-Process BLEACH_Rebirth_of_Souls -ErrorAction SilentlyContinue) | Select-Object -First 1).Id
Say "box pid $boxPid"
Start-Sleep -Seconds 15

# ---- 4. the host, second ---------------------------------------------------
# The reverse order is the safe one: a host started next to a running box leaves
# it alone.
"=== host (second) ===" | Add-Content $Report
RunLauncher 'host'
$d = (Get-Date).AddMinutes(6); $hostCode = $null
while ((Get-Date) -lt $d) {
    Start-Sleep -Seconds 10
    $hostCode = RoomCode $hlog
    if ($hostCode) { break }
}

# ---- 5. verify -------------------------------------------------------------
"=== verify ===" | Add-Content $Report
$hs = Session $hlog
$bs = Session $blog
$hb = ($hs | Select-String 'PATCHSTAMP: ' | Select-Object -First 1)
$bb = ($bs | Select-String 'PATCHSTAMP: ' | Select-Object -First 1)
Say "host code : $hostCode"
Say "box  code : $(RoomCode $blog)"
Say "host crashes: $(@($hs | Select-String 'CRASH: access violation').Count)   box crashes: $(@($bs | Select-String 'CRASH: access violation').Count)"

# The lobby code is seeded from the COMMIT, never from the binary, so two
# clients can agree on it while running different loaders. Compare the flags,
# not just the code.
function Flags($m) { if ($m) { ($m.ToString() -replace '^.*flags ', '') } else { '' } }
if ((Flags $hb) -and ((Flags $hb) -eq (Flags $bb))) {
    Say "build     : SAME on both sides"
} else {
    Say "build     : DIFFERENT -- the clients are not running the same loader"
    Say "  host: $(Flags $hb)"
    Say "  box : $(Flags $bb)"
}

$live = @(Get-Process BLEACH_Rebirth_of_Souls -ErrorAction SilentlyContinue)
Say "clients alive: $($live.Count)"
if ($live.Count -ge 2) { Say "RESULT: rig UP" } else { Say "RESULT: FAIL" }
"DONE $(Get-Date -Format 'HH:mm:ss')" | Add-Content $Report
