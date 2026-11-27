# RoomMatchBoot — boot straight into the online room-match menu

> **No Quick Launch installs this folder's loader since 2026-11-06.** The Quick
> Launch scripts were baked into the launcher: its right-click menu's Room Match
> entry starts the game with the normal loader (`Files/Matchmaking/dinput8.dll`)
> and `BROS_BOOT_MODE=roommatch`, which that loader reads at startup. This
> folder's own `dinput8.dll`, an older build than the normal loader, is
> installed only when a developer names `RoomMatchBoot` as a game mode; it also
> put its players in another matchmaking pool than a normal launch (the
> MATCHFIND investigation, cause C2). What follows is its record.

Not a game mode. A **launch shortcut**, the sibling of `TrainingBoot`: the game
goes logos → **Room Match** (Create room / Find room), skipping the title screen
and the menu walk. Started with `Quick Launch Room Match.py` (until 2026-11-06),
never from the launcher's game-mode list.

It lives under `GameModes/` only because that is where `setup_matchmaking()`
looks for a folder's own `dinput8.dll`. There is **no `Script/`**, so the data
layer is a no-op (`layers.build_stack` guards that with `is_dir()`).

## What it patches

Exactly the mechanism `TrainingBoot/README.md` documents, aimed somewhere else —
read that one first, it carries the full derivation and the two wrong turns.

The boot raises the *event* `LOGO_NEXT` through the flow's vtable slot `0x88`
and the flow graph maps that to Title. The patch rewrites that handoff to call a
C function in this DLL, which prepares state and then sends a scene **jump**
through `0x14089E310`, the flow's "jump to scene by name" entry.

```
RVA 0x750C72  mov rax,[rdi]; mov rbx,[rax+0x88]  ->  movabs rbx, <thunk>
RVA 0x750C86  the lea's disp32:  "LOGO_NEXT"     ->  "JUMP_RoomMatchMenu"
```

## The state it prepares — and why it differs from Training

Training needed the setup singleton's mode written (`+0x228 = 6`). **Room match
does not**: its normal issuer writes no mode at all.

```
0x1407E681F  mov ecx,[0x141CDF2E8]     ; 0 rank, 1 room match, 2 free match
0x1407E682D  sub ecx,1
0x1407E6830  je  0x1407E6847           ; -> the room-match branch
0x1407E6847  mov r8,-1
             lea rdx,"JUMP_RoomMatchMenu"
             mov rcx,rdi
0x1407E6865  call 0x14089E310          ; the same dispatcher
```

By the time that branch runs the online menu has already chosen, and the choice
lives in the selector at `0x141CDF2E8`. So the thunk writes **1** there and
jumps — the online-mode equivalent of what the Training thunk does with
`+0x228`.

Everything after the `lea` in that issuer (`"RoomMatch"`, `"Online"` strings
built at `0x1407E6888`/`0x1407E68AD`) is telemetry, not setup, and is not
replicated.

## The risk specific to this one — answered

TrainingBoot skips the Title flow and gets away with it because Training is
offline. This one lands on an **online** screen, and the Title flow is where
`JUMP_TitleOnlineCheck` runs, so it was an open question whether the online
subsystem would be ready at logo time and whether Steam would be up before the
menu needed it.

**Both are fine in practice** — the menu comes up and works. `JUMP_TitleOnlineCheck`
was never needed. What is *not* fine is coming back out; see the known bug
below.

## The loader

Built from the one canonical source, `Files/Matchmaking/dinput8_proxy.c`, with
`-DENABLE_BOOT_ROOMMATCH=1`:

```
cl /nologo /O2 /DNDEBUG /DENABLE_BOOT_ROOMMATCH=1 /W3 /LD dinput8_proxy.c ^
   /Fe:dinput8.dll /link kernel32.lib user32.lib
```

So it is the default loader plus this one patch — same balance data, same
patches, same online pool. `ENABLE_BOOT_ROOMMATCH` and `ENABLE_BOOT_TRAINING`
are **mutually exclusive**: they rewrite the same handoff, and each ships as its
own loader.

⚠ **Rebuild it whenever the default loader is rebuilt**, or the two drift. Same
caveat as the other mode folders.

## Version parity

Same as `TrainingBoot` and verified the same way: the match code seeds on
`f"{build}|{gameVersion}"`, `gameMode` is not in the seed, and
`Quick Launch Room Match.py` differs from `Quick Launch Training Mode.py` by
**one code line** — the `gameMode` value — with 229 code lines each. So a player
on this shortcut is in the same pool as one launching normally, which is correct
because this loader changes no simulation and carries no pool tag.

## ⚠ KNOWN BUG: Back from the room-match menu lands on the Story menu

**Confirmed in game 2026-08-26.** Getting *into* room match works. Pressing
Return from it lands on the **Story** menu, which then ignores Return — pressing
Confirm once unsticks it, and Return then goes to the main menu normally.

**Cause.** The dispatcher records where you came from. `0x14089E310` is a
two-argument wrapper that forwards its first argument as the third argument of
the real entry:

