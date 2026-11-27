# Reawakening Battle — a game mode that ships a loader *and* data

Casual mode. Every character who owns a Reawakening **starts the match already
in it**, and they all field **10 Konpaku**:

| | | `rev_soul_num` |
|---|---|---|
| pl001 | Ichigo Kurosaki (Bankai) — Full Hollowfication | already 10 |
| pl003 | Uryu Ishida — Quincy: Letzt Stil | 9 → **10** |
| pl020 | Sosuke Aizen — Complete Hogyoku Fusion | already 10 |
| pl036 | Ulquiorra Shifar — Resurreccion Segunda Etapa | 9 → **10** |
| pl052 | Yhwach — the Kaiser-level Reawakening | 8 → **10** |

Everyone else plays exactly as before, on their usual 9.

## Two halves, and why

**`dinput8.dll` — the starting form.** Which trigger a Reawakening uses *is*
data (the `ura_transform_mothod` column), but the starting form is not: it is an
argument the engine passes to the fighter's init, and only Training ever sets it
to "Reawakened". So that half is an exe hook.

`setup_matchmaking()` in the launcher installs `GameModes/<mode>/dinput8.dll`
when the selected mode has one, falling back to `Files/Matchmaking/dinput8.dll`
otherwise. It runs last in `launch()`, so the mode's loader wins cleanly rather
than racing the normal one. Any future loader-based mode works the same way —
drop a `dinput8.dll` in its folder, nothing else to wire.

The loader is built from the one canonical source,
`Files/Matchmaking/dinput8_proxy.c`, with `-DENABLE_REAWAKEN_BATTLE=1`. It
carries every patch the normal loader carries (matchmaking, Byakuya's gauge, the
room-match fixes, the crash guards); the only difference is PART 13 compiled in.
The roster lives in `g_reaw_ids` there.

**`CharaStatus.json` — the Konpaku count.** The per-form maximum is plain
data: `rev_soul_num` 10 on pl003, pl036 and pl052, and nothing else. The
launcher writes those three cells over the installed version's
`Script/CharaStatus.fsv` at launch (`launcher/mode_status.py`), so every other
number is whatever the version ships, after every balance change.

⚠ **Keep the two halves in step.** `g_reaw_ids` and the rows in
`CharaStatus.json` are the same roster written twice. Adding a character means
editing both, or they field a Reawakening on the wrong Konpaku count.

Until 2026-11-02 this half was a whole `Script/CharaStatus.fsv`, a copy of the
Community Patch table frozen the day it was made (as were BaseOnly's,
EightKonpakus' and InstantEvoAndSublimation's): every later balance change was
undone inside the mode, and on V1.2 / V1.3 the fork's numbers were replaced.
Those four copies are gone; each mode lists only its own cells.

## Online

The mode shifts its matchmaking issuer by `REAWAKEN_POOL_TAG`, so it lands in
its **own pool**. That is not a nicety: a client in this mode simulates a
different fight from a normal patched client, and the two would desync if they
met. Everyone in the match needs the mode on.

The mode is not remembered between launcher sessions — the same as the other
game modes — so the next launch reinstalls the normal loader unless you turn it
back on.

There is no way to end up in the mode without meaning to. The game is only ever
started **through the launcher**: `launch_patched()` runs the exe directly on
Windows precisely because starting through Steam makes EasyAntiCheat block the
injected `dinput8.dll`. So every launch goes past the loader install, and
whatever the toggle says at that moment is what you play.

## Status

**The mechanic is confirmed in game.** Three sessions on 2026-08-25/26 ran the
four-character build and the watcher counted fighters actually entering the
match Reawakened — 1, 2, 4, then 6 across matches — with the pool shifting as
designed.

**The current build has not been played.** Yhwach and the CharaStatus cells
landed after those sessions, so two things are still unverified:

* **that the Konpaku really read 10.** `rev_soul_num` feeding the Reawakened
  form's maximum is inferred from the column's name and from the transform
  reading a per-form table at `fighter+0xCB8+form*4` — it has not been observed.
  If the count comes out wrong it is one column to move.
* **Yhwach specifically.** His Reawakening is the one the exe forces
  (`ura_transform_mothod` 3, the Kaiser level), and his Kaiser counter has its
  own start-of-match data in `pl052.tadjpkg`. Least exercised path in the mode.

Full write-up: `DataChakka/guides/Nilsix researches/Reawakening Battle/`.
