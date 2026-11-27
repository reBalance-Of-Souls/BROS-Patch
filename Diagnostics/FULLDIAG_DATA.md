# Advanced diagnostics -- the data

What `fulldiag.dll` writes and what a Send carries, field by field. `FULLDIAG.md` says what it is for and how it is
used; `fulldiag_read.py` reads all of it. All numbers are little-endian; every binary record starts with its own magic,
version and size, so a reader can check it and skip a half-written last record.

## The session folder

`<game>\BROS_FullDiag\<yyyymmdd-hhmmss>Z_p<pid>\` -- the UTC time the game started and its process id.

| File | Written | What |
|---|---|---|
| `session.json` | once, at the start | the session, the recorder's settings, the switch files, the plugins, the machine |
| `events.jsonl` | as things happen | one JSON object per line, its kind in `t` |
| `timing.bin` | every frame, menus too | `FdTiming`, 80 bytes |
| `e1_bNN.bin` | every battle frame | the rollback lab's E1 record v5, 1,174 bytes |
| `fx_bNN.bin` | every battle frame | `FdExt`, 864 bytes: the inputs |
| `bind_bNN.bin` | at each battle start | the button bindings, 3,360 bytes |
| `prof_bNN.bin`, `prof_bNN_top.csv` | at each battle end | the sampling profiler (the rollback lab's format) |
| `sys.jsonl` | once a second | the PC and the recorder's counters |
| `threads.jsonl` | at the start, then once a second | every thread; CPU time per thread |
| `modules.jsonl` | at the start, then when the module list changes | every module |
| `.fulldiag_sent.json` | by the launcher, after a send | what was sent, file by file (size) |

`NN` is the battle number within the session (01, 02, ...). Battle frames join across files **by tick**: E1's `tick`,
`FdExt.tick` and `FdTiming.tick` are the same counter (`[[ComponentManager]+0x78]`, read right after the tick). Events
carry `frame` (the `FdTiming.frame` of the frame they happened in) and, for battle events, `tick_before`.

## `bros_fulldiag.txt`

Read once at game start (the plugin's `cfg_read`, mirrored by `launcher/fulldiag.py parse()`, held to it by a fuzz
test). One `key value` per line, `#` starts a comment, `on`/`yes`/`true` = 1 and `off`/`no`/`false` = 0, numbers in
base 10, a later line wins. The launcher writes only `on 1`.

| Key | Default | Range | Meaning |
|---|---|---|---|
| `on` | 0 | 0/1 | record at all |
| `e1` | 1 | 0/1 | E1 and fx records |
| `timing` | 1 | 0/1 | `timing.bin` |
| `sys` | 1 | 0/1 | `sys.jsonl` |
| `modules` | 1 | 0/1 | `modules.jsonl` |
| `long_ms` | 25 | 5..1000 | a frame longer than this is a long frame (flag, event) |
| `min_free_mb` | 2048 | 256..1000000 | the disk guard |
| `prof_hz` | 100 | 0..1000 | profiler samples per second (0: no profiler) |
| `prof_long_ms` | 25 | 5..1000 | the profiler's long-frame tag |
| `prof_max_mb` | 64 | 4..1024 | the profiler's sample buffer per battle |
| `prof_render` | 1 | 0/1 | sample the render thread too |
| `prof_stop_ms` | 20 | 5..1000 | if a sampled thread stays suspended this long after its context was read, sampling stops for the session (it would hurt the game) |

## `session.json`

