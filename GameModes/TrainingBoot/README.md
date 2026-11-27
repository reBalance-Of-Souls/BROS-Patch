# TrainingBoot — boot straight into the Training character select

> **No Quick Launch installs this folder's loader since 2026-11-06.** The Quick
> Launch scripts were baked into the launcher: its right-click menu's Training
> entry starts the game with the normal loader (`Files/Matchmaking/dinput8.dll`)
> and `BROS_BOOT_MODE=training`, which that loader reads at startup, with
> default rules -- or a developer's mode (`BROS_GAME_MODE`,
> `BalanceLeadTools/DevGameMode.txt`, gated as before, now in
> `launcher/quick_menu.py`). This folder's own `dinput8.dll` is installed only
> when a developer names `TrainingBoot` as that mode. What follows is its
> record.

Not a game mode. A **launch shortcut**: the game goes logos → Training character
select, skipping the title screen and the menu walk. Started with
`Quick Launch Training Mode.py` (until 2026-11-06), never from the launcher's
game-mode list.

**Status: CONFIRMED IN GAME 2026-08-26**, on the third attempt.

It lives under `GameModes/` only because that is where `setup_matchmaking()`
looks for a folder's own `dinput8.dll` — the same plumbing Reawakening Battle
and 4-5 use. There is **no `Script/`**, so the data layer is a no-op
(`layers.build_stack` guards that with `is_dir()`).

## ⚠ Two wrong attempts, both of which logged success

Worth keeping, because the failure is the instructive part.

The SLogo owner (`0x140750B10`) contains two `lea rdx,"JUMP_Title"` sites, at
RVA `0x750BCB` and `0x750C2C`. Repointing both at
`JUMP_TrainingCharacterSelect` looked exactly right, verified its guard bytes,
logged three confident success lines — and changed nothing whatsoever. Those two
sites sit on the branch taken when the scene already has an explicit command
pending in `[SLogo+0xB0]`, which never happens on a normal boot.

**Patching a site and watching a log line confirm it is not the same as patching
the site that runs.**

**Second attempt: right site, no mode.** Sending the scene jump from the live
handoff (below) did leave the logos and land on a character select — the
*offline versus* one. The character select is a single shared scene; which mode
it runs in comes from a global setup object that the jump does not touch. So the
first attempt proved nothing happened, and the second proved something happened
but not the right thing. Only the second was progress.

## What it actually patches

The path that runs is:

```
0x140750B66  je 0x140750C66          ; [SLogo+0xB0] empty -> normal boot
0x140750C69  call 0x14074F810        ; SLogo::Update
0x140750C70  je  ...                 ; returned 0 -> nothing to do yet
0x140750C72  mov rax,[rdi]
0x140750C75  mov rbx,[rax+0x88]      ; flow vtable slot 0x88
0x140750C83  lea rdx,[rip+0xD483FE]  ; "LOGO_NEXT"
0x140750C9C  call rbx
```

So **the boot never names its destination.** It raises the *event* `LOGO_NEXT`,
and the flow graph — built by the 32 KB function at `0x140866050` — is what maps
that event to the Title state. Slot `0x88` is the generic "send this request by
name" method; `SLogo` state 10 uses the same one for `INIT_OPTION` and
`INIT_FONT`.

Rather than rebuild a graph edge, the patch sends a scene **jump** from that
site instead of the event. `0x14089E310` is the flow's "jump to scene by name"
entry — a free function in no vtable, taking exactly `(rcx = flow,
rdx = &tsd::string)`, which is the signature `call rbx` is already set up for.
It builds its own singleton at `0x141CFBD18` lazily, so it needs no other state.

Two edits, no trampoline, and the site's own string construction is reused:

```
RVA 0x750C72  48 8B 07 48 8B 98 88 00 00 00   mov rax,[rdi]; mov rbx,[rax+0x88]
          ->  48 BB <mod+0x89E310>            movabs rbx, <jump dispatcher>

RVA 0x750C86  the lea's disp32:  "LOGO_NEXT" -> "JUMP_TrainingCharacterSelect"
```

Ten bytes and four bytes exactly, so nothing moves. `rax` is dead after the
replaced pair — its only would-be reader is the string constructor call at
`0x750C8F`, which clobbers it as its own return value. The result disassembles
as:

```
movabs rbx, 0x14089E310
mov    r8, -1
lea    rdx, "JUMP_TrainingCharacterSelect"
lea    rcx, [rsp+0x20]
call   <string ctor>
lea    rdx, [rsp+0x20]
mov    rcx, rdi
call   rbx
```

— the same shape as the two dead `JUMP_Title` sites, which is the point.

## Setting the mode

The jump alone lands on offline versus. The normal issuer — `0x1406EC3E3`,
reached when the menu selection is 6 — shows the missing half:

```
0x1406EC3F0  mov rax,[0x141CFBAB8]       ; setup singleton, created on demand
             ...if NULL: new(0x4D0), ctor 0x14082CF10, store the RETURN value
0x1406EC41B  mov dword [rax+0x228], 6    ; <-- the mode
0x1406EC42C  lea rdx,"JUMP_TrainingCharacterSelect"
```

