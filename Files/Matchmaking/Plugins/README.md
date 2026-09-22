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
