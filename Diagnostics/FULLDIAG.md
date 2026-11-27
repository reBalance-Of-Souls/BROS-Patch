# Advanced diagnostics (fulldiag)

A thorough recorder for one question: **why does the game play differently on one PC?** A move that comes out when it
should not (or the reverse), a character that cannot do what it should, a stutter, a desync. It records everything a
game session does, so the cause can be found from the recording instead of guessed. It is **off** unless the player
turns it on, and nothing leaves the PC until the player clicks Send.

The record layouts are in `FULLDIAG_DATA.md`; `fulldiag_read.py` reads everything (see the end of this file).

## Turning it on and off

- **The launcher's Diagnostics page** (the Diagnostics button on the main page) has the card **Advanced diagnostics**
  with its toggle. It is **OFF** unless switched on. The choice is kept in `Json/fulldiag.json` (not committed).
- **Switching it** writes `bros_fulldiag.txt` beside the game exe at once (`on 1`), or removes it (OFF), so a game
  started from the exe follows the switch too.
- **Every launch** that installs the loader writes or removes that file again: the launcher's Launch button and every
  start from its right-click Quick Launch menu (`launcher/fulldiag.py`, `launch_step`). If it cannot, the
  game is **not started** and the launcher says why, as for the netcode, developer-tools and Zangetsu switches: a game
  that records while the switch shows OFF (or the reverse) would be a "works for me" bug. A Vanilla start goes
  through Steam without the loader, so nothing records there.
- **It takes effect at the next game start:** the plugin reads `bros_fulldiag.txt` once, when the game starts.
- `bros_fulldiag.txt` also takes tuning keys (`long_ms`, `prof_hz` ... see `FULLDIAG_DATA.md`), but the launcher
  rewrites the file at every launch: to tune, edit it and start the game from the exe.

## What it records

