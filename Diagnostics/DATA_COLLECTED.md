# What Online Match Diagnostics collect

This file lists **everything** the online match recorder ("Online Match Diagnostics" in the launcher) writes on
your PC, everything the **Send diagnostics** button
uploads, and what is stored afterwards. The names in `code` are the field names in the files: the session files are
plain text (one JSON object per line, its kind in `t`), so you can open them in any text editor and check this list
against them.

## When anything is recorded

- **Only while recording is switched on.** We switch recording on by pushing `Diagnostics/tournament.txt`, and off
  again by pushing `on 0`. The launcher copies it beside the game as
  `bros_diag.txt` when you start the game. Without that file, the recorder does nothing at all. There is no time
  window: while the switch is on, every game you start records, for as long as it runs.
- **Only if you turn it on.** The launcher's **Game Modes** page has an **Online Match Diagnostics** switch, **OFF
  unless you turn it on**. OFF means nothing is recorded on your PC: the launcher removes `bros_diag.txt` at once,
  whenever it opens and at every launch. Your choice is kept in the launcher's `Json/diagnostics.json`.
- **Only online battles get battle data.** A game that records writes the session header and the program flags below
  as it starts, and the PC counters below every 10 seconds outside battles.
- **Nothing leaves your PC by itself.** Recording writes files on your own disk. They are only sent if you click
  **Send diagnostics** in the launcher, and then **Send**.
- **It changes nothing in the game.** The recorder adds, drops, delays or rewrites no packet, writes no game memory and
  changes no timing.

## Where it is kept on your PC

- **The switch copy:** `bros_diag.txt` beside the game exe. It holds the event's `tournament` name, `salt` and the
  patch `commit` you run.
- **The recordings:** `BROS_Diagnostics\diag_<UTC date and time>_<process number>.jsonl` in the game folder, one file
  per game session, with no size limit (a typical session is a few MB).