`format` ("fulldiag 1"), `plugin`, `build`, `session`, `utc`, `pid`; `exe` {`md5`, `bytes`}; `game_folder_name` (the
name only); `config` (the settings above as read; `fx` mirrors `e1`); `frame_hooks` (installed, or why not -- e.g. the
rollback lab armed); `profiler` (1 = running); `qpc_hz`; `records` (the record sizes and versions); `env` (only
`BROS_*`, `__COMPAT_LAYER`, `WINEDLLOVERRIDES`, `WINEESYNC`, `WINEFSYNC`, `DXVK_*`, `VKD3D_*`, `PROTON_*`,
`SteamAppId`, `SteamGameId`, `SteamOverlayGameId`; user folders replaced); `beside_exe` (every `*.txt`, `*.ini`,
`*.json`, `*.cfg` beside the exe: `name`, `bytes`, and `text` up to 64 KB -- `DevToken.txt`/`TokenOpen.txt` withheld,
a name that suggests a secret by `md5` only, `bros_diag.txt` without its salt and upload lines, the launcher's
`launcher_content_pool.json` and `launcher_patch_state.json` by `md5`); `plugins` (the DLLs in `ReBalanceOfSouls\`);
`input_devices` (the HID game controllers present, by hardware id `VID_xxxx&PID_xxxx...`, `" xN"` for several);
`machine` {`windows`, `cpu`, `logical_cpus`, `ram_mb`, `wine`, `priority_class`, `timer_ms` {coarsest, finest,
current}, `power_plan`}.

## `timing.bin` -- `FdTiming`, 80 bytes, magic `FDT1`

| Off | Type | Field | Meaning |
|---|---|---|---|
| 0 | u32 | magic | 0x31544446 "FDT1" |
| 4 | u16 | ver | 1 |
| 6 | u16 | size | 80 |
| 8 | u64 | frame | the recorder's frame number (counts publishes from game start) |
| 16 | u64 | qpc | QueryPerformanceCounter at the publish's end |
| 24 | u32 | tick | the engine tick right after this frame's tick (E1's tick) |
| 28 | f32 | tick_us | this frame's world tick |
| 32 | f32 | post_us | from the tick's end to the publish |
| 36 | f32 | pub_us | the publish (ComponentManager slot 4) |
| 40 | f32 | gap_us | from the previous publish's end to this tick's start (rendering waits, Present, the OS) |
| 44 | f32 | frame_us | from the previous tick's start to this one: the previous frame's tick + post + pub + this gap |
| 48 | f32 | rhold_us | the longest the render thread held a frame (slot 5 to slot 7) since the last record |
| 52 | f32 | hook_us | the recorder's own time on the game thread within frame_us |
| 56 | u32 | cyc_tick | CPU cycles of the game thread in the tick (QueryThreadCycleTime; 0xFFFFFFFE = saturated) |
| 60 | u32 | cyc_frame | CPU cycles of the game thread in the frame |
| 64 | u16 | rframes | frames the render thread released since the last record |
| 66 | u16 | state | the battle scene's state |
| 68 | u32 | sceneVt | the battle scene's vtable (exe RVA), 0 outside battles |
| 72 | u8 | kind | the battle kind in E1's numbering (0 Versus, 1 Training, 2 MatchingTraining, 3 Online, 4 Story, 5 Mission, 6 Tutorial, 7 Guide); with the battle flag only |
| 73 | u8 | flags | 0x01 long, 0x02 the game window had the focus, 0x04 battle, 0x08 online, 0x10 a cinematic played, 0x20 cycle counts not valid |
| 74 | u8 | nticks | ticks run since the previous publish |
| 76 | u16 | battle | the battle number, 0 outside battles |

## `e1_bNN.bin` -- E1 v5, 1,174 bytes, magic `E1RB` (0x42523145)

The rollback lab's per-tick record (`rbk_plugin.c` `E1Rec`, `Files/Matchmaking/rbk_lab/e1.py`), byte for byte, so the
lab's own tools read it: `e1.py dump`, `check`, `cm`, `diff`. Header: tick, the online frame `F` (-1 offline), the
scene, state, the timers, dt and time scales, the RNG index and hash, per-phase timing; per fighter (two): ids,
control, position, rotation, the action (kind, serial, name hash, clock, total, name), form, HP, Konpaku, death mode,
Reverse, guard, reiryoku, the Fighting Spirit caps and bars, combo hits, the 24 unique values, a status hash, the
altitude state, and **the commands executed this frame** (`ncmd` and up to 24 raw 6-byte entries of the fighter's
command list at +0xAB8; `e1.py` prints them as `b0/b1/u16/u16`); the v3 trailer (with `xbits`: the alternate-state and
world-pause bits); the v4/v5 probe block (the ComponentManager and EngineMemory at the save point; `rsmp`: the render
thread at the tick's start). `diff` compares every simulation field bit for bit; timing and the
probe block are not compared (`e1.py NOT_STATE`).

## `fx_bNN.bin` -- `FdExt`, 864 bytes, magic `FDX1`

| Off | Type | Field | Meaning |
|---|---|---|---|
| 0 | u32 | magic | 0x31584446 "FDX1" |
| 4 | u16 | ver | 1 |
| 6 | u16 | size | 864 |
| 8 | u64 | frame | as in FdTiming |
| 16 | u64 | tick | E1's tick |
| 24 | s32 | F | E1's online frame |
| 28 | u32 | flags | as in FdTiming |
| 32 | s32[2] | scheme | each player's control Type, `exe+0x1CDE710` (0..4: A, B, C, Custom, keyboard) |
| 40 | u32 | pad0Extra | `exe+0x18F3934`, ORed into pad 0's held mask |
| 44 | u8 | readOk | 1 pad manager, 2 pad 0, 4 pad 1, 8 key table, 16 schemes (31 = all read) |
| 48 | u8[192] | pads[0] | `[[exe+0x1CF94B8] + 0x40 ...]`: pad 0's record; its held mask at +0xA8 |
| 240 | u8[192] | pads[1] | `[[exe+0x1CF94B8] + 0xA8 + 0x40 ...]`: pad 1's; held mask at +0xA8 |
| 432 | u8[256] | keys | `exe+0x18D7BA0`: 32 x {u32 code\|flags, f32 repeat}, raw |
| 688 | FdBrain | fb[0] | fighter 0's brain |
| 776 | FdBrain | fb[1] | fighter 1's brain |

`FdBrain`, 88 bytes: `brainVt` u32 (the brain's vtable RVA; 0xFFFFFFFF none), `onA` `onB` u8 (BrainPad +0x50,
+0x51), `isPad` u8 (it is BrainPad), `ok` u8 (read), `padIdx` s32 (+0x88), `hold` f32[2] (+0x90), `masks` u32[17]
(+0xCC: the binding masks BrainPad tests). The raw stick values sit behind a virtual getter and are not decoded.

## `bind_bNN.bin` -- 3,360 bytes

`exe+0x1CE8380`, 0xD20 bytes as they are at the battle start: player 1's five binding sets of 0x150 bytes, then
player 2's from `exe+0x1CE8A10` (see `kbhoho_plugin.c`). A change during the battle is an event (`bindings`).

## The profiler -- `prof_bNN.bin`, `prof_bNN_top.csv`

The rollback lab's profiler, its format unchanged (`rbk_lab/prof.py`: a 320-byte header, a 64-byte entry per module,
a 120-byte record per sample with the thread, the lab window -- tick, post, publish, other -- the long-frame flag and
up to 20 return addresses; `prof.py summary`, `long`, `collapsed`, `check`; `--exe` names the exe's functions). It
runs in every battle, offline and online; a battle that replaces another before the previous profile is written starts sampling as soon as it is
(`profiler_late_start`). `prof_bNN_top.csv`, written beside it: `set,kind,module,rva,entry,samples,pct_of_set,set_samples`
-- per set (`game all`, `game tick`, `game post`, `game publish`, `game other`, `game long frames`, `render all`,
`render long frames`; a set with no samples is left out) the exclusive and inclusive top entries.

## `events.jsonl`

Every line has `ms` (milliseconds since the recorder started) and `t`.

| `t` | Fields |
|---|---|
| `session_start` | plugin, build, frame_hooks, profiler, writer_tid |
| `game_thread`, `render_thread` | tid (game: tick_hook) |
| `battle_begin` | battle, kind, online, frame, tick_before, fighters [{chara, slot, ctrl, brain (RTTI name), brain_vt}], scheme |
| `battle_end` | battle, kind, why, frame, tick_before, ticks, fight_ticks, frames, secs, sampled (1: profiled) |
| `state` | battle, from, to, frame, tick_before |
| `cinematic` | battle, on, frame, tick_before (marked, never analysed) |
| `long_frame` | frame, tick, battle, state, demo, frame_ms, prev_tick_ms, prev_post_ms, prev_pub_ms, gap_ms, hook_ms, render_hold_ms, render_frames, nticks -- the previous frame's phases and this gap: together they are frame_ms |
| `bindings` | battle, fighter, frame, tick, scheme |
| `profiler_late_start` | battle, started, frame, battle_ticks |
| `module_loaded` / `module_unloaded` | where, name / name, base |
| `focus` | on |
| `display` | refresh_hz, monitor [w,h], window [w,h], popup, covers_monitor, monitor_changed |
| `input_devices` | added [...], removed [...], now |
| `disk_guard` | free_mb, min_free_mb |
| `session_end` | why ("process exit" or "unloaded"), frames, battles, in_battle, ring_pending_bytes, written_bytes, dropped_records -- written without the C runtime, after a blank line |

## `sys.jsonl` (once a second)

`frames`, `battle`, `cpu_proc_pct`, `cpu_sys_pct` (-1 until two samples exist), `proc_mcycles`, `ws_mb`,
`private_mb`, `page_faults`, `hard_faults` (in the second), `io_read_mb`, `io_write_mb`, `handles`, `threads`,
`mem_load_pct`, `avail_mb`, `disk_free_mb`, `ac` (1 mains, 0 battery, -1 unknown), `battery_pct`, `focus`,
`refresh_hz` (the game window's monitor, re-read when it changes or once a minute), `timer_ms`, `prio_class`,
`tsc_mhz`, `hid` (HID game controllers, -1 unknown), `written_mb`, `dropped` [E1, fx, timing, events, bindings],
`ring_kb`, `reads`, `read_fails`, `disk_stop`.

## `threads.jsonl`

`thread`: `tid`, `first` (1: present at the start), `role` (game, render, fulldiag, fulldiag writer, or empty),
`start` (`module+0xRVA` of the thread's start address), `name` (its description, if it has one). `cpu` (once a
second): `n` threads, `busy` [[tid, CPU ms in the second, context switches, priority], ...] for every thread that ran,
`gone` [tids that ended].

## `modules.jsonl`

`module`: `first`, `where` (game / windows / other), `path` (inside the game folder, inside the Windows folder, or the
full path with `<user>`), `image_size`, `pe_time`, `md5` and `bytes` (not for Windows' own), and the version
information when there is one: `desc`, `product`, `company`, `file_version`, `product_version`, `original_name`,
`internal_name`, `version`.

## The launcher snapshot -- `BROS_FullDiag\launcher_<yyyymmdd-hhmmss>Z[_n].json`

Written at every launch while the switch is ON (`_n` for a second launch within the same second): `format`
("fulldiag-launcher 1"), `utc`, `version`, `game_mode`, `checkout` {head, branch, upstream, head_date}, `launcher_json`
(every `Json\*.json`, keys naming secrets replaced by `<removed>`), `game_file` {state, cfg}, `plugin` {installed,
md5}, `steam_app_settings` (the plain values of the game's block in each `localconfig.vdf`, without the account's id),
`running_tools` {category: [names]} (the collector's fixed TOOLS list only), `python`, `platform`. Scrubbed like the
rest.

## A send

Parts named `BROS_fulldiag_<UTC>_part<k>of<n>.zip` (saved) or `inbox/fulldiag/<UTC>_<receipt>.zip` (the relay). Each is
at most 8 MB and holds:

- `meta.json`: `format` ("fulldiag-bundle 1"), `batch` (the same in every part of a send), `part`, `parts`,
  `created_utc`, `pc_utc_offset_min`, `launcher_commit`, `comment` (scrubbed), `relay_folder`, `sessions`, `machine`
  {included, asked, exit, collector, collector_md5, left_out}, and `files`: one entry per zip entry -- `zip_name`,
  `kind` (readme, snapshot, machine, session), `session`, `name`, `offset`, `bytes`, `sha256`, `chunk` (0: the whole
  file), `last`, and on the last piece `file_bytes` and `file_sha256`; `scrubbed` for session files.
- `README.txt` (part 1), `launcher/<snapshot>`, `machine/<the collector's files>` (report.json, inventory.tsv,
  files/..., collector_output.txt), `sessions/<session>/<file>` or `<file>.chunkNNNN`.

Every entry's date is 1980-01-01 (a zip stores local clock time). `fulldiag_read.py join` checks every checksum, puts
chunks back by offset, and marks a file whose pieces are missing `.INCOMPLETE`.