All of it goes to `<game>\BROS_FullDiag\<UTC date-time>Z_p<process id>\`, one folder per game start.

- **Every battle frame, both fighters** (`e1_bNN.bin`, one file per battle, offline and online): the rollback lab's E1
  record, byte for byte -- the battle's tick, online frame, scene, state, timers, time scale, the random number
  generator's index and hash; per fighter the character, control, position, rotation, the action's name, serial and
  clock, form, HP, Konpaku, Reverse, guard, reiryoku, the five Fighting Spirit bars, combo, the 24 unique values, a
  status hash, altitude -- and **the exact commands each fighter executed that frame**.
- **The inputs, every battle frame** (`fx_bNN.bin`): each player's control scheme (Type A/B/C/Custom/keyboard), the
  raw records of pads 0 and 1 in the game's pad manager with the held mask, the game's keyboard table, and per fighter
  the brain's class, its active flags, its pad index, its hold timers and the 17 binding masks BrainPad reads.
- **The button bindings** at each battle start and whenever they change (`bind_bNN.bin`, and a `bindings` event).
- **The timing of every frame**, menus included (`timing.bin`): the game's tick, the post-tick work, the publish, the
  gap until the next tick, the whole frame, how long the render thread held the frame and how many frames it drew,
  how long the recorder itself took, the CPU cycles of the tick and of the frame, and flags (long frame, focus,
  battle, online, cinematic).
- **Where slow frames spent their time** (`prof_bNN.bin` and `prof_bNN_top.csv`): the rollback lab's sampling profiler,
  in every battle, offline and online. It samples the game and render threads 100 times a second and tags long frames
  (25 ms by default), so a stutter comes with the call paths it spent its time in.
- **The PC once a second** (`sys.jsonl`): the game's and the system's CPU, the game's memory, page faults, disk I/O,
  handles and threads, free memory and disk, mains or battery, whether the game window has the focus, the refresh rate
  of its monitor, the timer resolution, the game's priority, the number of game controllers connected, and the
  recorder's own counters (written, dropped, the disk guard).
- **Every thread in the game** (`threads.jsonl`): its role (game, render, the recorder's own), the module its code
  starts in, its name, and its CPU time and context switches every second.
- **Every module in the game** (`modules.jsonl`): at the start and whenever one is loaded or unloaded -- where it is
  from (the game folder: its path inside it; Windows: its path inside the Windows folder; anywhere else: the full path,
  with the user folder replaced by `<user>`), its size and link time, the md5 of every module that is not Windows',
  and its **version information** (description, product, company, version), so a foreign proxy DLL is named.
- **The session** (`session.json`): the plugin's build, the exe's md5, the game folder's own name (never its path),
  the recorder's settings, the patch's environment variables (`BROS_*`, Wine/Proton/DXVK/VKD3D, the compatibility
  layer, Steam's app ids -- nothing else), the switch files beside the exe with their content (token files never; a
  file whose name suggests a secret by its md5 only; the tournament switch without its salt and upload lines), the
  plugins in `ReBalanceOfSouls\`, the game controllers present (by hardware id), and the machine in brief (Windows
  version, CPU model, logical CPUs, RAM, Wine, timer resolution, power plan).
- **The events** (`events.jsonl`): the session's start and end; each battle's begin (kind, online, both fighters and
  their brains, the schemes) and end (why, how long); state changes; cinematics (marked, never analysed); every long
  frame with its phase split; focus lost and regained; display changes; controllers connected or disconnected;
  modules loaded or unloaded; binding changes; the disk guard.
- **The launcher's side** (`BROS_FullDiag\launcher_<UTC>Z.json`, at every launch while ON): the checkout's commit and
  branch, the version and game mode launched, the launcher's own switches (`Json\*.json`, secrets removed), the
  plugin's md5, Steam's settings for the game (Steam Input, launch options), and the known input-remapping, overlay,
  frame-pacing, memory-editing and injecting tools that are running (by the collector's fixed list; no other program
  is named).

## Disk and CPU

- **About half a GB per hour of battles** before packing (E1 ~250 MB, fx ~190 MB, the profiler ~85 MB, timing 7 MB);
  menus cost almost nothing. A send packs to much less.
- **The disk guard:** below 2 GB free on the game's drive, the recorder stops writing frame records (timing, E1, fx,
  bindings) and profiles, and an event says so; the small text files (events, the once-a-second samples) go on. The
  game's own saves never fail because of it.
- **Nothing is ever deleted on its own.** "Delete older recordings..." on the Diagnostics page deletes after a
  confirmation; a recording the game is still writing is never deleted.
- **CPU:** the game thread only copies a fixed-size record into memory each frame; a separate thread writes the files.
  About 200 safe memory reads a frame (est. 0.1-0.3 ms on Windows; `timing.bin` measures it as `hook_us`), and the
  profiler suspends the two threads for a few microseconds 100 times a second.

## Safety

- **It never changes the game:** its four hooks only pass through, it writes no game memory and calls no game function.
- **It never faults:** every read of game memory goes through `NtReadVirtualMemory` and is checked.
- **The rollback lab:** when `ReBalanceOfSouls\rbk.dll` is armed (`rbk.txt` says `enable 1`), the recorder leaves the
  frame hooks to it and still writes the session, the per-second samples and the module and thread lists.

## Privacy

- **Not recorded:** names, the Steam account, persona or ID, IP addresses, user folders (replaced by `<user>`), local
  times, and any program outside the fixed list of tools.
- **Before anything is packed** the launcher scrubs the recordings' text again (values only): this PC's Windows user
  and computer name, the Steam account and persona names found on it, Steam IDs and any run of 15 or more digits, user
  folders, access tokens, URL credentials, lobby data, salt and upload lines; the switch files' texts, the environment
  values and the player's comment also lose IP addresses and base64-like strings.
- **The time zone is part of a send:** the report of the PC and the game's own logs keep the PC's clock, and the send's
  `meta.json` carries the offset (`pc_utc_offset_min`) so log lines can be put on the recordings' UTC clock. The Send
  window says so. (The tournament data hides the time zone; this mode is for a thorough diagnosis.)

## Sending

**Send recordings...** on the Diagnostics page opens a window that says what is included, lists the recordings not
sent yet (and those that grew since they were sent), all chosen -- click one to leave it out -- and takes an optional
comment. Then:

1. **A fresh report of the PC** is made with `Diagnostics\brosdiag_collect.py` (about two minutes on a full game
   folder): machine, displays, controllers, Steam and Steam Input, the checkout, the game folder's file list with the
   checksums of everything a patch can change, the patch's log and crash logs (scrubbed by the collector). The
   tournament recordings it would copy are left out, so the two kinds never mix.
2. **The zips:** the chosen recordings, the launcher snapshot taken before each, and the report, in parts of about
   8 MB, written one after another to `BROS_FullDiag\_send_tmp\` (a recording is never held in memory whole). A file
   larger than a part is cut into numbered chunks, each with its offset and checksum.
3. **Send** posts the parts in order to the relay (the `upload` address of `Diagnostics/fulldiag.txt` when that file
   exists, otherwise of `Diagnostics/tournament.txt`) as tournament `fulldiag`: the relay files them under
   `inbox/fulldiag/`, apart from the tournaments. A recording counts as sent only when every part got through.
   **Save zips to Desktop** writes the same parts locally instead, to send by hand.
4. More than 2 GB before packing asks once more.

Parts are 8 MB, not the tournament's 18 MB: the relay (a Cloudflare Worker with 128 MB of memory) turns each upload
into a base64 string before storing it, and 8 MB keeps that well inside its memory.

## By hand

```
python launcher\fulldiag.py status   [<game folder>]                     the switch, the file, the recordings
python launcher\fulldiag.py on|off   [<game folder>]                     set the switch and apply it now
python launcher\fulldiag.py pack     [<game folder>] [--out <folder>] [--no-report]
python launcher\tests\test_fulldiag.py                                   the module's own test (263 checks)
```

## Reading

```
python Diagnostics\fulldiag_read.py join    <zips or folders ...> --out <folder>
python Diagnostics\fulldiag_read.py summary <session folder>
python Diagnostics\fulldiag_read.py timing  <session folder> [--long] [--battle N]
python Diagnostics\fulldiag_read.py frames  <session folder> --battle N [--from TICK] [--count N] [--inputs]
python Diagnostics\fulldiag_read.py diff    <session A> <session B> --battle N [--battle-b M] [--key rel|F|tick]
```

`diff` answers "where do two PCs' battles first disagree": it compares every simulation field of E1 bit for bit
(E1's own rule), keyed on the frame within the battle offline and on the lockstep frame online, and prints both PCs'
inputs at the first difference and the three frames before it. E1 is read with the rollback lab's `e1.py`
(`Files/Matchmaking/rbk_lab/`), the profiles in depth with its `prof.py`.

## Known limits

- **First measured on Berg's PC:** the recorder's own cost per frame on Windows, the controller list (Wine's cfgmgr32
  gives none) and the CPU cycle counts (Wine gives none). Everything else was verified under Wine against an
  independent reader (pass fd, `D:\Development Log\FULLDIAG_2026-10-31\`).
- **Under Wine or Proton** (Linux, Steam Deck) every checked read is a round trip to the wineserver: there the
  recorder takes about 10 ms of the game thread per battle frame (p50 12 ms in the pass's harness) and causes long
  frames itself. `timing.bin` keeps its own time (`hook_us`) apart and `fulldiag_read.py summary` prints it
  ("fulldiag's own ms"), so its share can be told apart, but a stutter diagnosis on such a PC is limited.
- **The raw stick values** are behind a virtual getter and are not decoded; the pad records are kept raw, and E1 holds
  the commands each fighter executed.
- **The relay's storage** is a git repository: large sends fill it quickly.