`+0x228 = 6` is the whole difference. It is the **only** write to that field in
the 11,401-byte issuer, and it sits immediately before the Training jump.

That singleton is lazily created, so at logo time it may still be NULL — which
is why this half cannot be a byte patch. `call rbx` is therefore pointed at a C
function in this DLL rather than straight at the dispatcher: `boottr_handoff`
takes the site's own `(rcx = flow, rdx = &string)`, does the
singleton-and-mode dance the way the issuer does, then tail-calls the real
dispatcher. A plain C function is already `(rcx, rdx)` under the MS x64 ABI,
preserves the non-volatiles the site relies on (`rdi` has to survive to
`0x140750C9E`), and the frame that just called the string constructor at
`0x750C8F` already has the shadow space for it.

The `imm64` is written at patch time from the **runtime** address of that
function, so it is ASLR-correct, and the guard pins all 44 bytes of the window
before anything is touched.

Full write-up: `DataChakka/guides/Nilsix researches/Boot Sequence/`.

## The loader

Built from the one canonical source, `Files/Matchmaking/dinput8_proxy.c`, with
`-DENABLE_BOOT_TRAINING=1`:

```
cl /nologo /O2 /DNDEBUG /DENABLE_BOOT_TRAINING=1 /W3 /LD dinput8_proxy.c ^
   /Fe:dinput8.dll /link kernel32.lib user32.lib
```

That is the whole answer to "will it stay on the same version as the main DLL":
it **is** the main DLL's source with one extra flag, so it carries Byakuya's
gauge, fast boot, the room-match fixes and the crash guards exactly as the
default loader does — and no experimental mode.

⚠ **Rebuild it whenever the default loader is rebuilt**, or the two drift. Same
caveat as `4-5/` and `ReawakeningBattle/`.

## No pool tag, on purpose

Meri's mode and Reawakening Battle shift `g_issuer` because a client running
them simulates a different fight and would desync against a stock patched
client. This one does not: it changes **which scene the flow hands off to**, and
nothing else.

## ★ Version parity with the default loader

The point of building this from the one canonical source is that a player on
this shortcut and a player launching normally are on **the same build**.
Verified rather than assumed, three ways:

**1. The same patches.** Comparing the two DLLs' log-string inventories, every
patch matches — VERSION, SELFCOST, BYAKUYA_GAUGE, STAGEGATE, TEARDOWN,
ROOMRESULT, REMATCHWAIT, the three ROOMGUARDs, FASTBOOT — and MERI and REAWAKEN
are `DISABLED` in both. **The only difference in the whole inventory is
`BOOTTRAIN`.**

**2. The same balance data.** Diffing `Quick Launch Training Mode.py` against
`Quick Launch Community Patch.py` with comments stripped, the *entire* delta is
the `gameMode` value, the mode-loader pick in `setup_matchmaking()`, and an
`os.path.exists` guard around the mode's `Script/` copy. **Nothing in the data
injection differs**, both carry `GAME_VERSION = "Bleach Rebirth of Souls
Community Patch"`, and TrainingBoot ships no `Script/` — so the balance patch
lands identically.

**3. The same online pool.** The match code is

```python
seed = f"{build}|{gameVersion}"
code = 100000 + (zlib.crc32(seed.encode("utf-8")) % 800000)
```

`build` is the repo's commit SHA and `gameVersion` is that same string in both
scripts. **`gameMode` is not in the seed.** So the two launches compute the same
pool code and can match each other — which is correct here, because unlike
Meri's mode and Reawakening Battle this loader changes no simulation and has no
pool tag.

The one thing to keep true: **rebuild this loader whenever the default one is
rebuilt.** Nothing enforces it. All four loaders — default, TrainingBoot, 4-5,
ReawakeningBattle — were last rebuilt together on 2026-08-26 when
`patch_skip_logos` landed, so they are in step as of that commit.

*Not measured:* the thunk leaves `setup+0x228` at 6. Every menu transition
writes that field for its own destination, so walking to online from here should
overwrite it before a match — reasoning, not a measurement.

## Status

**Confirmed in game 2026-08-26.** Boot lands on the Training character select.

Three attempts, and the first two both logged success:

1. patched a dead site — proved nothing happened;
2. patched the live site — proved something happened, but landed on offline
   versus;
3. added the mode write — correct.

**`JUMP_DirectTrainingMode`** (RVA `0x14A84E0`) was never needed, but it stays
noted as the alternative destination: a one-constant change to
`BOOTTR_JUMP_TRAINING_RVA`.

The log says what was rewritten rather than merely that a byte matched:

```
BOOTTRAIN: LOGO_NEXT handoff at RVA 0x750C72 rewritten -- the logo scene now
           calls <thunk>, which sets the setup singleton's mode to Training and
           then sends JUMP_TrainingCharacterSelect to the dispatcher at <addr>
BOOTTRAIN: setup singleton <ptr>, mode +0x228 set to 6 (Training) before the jump
```

The second line comes from the game thread at the moment of the handoff, so its
absence means the rewritten site never ran.
