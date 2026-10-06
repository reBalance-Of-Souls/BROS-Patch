# Files/Matchmaking/Plugins

Every `*.dll` in this folder is mirrored by the launcher into
`<game>/ReBalanceOfSouls/` and then sha256-verified against the copy here. The
loader (`Files/Matchmaking/dinput8.dll`) loads every DLL in that folder in name
order, calls its `BrosPluginInit`, and logs the result to
`<game>/patch_ranked.log`.

Only `*.dll` is mirrored, so this README and the `.c` beside it never reach a
player's game folder. They are here so the binary is auditable.

A plugin is an add-on. If one fails to install, or declines to arm, or fails to
load, the game still runs and the launcher says so and carries on.

---

## gfx_native_scale.dll — render at your own resolution on Texture High

| | |
|---|---|
| size | 56,320 bytes |
| sha256 | `b4a86722ca276c71d7eaa7aa90e17ef7513d305f8cf18661226b168c691d4e38` |
| md5 | `85b4115181ad642d2034fa7710d1f5e9` |
| `BrosPluginId()` | `c14d1e9-dirty` |
| exports | `BrosPluginInit`, `BrosPluginId` — nothing else |
| imports | `kernel32` plus the UCRT forwarders; no file, registry, network, `LoadLibrary` or `GetProcAddress` imports |
| source | `gfx_native_scale_plugin.c`, beside this file |

### What it does

`ComputeResolutionScale` (exe RVA `0x5E4F10`) computes

```
render scale = min(nominal, max(2880 / width, 1620 / height))
```

and the *nominal* is `1.5f` when the Texture Quality byte at `0x1CEDA6D` is 1
(High) and `1.0f` when it is 0 (Low). So on High the engine has always been
rendering at a fixed 2880x1620 internal target and scaling back down to your
window — 1080p renders 1.5x, 1440p 1.125x, 4K 0.75x.

This plugin re-points the High branch's load at the `1.0f` constant the Low
branch already uses, so High renders at your window's own resolution.

**The one write, in memory only, nothing on disk:**

```
RVA 0x5E4F7B   0xBD -> 0x85

before: F3 0F 10 0D BD B3 ED 00   movss xmm1,[rip+0x00EDB3BD] -> RVA 0x14C033C = 1.5f
after : F3 0F 10 0D 85 B3 ED 00   movss xmm1,[rip+0x00EDB385] -> RVA 0x14C0304 = 1.0f
```

That is the low byte of one rip-relative operand. The four floats this routine
can select (1.0 / 1.25 / 1.5 / 2.0, at RVA `0x14C0304` / `0x32C` / `0x33C` /
`0x360`) differ only in the low byte of their operand, so a single-byte store
cannot tear and no thread can observe a half-written operand.

### What it does NOT touch

- **The cap.** The `jbe` at `0x5E4F97` is deliberately left alone, so
  `min(...)` still binds. A display is unchanged only if it is at least 2880 wide AND at least
  1620 tall (4K, 5120x2880): the cap takes the LARGER of 2880/width and
  1620/height, so any 1440-tall panel -- 2560x1440, 3440x1440, 5120x1440 --
  is bound by its height and moves 1.125 -> 1.0, like any other 1440p display.
  A display that qualifies is completely unchanged — it was already below 1.0 and stays there. Flipping
  that branch would be a large, silent performance *loss* for 4K players.
- **Textures.** Texture Quality High still loads High textures. Only the render
  resolution changes. Texture Quality Low is unchanged at every resolution,
  because Low was already 1.0.
- **The exe on disk.** Nothing is written to any file. Remove the plugin and
  the next launch is stock.
- **Anything else in the process.** The entire `.text` contains exactly one
  store into the game image: `mov byte ptr [rbx], 0x85`, and it executes only
  after `claim()` has granted the bytes and `VirtualProtect` has succeeded.

### It declines rather than guesses

Before writing anything it checks, and on any of these it logs one line, writes
nothing, and returns 0 (the game runs at the stock scale):

- the host ABI is not 1, or the host does not offer `mod` / `log` / `claim`;
- the site is outside the image it was handed;
- `native_scale_off.txt` exists beside the exe (see below) — it declines
  *before* claiming, so the bytes stay free for anything else;