```
0x14089E364  mov r8, rsi          ; rsi = the wrapper's rcx = the calling scene
0x14089E36D  call 0x1408A06E0     ; (flow singleton, &string, calling scene)
```

The normal issuer passes `rdi`, the **online menu scene**, so Return pops back
to it. The patched handoff passes the site's own `rdi`, which is the **logo
scene's owner** — an object torn down moments later. So the flow's history holds
a dead entry, and Return resolves it to whatever that slot decays to.

**The fix is routing, not a value.** Send `JUMP_MainMenu` from the logo handoff,
let the flow build normally, then issue `JUMP_RoomMatchMenu` *from the main menu
scene* once it exists — that produces a real history entry and Return works.
That needs a second trigger after the main menu is up, so it is not a one-line
change to this patch.

**Traced further, 2026-08-26.** The calling scene is not stored as a pointer —
it is used to *derive a record*:

```
0x1408A084A  mov  r8, r13              ; the calling scene
0x1408A0851  call 0x14089F110          ; -> a record, kept in r13
0x1408A088E  lea  r12,[r13+0x18]       ; the record holds STRINGS at +0x18,
0x1408A08C3  lea  r12,[r13+0x30]       ; +0x30, +0x48 and an int at +0x60
```

So the history entry is the previous scene's **name**, derived from the object.
Handing it a torn-down object yields a garbage name, which is why Return
resolves to an unrelated screen instead of failing outright.

That also rules out the cheap escape: **passing NULL is not safe**, because the
pointer goes straight into `0x14089F110` to be read, not into a null-checked
slot.

**There is also no jump command for the Online screen.** Dumping every triple in
the registry at `0x140864100` shows `"Online"` is a *group* — its entries are
`RankMatch`/`FreeMatch`/`RoomMatch`/`BattleSetting` — and the Online screen
itself is a state of the main menu, not a destination. So "boot to the Online
menu instead" is not a one-constant change either.

## ★★ The real answer: JUMP is the wrong verb

Dumping every named state and every transition string out of the flow builder at
`0x140866050` settles it. The flow has **167 named states**, each with its own
handler function, and transitions between them are **events**, not jumps:

```
state  TitleOnlineCheck   handler 0x1408760A0
state  TitleOnline        handler 0x140878260     <- the ONLINE screen
state  Menu               handler 0x1408756D0
state  RoomMatch          handler 0x1408794F0

MOVE_PUSH_ONLINE       TitleOnlineCheck -> TitleOnline
MOVE_PUSH_ROOMMATCH    TitleOnline      -> RoomMatch
BACK_ONLINE_MENU       the return edge the menus use
```

★ **`MOVE_PUSH_*` is what builds the history.** A `JUMP_*` replaces the current
state; a `PUSH` stacks it so `BACK_*` can unwind. Every menu navigates with
`MOVE_PUSH_`, and this patch has been sending `JUMP_RoomMatchMenu` — arriving at
the right screen with nothing underneath it. That is the bug, not the calling
scene: the calling scene only decided *which* garbage name the empty stack
decayed to.

Note also that the ONLINE screen **is** a state, `TitleOnline` — the earlier
conclusion that it was only a main-menu sub-state was wrong. It has no `JUMP_`
command because nothing jumps to it; it is reached by `MOVE_PUSH_ONLINE`.

### The plan this gives

Events go through the flow's **vtable slot `0x88`** — the same method the
untouched boot uses for `LOGO_NEXT`, and the one `SLogo` state 10 uses for
`INIT_OPTION`. So the shape is:

1. leave the boot handoff **alone** — let `LOGO_NEXT` run and the flow reach
   Title/Menu normally, history intact;
2. hook the entry of the state handler that is live when we want to move on
   (`0x1408760A0` for `TitleOnlineCheck`, then `0x140878260` for `TitleOnline`);
3. from each, send the next `MOVE_PUSH_*` once, then disarm.

That arrives at Room Match with a real stack under it, so `BACK_ONLINE_MENU`
lands on the ONLINE screen exactly as it does in normal play — which is what was
asked for.

**Not implemented yet.** It replaces the current `JUMP_RoomMatchMenu` approach
rather than extending it, and it needs the per-state hooks above. The current
loader keeps the broken Back until then.

⚠ **This very likely affects `TrainingBoot` the same way** — it uses the same
handoff and passes the same dead `rdi`. Not reported there yet, so either the
Training back path decays somewhere harmless or it has not been exercised.

## Status

**Works for getting in** (confirmed in game 2026-08-26). See the known bug
above for getting back out.

The log names what it did:

```
BOOTTRAIN: LOGO_NEXT handoff at RVA 0x750C72 rewritten -- ... sends
           JUMP_RoomMatchMenu to the dispatcher at <addr>
BOOTTRAIN: online selector at RVA 0x1CDF2E8 set to 1 (room match) before the jump
```

The second line comes from the game thread at the moment of the handoff, so its
absence means the rewritten site never ran.
