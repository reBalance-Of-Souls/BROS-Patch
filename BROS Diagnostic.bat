<# :
@echo off
setlocal
set "BROS_DIAG_SELF=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText($env:BROS_DIAG_SELF); $i=$s.IndexOf([char]10+'#'+[char]62); Invoke-Expression $s.Substring($i+3)"
if not defined BROS_DIAG_NOPAUSE pause
exit /b
#>
# BROS Diagnostic -- one report of what happened in a player's games: crashes, performance, online matches, inputs.
#
# Double-click it. It only READS: nothing on the PC is changed and nothing is sent anywhere. It writes one zip on the
# Desktop (BROS_Diagnostic_<date>.zip) that the player sends to the patch team by hand. report.txt inside starts with
# what stands out, then every detail the team needs to work without asking twice.
#
# Test knobs: BROS_DIAG_NOPAUSE=1 (no pause, no Explorer window), BROS_DIAG_OUT=<folder> (where the zip goes),
# BROS_DIAG_GAME=<game folder> (skip the search).

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$DiagVersion = '2026-10-04'
$NoPause = [bool]$env:BROS_DIAG_NOPAUSE
$Inv = [Globalization.CultureInfo]::InvariantCulture

function Say([string]$t) { Write-Host $t }

Say ''
Say '  BROS Diagnostic -- what happened in your games'
Say '  ----------------------------------------------'
Say '  It only reads: nothing on your PC is changed, nothing is sent by itself.'
Say '  It puts into one zip on your Desktop, for you to send to the patch team:'
Say '    - the game''s patch log and crash reports (they hold your Steam ID and your opponents'')'
Say '    - a summary of your PC: Windows, CPU, RAM, page file, graphics card and driver, drives, power plan'
Say '    - which programs run right now (names only) and which mods sit in the game folder'
Say '    - Windows'' records of game crashes, graphics driver resets and memory shortages (last 30 days)'
Say '    - Steam''s lines about this game''s launches, Steam disconnections and controllers (IP addresses removed)'
Say '    - a 20-second ping test of your connection'
Say '  It takes about a minute.'
Say ''

# ============================================================ where things are
$root = Split-Path -Parent $env:BROS_DIAG_SELF
if (-not $root) { $root = (Get-Location).Path }