- any of the 34 bytes of the window at `0x5E4F77` is not this exe's stock
  `ComputeResolutionScale`, the cap's `jbe` included — so an exe where someone
  removed the `min()` is refused;
- the operand is already something other than the stock `0x00EDB3BD` (somebody
  else set the render scale);
- the constant the new operand would point at does not read `1.0f`;
- the loader's claim registry refuses the 4 bytes at `0x5E4F7B` because another
  plugin owns them (the refusal names the other owner);
- `VirtualProtect` fails.

If the operand already reads `0x00EDB385` it returns 1 and writes nothing, so
it is idempotent.

All of the above except the `VirtualProtect` failure were exercised against a
real mapping of the stock exe, including all 34 single-byte corruptions, and
none of them wrote a byte.

### How a player turns the resolution change off

Put an **empty file named `native_scale_off.txt`** next to
`BLEACH_Rebirth_of_Souls.exe` and relaunch. That file is not a `.dll`, so the
launcher's plugin mirror never deletes it, and it survives every update. The
log then says:

```
NATIVE/scale: native_scale_off.txt is present beside the exe -- declined on purpose, stock render scale
```

Delete the file to turn it back on.

### How to verify it applied

Read `<game>/patch_ranked.log` after a launch. **Not** the launcher's console —
the launcher hides its console window at startup, so `[plugins] installed ...`
goes nowhere you can see. `grep` the log; it is large.

Four lines to look for:

1. `BROS/plugins: BROS_PLUGIN_HOST_ABI=1 -- ReBalanceOfSouls\ holds 1 .dll; loading them in name order`
   — the folder was found.
2. `BROS/plugins: ... "gfx_native_scale.dll" armed.` — it loaded and armed.
3. `NATIVE/scale [c14d1e9-dirty]: RVA 0x5E4F7B disp32 0xEDB3BD -> 0xEDB385, so ComputeResolutionScale's nominal is now 1.0 ...`
   — the byte went in, and the `[...]` names the build.
4. `BROS/plugins: 1 found, 1 armed, 0 declined, 0 not plugins; 1 exe range(s) claimed, 0 refused.`

If it did not take, the log says which of the above it was:

- `"gfx_native_scale.dll" declined to arm (returned 0)` — read the
  `NATIVE/scale:` line directly above it; it names the reason.
- `BROS/claim: ... REFUSED` — another plugin owns `0x5E4F7B`.
- `loader armed -- but there is no ReBalanceOfSouls\ folder beside the exe, or
  it holds no .dll` — the plugin was not installed at all.
- **No `BROS/plugins` lines at all** — that session ran a loader with no plugin
  host. The in-app Quick Launch buttons (Training Mode, Room Match) and the
  Reawakening Battle toggle install the frozen `GameModes/<mode>/dinput8.dll`,
  which cannot host plugins; the launcher deletes the installed plugin for
  those runs and the next default launch puts it back.

### How it was built

Built from `gfx_native_scale_plugin.c` (this folder) with the C-track repo's
own `build_plugin.sh` and its vendored Zig 0.16.0, target
`x86_64-windows-gnu`:

```
zig cc -target x86_64-windows-gnu -std=c11 -Os -fno-asynchronous-unwind-tables \
       -Wall -Wextra -Wundef -Werror=undef \
       -Wno-unused-parameter -Wno-cast-function-type \
       -DWIN32_LEAN_AND_MEAN -fms-extensions -Wno-date-time -shared \
       -DPATCH_BUILD_ID="\"c14d1e9-dirty\"" \
       -I <c-track>/src/vfs -I <c-track>/src/plugins/gfx_native_scale \
       -o gfx_native_scale.dll gfx_native_scale_plugin.c -lkernel32
```

`bros_plugin.h` lives in that private repo and is not reproduced here. The
plugin reads exactly five of its fields — `abi` (+0), `size` (+4), `mod` (+8),
`log` (+0x10) and `claim` (+0x28) — and the shipped
`Files/Matchmaking/dinput8.dll` assigns all five at those offsets, which is why
the ABI-1 contract holds without the header. Every field is guarded with
`BROS_HOST_HAS`, never `host->size < sizeof(BrosHost)`: the shipped loader
advertises size 96 while the header is larger, and a `sizeof` test would make
the plugin decline for no reason.