- **After sending:** sent files move to `BROS_Diagnostics\sent\`. You can delete the whole `BROS_Diagnostics` folder
  at any time.

## Recorded once per game session (the header, a line with `"t":"h"`)

- **The recorder:** its format version (`v`), the loader's build id (`build`), the tournament name (`tour`) and the
  patch commit the launcher installed (`commit`).
- **The clock:** when the session started, in UTC (`utc`); and your PC's timer frequency (`qpf`). (`from` and
  `until` are there too, as 0: version 1 of the recorder had a time window, version 2 has none.)
- **The netcode settings in force** (`net`): whether `bros_net.txt` was read (`file`), and the `lock`, `sleep`,
  `window`, `delay`, `probe` and `capture` settings, which the New/Classic netcode switch decides.
- **The patch's plugins:** the file names of the DLLs in the game's `ReBalanceOfSouls` folder (`plugins`), and whether
  the frame-pacing switch files `pacing_off.txt` and `pacing.txt` exist (`pacing_off`, `pacing_txt`).
- **Your hardware and Windows:**
  - the Windows version number (`os`);
  - the CPU model name (`cpu`), its thread and core counts (`threads`, `cores`);
  - the installed RAM in MB (`ram_mb`);
  - the main graphics adapter's model name (`gpu`) and the main display's refresh rate (`hz`);
  - whether the PC runs on mains power (`ac`) and its battery level (`batt`);
  - the Windows timer resolution, as minimum, maximum and current (`tres`).
- **Your connection** (`nic`), for the network adapter your internet traffic goes through:
  - its type, such as cable or Wi-Fi (`ift`), and whether it is connected (`media`);
  - its link speed up and down in Mbit/s (`tx_mbps`, `rx_mbps`);
  - a yes/no for whether that adapter is a VPN or virtual tunnel (`vpn`). This is decided from the adapter's
    description containing one of: tap-, tap , wireguard, wintun, vpn, nordlynx, hamachi, zerotier, radmin, mullvad,
    tailscale, openvpn, anyconnect, fortinet, surfshark, windscribe, proton. The description itself is **not**
    written.
- **Wi-Fi** (`wifi`), only when that adapter is Wi-Fi; otherwise `null`:
  - the signal quality from 0 to 100 (`q`);
  - the Wi-Fi standard (`phy`);
  - the link rates in kbit/s (`rx_kbps`, `tx_kbps`);
  - the channel (`ch`).

  The network's name is **not** written.

## Recorded at the start of the session and of every battle (program flags, `"t":"a"`)

- the battle number, 0 at the start of the session (`b`), and the time since the session started, in ms (`ts`);
- how many programs are running in total (`procs`);
- **yes/no flags** (`apps`) for 11 kinds of program. Only the yes/no per kind is written, **never which program, and
  never a list of programs**:
  - `stream`: obs64.exe, obs32.exe, obs.exe, streamlabs obs.exe, streamlabs desktop.exe, xsplit.core.exe;
  - `discord`: discord.exe, discordptb.exe, discordcanary.exe;
  - `browser`: chrome.exe, msedge.exe, firefox.exe, opera.exe, brave.exe, vivaldi.exe;
  - `remoteplay`: parsecd.exe;
  - `torrent`: qbittorrent.exe, utorrent.exe, bittorrent.exe, deluge.exe, transmission-qt.exe;
  - `cloudsync`: onedrive.exe, dropbox.exe, googledrivefs.exe;
  - `recorder`: nvsphelper64.exe, nvidia share.exe, medal.exe, gamebar.exe, gamebarftserver.exe, overwolf.exe;
  - `vpn`: nordvpn.exe, expressvpn.exe, protonvpn.exe, openvpn.exe, openvpn-gui.exe, wireguard.exe, mullvad vpn.exe,
    surfshark.exe, hamachi-2-ui.exe, radminvpn.exe, zerotier_desktop_ui.exe, tailscale-ipn.exe, windscribe.exe;
  - `launcher`: epicgameslauncher.exe, eadesktop.exe, battle.net.exe, ubisoftconnect.exe, galaxyclient.exe;
  - `music`: spotify.exe;
  - `wallpaper`: wallpaper64.exe, wallpaper32.exe.

## Recorded when an online battle starts (`"t":"b0"`)

- the battle number (`b`), the time since the session started (`ts`) and the time in UTC (`utc`);
- your **role**: host, guest or spectator (`role`);
- the **input delay** in frames the netcode uses (`D`), and the one the game chose before the patch's `delay` setting
  (`D0`);
- the **ping** to the other player that the room measured, in ms (`rtt`), and the netcode's input window (`W`);
- the **anonymous match key** (`mk`): a hash of the event's salt and the room's Steam lobby number. A lobby is a room,
  not a person; both players of a match get the same key, which is how their two recordings are paired. The lobby
  number itself is **not** written;
- the battle's number within that room (`lb`) and how many players are in the room (`mem`);
- the netcode settings for this battle (`lock`, `sleep`, `capture`).

## Recorded every second of an online battle (`"t":"s"`)

- the battle number (`b`), the time since the session started (`ts`) and the game's frame number (`F`);
- **smoothness:** how many frames the game advanced in that second (`df`), and the longest wait between two frames, in
  ms (`fmx`);
- **freezes** that ended in that second: their number, their total length in ms, and the longest one (`st`); then the
  same split by cause as [number, ms] (`sn` waiting for the other player's input, `sc` after a cutscene, `sk` at a
  KO); and whether the game was frozen at that moment (`fz`);
- **the input buffer:** the fewest frames of the other player's input that were in hand (`am`), the average × 10
  (`aa`), and the catch-up tempo used (`tp`, the highest step that second);
- **resend requests** the other side made in that second (`nk`);
- **the network thread's timing:** its median, 90th-percentile and longest period, in quarter-milliseconds (`np`);
- **how often the game's two threads met or gave up waiting** on the netcode's lock (`lk`);
- **per connection** (`pp`), by slot number 0–7, never by player: packets and bytes sent, packets and bytes received,
  and the longest gap between two received packets in ms.

## Recorded about your PC once a second during a battle, and every 10 s otherwise (`"t":"o"`)

- the battle number (`b`) and the time since the session started (`ts`);
- the **whole PC's CPU load** (`cpu`) and **the game's own CPU use** (`pcpu`), each in tenths of a percent;
- the **total traffic** of your network adapter, in and out in bytes per second (`nin`, `nout`). This is a sum over
  all programs; no address or destination is recorded;
- the number of **faulty UDP packets** Windows received since the previous line, for the whole PC (`udpe`);
- the **Wi-Fi signal quality**, at most every 5 seconds (`wq`; -1 when not measured or not Wi-Fi).

## Recorded when something happens (`"t":"e"`; the kind is in `k`)

- `p2p`: a change in the Steam connection to another player in the room. For slot (`slot`) it records:
  - whether Steam answered (`ok`);
  - whether the connection is active (`act`) or still connecting (`conn`);
  - Steam's error code (`err`);
  - whether it goes **through Steam's relay servers** (`relay`);
  - how many bytes and packets wait to be sent (`qb`, `qp`).

  Steam's view of the other player's address is **not** written.
- `members`: the number of players in the room changed (`n`).
- `stall`: a freeze of 100 ms or more: its length (`ms`), its cause, network, cutscene or KO (`cls`), and the frame
  (`F`).
- `drop`: lines lost because the recorder's buffer was full (`n`).
- (`capped` was version 1's event for a session file that reached 64 MB. Version 2 has no such limit and never
  writes it.)

Each event also carries the battle number (`b`) and the time since the session started (`ts`).

## Recorded when an online battle ends (`"t":"b1"`)

- the battle number (`b`), the time since the session started (`ts`) and the time in UTC (`utc`);
- **how it ended**, as the patch's netcode measurement names it (`why`);
- the battle's length (`run_ms`), the freeze it ended in (`tail_ms`), and the wait before its first frame (`w0_ms`);
- **freeze totals:** [number, number of 33 ms or longer, total ms, longest ms]. Given for all freezes (`all`) and by
  cause (`net`, `cut`, `ko`);
- **histograms:**
  - network freezes by length (`nh`);
  - frames of input in hand (`ah`);
  - catch-up tempo (`th`);
- **per connection over the whole battle** (`pp`): slot, packets and bytes sent, packets and bytes received.

## What "Send diagnostics" uploads

One zip file, only when you click **Send** (or saves it to your Desktop if you choose **Save zip to Desktop**). If
your recordings are larger than one upload may be (about 18 MB packed), they go as several zips, one after the other,
each with its own `meta.json`; a recording too large for one zip is cut, at line ends, into pieces
(`sessions/<name>.chunk<k>of<m>`). Your recordings count as sent only when every zip got through:

- `sessions/`: your recording files listed in the dialog (the ones not sent yet), unchanged.
- `log_extract.txt`: only the netcode lines of the patch's log (`patch_ranked.log` and `patch_ranked.log.1`, at most
  the last 8 MB of each).
  - It keeps only the lines with `] NET/`, `] NET:`, `] PACING:`, `] NETDIAG:` or `] PATCHSTAMP`, and never a ROOM3
    line.
  - Every long number (15 to 20 digits, such as a Steam ID) becomes `<id>`, every IPv4 address `<ip>`, and every drive
    path `<path>`.
  - Its clock times are converted to UTC. The files in the zip carry a fixed date (1 January 1980) instead of your
    PC's clock, so an upload does not tell your time zone.
- `meta.json`:
  - the bundle format (`format`, and `bundle` 2), when the zip was made (`created_utc`), and the launcher's commit
    (`launcher_commit`);
  - which send it belongs to (`batch`, a random id made for that send) and which of its zips it is (`part`, `parts`);
  - **your pseudonym, only if you typed one** (`pseudonym`, at most 40 characters);
  - **your comment, only if you typed one** (`comment`, at most 4,000 characters);
  - the version of Python the launcher runs on (`python`);
  - for each recording file (`files`): its `name`, size in `bytes`, `sha256` checksum, number of `battles` and
    `tournament`; for a piece of a cut recording also `chunk`, `chunks`, `offset`, `chunk_bytes` and `chunk_sha256`.

The upload goes over HTTPS to our relay (a Cloudflare Worker) with the headers `X-BROS-Format` (the bundle format) and
`X-BROS-Tournament` (the tournament name), and the user agent `BROS-Launcher-Diagnostics/2`.

## What is stored, and where

- The relay accepts only this zip format, up to 20 MB per zip. It saves each zip **as it is** in a **private GitHub
  repository** of the patch team, as `inbox/<tournament>/<UTC time>_<first 8 characters of the receipt>.zip`.
- Every upload is its own file: nothing ever overwrites another upload.
- The relay stores **no IP address and no headers**. As with any website, Cloudflare's network sees your IP address
  while the upload is in transit; the relay does not write it anywhere.
- The dialog shows you a **receipt** after sending. Keep it if you want your upload deleted later: give Berg the
  receipt and that file is removed.
- The repository is private to the patch team. The data is used to find the causes of lag, freezes and disconnects
  in online matches, and it is deleted after the analysis.

## Never recorded or sent

- your name, your Steam name or Steam ID, your friends;
- any IP address, yours or the other player's;
- the name of your PC, your Windows user name, your folders and paths, your time zone;
- your Wi-Fi network's name, or your adapters' names;
- which programs you run (only the yes/no per kind above), your files, your chat, your screen, your keyboard or mouse;
- anything at all while recording is switched off, or while your own Game Modes switch is OFF (as it is unless you
  turn it on).
