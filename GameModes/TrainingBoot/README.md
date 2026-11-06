# TrainingBoot — boot straight into the Training character select

Started by the launcher's **Quick Launch Training Mode** button, or by the
Training entry of the right-click menu on the launcher's file (until 2026-11-06
also by `Quick Launch Training Mode.py`): the normal loader with
`BROS_BOOT_MODE=training`. The game goes logos → Training character select,
skipping the title screen and the menu walk.

**Confirmed working.**

## What it patches

The boot does not name its destination: `SLogo::Update`'s owner raises the event
`LOGO_NEXT` through the flow's vtable slot `0x88`, and the flow graph maps that
to Title. The patch rewrites that handoff (RVA `0x750C72`) to call a small
function in the loader, which sets the scene-setup singleton's mode to Training
(`+0x228 = 6`, what the real menu path writes) and then sends
`JUMP_TrainingCharacterSelect` through the flow's own jump dispatcher.

Ten bytes and four bytes, in place, no trampoline. Full derivation — including
the two wrong attempts that both logged success — is in the dev environment's
copy of this file.

## The loader

(Not installed by any of those starts since 2026-09-24: the shortcut travels
as `BROS_BOOT_MODE` on the normal loader -- the launcher's `launch()`
docstring says why. What follows is the record of this folder's own build.)

Built from this repo's `Files/Matchmaking/dinput8_proxy.c` with `-DENABLE_BOOT_TRAINING=1`, so it is
the normal patch loader plus this one shortcut — same matchmaking, same patches,
same balance data. It is **not** a game mode: there is no `Script/`, and it does
not appear in the launcher's game-mode list.

`setup_matchmaking()` installs `GameModes/<name>/dinput8.dll` when the selected
name has one, so nothing else is wired.

⚠ **Rebuild it whenever the default loader is rebuilt**, or the two drift.

## No pool tag

It changes which scene the boot flow hands off to and nothing else, so a player
using the shortcut simulates identically to one launching normally and lands in
the same matchmaking pool. That is deliberate.
