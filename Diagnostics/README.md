# Diagnostics — the tournament recorder's switch

Recording is **off** unless this folder holds `tournament.txt` with `on 1`. Nothing is recorded in normal play.

## How it works

1. **The switch.** Berg pushes `Diagnostics/tournament.txt` for an event:

   ```
   on 1
   tournament 2026-10-16
   salt <a new random word for each event>
   upload <the relay's address>
   ```

   - There is **no time window** (version 2, 2026-10-16): while the switch says `on 1`, every game started through
     the launcher records, for as long as it runs. Berg turns it off by pushing `on 0` (or deleting the file).
   - Version 1 (2026-10-12) also had `from` and `until`. The launcher no longer passes them to the loader, and the
     loader no longer limits anything by them. (The Dev test switch of 10-12 ended on 10-14 06:00 UTC, and the
     version 1 loader then refused to arm: that is why the Dev Environment stopped recording.)
2. **The player's own switch.** The launcher's **Diagnostics** page (the Diagnostics button on the main page; on the
   Game Modes page until 2026-10-31) has **Tournament diagnostics**, ON by default.
   OFF means nothing runs on that PC: the launcher removes `bros_diag.txt` at once and at every launch, and the loader
   never arms. The choice is kept in `Json/diagnostics.json` (not committed).
3. **Every launch** that installs the loader copies the switch beside the game exe as `bros_diag.txt`, when both
   switches are on: the launcher's Launch button and every start from its right-click Quick Launch menu (until
   2026-11-06 also the Quick Launch scripts) (`launcher/diagnostics.py`). A Vanilla start goes through Steam without
   the loader, so it records nothing.
   - The copy holds `tournament` and `salt`, plus the commit the player runs; never `upload`.
   - Without `tournament.txt`, with `on 0`, or with the player's switch OFF, the launch removes `bros_diag.txt`.
4. **The loader** (PART 43 "NETDIAG" of `Files/Matchmaking/dinput8_proxy.c`, format `bros-diag 2`) reads
   `bros_diag.txt` once at game start. It then writes `<game>\BROS_Diagnostics\diag_<UTC>_<pid>.jsonl`.
   - There is no limit on the number of sessions or battles, or on a session's size (version 1 stopped a session
     file at 64 MB).
   - It adds no packets, no game memory writes and no timing changes.
   - Without the file it starts nothing.
   - The Dev `dinput8.dll` is built from Nilsix's recipe source plus PART 43, the same source the 10-08 Dev master
     was built from. `dinput8_proxy.c` here carries the same PART 43 text.
5. **After the event**, players open the launcher's **Diagnostics** page and click **Send diagnostics** in the
   "Tournament diagnostics" card.
   - The dialog shows what is included. Players can give an optional pseudonym and a comment.
   - It uploads the recordings to the relay, which files each upload in a private repository. The relay takes at
     most 20 MB per upload, so a larger send goes as several zips with one `batch` id, and a recording too large for
     one zip is cut into pieces at line ends.
   - If the upload fails, the zips can be saved to the Desktop and sent by hand.

## Privacy

Recording is fully anonymous:
- **Never written:** Steam IDs, names, IP addresses, the names of networks or adapters, the names of programs.
- **Matches are paired** by a hash of the room's lobby id with the event's salt.
- **Programs** are recorded only as yes/no flags for kinds of program: streaming, Discord, browsers, downloads and so
  on.
- **The log extract** that goes with an upload keeps only the netcode lines, scrubbed of ids, addresses and paths.

The full list of what is recorded and sent is in `DATA_COLLECTED.md` in this folder.

## Turning it off

Push `on 0`, or delete `tournament.txt`. A game already running keeps what it read at its start; the next launch
removes `bros_diag.txt`.

**In the Dev Environment every push moves the match pool.** The launcher derives the online match code from the
commit itself (`get_snapshot()`) and the game version, so a switch push gives a new pool to everyone who relaunches on
it. Both players of a test must run the same commit.

## Advanced diagnostics

The same page has a second, separate recorder: **Advanced diagnostics** (`fulldiag.dll`, `launcher/fulldiag.py`),
OFF unless a player turns it on, for finding why the game plays differently on one PC. It has nothing to do with
`tournament.txt`, writes to `BROS_FullDiag\` instead of `BROS_Diagnostics\`, and its sends go to the relay's
`inbox/fulldiag/` folder. See `FULLDIAG.md` and `FULLDIAG_DATA.md`.