function Get-SteamPath {
    try {
        $sp = (Get-ItemProperty 'HKCU:\Software\Valve\Steam' -ErrorAction Stop).SteamPath
        if ($sp) { return ($sp -replace '/', '\') }
    } catch {}
    foreach ($c in @("${env:ProgramFiles(x86)}\Steam", "$env:ProgramFiles\Steam")) { if (Test-Path $c) { return $c } }
    return $null
}
function Get-SteamLibraries([string]$steam) {
    $libs = @()
    if (-not $steam) { return $libs }
    $libs += $steam
    $vdf = Join-Path $steam 'steamapps\libraryfolders.vdf'
    if (Test-Path $vdf) {
        foreach ($m in [regex]::Matches([IO.File]::ReadAllText($vdf), '"path"\s+"([^"]+)"')) { $libs += ($m.Groups[1].Value -replace '\\\\', '\') }
    }
    return @($libs | Select-Object -Unique)
}
function Test-Game([string]$g) { return ($g -and (Test-Path (Join-Path $g 'BLEACH_Rebirth_of_Souls.exe'))) }

$steam = Get-SteamPath
$libs = Get-SteamLibraries $steam
$cfg = $null
$cfgPath = Join-Path $root 'Json\config.json'
if (Test-Path $cfgPath) { try { $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json } catch {} }

$game = $env:BROS_DIAG_GAME
if (-not (Test-Game $game) -and $cfg -and $cfg.GAME_PATH) { $game = ($cfg.GAME_PATH -replace '/', '\') }
$manifest = $null
foreach ($l in $libs) {
    $acf = Join-Path $l 'steamapps\appmanifest_1689620.acf'
    if (Test-Path $acf) {
        $manifest = $acf
        if (-not (Test-Game $game)) {
            $dir = 'BLEACH Rebirth of Souls'
            $mm = [regex]::Match([IO.File]::ReadAllText($acf), '"installdir"\s+"([^"]+)"')
            if ($mm.Success) { $dir = $mm.Groups[1].Value }
            $game = Join-Path $l "steamapps\common\$dir"
        }
    }
}
if (-not (Test-Game $game)) {
    if ($NoPause) { Say '  The game folder was not found.'; return }
    $game = (Read-Host '  The game folder was not found. Paste the folder that holds BLEACH_Rebirth_of_Souls.exe').Trim().Trim('"')
}
if (-not (Test-Game $game)) { Say "  No BLEACH_Rebirth_of_Souls.exe in '$game' -- stopping."; return }
Say "  Game folder:  $game"
Say "  Patch folder: $root"

$stamp = Get-Date -Format 'yyyyMMdd_HHmm'
$outRoot = $env:BROS_DIAG_OUT
if (-not $outRoot) { $outRoot = [Environment]::GetFolderPath('Desktop') }
$work = Join-Path $env:TEMP "BROS_Diagnostic_$stamp"
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory -Force -Path $work | Out-Null

$findings = New-Object System.Collections.Generic.List[string]
function Flag([string]$t) { $findings.Add($t) }
$sections = [ordered]@{}
function Sec([string]$name) { $l = New-Object System.Collections.Generic.List[string]; $sections[$name] = $l; return , $l }

function Open-Reader([string]$path) {
    $fs = New-Object IO.FileStream($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    return (New-Object IO.StreamReader($fs, [Text.Encoding]::UTF8))
}
function Short-Hash([string]$p) { try { return (Get-FileHash $p -Algorithm SHA256).Hash.Substring(0, 16) } catch { return '?' } }
function Build-Id([string]$p) {
    try {
        $s = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($p))
        $m = [regex]::Match($s, '[0-9a-f]{7}-[A-Za-z0-9-]+-20\d{6}')
        $id = '(no build id)'
        if ($m.Success) { $id = $m.Value }
        if ($s.Contains('BROS_PLUGIN_HOST_ABI=')) { $id += ', plugin host' }
        if ($s.Contains('bros_net.txt')) { $id += ', New netcode switch' }
        return $id
    } catch { return '?' }
}
function Num([string]$s) { return [double]::Parse($s, $Inv) }

# ============================================================ the install
Say '  Checking the install...'
$inst = Sec 'INSTALL'
$git = $null
try { $git = (Get-Command git -ErrorAction Stop).Source } catch {}
if ($git -and (Test-Path (Join-Path $root '.git'))) {
    try {
        $head = (& $git -C $root log -1 --format='%h %ci %s' 2>$null)
        $inst.Add("Patch folder commit: $head")
        $dirty = @(& $git -C $root status --porcelain --untracked-files=no 2>$null).Count
        $inst.Add("Files changed by hand in the patch folder (tracked): $dirty")
        $behind = (& $git -C $root rev-list --count 'HEAD..origin/main' 2>$null)
        if ($behind) { $inst.Add("Commits on origin/main not installed here (as of the last fetch): $behind") }
        $fh = Join-Path $root '.git\FETCH_HEAD'
        if (Test-Path $fh) { $inst.Add("Last update check (git fetch): " + (Get-Item $fh).LastWriteTime.ToString('yyyy-MM-dd HH:mm')) }
        if ($dirty -gt 0) { Flag ("The patch folder has {0} file(s) changed by hand: the launcher may not install what the patch ships." -f $dirty) }
    } catch { $inst.Add('git: could not be read') }
} else { $inst.Add('git: not available, or the patch folder is not a git clone') }
if ($cfg) {
    $keep = @()
    foreach ($k in @('TEAM_BATTLE', 'awakeningaura', 'breaker_grab', 'hakugeki', 'hit', 'reverse_globe', 'skill_activation')) {
        if ($cfg.PSObject.Properties.Name -contains $k) { $keep += ('{0}={1}' -f $k, $cfg.$k) }
    }
    $inst.Add('Launcher settings: ' + ($keep -join ', '))
}
$nj = Join-Path $root 'Json\netcode.json'
if (Test-Path $nj) { $inst.Add('New netcode switch saved by the player: ' + ((Get-Content $nj -Raw) -replace '\s+', ' ')) } else { $inst.Add('New netcode switch: never touched (default)') }

$exe = Get-Item (Join-Path $game 'BLEACH_Rebirth_of_Souls.exe')
$inst.Add(("Game exe: {0} bytes, file version {1}, {2}" -f $exe.Length, $exe.VersionInfo.FileVersion, $exe.LastWriteTime.ToString('yyyy-MM-dd HH:mm')))
if ($manifest) {
    $mt = [IO.File]::ReadAllText($manifest)
    $b = [regex]::Match($mt, '"buildid"\s+"(\d+)"'); $u = [regex]::Match($mt, '"LastUpdated"\s+"(\d+)"')
    $when = ''
    if ($u.Success) { $when = ([DateTimeOffset]::FromUnixTimeSeconds([long]$u.Groups[1].Value)).LocalDateTime.ToString('yyyy-MM-dd HH:mm') }
    if ($b.Success) { $inst.Add("Steam build of the game: $($b.Groups[1].Value), updated $when") }
}
$gameDll = Join-Path $game 'dinput8.dll'
$repoDll = Join-Path $root 'Files\Matchmaking\dinput8.dll'
if (Test-Path $gameDll) {
    $gi = Get-Item $gameDll
    $line = ("Loader in the game: dinput8.dll {0} bytes, {1}, sha256 {2}, build {3}" -f $gi.Length, $gi.LastWriteTime.ToString('yyyy-MM-dd HH:mm'), (Short-Hash $gameDll), (Build-Id $gameDll))
    $inst.Add($line)
    if (Test-Path $repoDll) {
        if ((Short-Hash $gameDll) -eq (Short-Hash $repoDll)) { $inst.Add('  = the loader this patch folder ships') }
        else {
            $inst.Add(("  DIFFERENT from the patch folder's loader ({0}, build {1})" -f (Short-Hash $repoDll), (Build-Id $repoDll)))
            Flag 'The game folder holds a different loader (dinput8.dll) than this patch folder ships: an older or a foreign one. Launch through the launcher to install the right one.'
        }
    }
} else {
    $inst.Add('Loader in the game: none (dinput8.dll absent -- the game runs without the patch, or Vanilla was launched last)')
}
if (Test-Path (Join-Path $game 'dinput8_inner.dll')) { $inst.Add('dinput8_inner.dll present: a measuring tool''s leftover, harmless only if dinput8.dll is the patch loader') }
$plugDir = Join-Path $game 'ReBalanceOfSouls'
$repoPlug = Join-Path $root 'Files\Matchmaking\Plugins'
$have = @{}
if (Test-Path $plugDir) { foreach ($d in (Get-ChildItem $plugDir -Filter *.dll -ErrorAction SilentlyContinue)) { $have[$d.Name] = Short-Hash $d.FullName } }
$want = @{}
if (Test-Path $repoPlug) { foreach ($d in (Get-ChildItem $repoPlug -Filter *.dll -ErrorAction SilentlyContinue)) { $want[$d.Name] = Short-Hash $d.FullName } }
foreach ($n in ($have.Keys | Sort-Object)) {
    $s = 'not shipped by this patch folder'
    if ($want.ContainsKey($n)) { if ($want[$n] -eq $have[$n]) { $s = 'same as shipped' } else { $s = 'DIFFERENT from the shipped one' } }
    $inst.Add(("Plugin {0}: sha256 {1} -- {2}" -f $n, $have[$n], $s))
}
foreach ($n in ($want.Keys | Sort-Object)) { if (-not $have.ContainsKey($n)) { $inst.Add("Plugin $n shipped but NOT installed in the game") } }
foreach ($n in @('bros_net.txt', 'patch_ranked.txt', 'bros_boot_mode.txt')) {
    $p = Join-Path $game $n
    if (Test-Path $p) { $inst.Add(("{0}: {1}" -f $n, ((Get-Content $p -ErrorAction SilentlyContinue | Where-Object { $_ -and -not $_.StartsWith('#') }) -join ', '))) }
}
$state = Join-Path $game 'launcher_patch_state.json'
if (Test-Path $state) {
    $mm = [regex]::Match([IO.File]::ReadAllText($state), '"version"\s*:\s*"([^"]*)"')
    if ($mm.Success) { $inst.Add("Version installed by the launcher: $($mm.Groups[1].Value)") }
}
# The launcher's effect toggles copy ONE folder into both quality tiers, and 'original' holds the HIGH bytes, so a
# player on a lower graphics preset gets the High effects for these nine (sizes: stock MIDDLE, stock HIGH).
$fxStock = [ordered]@{
    'COM_tm_EvolveAura00.desktop.vfxt' = @(1482020, 6401101); 'COM_tm_EvolveAura01.desktop.vfxt' = @(1482020, 6401101)
    'COM_tm_EvolveAura02.desktop.vfxt' = @(1482020, 6401101); 'COM_tm_BreakDown00.desktop.vfxt' = @(52074, 113332)
    'COM_tm_BreakDown01.desktop.vfxt' = @(198747, 516762); 'COM_tm_Ignition01.desktop.vfxt' = @(32365, 82879)
    'COM_tm_HitSlash_00.desktop.vfxt' = @(370427, 1174157); 'COM_tm_HitStrike_00.desktop.vfxt' = @(100959, 278851)
    'COM_tm_Ignition00.desktop.vfxt' = @(230711, 629125)
}
$fxHigh = 0; $fxStockN = 0; $fxOther = 0
foreach ($k in $fxStock.Keys) {
    $p = Join-Path $game "01MIDDLE\Effect\spfx\com\$k"
    if (-not (Test-Path $p)) { continue }
    $len = (Get-Item $p).Length
    if ($len -eq $fxStock[$k][1]) { $fxHigh++ } elseif ($len -eq $fxStock[$k][0]) { $fxStockN++ } else { $fxOther++ }
}
$inst.Add(("Middle-quality effects (hits, evolve auras, breaker, ignition): {0} of 9 are the HIGH versions, {1} stock, {2} other (low-spec toggle or modded)" -f $fxHigh, $fxStockN, $fxOther))
$stock = @('SPFXEngine.dll', 'steam_api64.dll', 'dinput8.dll', 'dinput8_inner.dll')
$foreign = @(Get-ChildItem $game -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -in @('.dll', '.asi', '.ini') -and $stock -notcontains $_.Name -and $_.Name -notmatch '^(window_position)\.ini$' })
foreach ($f in $foreign) {
    $vi = $f.VersionInfo
    $inst.Add(("Not a game file, in the game folder: {0} ({1} bytes) {2} {3}" -f $f.Name, $f.Length, $vi.CompanyName, $vi.FileDescription))
}
$foreignDll = @($foreign | Where-Object { $_.Extension -ne '.ini' })
if ($foreignDll.Count) { Flag ("Mods or injectors in the game folder: " + (($foreignDll | ForEach-Object { $_.Name }) -join ', ') + ' -- they load into the game and can cause crashes or stutter.') }
$bn = Join-Path $game 'bros_net.txt'
if (Test-Path $bn) {
    $bt = (Get-Content $bn -ErrorAction SilentlyContinue | Where-Object { $_ -and -not $_.StartsWith('#') }) -join ', '
    $mode = 'custom values'
    if ($bt -match 'lock 1, sleep 1, window 8') { $mode = 'New netcode ON' } elseif ($bt -match 'lock 0, sleep 8, window 3') { $mode = 'New netcode OFF (the game''s own)' }
    Flag ("Netcode set in the game folder now: {0} ({1})." -f $mode, $bt)
}

# ============================================================ the patch log
Say '  Reading the patch log...'
$rxAny = New-Object regex('PATCHSTAMP: |NET: bros_net|NET/(match|loop|snap|stall) |HOOKS INSTALLED|KBHOHO|PERF: |JOIN BLOCKED|MATCH: no matchmaking|ROOM3/p2p: |CRASH: |HANG', 'Compiled')
$rxTime = New-Object regex('^\[(\d\d:\d\d:\d\d)\.\d+\] ', 'Compiled')
$rxNetEnd = New-Object regex('NET/match #(\d+) (\w+) -- (the battle ended|no frame for 20 s)[^|]*\| D (\d+)(?: \(game (\d+), delay (-?\d+)\))? from RTT'' (\d+) ms \| battle time (\d+)m (\d+)s \| network stalls (\d+), felt (\d+) = ([\d.]+)/min, longest (\d+) ms \| ([^|]*)\| frozen ([\d.]+) s \(([\d.]+)%\), network ([\d.]+) s', 'Compiled')
$rxLoop = New-Object regex('NET/loop #(\d+): network thread period p50 ([\d.]+) ms, p90 ([\d.]+) ms, p99 ([\d.]+) ms', 'Compiled')

function New-Session([string]$time, [string]$kind, [string]$id) {
    [pscustomobject]@{
        Start = $time; Kind = $kind; Build = $id; Netcode = ''; Pool = ''; Kbhoho = ''
        Scheme = @{}; Rewrites = (New-Object System.Collections.Generic.List[string]); RewriteCount = @{}
        KbReleases = 0; Battles = (New-Object System.Collections.Generic.List[object]); Loop = @{}
        Snap = (New-Object System.Collections.Generic.List[string])
        MaxLoad = -1; MinAvail = -1; MinCommit = -1; MaxHandles = -1
        JoinBlocked = 0; NoMatchmaking = 0; Relay = 0; P2PErrors = 0; CrashLines = 0; LastTime = $time
    }
}
$schemeName = @{ '0' = 'Type A'; '1' = 'Type B'; '2' = 'Type C'; '3' = 'Custom' }
$sessions = New-Object System.Collections.Generic.List[object]
$cur = $null
$logFiles = @()
foreach ($n in @('patch_ranked.log.1', 'patch_ranked.log')) { $p = Join-Path $game $n; if (Test-Path $p) { $logFiles += $p } }
$lineCount = 0
foreach ($p in $logFiles) {
    $sr = Open-Reader $p
    try {
        while ($null -ne ($line = $sr.ReadLine())) {
            $lineCount++
            if (-not $rxAny.IsMatch($line)) { continue }
            $tm = $rxTime.Match($line)
            $t = ''
            if ($tm.Success) { $t = $tm.Groups[1].Value }
            if ($line -match 'PATCHSTAMP: (\w+) build, id (\S+?),') {
                $cur = New-Session $t $Matches[1] $Matches[2]
                $sessions.Add($cur)
                continue
            }
            if ($null -eq $cur) { $cur = New-Session $t 'unknown' '(before any PATCHSTAMP line)'; $sessions.Add($cur) }
            if ($t) { $cur.LastTime = $t }
            if ($line -match 'NET: bros_net\.txt read -> (lock \d, sleep \d+ ms, window \d+, delay -?\d+)') { $cur.Netcode = $Matches[1] }
            elseif ($line -match 'HOOKS INSTALLED .*pool code (\d+)') { $cur.Pool = $Matches[1] }
            elseif ($line -match 'KBHOHO: ARMED') { $cur.Kbhoho = 'armed' }
            elseif ($line -match 'KBHOHO: .*NOT armed') { $cur.Kbhoho = 'NOT armed' }
            elseif ($line -match 'KBHOHO/diag: BrainPad P(\d) .*scheme (\d+)') { $cur.Scheme[$Matches[1]] = $Matches[2] }
            elseif ($line -match 'KBHOHO/pad: P(\d+) Custom, (\w+) = SP trigger \+ button (0x[0-9A-Fa-f]+), which is (.+?) -- with the trigger down it counts as (.+?), as in Type A') {
                $cur.Rewrites.Add(('P{0} {1} (SP trigger + button {2}): that button is {3}; with the trigger held it now counts as {4}' -f $Matches[1], $Matches[2], $Matches[3], $Matches[4], $Matches[5]))
            }
            elseif ($line -match 'KBHOHO/pad: (\w+) -- (\d+) trigger press\(es\) rewritten') { $cur.RewriteCount[$Matches[1]] = [int]$Matches[2] }
            elseif ($line -match 'KBHOHO: (\d+) keyboard Hoho release') { $cur.KbReleases = [int]$Matches[1] }
            elseif ($line -match 'PERF: .*handles (\d+) .*load (\d+)% availphys (\d+) MB \| commit free (\d+) MB') {
                $hd = [int]$Matches[1]; $ld = [int]$Matches[2]; $av = [int]$Matches[3]; $cf = [int]$Matches[4]
                if ($hd -gt $cur.MaxHandles) { $cur.MaxHandles = $hd }
                if ($ld -gt $cur.MaxLoad) { $cur.MaxLoad = $ld }
                if ($cur.MinAvail -lt 0 -or $av -lt $cur.MinAvail) { $cur.MinAvail = $av }
                if ($cur.MinCommit -lt 0 -or $cf -lt $cur.MinCommit) { $cur.MinCommit = $cf }
            }
            elseif ($line -match 'JOIN BLOCKED') { $cur.JoinBlocked++ }
            elseif ($line -match 'MATCH: no matchmaking after') { $cur.NoMatchmaking++ }
            elseif ($line -match 'ROOM3/p2p: ') {
                if ($line -match 'relay 1') { $cur.Relay++ }
                if ($line -match 'error (\w+)' -and $Matches[1] -ne 'none') { $cur.P2PErrors++ }
            }
            elseif ($line -match 'NET/snap #\d+ guest: (\d+) host snapshots checked') { $cur.Snap.Add($line.Substring([Math]::Min(15, $line.Length))) }
            elseif ($line -match '^\[[\d:.]+\] CRASH: (?!vectored handler armed)') { $cur.CrashLines++ }
            else {
                $m = $rxLoop.Match($line)
                if ($m.Success) { $cur.Loop[$m.Groups[1].Value] = ('p50 {0} ms, p99 {1} ms' -f $m.Groups[2].Value, $m.Groups[4].Value); continue }
                $m = $rxNetEnd.Match($line)
                if ($m.Success) {
                    $run = [int]$m.Groups[8].Value * 60 + [int]$m.Groups[9].Value
                    $net = Num $m.Groups[17].Value
                    $pct = 0.0
                    if ($run -gt 0) { $pct = 100.0 * $net / $run }
                    $cur.Battles.Add([pscustomobject]@{
                        End = $t; N = $m.Groups[1].Value; Seat = $m.Groups[2].Value; D = [int]$m.Groups[4].Value; Game = $m.Groups[5].Value
                        Delay = $m.Groups[6].Value; Rtt = [int]$m.Groups[7].Value; Run = $run; Stalls = [int]$m.Groups[10].Value
                        Felt = [int]$m.Groups[11].Value; FeltMin = (Num $m.Groups[12].Value); Longest = [int]$m.Groups[13].Value
                        Hist = $m.Groups[14].Value.Trim(); NetPct = $pct; How = $m.Groups[3].Value
                    })
                }
            }
        }
    } finally { $sr.Close() }
}
Say ("  {0} lines read, {1} game session(s) found." -f $lineCount, $sessions.Count)

# ============================================================ crash reports and dumps
$crashDir = Join-Path $game 'crashlogs'
$crashes = @()
if (Test-Path $crashDir) { $crashes = @(Get-ChildItem $crashDir -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^(crash|hang)-' } | Sort-Object LastWriteTime -Descending) }
$crashSec = Sec 'CRASH REPORTS WRITTEN BY THE PATCH (newest first; unhandled = the game died, hang = frozen 20 s or more, first-chance = an error the game survived)'
foreach ($c in ($crashes | Select-Object -First 30)) {
    $culprit = ''
    try {
        $txt = @(Get-Content $c.FullName -TotalCount 14 -ErrorAction Stop)
        $caught = $txt | Where-Object { $_ -match '^caught:' } | Select-Object -First 1
        for ($k = 0; $k -lt $txt.Count; $k++) { if ($txt[$k] -match 'PROBABLE CULPRIT' -and $k + 1 -lt $txt.Count) { $culprit = $txt[$k + 1].Trim(); break } }
        if (-not $culprit) { $culprit = ($txt | Where-Object { $_ -match 'freeze|hang|HANG|Frozen|frozen' } | Select-Object -First 1) }
        if ($caught) { $culprit = "$caught | $culprit" }
    } catch {}
    $crashSec.Add(("{0}  {1}  {2}" -f $c.LastWriteTime.ToString('yyyy-MM-dd HH:mm'), $c.Name, $culprit))
}
if (-not $crashes.Count) { $crashSec.Add('(none)') }
if (Test-Path (Join-Path $crashDir 'session.active')) {
    $crashSec.Add('session.active is present: the last game session did not end cleanly (or the game is running now).')
}
$dumpDir = Join-Path $env:LOCALAPPDATA 'CrashDumps'
$dumps = @()
if (Test-Path $dumpDir) { $dumps = @(Get-ChildItem $dumpDir -Filter 'BLEACH_Rebirth_of_Souls*.dmp' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending) }
foreach ($d in ($dumps | Select-Object -First 6)) { $crashSec.Add(("Crash dump (kept on the PC, too big to send): {0}  {1:N0} MB  {2}" -f $d.LastWriteTime.ToString('yyyy-MM-dd HH:mm'), ($d.Length / 1MB), $d.Name)) }
$recentCrash = @($crashes | Where-Object { $_.LastWriteTime -gt (Get-Date).AddDays(-14) })
$nUnh = @($recentCrash | Where-Object { $_.Name -like 'crash-unhandled-*' }).Count
$nHang = @($recentCrash | Where-Object { $_.Name -like 'hang-*' }).Count
$nFirst = $recentCrash.Count - $nUnh - $nHang
if ($nUnh -or $nHang) { Flag ("CRASHES (patch reports, last 14 days): {0} crash(es) and {1} freeze(s) of 20 s or more; plus {2} error(s) the game survived." -f $nUnh, $nHang, $nFirst) }

# ============================================================ Windows' own records (30 days)
Say '  Reading Windows'' crash and driver records...'
$since = (Get-Date).AddDays(-30)
$ev = Sec 'WINDOWS RECORDS, LAST 30 DAYS (game crashes and hangs, graphics driver resets, memory shortages, unexpected shutdowns, hardware errors)'
function Get-Ev($filter) { try { return @(Get-WinEvent -FilterHashtable $filter -ErrorAction Stop) } catch { return @() } }
$appErr = @(Get-Ev @{ LogName = 'Application'; ProviderName = 'Application Error'; Id = 1000; StartTime = $since } | Where-Object { $_.Properties.Count -gt 7 -and [string]$_.Properties[0].Value -like 'BLEACH_Rebirth_of_Souls*' })
foreach ($e in ($appErr | Select-Object -First 25)) {
    $ev.Add(("{0}  GAME CRASH  module {1} {2}, exception 0x{3}, offset {4}" -f $e.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss'), $e.Properties[3].Value, $e.Properties[4].Value, $e.Properties[6].Value, $e.Properties[7].Value))
}
$appHang = @(Get-Ev @{ LogName = 'Application'; ProviderName = 'Application Hang'; Id = 1002; StartTime = $since } | Where-Object { $_.Properties.Count -gt 0 -and [string]$_.Properties[0].Value -like 'BLEACH_Rebirth_of_Souls*' })
foreach ($e in ($appHang | Select-Object -First 15)) { $ev.Add(("{0}  GAME HANG (Windows closed it as not responding)" -f $e.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss'))) }
$tdr = @(Get-Ev @{ LogName = 'System'; ProviderName = 'Display'; Id = 4101; StartTime = $since })
foreach ($e in ($tdr | Select-Object -First 15)) { $ev.Add(("{0}  GRAPHICS DRIVER RESET (TDR) {1}" -f $e.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss'), $(if ($e.Properties.Count) { $e.Properties[0].Value } else { '' }))) }
$nv = @(Get-Ev @{ LogName = 'System'; ProviderName = 'nvlddmkm'; StartTime = $since })
foreach ($e in ($nv | Select-Object -First 15)) {
    $msg = ''
    try { $msg = ($e.Message -replace '\s+', ' '); if ($msg.Length -gt 160) { $msg = $msg.Substring(0, 160) } } catch {}
    $ev.Add(("{0}  NVIDIA driver event {1}: {2}" -f $e.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss'), $e.Id, $msg))
}
$lowMem = @(Get-Ev @{ LogName = 'System'; ProviderName = 'Microsoft-Windows-Resource-Exhaustion-Detector'; Id = 2004; StartTime = $since })
foreach ($e in ($lowMem | Select-Object -First 10)) {
    $msg = ''
    try { $msg = ($e.Message -replace '\s+', ' '); if ($msg.Length -gt 300) { $msg = $msg.Substring(0, 300) } } catch {}
    $ev.Add(("{0}  LOW VIRTUAL MEMORY: {1}" -f $e.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss'), $msg))
}
$kp = @(Get-Ev @{ LogName = 'System'; ProviderName = 'Microsoft-Windows-Kernel-Power'; Id = 41; StartTime = $since })
foreach ($e in ($kp | Select-Object -First 10)) { $ev.Add(("{0}  UNEXPECTED SHUTDOWN / RESTART (Kernel-Power 41)" -f $e.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss'))) }
$whea = @(Get-Ev @{ LogName = 'System'; ProviderName = 'Microsoft-Windows-WHEA-Logger'; StartTime = $since })
foreach ($e in ($whea | Select-Object -First 10)) { $ev.Add(("{0}  HARDWARE ERROR (WHEA {1})" -f $e.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss'), $e.Id)) }
if (-not $ev.Count) { $ev.Add('(nothing relevant)') }
if ($appErr.Count) {
    $mods = ($appErr | Group-Object { $_.Properties[3].Value } | Sort-Object Count -Descending | Select-Object -First 3 | ForEach-Object { '{0} x{1}' -f $_.Name, $_.Count }) -join ', '
    Flag ("Windows recorded {0} game crash(es) in 30 days, in: {1}." -f $appErr.Count, $mods)
}
if ($tdr.Count -or $nv.Count) { Flag ("GRAPHICS: the graphics driver reset or reported errors {0} time(s) in 30 days -- update or clean-install the driver; check overclocks and temperatures." -f ($tdr.Count + $nv.Count)) }
if ($lowMem.Count) { Flag ("MEMORY: Windows ran out of virtual memory {0} time(s) in 30 days. The game reserves about 8 GB: keep the page file on 'System managed' and close other programs." -f $lowMem.Count) }
if ($kp.Count) { Flag ("The PC shut down or restarted unexpectedly {0} time(s) in 30 days (power, overheating, or a hard freeze)." -f $kp.Count) }
if ($whea.Count) { Flag ("HARDWARE: Windows logged {0} hardware error(s) in 30 days (CPU, RAM or PCIe): an unstable overclock or XMP profile can crash games." -f $whea.Count) }

# ============================================================ Steam's logs
Say '  Reading Steam''s logs...'
$launch = Sec 'GAME LAUNCHES SEEN BY STEAM, LAST 30 DAYS (dated; the patch log has times only -- match its sessions with these)'
$conn = New-Object System.Collections.Generic.List[string]
$ctrl = New-Object System.Collections.Generic.List[string]
$gamePids = @{}
$steamCrashes = 0
$since30 = (Get-Date).AddDays(-30).ToString('yyyy-MM-dd')
$since14 = (Get-Date).AddDays(-14).ToString('yyyy-MM-dd')
function Exit-Meaning([string]$code) {
    switch ($code) {
        '0' { 'closed normally' }
        '-1' { 'ended by another program (the launcher, Task Manager, a tool)' }
        '-1073741819' { 'CRASH: access violation (0xC0000005)' }
        '-1073740791' { 'CRASH: fail-fast / stack buffer overrun (0xC0000409)' }
        '-1073741571' { 'CRASH: stack overflow (0xC00000FD)' }
        '-1073740940' { 'CRASH: heap corruption (0xC0000374)' }
        '-1073741676' { 'CRASH: integer divide by zero (0xC0000094)' }
        '-1073741795' { 'CRASH: illegal instruction (0xC000001D)' }
        '-1073741801' { 'CRASH: out of memory (0xC0000017)' }
        default {
            $v = 0L
            if ([long]::TryParse($code, [ref]$v)) { ('exit code {0} (0x{1:X8})' -f $code, ([uint32]($v -band 0xFFFFFFFFL))) } else { "exit code $code" }
        }
    }
}
if ($steam) {
    foreach ($n in @('gameprocess_log.previous.txt', 'gameprocess_log.txt')) {
        $p = Join-Path $steam "logs\$n"
        if (-not (Test-Path $p)) { continue }
        $sr = Open-Reader $p
        try {
            while ($null -ne ($l = $sr.ReadLine())) {
                if ($l -notmatch '1689620') { continue }
                if ($l -lt "[$since30") { continue }
                if ($l -match '^\[([\d-]+ [\d:]+)\] AppID 1689620 adding PID (\d+)') {
                    $gamePids[$Matches[2]] = 1
                    $launch.Add(('{0}  game started (pid {1})' -f $Matches[1], $Matches[2]))
                }
                elseif ($l -match '^\[([\d-]+ [\d:]+)\] AppID 1689620 no longer tracking PID (\d+), exit code (-?\d+)') {
                    if (-not $gamePids.ContainsKey($Matches[2])) { continue }
                    $when = $Matches[1]; $pidN = $Matches[2]
                    $how = Exit-Meaning $Matches[3]
                    $launch.Add(('{0}  pid {1} ended: {2}' -f $when, $pidN, $how))
                    if ($how.StartsWith('CRASH') -and $when -ge $since14) { $steamCrashes++ }
                }
            }
        } finally { $sr.Close() }
    }
    $rxIp = New-Object regex('\b\d{1,3}(\.\d{1,3}){3}(:\d+)?\b')
    foreach ($n in @('connection_log.previous.txt', 'connection_log.txt')) {
        $p = Join-Path $steam "logs\$n"
        if (-not (Test-Path $p)) { continue }
        $sr = Open-Reader $p
        try {
            while ($null -ne ($l = $sr.ReadLine())) {
                if ($l -lt "[$since30") { continue }
                if ($l -match 'IPv6|ipv6|external|public ip|PublicIP') { continue }
                if ($l -match 'ConnectionDisconnected|\[Logged On, |Log session ended|Connectivity test: result|RecvMsgClientLogOnResponse|LogOff\(\)|Reconnect') { $conn.Add($rxIp.Replace($l, '<ip>')) }
            }
        } finally { $sr.Close() }
    }
    foreach ($n in @('controller.previous.txt', 'controller.txt')) {
        $p = Join-Path $steam "logs\$n"
        if (-not (Test-Path $p)) { continue }
        $sr = Open-Reader $p
        try {
            while ($null -ne ($l = $sr.ReadLine())) {
                if ($l -lt "[$since30") { continue }
                if ($l -match 'Product:|Manufacturer:|opened for index|reserving XInput|isconnect|Steam Input|ontroller type|1689620') { $ctrl.Add($l) }
            }
        } finally { $sr.Close() }
    }
}
if (-not $launch.Count) { $launch.Add('(none found)') }
if ($steamCrashes) { Flag ("Steam saw the game end on a crash {0} time(s) in the last 14 days." -f $steamCrashes) }
$drops = @($conn | Where-Object { $_ -match 'ConnectionDisconnected' -and $_ -notmatch 'user initiated' -and $_ -ge "[$since14" })
if ($drops.Count -ge 3) { Flag ("STEAM: the PC lost its connection to Steam {0} time(s) in the last 14 days (not counting logoffs)." -f $drops.Count) }

# ============================================================ the PC
Say '  Reading the PC''s summary...'
$pc = Sec 'THE PC'
$ramTotal = 0
try {
    $os = Get-CimInstance Win32_OperatingSystem
    $ramTotal = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
    $pc.Add(("Windows: {0} ({1}), time zone {2}" -f $os.Caption, $os.Version, (Get-TimeZone).Id))
    $pc.Add(("RAM: {0} GB, {1:N0} MB free right now; commit limit {2:N1} GB ({3:N1} GB free)" -f $ramTotal, ($os.FreePhysicalMemory / 1KB), ($os.TotalVirtualMemorySize / 1MB), ($os.FreeVirtualMemory / 1MB)))
    if ($ramTotal -lt 15) { Flag ("RAM: {0} GB. The game alone uses 3 GB or more and reserves about 8 GB; with less than 16 GB, close everything else while playing." -f $ramTotal) }
} catch { $pc.Add('Windows/RAM: could not be read') }
try {
    $auto = (Get-CimInstance Win32_ComputerSystem).AutomaticManagedPagefile
    $pf = @(Get-CimInstance Win32_PageFileUsage)
    if ($pf.Count) { foreach ($f in $pf) { $pc.Add(("Page file: {0}, {1} MB allocated, {2} MB peak use, system managed: {3}" -f $f.Name, $f.AllocatedBaseSize, $f.PeakUsage, $auto)) } }
    else {
        $pc.Add('Page file: NONE')
        Flag 'MEMORY: the page file is switched off. The game reserves about 8 GB of virtual memory: without a page file it can crash when memory runs short. Set it back to "System managed".'
    }
} catch {}
try {
    foreach ($c in (Get-CimInstance Win32_Processor)) { $pc.Add(("CPU: {0} -- {1} cores / {2} threads, {3} MHz" -f $c.Name.Trim(), $c.NumberOfCores, $c.NumberOfLogicalProcessors, $c.MaxClockSpeed)) }
} catch {}
try {
    $vram = @{}
    Get-ItemProperty 'HKLM:\SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0*' -ErrorAction SilentlyContinue |
        Where-Object { $_.'HardwareInformation.qwMemorySize' } |
        ForEach-Object { $vram[$_.DriverDesc] = [math]::Round([double]$_.'HardwareInformation.qwMemorySize' / 1GB, 1) }
    foreach ($g in (Get-CimInstance Win32_VideoController)) {
        if (-not $g.CurrentHorizontalResolution) { continue }
        $v = ''
        if ($vram.ContainsKey($g.Name)) { $v = ", $($vram[$g.Name]) GB" }
        $dd = ''
        try { $dd = ([datetime]$g.DriverDate).ToString('yyyy-MM-dd') } catch {}
        $pc.Add(("GPU: {0}{1}, driver {2} ({3}), {4}x{5} at {6} Hz" -f $g.Name, $v, $g.DriverVersion, $dd, $g.CurrentHorizontalResolution, $g.CurrentVerticalResolution, $g.CurrentRefreshRate))
    }
} catch {}
$gameDisk = ''
try {
    $letter = (Get-Item $game).PSDrive.Name
    $part = Get-Partition -DriveLetter $letter -ErrorAction Stop
    $disk = Get-Disk -Number $part.DiskNumber -ErrorAction Stop
    $media = ''
    try { $media = (Get-PhysicalDisk -ErrorAction Stop | Where-Object { $_.DeviceId -eq [string]$disk.Number } | Select-Object -First 1).MediaType } catch {}
    $gameDisk = ("{0}: {1}, {2}, bus {3}" -f $letter, $disk.FriendlyName, $media, $disk.BusType)
    $pc.Add("Game drive: $gameDisk")
} catch { $pc.Add('Game drive: could not be read') }
if ($gameDisk -match 'HDD|USB') { Flag ("The game is on a hard disk or a USB drive ({0}): loading is slower, and the patch log is written to it." -f $gameDisk) }
try {
    foreach ($dl in (@((Get-Item $game).PSDrive.Name, $env:SystemDrive.TrimEnd(':')) | Select-Object -Unique)) {
        $dv = Get-PSDrive -Name $dl -ErrorAction Stop
        $freeGb = [math]::Round($dv.Free / 1GB, 1)
        $pc.Add(("Free space on {0}: {1} GB" -f $dl, $freeGb))
        if ($freeGb -lt 10) { Flag ("DISK: only {0} GB free on {1}: -- Windows needs room for the page file and the game for its caches." -f $freeGb, $dl) }
    }
} catch {}
try {
    $plan = (powercfg /getactivescheme) -join ' '
    $mm = [regex]::Match($plan, '\(([^)]+)\)')
    if ($mm.Success) { $pc.Add("Power plan: $($mm.Groups[1].Value)") }
} catch {}
try {
    $hags = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers' -ErrorAction Stop).HwSchMode
    if ($hags) { $pc.Add(("Hardware-accelerated GPU scheduling: {0}" -f $(if ($hags -eq 2) { 'on' } else { 'off' }))) }
} catch {}
$procSec = Sec 'PROGRAMS RUNNING NOW (names only)'
try {
    $procs = @(Get-Process -ErrorAction SilentlyContinue)
    $top = $procs | Group-Object ProcessName | ForEach-Object { [pscustomobject]@{ Name = $_.Name; MB = [int](($_.Group | Measure-Object WorkingSet64 -Sum).Sum / 1MB) } } | Sort-Object MB -Descending | Select-Object -First 15
    $procSec.Add('Biggest by memory: ' + (($top | ForEach-Object { '{0} {1} MB' -f $_.Name, $_.MB }) -join ', '))
    $known = 'RTSS|MSIAfterburner|obs64|obs32|Medal|Overwolf|XboxGameBar|GameBar|NVIDIA Share|RadeonSoftware|Discord|Bandicam|Fraps|ReShade|Wallpaper|lively|CheatEngine|Razer|iCUE|SignalRgb|ArmouryCrate|LGHUB|steelseries|vgc|vgtray|FACEIT|EasyAntiCheat'
    $hits = @($procs | Where-Object { $_.ProcessName -match $known } | ForEach-Object { $_.ProcessName } | Select-Object -Unique)
    if ($hits.Count) { $procSec.Add('Overlays, recorders and hardware tools running: ' + ($hits -join ', ')) }
    if (@($procs | Where-Object { $_.ProcessName -eq 'BLEACH_Rebirth_of_Souls' }).Count) { $procSec.Add('The game is running right now.') }
} catch {}

# ============================================================ the network
Say '  Testing the connection (about 20 seconds)...'
$netSec = Sec 'THE CONNECTION'
$wifi = $false
try {
    $route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop | Sort-Object { $_.RouteMetric + $_.InterfaceMetric } | Select-Object -First 1
    $ad = Get-NetAdapter -InterfaceIndex $route.InterfaceIndex -ErrorAction Stop
    $wifi = ($ad.PhysicalMediaType -match '802\.11') -or ($ad.InterfaceDescription -match 'Wi-?Fi|Wireless|WLAN')
    $kind = 'wired (Ethernet)'
    if ($wifi) { $kind = 'Wi-Fi' }
    $netSec.Add(("Internet goes through: {0} -- {1}, {2}, {3}" -f $ad.Name, $ad.InterfaceDescription, $kind, $ad.LinkSpeed))
    $vpn = @(Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' -and $_.InterfaceDescription -match 'VPN|TAP-|WireGuard|Tailscale|ZeroTier|Hamachi|Radmin|NordLynx|Proton' })
    if ($vpn.Count) { $netSec.Add('VPN-type adapters up: ' + (($vpn | ForEach-Object { $_.InterfaceDescription }) -join ', ')) }
} catch { $netSec.Add('Network adapter: could not be read') }
function Ping-Stats([string]$target, [int]$n) {
    $pg = New-Object System.Net.NetworkInformation.Ping
    $rt = New-Object System.Collections.Generic.List[int]
    $lost = 0
    for ($k = 0; $k -lt $n; $k++) {
        try { $r = $pg.Send($target, 1000); if ($r.Status -eq 'Success') { $rt.Add([int]$r.RoundtripTime) } else { $lost++ } } catch { $lost++ }
        Start-Sleep -Milliseconds 200
    }
    if ($rt.Count -eq 0) { return [pscustomobject]@{ Text = "$target -- no answer at all"; Jitter = -1; Loss = 100.0 } }
    $jit = 0.0
    for ($k = 1; $k -lt $rt.Count; $k++) { $jit += [math]::Abs($rt[$k] - $rt[$k - 1]) }
    if ($rt.Count -gt 1) { $jit = $jit / ($rt.Count - 1) }
    $s = $rt | Measure-Object -Minimum -Maximum -Average
    $loss = 100.0 * $lost / $n
    return [pscustomobject]@{ Jitter = $jit; Loss = $loss; Text = ("{0} -- min {1} ms, avg {2:N0} ms, max {3} ms, jitter {4:N1} ms, lost {5:N0} %" -f $target, $s.Minimum, $s.Average, $s.Maximum, $jit, $loss) }
}
$pings = @((Ping-Stats '1.1.1.1' 50), (Ping-Stats '8.8.8.8' 50))
foreach ($pg in $pings) {
    $netSec.Add('Ping: ' + $pg.Text)
    if ($pg.Loss -ge 2 -or $pg.Jitter -ge 8) { Flag ("CONNECTION: unstable right now -- {0}" -f $pg.Text) }
}
if ($wifi) { Flag 'CONNECTION: the PC is on Wi-Fi. Wi-Fi adds jitter and short drops, which the game turns into freezes for both players; a cable is much steadier.' }

# ============================================================ findings from the log
$allRewrites = @{}; $scheme = @{}; $kbRel = 0; $rewriteTotal = 0
foreach ($s in $sessions) {
    foreach ($w in $s.Rewrites) { $allRewrites[$w] = 1 }
    foreach ($k in $s.Scheme.Keys) { $scheme[$k] = $s.Scheme[$k] }
    if ($s.KbReleases -gt $kbRel) { $kbRel = $s.KbReleases }
    foreach ($v in $s.RewriteCount.Values) { $rewriteTotal += $v }
}
if ($scheme.Count) {
    $names = @()
    foreach ($k in ($scheme.Keys | Sort-Object)) { $nm = "scheme $($scheme[$k])"; if ($schemeName.ContainsKey($scheme[$k])) { $nm = $schemeName[$scheme[$k]] }; $names += "P$k $nm" }
    Flag ('INPUTS: control scheme seen by the input plugin: ' + ($names -join ', ') + '.')
}
if ($allRewrites.Count) {
    Flag ("INPUTS: kbhoho.dll (the input plugin added on 2026-09-28) rewrote this player's Custom SP-trigger combos: " + ($allRewrites.Keys -join ' ; ') + (". {0} trigger press(es) rewritten in all. An option select that relied on SP trigger + that button now gives another move." -f $rewriteTotal))
}
if ($kbRel -gt 0) { Flag ("INPUTS: {0} keyboard Hoho release(s) were handled by kbhoho.dll -- this player uses a keyboard, at least partly." -f $kbRel) }
$worstLoad = ($sessions | Where-Object { $_.MaxLoad -ge 0 } | Measure-Object -Property MaxLoad -Maximum).Maximum
$worstAvail = ($sessions | Where-Object { $_.MinAvail -ge 0 } | Measure-Object -Property MinAvail -Minimum).Minimum
$worstCommit = ($sessions | Where-Object { $_.MinCommit -ge 0 } | Measure-Object -Property MinCommit -Minimum).Minimum
if ($worstLoad -ge 95 -or ($null -ne $worstAvail -and $worstAvail -lt 600)) {
    Flag ("MEMORY: the PC ran out of RAM while the game ran (load up to {0} %, as little as {1} MB free). That causes freezes of several seconds, and online the other player freezes too." -f $worstLoad, $worstAvail)
}
if ($null -ne $worstCommit -and $worstCommit -lt 1500) { Flag ("MEMORY: virtual memory (commit) came down to {0} MB free during play: close to a crash. Keep the page file on 'System managed'." -f $worstCommit) }
$battles = @()
foreach ($s in $sessions) { foreach ($b in $s.Battles) { $battles += $b } }
if ($battles.Count) {
    $runAll = ($battles | Measure-Object -Property Run -Sum).Sum
    $netAll = 0.0
    foreach ($b in $battles) { $netAll += $b.NetPct * $b.Run / 100.0 }
    $pctAll = 0.0
    if ($runAll -gt 0) { $pctAll = 100.0 * $netAll / $runAll }
    $bad = @($battles | Where-Object { $_.NetPct -gt 1.0 -or $_.FeltMin -gt 1.0 })
    $far = @($battles | Where-Object { $_.Rtt -ge 120 })
    Flag ("ONLINE: {0} measured battle(s), {1:N0} min in all, frozen waiting for the network {2:N2} % of the time; {3} over the line (more than 1 % frozen or more than 1 felt freeze a minute); {4} against a far opponent (ping 120 ms or more)." -f $battles.Count, ($runAll / 60.0), $pctAll, $bad.Count, $far.Count)
} else {
    Flag 'ONLINE: no measured battle in the log (battles are measured since the 2026-10-03 New netcode update).'
}
$relayAll = ($sessions | Measure-Object -Property Relay -Sum).Sum
if ($relayAll -gt 0) { Flag ("ONLINE: Steam relayed the link to the other player ({0} log line(s) with relay 1): a relayed link adds ping." -f $relayAll) }

# ============================================================ the report
$rep = New-Object System.Collections.Generic.List[string]
$rep.Add(("BROS Diagnostic {0} -- made {1}" -f $DiagVersion, (Get-Date -Format 'yyyy-MM-dd HH:mm zzz')))
$rep.Add("Game folder: $game")
$rep.Add("Patch folder: $root")
$rep.Add('')
$rep.Add('=== WHAT STANDS OUT ===')
if ($findings.Count) { foreach ($f in $findings) { $rep.Add("- $f") } } else { $rep.Add('- nothing unusual found automatically') }
foreach ($k in @('INSTALL')) { $rep.Add(''); $rep.Add("=== $k ==="); foreach ($l in $sections[$k]) { $rep.Add($l) } }
$rep.Add('')
$launchKey = @($sections.Keys | Where-Object { $_ -like 'GAME LAUNCHES*' })[0]
$rep.Add("=== $launchKey ===")
foreach ($l in ($launch | Select-Object -Last 80)) { $rep.Add($l) }
$recent = @($sessions | Select-Object -Last 40)
$rep.Add('')
$rep.Add(("=== GAME SESSIONS IN THE PATCH LOG (last {0} of {1}; start-end times only) ===" -f $recent.Count, $sessions.Count))
foreach ($s in $recent) {
    $sch = @()
    foreach ($k in ($s.Scheme.Keys | Sort-Object)) { $nm = "scheme $($s.Scheme[$k])"; if ($schemeName.ContainsKey($s.Scheme[$k])) { $nm = $schemeName[$s.Scheme[$k]] }; $sch += "P$k $nm" }
    $ram = ''
    if ($s.MaxLoad -ge 0) { $ram = (" | RAM up to {0} %, {1} MB free at worst, commit {2} MB free at worst, handles up to {3}" -f $s.MaxLoad, $s.MinAvail, $s.MinCommit, $s.MaxHandles) }
    $nc = 'game''s own'
    if ($s.Netcode) { $nc = $s.Netcode }
    $rep.Add(("{0}-{1}  build {2}  pool {3}  netcode: {4}  kbhoho: {5}  scheme: {6}{7}" -f $s.Start, $s.LastTime, $s.Build, $s.Pool, $nc, $s.Kbhoho, ($sch -join ', '), $ram))
    foreach ($w in $s.Rewrites) { $rep.Add("      rewrite: $w") }
    foreach ($k in $s.RewriteCount.Keys) { $rep.Add(("      {0}: {1} trigger press(es) rewritten" -f $k, $s.RewriteCount[$k])) }
    if ($s.KbReleases) { $rep.Add(("      keyboard Hoho releases handled: {0}" -f $s.KbReleases)) }
    if ($s.JoinBlocked) { $rep.Add(("      joins blocked (a room of another build): {0}" -f $s.JoinBlocked)) }
    if ($s.NoMatchmaking) { $rep.Add(("      'no matchmaking yet' warnings: {0}" -f $s.NoMatchmaking)) }
    if ($s.Relay) { $rep.Add(("      relayed P2P lines: {0}" -f $s.Relay)) }
    if ($s.P2PErrors) { $rep.Add(("      P2P session errors: {0}" -f $s.P2PErrors)) }
    if ($s.CrashLines) { $rep.Add(("      CRASH lines in the log: {0}" -f $s.CrashLines)) }
    foreach ($b in $s.Battles) {
        $wanted = ''
        if ($b.Game) { $wanted = " (game wanted $($b.Game), delay $($b.Delay))" }
        $how = ''
        if ($b.How -ne 'the battle ended') { $how = " [$($b.How)]" }
        $loop = ''
        if ($s.Loop.ContainsKey($b.N)) { $loop = " | net thread $($s.Loop[$b.N])" }
        $rep.Add(("      battle #{0} ended {1}: {2}, RTT' {3} ms, D {4}{5}, {6} s, stalls {7} [{8}], felt {9} ({10}/min), longest {11} ms, network-frozen {12:N2} %{13}{14}" -f $b.N, $b.End, $b.Seat, $b.Rtt, $b.D, $wanted, $b.Run, $b.Stalls, $b.Hist, $b.Felt, $b.FeltMin, $b.Longest, $b.NetPct, $how, $loop))
    }
    foreach ($sn in $s.Snap) { $rep.Add("      $sn") }
}
foreach ($k in @($sections.Keys | Where-Object { $_ -notlike 'INSTALL' -and $_ -notlike 'GAME LAUNCHES*' })) {
    $rep.Add(''); $rep.Add("=== $k ===")
    foreach ($l in $sections[$k]) { $rep.Add($l) }
}
$rep.Add('')
$rep.Add('=== STEAM CONNECTION EVENTS, LAST 30 DAYS (last 80; IP addresses removed) ===')
if ($conn.Count) { foreach ($l in ($conn | Select-Object -Last 80)) { $rep.Add($l) } } else { $rep.Add('(none)') }
$rep.Add('')
$rep.Add('=== CONTROLLERS SEEN BY STEAM, LAST 30 DAYS (last 40 lines) ===')
if ($ctrl.Count) { foreach ($l in ($ctrl | Select-Object -Last 40)) { $rep.Add($l) } } else { $rep.Add('(none)') }

[IO.File]::WriteAllLines((Join-Path $work 'report.txt'), $rep)
$launch | Set-Content (Join-Path $work 'steam_game_launches.txt') -Encoding UTF8
$conn | Select-Object -Last 500 | Set-Content (Join-Path $work 'steam_connection.txt') -Encoding UTF8
$ctrl | Select-Object -Last 400 | Set-Content (Join-Path $work 'steam_controllers.txt') -Encoding UTF8

# ============================================================ copies, then the zip (kept under Discord's 10 MB)
function Copy-Tail([string]$src, [string]$dst, [long]$max) {
    $fs = New-Object IO.FileStream($src, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try {
        if ($fs.Length -gt $max) { [void]$fs.Seek(-$max, [IO.SeekOrigin]::End) }
        $out = [IO.File]::Create($dst)
        try { $fs.CopyTo($out) } finally { $out.Close() }
    } finally { $fs.Close() }
}
if ($crashes.Count) {
    $cd = Join-Path $work 'crashlogs'
    New-Item -ItemType Directory -Force -Path $cd | Out-Null
    $pick = @($crashes | Where-Object { $_.Name -like 'crash-unhandled-*' -or $_.Name -like 'hang-*' } | Select-Object -First 15)
    $pick += @($crashes | Where-Object { $_.Name -notlike 'crash-unhandled-*' -and $_.Name -notlike 'hang-*' } | Select-Object -First 5)
    foreach ($c in $pick) { Copy-Item $c.FullName $cd -Force }
}
$cap = 40MB
$zip = Join-Path $outRoot ("BROS_Diagnostic_{0}.zip" -f $stamp)
for ($try = 0; $try -lt 4; $try++) {
    foreach ($p in $logFiles) { Copy-Tail $p (Join-Path $work (Split-Path $p -Leaf)) $cap }
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path (Join-Path $work '*') -DestinationPath $zip -CompressionLevel Optimal
    if ((Get-Item $zip).Length -le 9.5MB) { break }
    $cap = [long]($cap / 3)
}
Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue

Say ''
Say '  WHAT STANDS OUT'
if ($findings.Count) { foreach ($f in $findings) { Say "   - $f" } } else { Say '   - nothing unusual found automatically' }
Say ''
Say ("  Done. Send this file to the patch team (Discord): {0}  ({1:N1} MB)" -f $zip, ((Get-Item $zip).Length / 1MB))
if (-not $NoPause) { Start-Process explorer.exe -ArgumentList "/select,`"$zip`"" }