The build was reproduced independently from this source and came out
byte-identical to the DLL committed here.

One honest note: the comments in this `.c` were corrected after that build (the
"change one constant" line was wrong — a 1.25 variant is a three-constant
edit). Comments do not reach the binary; strip the block comments from this
file and from the build tree's copy and the code text is byte-identical.

### If you change it

The five `_Static_assert`s at the top are the safety net for the one-byte
store. If you retarget the nominal (say to 1.25), you must move
`NS_DISP_NATIVE`, `NS_FLOAT_RVA` **and** `NS_FLOAT_ONE` together; a partial
edit, or a target whose operand differs above its low byte, fails to compile.
Do not "fix" that by deleting the assert — write all four operand bytes under
the existing claim instead, which already covers them.

---

## kbhoho.dll — inputs that behave the same as Type A, on a Custom scheme and on keyboard

| | |
|---|---|
| size | 192,000 bytes |
| sha256 | `0e11639d03e2139c9d7c0ef34977e0a22eef389a2678d31055074a3401e7a2e6` |
| md5 | `db963dffa383a3f5a3eae2d8969d5613` |
| built from | dev environment commit `360daed` (source), shipped there as `f91d230` |
| exports | `BrosPluginInit` — nothing else |
| imports | `kernel32` (`CreateThread`, `Sleep`, critical sections, `VirtualProtect`, `VirtualQuery`, `TlsGetValue`, `GetLastError`, `CloseHandle`) plus the UCRT forwarders; no file, registry, network, `LoadLibrary` or `GetProcAddress` imports |
| source | `kbhoho_plugin.c`, beside this file |

### What it fixes

**1. Custom control schemes: an SP-trigger combo can fire the wrong move.** In a
Custom scheme, the button of an SP-trigger combo can also carry an attack. The game
emits that attack every frame the button is held, whether or not the trigger is down.
The two reported cases are both vanilla, with Signature Move on A, Kikon Move on B,
Hohō = trigger + A and SP2 = trigger + B:

- hold guard and input the Hohō: **SP2 comes out**. Signature + trigger is SP2 in the
  combo tables, and the game does not allow the Hohō while guarding.
- Hakugeki → yellow Reverse → SP2: **a Hakugeki comes out**. The game does not accept the
  dedicated SP command during a Reverse, so the Kikon Move on B wins.

Type A never has either overlap. The plugin makes a Custom scheme resolve like Type A:
while the trigger and a combo's button are both held, that button counts as the attack
Type A puts on it, and as nothing else. The rule stays on until that button is released:

| combo | counts as |
|---|---|
| SP1 | Flash Attack |
| SP2 | Signature Move |
| Reverse | Quick Attack |
| Hohō | no attack (Type A's Hohō button is Step/Dash) |

**2. Keyboard: the Hohō after an attack is less reliable than on a pad.** On a pad,
releasing the Hohō button while the trigger is held asks for the Hohō a second time.
The keyboard path does not. The plugin makes a keyboard release behave like the pad's.

### What it writes

- **One pointer in the game image, claimed.** Slot 2 of the `BrainPad` vtable (RVA
  `0x142C058`, 8 bytes) is swapped for a wrapper around the original function
  (`0x140410ED0`). This is done only after `claim()` grants the 8 bytes, and only if the
  slot still holds the stock function. The wrapper always calls the original.
- **Only for the length of that call:**
  - Custom scheme: the five attack masks of the player's `BrainPad` object (heap memory,
    not the exe) are rewritten as described above, then put back when the call returns.
  - Keyboard: one entry of the game's key table gets its pressed bit, then is put back.
- **Nothing on disk.** Remove the plugin and the next launch is stock.

### What it does NOT touch

- **Type A, Type B and Type C.** Their buttons already follow the rule, so the plugin
  leaves them alone. Type C is left exactly as the game ships it.
- **A Custom scheme with "Unpair Spiritual Pressure Move Trigger" on.** There is no
  trigger combo in that mode.
- **No command is added or removed.** Every command still comes from the game's own
  code. The only change is which button the game thinks is held.
- **Online.** Each client runs the input conversion for its own player only, so the change
  is made before the input leaves the machine, and both clients see the same match.
  Checked on a two-client room match.

### It declines rather than guesses

