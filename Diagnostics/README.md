# Diagnostics — Online Match Diagnostics (the online match recorder) and its switch

Recording is **off** unless this folder holds `tournament.txt` with `on 1`. Nothing is recorded in normal play.

## How it works

1. **The switch.** Berg pushes `Diagnostics/tournament.txt` for an event:

   ```
   on 1
   tournament 2026-10-16
   salt <a new random word for each event>
   upload <the relay's address>
   ```

   - There is **no time window**: while the switch says `on 1`, every game started through the launcher records,
     for as long as it runs. Berg turns it off by pushing `on 0` (or deleting the file).
   - Version 1 (2026-10-12) also had `from` and `until`. The launcher no longer passes them to the loader, and the
     loader no longer limits anything by them.
2. **The player's own switch.** The launcher's **Game Modes** page has **Online Match Diagnostics**, **ON unless the
   player turns it off**, for the event of 2026-10-17 (Berg). After that event it goes back to **OFF unless the
   player turns it on**, as it was earlier on 2026-10-17. Before 2026-10-17 it was called Tournament diagnostics
   and was ON by default.
   OFF means nothing runs on that PC: the launcher removes `bros_diag.txt` at once, whenever it opens and at every
   launch, and the loader never arms. The choice is kept in `Json/diagnostics.json` (not committed); only the
   player's own click writes it.
3. **Every launch** that installs the loader copies the switch beside the game exe as `bros_diag.txt`, when both
   switches are on. This happens in the main launcher (also for the beta) and in the Community Patch, Room Match and
   Training Mode quick launchers (`launcher/diagnostics.py`).
   - The copy holds `tournament` and `salt`, plus the commit the player runs; never `upload`.
   - Without `tournament.txt`, with `on 0`, or with the player's switch OFF, the launch removes `bros_diag.txt`.
4. **The loader** (`Files/Matchmaking/dinput8_proxy.c`, PART 43 "NETDIAG", format `bros-diag 2`) reads
   `bros_diag.txt` once at game start. It then writes `<game>\BROS_Diagnostics\diag_<UTC>_<pid>.jsonl`.
   - There is no limit on the number of sessions or battles, or on a session's size (version 1 stopped a session
     file at 64 MB).
   - It adds no packets, no game memory writes and no timing changes.
   - Without the file it starts nothing.
5. **After the event**, players open the launcher and click **Send diagnostics** in the "Online Match Diagnostics"
   card.
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
removes `bros_diag.txt`. A switch push does **not** change the match pool, because the pool covers only what the game
loads. A push that changes game files, the loader or the plugins does change it. Never push one of those during an
event: everyone who relaunches would land in a different pool from everyone who did not.
