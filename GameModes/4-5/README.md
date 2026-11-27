# 4-5 — no 5-Konpaku Kikon before your first kill

Until a player has broken a Konpaku, their Kikon destroys **at most 4, never 5**.
Once they have killed once, the sublimation Kikon does its full 5 again.

## The problem it removes

Everyone has 9 Konpaku. A Kikon in Awakening destroys 4, a sublimation Kikon
destroys 5 — so a match is exactly two kills, and the *order* decides who is
squeezed:

* You kill first **without** sublimation: you take 4, leave 5. Your second kill
  now **requires** sublimation.
* Your opponent, who is behind, reaches sublimation before their own first kill:
  they take 5, leave 4. Their second kill needs only 4 — any Kikon does it.

Being better first is punished. Capping the first kill at 4 for both sides
removes the split: kill one is always 4, kill two is always 5, whoever gets
there first. Hence the name.

## What it is

An exe hook, so this mode has no `Script/` folder; its few data changes are
CharaStatus cells the launcher writes at launch (see "Its own CharaStatus"). Since
2026-09-29 the hook lives in the **master** loader, `Files/Matchmaking/dinput8.dll`,
and is armed at run time: every launch installs the same loader, and
`BROS_GAME_MODE=4-5` in the game's environment arms the mode (set until
2026-11-02 by the main launcher's 4-5 toggle and until 2026-11-06 by Quick
Launch 4-5; a room's Game Mode row picks it in game now, and a developer can
still set the variable for a right-click start). A launch without it plays stock
rules.
Anything the master learns, 4-5 has on the next launch.

⚠ **Do not bring a mode loader back.** Until 2026-09-29 this folder shipped its
own `dinput8.dll`, a build frozen on 2026-09-01 that shadowed the master for
every 4-5 launch. By the time anyone looked it was 59 loader commits behind:
rooms capped at two (no spectator seat), no plugin host (Zangetsu, Byakuya's
gauge and every other plugin absent from the process), no netcode switch.

Source: `Files/Matchmaking/dinput8_proxy.c`, PART 12 (what the hit does) and
PART 14 (what the Konpaku bar says) — the hit and the display read two
different numbers, which is why it takes two. `game_mode_from_env()` is the
switch. The launchers refuse to start 4-5 on a master whose bytes do not
contain `BROS_GAME_MODES=4-5`, and the log says what ran: `MERI=1` in the
`PATCHSTAMP` line and `GAMEMODE: BROS_GAME_MODE='4-5' -- 4-5 (Meri's mode) armed`.

Scope is the `g_meri_ids` array in that source. Characters outside it are
untouched, and a roster id of 64 or more falls outside the stub's bitmask and is
reported as dropped in the log.

## Nnoitora: Six Arms comes with Spirit Drive (since 2026-09-30)

In 4-5, Nnoitora (pl037) grows his extra arms when he **enters Spirit Drive**,
whatever his Konpaku. Stock grows them at **4 Konpaku or less**, and in 4-5 that
no longer triggers anything.

The stock rule is exe code, not data: his per-frame behaviour (`0x140509A10`)
tests `Konpaku <= 4.0` at `exe+0x509A6B`, then plays the transformation
(`evo_atk_dx01`) and arms enhance level 2, which his six-arm hitboxes answer to.
`Files/Matchmaking/pl037_plugin.c` (`ReBalanceOfSouls\pl037.dll`) replaces that
one test with the Spirit Drive byte (`fighter+0x11F1`); the transformation and
the arms are the game's own. It arms on the same `BROS_GAME_MODE=4-5` as the
master, and every other launch leaves Nnoitora stock. Log: `PL037/sixarms:`,
one line per change of form, Konpaku, Kikon Channel, Spirit Drive and Six Arms.
Tested in Training on 2026-09-30: no arms at 3 Konpaku without Spirit Drive;
arms 1.2 s after Spirit Drive at 9 Konpaku.

## Its own CharaStatus

`CharaStatus.json` holds the cells 4-5 changes, and ONLY those. The launchers
write them over the installed version's `Script/CharaStatus.fsv` at every 4-5
launch (`launcher/mode_status.py`), after the version, the mode and Team Battle
are in place. Every other number stays whatever the version ships, so a
Community Patch balance change reaches 4-5 on the next launch, and V1.2 / V1.3
keep their own rows. `"+x"` adds to the version's value; a bare number replaces
it.

| row | column | change | why |
|---|---|---|---|
| `pl037` | `evo_kikonsyouka_param` | `+0.5` (2.5 -> 3) | Six Arms now comes with Spirit Drive, so his Kikon Channel -> Spirit Drive run takes more Fighting Spirit |

⚠ The column is `evo_kikonsyouka_param`, not `rev_fighting_param`. Awakened, the
Kikon Channel -> Spirit Drive step fills meter 3 against the cap copied from
`evo_kikonsyouka_param` (state machine `0x14046C3C0`); `rev_fighting_param` is
meter 2, read only in the Reawakened form, which Nnoitora does not have. Read
live off his fighter on 2026-09-30: caps `3.0 / 3.5 / 2.0 / 2.5 / 4.0` =
`fighting / evo_fighting / rev_fighting / evo_kikonsyouka / rev_kikonsyouka`.

Why not a whole `Script/CharaStatus.fsv` here, as BaseOnly or EightKonpakus did
until 2026-11-02: a
copy is frozen the day it is made, silently undoes every later balance change
inside the mode, and on V1.2 / V1.3 replaces the fork's numbers with the Community
Patch's. The launcher refuses to start if a table still holds a mode's values
from an earlier launch (the `.modestatus` sidecar next to the table).

## Online

The mode shifts its matchmaking issuer by `MERI_POOL_TAG` (4002), on top of the
three-player room's `ROOM3_POOL_TAG` (4003), so it lands in its **own pool**,
distinct from both the normal patch and Reawakening Battle. It has to: a client
in this mode simulates a different fight and would desync against a stock
patched client. Everyone in the match needs the mode on. The shift is made only
once the hook is in, so the rule and the pool are armed together or not at all.

On Linux and macOS the launchers start the game through Steam, which does not
pass `BROS_GAME_MODE` on: such a launch plays stock rules in the normal pool,
and the launcher says so.

## Status

The mechanic is **confirmed working offline versus CPU** — measured, not
eyeballed: kill one took 4 Konpaku on an untouched target, kill two took 5.
It has **never been run online**, and it had never been driven through the
launcher as a game mode before this.

⚠ Do not judge this mode in **Training**. The dummy does not get its Konpaku
back between attempts, so only the very first Kikon of the whole session meets
the "no kill yet" condition and every later one runs at full value — it reads
exactly like the mode being dead. Offline versus CPU is the correct test: each
match starts fresh.

Full write-up: `DataChakka/guides/Nilsix researches/Konpaku and Kikon/`.