It logs one line, writes nothing, and returns 0 (the game runs stock) if:

- the host ABI is not 1;
- the `BrainPad` vtable slot does not hold the stock `BrainPad::vfunc2`;
- the loader's claim registry refuses the 8 bytes at `0x142C058`, because another plugin
  owns them;
- `VirtualProtect` fails.

### How to verify it applied

In `<game>/patch_ranked.log`:

1. `KBHOHO: ARMED -- ...` and `BROS/plugins: ... "kbhoho.dll" armed.`
2. Once per player per session, at the first battle:
   `KBHOHO/diag: BrainPad P1 (...) first active call -- scheme N, unpaired N; hoho .. trig .. ...`.
   Scheme 3 is Custom. The masks are the buttons as the game sees them.
3. On a Custom scheme that needs the rule, one line per combo:
   `KBHOHO/pad: P1 Custom, SP2 = SP trigger + button 0x10, which is Kikon Move -- with the trigger down it counts as Signature Move, as in Type A`.
4. While playing: `KBHOHO/pad: <combo> -- N trigger press(es) rewritten to Type A so far`.

### How it was built

Built from `kbhoho_plugin.c` (this folder) with the dev environment's `build_plugin.sh`
and Zig, target `x86_64-windows-gnu`:

```
zig cc -target x86_64-windows-gnu -O2 -fms-extensions -Xclang -fasync-exceptions \
       -Wno-date-time -shared -DPATCH_BUILD_ID="\"360daed-20260927-dirty\"" \
       -o kbhoho.dll kbhoho_plugin.c
```

`-Xclang -fasync-exceptions` is required. Without it, the `__try` blocks around the
plugin's reads catch nothing.

`bros_plugin.h` is not reproduced here. The plugin reads four of its fields: `abi` (+0),
`mod` (+8), `log` (+0x10) and `claim` (+0x28). The shipped
`Files/Matchmaking/dinput8.dll` assigns all four, and was checked to load it:
`3 found, 3 armed, 0 declined ... 3 exe range(s) claimed, 0 refused`.

---

## pacing.dll — the game's frame limiters sleep instead of spinning, on a fixed schedule

| | |
|---|---|
| size | 190,976 bytes |
| sha256 | `fa231a86eafaf5c6550f693fd857516dc16a07aef252e6faa9224751075b2498` |
| md5 | `11b0e916499bce8c57ac5b96cd6df307` |
| `BrosPluginId()` | `725f4e3-20261006` |
| built from | dev environment commit `725f4e3` (source), shipped there as `87c62b8` |
| exports | `BrosPluginInit`, `BrosPluginId` — nothing else |
| imports | `kernel32` (`CreateWaitableTimerExW`, `SetWaitableTimer`, `WaitForSingleObject`, `SwitchToThread`, `TlsAlloc`/`TlsGetValue`/`TlsSetValue`, `VirtualProtect`, `FlushInstructionCache`, `CreateThread`, `Sleep`, `GetModuleFileNameA`, `CreateFileA`, `ReadFile`, `GetFileAttributesA`, `CloseHandle`, ...) plus the UCRT forwarders; no registry, network, `LoadLibrary` or `GetProcAddress` imports |
| source | `pacing_plugin.c`, beside this file |

### What it fixes

The game runs two frame limiters: one on the render loop (exe RVA `0x9E6FA0`)
and one on the main thread (`0x9E7300`). Both are the same loop:

```
while ((now - mark) / 1000 < 1000000 / fps)
    SwitchToThread();
mark = now;
```

- The loop spins for the whole slack of every frame, on two threads, and
  `SwitchToThread` gives the core to any other ready thread: the loop can get it
  back a scheduler quantum late, past the frame's deadline.
- `mark = now` keeps every overshoot, so the frame rate drifts below 60 and
  never catches up.

Measured on 2026-10-06 with two clients on one PC (Ryzen 7 2700X), each pinned
to its own 4 cores, Byakuya mirror room match, ~5 minutes per battle:

| build | fps, host / guest | frames over 33 ms per minute | 95th percentile frame |
|---|---|---|---|
| vanilla | 57.0 / 57.5 | 85 / 66 | 24.5 ms |
| patch, before this plugin | 56.9 / 57.6 | 89 / 69 | 25.0 ms |
| patch with this plugin | 59.8 / 59.7 | 4 / 6 | 18.4 ms |

The patch measured the same as vanilla online: the drops come from the stock
limiter, and vanilla has them too. In Training, one client: 58.5–58.9 fps and
32–40 frames over 33 ms per minute before, 59.9–60.0 fps and 0–4 with the plugin.

### What it does

- **The wait.** The `SwitchToThread` call in each loop (`0x9E700D`, `0x9E7370`)
  goes to a function that sleeps on a high-resolution waitable timer until about
  1 ms before the frame is due, then spins on `PAUSE` without giving the core
  away. The loop's own test still decides when the frame is due.
- **The schedule.** Where the loop stores `mark = now` (`0x9E704B`, `0x9E73C0`),
  the mark becomes the previous mark plus one frame interval, so one late frame
  is made up by the next one. If a frame is a whole interval late, the mark is
  set to now, so the game never plays a burst of catch-up frames. The interval
  comes from the game's own frame-rate words (`[timer+0x80]`, `[timer+0x82]`),
  read every frame.

### What it does NOT touch

- **Gameplay.** No simulation, input, netcode or data code is changed. Every frame
  is still one game frame; only the moment the wait before it ends changes.
- **Online sync.** Both players still advance one frame at a time and still wait
  for each other's inputs exactly as before. The netcode's own pacing (PART 41 in
  the loader) is unchanged.
- **The exe on disk.** Nothing is written to any file. Remove the plugin and the
  next launch is stock.

### It declines rather than guesses

It logs one line, writes nothing and returns 0 (stock limiters) if:

- the host ABI is not 1, or the host does not offer `mod` / `log` / `alloc_near` / `claim`;
- `pacing_off.txt` exists beside the exe (see below); it declines before claiming;
- any of the 35 bytes at the four sites is not this exe's stock code;
- `pacing.txt` says `wait 0` and `abs 0`;
- the loader's claim registry refuses one of the four ranges (another plugin owns it);
- no stub memory is available near the exe.

On a Windows without high-resolution waitable timers (before Windows 10 1803) it
keeps the stock `SwitchToThread` wait, because a plain timer wakes on the 15.6 ms
tick, and only the schedule half applies. The log says so.

### How a player turns it off

Put a file named **`pacing_off.txt`** (any content) next to
`BLEACH_Rebirth_of_Souls.exe` and relaunch. It is not a `.dll`, so the launcher's
plugin mirror never deletes it. The log then says:

```
PACING: pacing_off.txt is beside the exe -- declined on purpose, stock frame limiters
```

Delete the file to turn it back on. For a test, `pacing.txt` beside the exe takes
`wait 0` (stock wait, schedule kept) or `abs 0` (sleep kept, stock `mark = now`).

### How to verify it applied

In `<game>/patch_ranked.log`:

1. `PACING: ARMED [725f4e3-20261006] -- wait 1 (high-resolution timer sleep, then PAUSE spin), abs 1 (absolute schedule) ...`
2. `BROS/plugins: ... "pacing.dll" armed.`
3. 30 s after the start, then every 5 minutes:
   `PACING: 30 s -- 1799 waits slept on the timer, marks 3597 on schedule / 1 reset to now`.
   About 3600 marks in 30 s means both loops ran at 60 frames per second. A few
   resets are normal (loading screens).

### How it was built

Built from `pacing_plugin.c` (this folder) with the dev environment's
`build_plugin.sh` and Zig, target `x86_64-windows-gnu`, from a `git archive` of the
committed sources:

```
zig cc -target x86_64-windows-gnu -O2 -fms-extensions -Xclang -fasync-exceptions \
       -Wno-date-time -shared -DPATCH_BUILD_ID="\"725f4e3-20261006\"" \
       -o pacing.dll pacing_plugin.c
```

`bros_plugin.h` is not reproduced here. The plugin reads six of its fields: `abi`
(+0), `size` (+4), `mod` (+8), `log` (+0x10), `alloc_near` (+0x18) and `claim`
(+0x28), each checked against `size` before use. The shipped `Files/Matchmaking/dinput8.dll`
(`e525118-stackscan`) was checked to load it: `4 found, 4 armed, 0 declined ...
13 exe range(s) claimed, 0 refused`.
