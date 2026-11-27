"""vanilla_revert.py -- a vanilla start leaves the game folder as Steam ships it (V1.5 delivery B.1, pass rn, 2026-11-02).

Berg, 2026-11-02: "We can go with 1" -- Steam's own file list is the authority for what stock is -- and "they should
keep vanilla unless the performance mods or gamemodes or whatnot is applied". So a vanilla start is: stock, proven
file by file, then only the extras the player chose in the launcher (they are applied AFTER run(), by the launcher, as
before), and nothing else of ours.

The launcher's vanilla start calls it (version "Bleach Rebirth of Souls": its Launch button and its right-click
Quick Launch entry; until 2026-11-06 Quick Launch Bros Vanilla too), and the start of a vanilla plus version
(launcher/vanilla_plus.py, 2026-11-13: the Steam game plus its own loader and plugins, installed after the proof).
    run(base_dir, game_path, parent=None)   after the launcher's own revert steps (mirror, overlays, exe) and BEFORE
                                            the player's extras: the plan, the actions, the proof. False = do not start.
                                            keep=: a vanilla plus version's own plugin state (PLUGIN_STATE), left
                                            where it is for that version's start (its vanilla_plus.json "keep").
    finalize(base_dir, game_path)           last, just before the Steam start: the launcher's own files out of the
                                            game folder (its report to the repo's Json\\).

THE AUTHORITY (steam_list). Read only:
  1. the app manifest, <library>\\steamapps\\appmanifest_1689620.acf (the game folder is
     <library>\\steamapps\\common\\<installdir>): the installed build and depot 1689621's manifest id;
  2. Steam's copy of that manifest, <Steam>\\depotcache\\1689621_<manifest id>.manifest (Steam's folder from the app
     manifest's LauncherPath, else the registry, else the default): every file's size and SHA-1;
  3. else the repo's copy for that same build and manifest id,
     Files\\Stock\\steam_1689621_<build>_<manifest id>.tsv.gz;
  4. else none: the repo's stock manifest (Files\\Stock\\stock_manifest_sha256.txt: sizes; SHA-256 for 1,298 files)
     stands in, and the report says the proof is by size only.

WHAT IS OURS (ours_index, RUNTIME). A path is ours when the repo can put a file there -- every version folder
(Script, Motion, 00HIGH, 01MIDDLE, 02LOW, Root, Overlay), every game mode (Script, Motion, its loader), Team Battle's
table, every rework, every Spec Mod value, the loader and every plugin, a vanilla plus version's loader and plugins
(its vanilla_plus.json: launcher/vanilla_plus.py) -- or when our code writes it at run time
(RUNTIME: the switch files, the match code, the logs and recordings, the launcher's own state). Everything else in the
game folder is the player's, and stays.
A VANILLA PLUS START keeps its own plugins' state (2026-11-14): the names its vanilla_plus.json lists under "keep"
that are in PLUGIN_STATE (hitbox.dll's hitbox.txt and hitbox_reach.txt) stay where they are -- the settings a player
chose there are the version's -- and the proof does not count them; a Vanilla start removes them like any of ours.

THE PLAN (plan(); it writes nothing):
  restore  a Steam path that is missing, has the wrong size, or -- where it is checked -- the wrong SHA-1. It is
           checked when the repo can write it (1,513 paths, 2.14 GB at build 21095206) or when the launcher kept a
           backup of it; the rest by size. A cache (%LOCALAPPDATA%\\BROS Launcher\\stock_sha1.json: path, size,
           mtime -> SHA-1) makes the next start quick.
  remove   a non-stock path that is ours (a version's file, a plugin, the loader, a switch file, a generated file).
  clear    the logs and the recordings: moved, not deleted, to %LOCALAPPDATA%\\BROS Launcher\\cleared\\<UTC>\\.
  keep     everything else: the player's, listed (the first 25 by name, all of them in the report).
RESTORE SOURCES, each proven by its SHA-1 against Steam's before it is used: the repo's vanilla folder
  (GameVersions\\Bleach Rebirth of Souls), Clean_EXE\\ for the exe, the launcher's backup (_launcher_vanilla_backup\\).
  A file none of them can give is left as it is and named, and Steam's verify is offered.
COPIES OF THE PLAYER'S EDITS (restore_stock's rule): before stock bytes replace bytes that are neither stock nor any
  repo file's for that path, and before a text file of ours (.txt .ini .json .cfg .xml) that the player edited is
  removed, a copy goes to _launcher_user_overwrites\\<path> (the player's; this module never removes it). A binary
  file at a path only the patch uses (a model, a motion, an effect) is the patch's -- this commit's or an older
  one's -- and goes without a copy and without being read.
THE PROOF (after the actions): every Steam path present with its size, every checked path with its SHA-1, nothing of
  ours left. Only then are the launcher's state and backups removed (they are what a failed revert needs next time).

Python 3.8, standard library only. Every write: <file>.vr_tmp, then os.replace, then the file is read again.
"""
import gzip
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import time

APP_ID = "1689620"
DEPOT_ID = "1689621"
EXE_NAME = "BLEACH_Rebirth_of_Souls.exe"
VANILLA_VERSION = "Bleach Rebirth of Souls"
VERIFY_URL = "steam://validate/" + APP_ID

# ---------------------------------------------------------------------------------------- what our code writes
# Game-root files written at run time by the launchers and the plugins (and recreated at the next patched start).
# Each name was read from its writer: launcher/*_mode.py, content_pool.py, diagnostics.py, fulldiag.py,
# install_guard.py, the main launcher's setup_matchmaking, and the plugins' sources (Files/Matchmaking/*.c).
RUNTIME_REMOVE = {
    "dinput8.dll": "the loader (setup_matchmaking)",
    "patch_ranked.txt": "the match code (setup_matchmaking)",
    "bros_net.txt": "the netcode switch (launcher/netcode_mode.py; V1.2's Overlay too)",
    "bros_tools.txt": "the developer-tool switches (launcher/devtools_mode.py)",
    "bros_zangetsu.txt": "the Zangetsu switch (launcher/zangetsu_mode.py)",
    "bros_fulldiag.txt": "the Advanced diagnostics switch (launcher/fulldiag.py)",
    "bros_diag.txt": "the tournament recorder's switch (launcher/diagnostics.py)",
    "bros_roster_v12.txt": "a roster marker (an Overlay; the overlay revert removes it too)",
    "bros_roster_v13.txt": "a roster marker (an Overlay; the overlay revert removes it too)",
    "bros_pl015_rework.txt": "V1.7's pl015 marker (an Overlay)",
    "launcher_content_pool.json": "the online pool of a patched start (launcher/content_pool.py)",
    "launcher_install_ids.json": "which bytes each installed file holds (launcher/install_guard.py IDS)",
    "replay_settings.txt": "replay.dll's Options > Save replays value",
    # the hit / hurt display (hitbox_plugin.c, 2026-11-14): its settings (the pause menu's Hitbox Display row and page
    # write them; a player may edit them by hand: RESCUE_RUNTIME), what its reach ring learned, and each one's copy
    # while it is written (a crash can leave one)
    "hitbox.txt": "hitbox.dll's settings: the pause menu's Hitbox Display row and page (hitbox_plugin.c)",
    "hitbox.txt.tmp": "hitbox.dll's settings being written (hitbox_plugin.c)",
    "hitbox_reach.txt": "what hitbox.dll's reach ring learned (hitbox_plugin.c)",
    "hitbox_reach.txt.tmp": "what hitbox.dll's reach ring learned, being written (hitbox_plugin.c)",
}
# Of those, the ones a player may also edit by hand (beyond the menus): a copy goes to _launcher_user_overwrites before
# a Vanilla start removes them, as for an edited text file the repo ships.
RESCUE_RUNTIME = ("hitbox.txt",)
# A plugin's own state beside the exe that a vanilla plus version keeps from one of its starts to the next, when its
# vanilla_plus.json names it under "keep" (launcher/vanilla_plus.py): its start leaves it where it is (run(keep=)),
# a Vanilla start removes it as above. Only these names can be kept; each is also in RUNTIME_REMOVE.
PLUGIN_STATE = {
    "hitbox.txt": "hitbox.dll's settings (the pause menu's Hitbox Display row and page)",
    "hitbox_reach.txt": "what hitbox.dll's reach ring learned",
}
# Files below the game root that our code writes at run time (game-relative, '/').
RUNTIME_REMOVE_PATHS = {
    "Script/CharaStatus.fsv.modestatus": "launcher/mode_status.py's sidecar beside a game mode's table",
    # the main launcher's _OVERLAY_ALWAYS_REMOVE: the pl005 sword copies of the 2026-09 intro work (1cb622a)
    "00HIGH/Model/chara/pl005_wep00_00_01.lds": "a pl005 sword copy (the main launcher's _OVERLAY_ALWAYS_REMOVE)",
    "00HIGH/Model/chara/pl005_wep00_00_01.tmd2": "a pl005 sword copy (the main launcher's _OVERLAY_ALWAYS_REMOVE)",
    "00HIGH/Model/chara/pl005_wep02_00_00.lds": "a pl005 sword copy (the main launcher's _OVERLAY_ALWAYS_REMOVE)",
    "00HIGH/Model/chara/pl005_wep02_00_00.tmd2": "a pl005 sword copy (the main launcher's _OVERLAY_ALWAYS_REMOVE)",
    "01MIDDLE/Model/chara/pl005_wep00_00_01.lds": "a pl005 sword copy (the main launcher's _OVERLAY_ALWAYS_REMOVE)",
    "01MIDDLE/Model/chara/pl005_wep00_00_01.tmd2": "a pl005 sword copy (the main launcher's _OVERLAY_ALWAYS_REMOVE)",
    "01MIDDLE/Model/chara/pl005_wep02_00_00.lds": "a pl005 sword copy (the main launcher's _OVERLAY_ALWAYS_REMOVE)",
    "01MIDDLE/Model/chara/pl005_wep02_00_00.tmd2": "a pl005 sword copy (the main launcher's _OVERLAY_ALWAYS_REMOVE)",
    "Physics/chara/pl005_wep00_01.cphy": "a pl005 sword copy (the main launcher's _OVERLAY_ALWAYS_REMOVE)",
}
# The launcher's own state: removed only after a proof that passes (a failed revert needs them next time).
LAUNCHER_STATE = ("launcher_patch_state.json",)
# The launcher's report of this start: finalize() moves it to the repo's Json\ (it is written after run()).
LAUNCHER_REPORT = "launcher_install_report.txt"
LAUNCHER_DIRS = ("_launcher_vanilla_backup",)
# Logs and recordings: moved out of the game folder (clear), never deleted.
RUNTIME_CLEAR = {
    "patch_ranked.log": "the loader's log (dinput8_proxy.c)",
    "patch_ranked.log.1": "the loader's previous log",
    "zang.log": "the pl005 roster table's diagnostic log (v12_table.h)",
    "kbhoho.log": "kbhoho.dll's log",
    "kbprobe.log": "kbprobe.dll's log",
    "studio.log": "BRoS Studio's log (studio_plugin.c)",
    "studio_events.log": "BRoS Studio's log",
    "studio_view.log": "BRoS Studio's log",
    "studio_crash.log": "BRoS Studio's log",
    "studio_camera.csv": "BRoS Studio's recording",
    "studio_bones.csv": "BRoS Studio's recording",
    "studio_fx.csv": "BRoS Studio's recording",
    "roomtrain_ot_trace.txt": "roomtrain.dll's trace",
    "roomtrain_ot_crumbs.txt": "roomtrain.dll's trace",
    "trainlab_probe.log": "trainlab.dll's probe log",
    "studio_last.txt": "BRoS Studio's breadcrumb log (studio_plugin.c)",
    "studio_last_old.txt": "BRoS Studio's previous breadcrumb log",
    "hitbox.log": "hitbox.dll's log (hitbox_plugin.c)",
}
RUNTIME_CLEAR_DIRS = {
    "crashlogs": "the loader's crash logs (crashlog.c)",
    "BROS_Diagnostics": "the tournament recorder's recordings (dinput8_proxy.c, launcher/diagnostics.py)",
    "BROS_FullDiag": "Advanced diagnostics' recordings and the launcher's snapshots (fulldiag.dll, launcher/fulldiag.py)",
    "studio_runs": "BRoS Studio's recordings",
    "studio_frames": "BRoS Studio's frames",
    "_launcher_quarantine": "stray effect backups the launcher moved out of the effect folders (install_guard)",
}
# Inside ReBalanceOfSouls\: every .dll is a plugin (ours), plus the files the plugins make at each start.
PLUGIN_DIR = "ReBalanceOfSouls"
PLUGIN_DIR_REMOVE = {
    "trainlab_Training.bin": "trainlab.dll's copy of Training.bin, made at each start",
    "roomtrain_Room_Match.bin": "roomtrain.dll's copy of Room_Match.bin, made at each start",
    "replay_Title_scene.bin": "replay.dll's copy of the title scene Title.bin, made at each start",
    "replay_Title_event.bin": "replay.dll's copy of the title event Title.bin, made at each start",
    # the Room Match check (pass rt, 2026-11-09): online.dll's list while the game runs, and the launcher window's
    # "I am open" file (launcher/room_check.py)
    "online_room_check.json": "online.dll's Room Match check list, rewritten while the game runs",
    "online_room_check.json.tmp": "online.dll's Room Match check list being written",
    "online_room_check.want": "the launcher's Room Match check window: open (rewritten every 5 s)",
    # the Rapid Reverse switch (launcher/rapidreverse_mode.py, 2026-11-13): written while it is OFF
    "rapidreverse.txt": "the launcher's Rapid Reverse switch (launcher/rapidreverse_mode.py), there while it is OFF",
    # the Komamura rework switch (launcher/komamura_rework.py, pass kr 2026-11-14): written while it is ON
    "komamura_rework.txt": "the launcher's Komamura rework switch (launcher/komamura_rework.py), there while it is ON",
}
# Never touched, even when a rule above would match a file in them.
KEEP_DIRS = {
    "_launcher_user_overwrites": "the player's own edits, kept by a revert",
    "_beta_staging": "the public beta launcher's folder",
}
# File-name literals the plugin sources hold that are NOT files our code writes in the game folder: the game's own
# files, system DLLs, inputs a developer writes by hand (kept as the player's), processes fulldiag names. The test
# (launcher/tests/test_vanilla_revert.py) reads every quoted name ending in .txt/.log/.jsonl/.csv/.json/.bin in
# Files/Matchmaking/*.c and fails on one that is in none of RUNTIME_*, PLUGIN_DIR_REMOVE, NOT_WRITTEN.
NOT_WRITTEN = {
    # hand-made inputs and test switches (read, never written): the player's / developer's
    "pl005_trigger.txt", "pl005_subl.txt", "pl005_stacks.txt", "pl005_reawaken.txt", "pl005_pose.txt",
    "pl005_mode.txt", "pl005_id52.txt", "pl005_hoho.txt", "pacing.txt", "pacing_off.txt", "framedata.txt",
    "patch_d3d12_debug.txt", "patch_ranked_logonly.txt", "bros_roster_size.txt", "bros_roster_row8.txt",
    "bros_roster_mode.txt", "bros_roster_member.txt", "bros_roster_limit.txt", "bros_roster_count.txt",
    "trainlab_test.txt", "trainlab_probe.txt", "roomtrain_ot.txt", "roomtrain_nt_test.txt",
    "studio.txt", "studio_scene.txt", "studio_game.txt", "studio_names.txt", "studio_mesh.txt",
    "studio_targets.txt", "TokenOpen.txt", "DevToken.txt", "replay.txt",
    # in ReBalanceOfSouls\, shipped by the versions' Overlays (ours by ours_index when they match a shipped copy)
    "dcreborn.txt", "dckeys.txt", "dcbossrush.txt", "eclipse_skins.txt",
    # the game's own files the plugins read or serve
    "CharaSelect.bin", "Training.bin", "training.bin", "Room_Match.bin", "room_match.bin",
    "Character_Select.bin", "Mission.bin", "timing.bin", "Title.bin", "title.bin",
    # fulldiag's machine snapshot and session files, written in its own folder under BROS_FullDiag (cleared)
    "threads.jsonl", "sys.jsonl", "modules.jsonl", "events.jsonl", "session.json", "meta.json", "config.json",
    "collector_output.txt", "README.txt",
    # the launcher's own files (LAUNCHER_STATE above, or the report finalize() moves)
    "launcher_patch_state.json", "launcher_content_pool.json", "launcher_install_report.txt", "launcher_install_ids.json",
}

# Stock files whose SHA-1 is always checked: the exe (a recipe build can keep the stock size) and the root binaries.
ALWAYS_CHECK = (EXE_NAME, "SPFXEngine.dll", "steam_api64.dll", "start_protected_game.exe")

_RUNTIME_PATHS_LOWER = {k.lower(): k for k in RUNTIME_REMOVE_PATHS}
# The files a player edits by hand. A file of ours with one of these extensions whose bytes are no repo file's is
# copied to _launcher_user_overwrites before it goes; any other file of ours goes without a copy (see plan()).
TEXT_EXT = (".txt", ".ini", ".json", ".cfg", ".xml")

CACHE_NAME = "stock_sha1.json"
TMP_SUFFIX = ".vr_tmp"


def _norm(rel):
    return rel.replace("\\", "/").strip("/")


def _key(rel):
    return _norm(rel).lower()


def _join(root, rel):
    return os.path.join(root, *_norm(rel).split("/"))


def app_data_dir():
    root = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(root, "BROS Launcher")


# ---------------------------------------------------------------------------------------- Steam's file list
class SteamList:
    """files: {lower path: (path with '/', size, sha1 hex or None)}; sha1 None = this source has sizes only."""

    def __init__(self, source, build, manifest, files, hashed):
        self.source, self.build, self.manifest, self.files, self.hashed = source, build, manifest, files, hashed


def parse_vdf(text):
    """Valve's KeyValues text, enough for an app manifest: {key: str or dict}."""
    toks = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    stack, cur, key = [], {}, None
    for s, brace in toks:
        if brace == "{":
            new = {}
            cur[key] = new
            stack.append(cur)
            cur, key = new, None
        elif brace == "}":
            cur = stack.pop() if stack else cur
            key = None
        elif key is None:
            key = s.replace("\\\\", "\\")
        else:
            cur[key] = s.replace("\\\\", "\\")
            key = None
    return cur


def _varint(b, o):
    v = s = 0
    while True:
        c = b[o]
        o += 1
        v |= (c & 0x7F) << s
        if c < 0x80:
            return v, o
        s += 7


def _fields(b):
    o = 0
    while o < len(b):
        k, o = _varint(b, o)
        f, w = k >> 3, k & 7
        if w == 0:
            v, o = _varint(b, o)
        elif w == 1:
            v = struct.unpack_from("<Q", b, o)[0]
            o += 8
        elif w == 2:
            n, o = _varint(b, o)
            v = b[o:o + n]
            o += n
        elif w == 5:
            v = struct.unpack_from("<I", b, o)[0]
            o += 4
        else:
            raise ValueError("protobuf wire type %d" % w)
        yield f, v


def parse_depot_manifest(data):
    """Steam's depotcache file: [u32 magic][u32 length][protobuf] sections; the payload (0x71F617D0) lists the files.
    Returns (metadata dict, {lower path: (path, size, sha1 hex)}); folders (flag 64) are left out."""
    o, sections = 0, {}
    while o + 8 <= len(data):
        magic, n = struct.unpack_from("<II", data, o)
        if magic == 0x32C415AB:
            break
        sections[magic] = data[o + 8:o + 8 + n]
        o += 8 + n
    if 0x71F617D0 not in sections:
        raise ValueError("no payload section: not a Steam depot manifest")
    meta = {}
    for f, v in _fields(sections.get(0x1F4812BE, b"")):
        meta[f] = v
    if meta.get(4):
        raise ValueError("the file names are encrypted")
    files = {}
    for f, v in _fields(sections[0x71F617D0]):
        if f != 1:
            continue
        name, size, flags, sha = None, 0, 0, b""
        for g, x in _fields(v):
            if g == 1:
                name = x.decode("utf-8")
            elif g == 2:
                size = x
            elif g == 3:
                flags = x
            elif g == 5:
                sha = x
        if name is None or flags & 64:
            continue
        rel = _norm(name)
        files[rel.lower()] = (rel, size, sha.hex() if sha else None)
    return {"depot_id": meta.get(1), "manifest": meta.get(2), "created": meta.get(3)}, files


def _steam_dirs(acf):
    out = []
    lp = (acf or {}).get("LauncherPath")
    if lp:
        out.append(os.path.dirname(lp))
    if sys.platform == "win32":
        try:
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for sub, val in (("Software\\Valve\\Steam", "SteamPath"),
                                 ("SOFTWARE\\WOW6432Node\\Valve\\Steam", "InstallPath")):
                    try:
                        with winreg.OpenKey(hive, sub) as k:
                            out.append(winreg.QueryValueEx(k, val)[0])
                    except OSError:
                        pass
        except Exception:
            pass
    out.append(r"C:\Program Files (x86)\Steam")
    seen, res = set(), []
    for d in out:
        d = os.path.normpath(d.replace("/", os.sep)) if d else d
        if d and d.lower() not in seen:
            seen.add(d.lower())
            res.append(d)
    return res


def read_tsv(path):
    opener = gzip.open if path.endswith(".gz") else open
    files = {}
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 4:
                rel = _norm(p[0])
                files[rel.lower()] = (rel, int(p[1]), p[3] or None)
    return files


def write_tsv(files, path):
    """The repo's copy: path (backslashes, as Steam writes it), size, flags (0), sha1, chunks (0)."""
    rows = sorted(files.values(), key=lambda t: t[0].lower())
    data = "".join("%s\t%d\t0\t%s\t0\n" % (r.replace("/", "\\"), s, h or "") for r, s, h in rows).encode("utf-8")
    with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as f:
        f.write(data)                   # no name and no time in the header: the same bytes on every machine


def stock_manifest(base_dir):
    """The repo's Files/Stock/stock_manifest_sha256.txt as a size-only list ('-' or a SHA-256 is not a SHA-1)."""
    p = os.path.join(base_dir, "Files", "Stock", "stock_manifest_sha256.txt")
    files = {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                q = line.rstrip("\n").split("\t")
                if len(q) == 3:
                    rel = _norm(q[2])
                    files[rel.lower()] = (rel, int(q[1]), None)
    except OSError:
        pass
    return files


def steam_list(base_dir, game_path, steam_dirs=None):
    """The authority for this game folder -- see the module docstring. Never raises; .source says what it is."""
    game_path = os.path.normpath(game_path)
    steamapps = os.path.dirname(os.path.dirname(game_path))
    acf, build, manifest = None, None, None
    try:
        with open(os.path.join(steamapps, "appmanifest_%s.acf" % APP_ID), "r", encoding="utf-8",
                  errors="replace") as f:
            acf = parse_vdf(f.read()).get("AppState", {})
        build = acf.get("buildid")
        manifest = acf.get("InstalledDepots", {}).get(DEPOT_ID, {}).get("manifest")
    except Exception:
        acf = None
    if manifest:
        for d in (steam_dirs if steam_dirs is not None else _steam_dirs(acf)):
            p = os.path.join(d, "depotcache", "%s_%s.manifest" % (DEPOT_ID, manifest))
            if os.path.isfile(p):
                try:
                    with open(p, "rb") as f:
                        meta, files = parse_depot_manifest(f.read())
                    if str(meta.get("manifest")) == str(manifest):
                        return SteamList("Steam's depot manifest %s (build %s)" % (manifest, build), build,
                                         manifest, files, True)
                except Exception:
                    pass
        rp = os.path.join(base_dir, "Files", "Stock", "steam_%s_%s_%s.tsv.gz" % (DEPOT_ID, build, manifest))
        if os.path.isfile(rp):
            try:
                return SteamList("the repo's copy of Steam's list (build %s, manifest %s)" % (build, manifest),
                                 build, manifest, read_tsv(rp), True)
            except Exception:
                pass
    files = stock_manifest(base_dir)
    return SteamList("the repo's stock manifest, by size only (no Steam list for build %s)" % (build or "?"),
                     build, manifest, files, False)


# ---------------------------------------------------------------------------------------- what the repo can write
def _excluded(name):
    try:
        from launcher.layers import is_excluded
        return is_excluded(name)
    except Exception:
        n = name.lower()
        return n in {"thumbs.db", "desktop.ini", ".gitkeep", ".gitignore", ".ds_store"} or bool(
            re.search(r"\.bak$|_bak$|\s\(\d+\)\.|\.(bat|py)(\s|$)", name, re.I))


def _walk(src_root, dest_prefix, out, only_dll=False, skip=("_overlay_manifest.json",)):
    if not os.path.isdir(src_root):
        return
    for dirpath, dirs, files in os.walk(src_root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f in skip or _excluded(f) or (only_dll and not f.lower().endswith(".dll")):
                continue
            src = os.path.join(dirpath, f)
            rel = os.path.relpath(src, src_root).replace("\\", "/")
            rel = (dest_prefix + "/" + rel) if dest_prefix else rel
            k = rel.lower()
            if k not in out:
                out[k] = (rel, [])
            out[k][1].append(src)


def _vanilla_plus_files(vd, out):
    """A vanilla plus version's loader (-> dinput8.dll) and plugins (-> ReBalanceOfSouls\\<name>), as its
    vanilla_plus.json lists them (launcher/vanilla_plus.py checks that file before a launch; this only reads it, and a
    file it cannot read adds nothing)."""
    try:
        with open(os.path.join(vd, "vanilla_plus.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    entries = [("dinput8.dll", data.get("loader"))]
    entries += [(None, p) for p in (data.get("plugins") if isinstance(data.get("plugins"), list) else [])]
    for dest, rel in entries:
        if not isinstance(rel, str) or os.path.isabs(rel) or ".." in rel.replace("\\", "/").split("/"):
            continue
        src = os.path.join(vd, *rel.replace("\\", "/").split("/"))
        if not os.path.isfile(src):
            continue
        g = dest or PLUGIN_DIR + "/" + os.path.basename(src)
        out.setdefault(g.lower(), (g, []))[1].append(src)


def ours_index(base_dir):
    """{lower game path: (path, [repo files that can land there])} -- see the module docstring."""
    out = {}
    gv = os.path.join(base_dir, "GameVersions")
    for v in sorted(os.listdir(gv)) if os.path.isdir(gv) else []:
        vd = os.path.join(gv, v)
        if not os.path.isdir(vd):
            continue
        for sub in ("Script", "Motion", "00HIGH", "01MIDDLE", "02LOW"):
            _walk(os.path.join(vd, sub), sub, out)
        _walk(os.path.join(vd, "Root"), "", out)
        _walk(os.path.join(vd, "Overlay"), "", out)
        _vanilla_plus_files(vd, out)
    gm = os.path.join(base_dir, "GameModes")
    for m in sorted(os.listdir(gm)) if os.path.isdir(gm) else []:
        md = os.path.join(gm, m)
        if not os.path.isdir(md):
            continue
        for sub in ("Script", "Motion"):
            _walk(os.path.join(md, sub), sub, out)
        for f in ("dinput8.dll",):
            p = os.path.join(md, f)
            if os.path.isfile(p):
                out.setdefault(f.lower(), (f, []))[1].append(p)
    tb = os.path.join(gm, "TeamBattle", "CharaStatus.fsv")
    if os.path.isfile(tb):
        out.setdefault("script/charastatus.fsv", ("Script/CharaStatus.fsv", []))[1].append(tb)
    rw = os.path.join(base_dir, "Reworks")
    for r in sorted(os.listdir(rw)) if os.path.isdir(rw) else []:
        for sub in ("Script", "Motion"):
            _walk(os.path.join(rw, r, sub), sub, out)
        # a rework's files outside Script / Motion, at their game paths (the Komamura rework's Overlay/, installed
        # through the main launcher's overlay pairs; pass kr 2026-11-14)
        _walk(os.path.join(rw, r, "Overlay"), "", out)
        # and its plugin (Reworks/<r>/Plugin/*.dll -> ReBalanceOfSouls\, installed by the rework's launch step while
        # its switch is ON; pass kr 2026-11-14)
        _walk(os.path.join(rw, r, "Plugin"), PLUGIN_DIR, out, only_dll=True)
    sm = os.path.join(base_dir, "Files", "Spec Mod")
    for feat in sorted(os.listdir(sm)) if os.path.isdir(sm) else []:
        fd = os.path.join(sm, feat)
        for val in sorted(os.listdir(fd)) if os.path.isdir(fd) else []:
            vd = os.path.join(fd, val)
            if not os.path.isdir(vd):
                continue
            if feat == "reverse_globe":
                _walk(os.path.join(vd, "high"), "00HIGH/Effect/spfx/com", out)
                _walk(os.path.join(vd, "middle"), "01MIDDLE/Effect/spfx/com", out)
            elif val.endswith("_middle"):
                _walk(vd, "01MIDDLE/Effect/spfx/com", out)
            else:
                _walk(vd, "00HIGH/Effect/spfx/com", out)
                _walk(vd, "01MIDDLE/Effect/spfx/com", out)
    mm = os.path.join(base_dir, "Files", "Matchmaking")
    p = os.path.join(mm, "dinput8.dll")
    if os.path.isfile(p):
        out.setdefault("dinput8.dll", ("dinput8.dll", []))[1].append(p)
    _walk(os.path.join(mm, "Plugins"), PLUGIN_DIR, out, only_dll=True)
    return out


# ---------------------------------------------------------------------------------------- hashing, with a cache
class Hasher:
    def __init__(self, cache_path=None, progress=None):
        self.cache_path = cache_path
        self.progress = progress
        self.cache = {}
        self.dirty = False
        self.hashed_bytes = 0
        if cache_path:
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
            except Exception:
                self.cache = {}

    def sha1(self, path, done_cb=None):
        """SHA-1 hex of a file, from the cache when its size and mtime are the same; None when it cannot be read."""
        try:
            st = os.stat(path)
        except OSError:
            return None
        k = os.path.normcase(os.path.abspath(path))
        c = self.cache.get(k)
        if c and c[0] == st.st_size and c[1] == st.st_mtime_ns:
            return c[2]
        h = hashlib.sha1()
        try:
            with open(path, "rb") as f:
                while True:
                    b = f.read(1 << 20)
                    if not b:
                        break
                    h.update(b)
                    self.hashed_bytes += len(b)
                    if done_cb:
                        done_cb(len(b))
        except OSError:
            return None
        d = h.hexdigest()
        self.cache[k] = [st.st_size, st.st_mtime_ns, d]
        self.dirty = True
        return d

    def forget(self, path):
        """Drop a path from the cache (a file this module has just written: hash it again, for real)."""
        if self.cache.pop(os.path.normcase(os.path.abspath(path)), None) is not None:
            self.dirty = True

    def save(self):
        if not (self.cache_path and self.dirty):
            return
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            tmp = self.cache_path + TMP_SUFFIX
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.cache, f)
            os.replace(tmp, self.cache_path)
            self.dirty = False
        except Exception:
            pass


# ---------------------------------------------------------------------------------------- the plan
class Plan:
    def __init__(self):
        self.restore = []       # (rel, why, source path or None)
        self.remove = []        # (rel, why, rescue: bool)
        self.clear = []         # (rel, why, is_dir)
        self.keep = []          # rel (files the player has: not stock, not ours)
        self.ok_stock = 0
        self.checked = 0        # stock paths checked by SHA-1
        self.notes = []

    def counts(self):
        return dict(restore=len(self.restore), unrestorable=sum(1 for r in self.restore if r[2] is None),
                    remove=len(self.remove), clear=len(self.clear), keep=len(self.keep), ok_stock=self.ok_stock,
                    checked=self.checked)


def _stock_sources(base_dir, game_path, rel):
    """Candidate sources for a stock path, in order: the vanilla folder, Clean_EXE, the launcher's backup."""
    out = []
    parts = _norm(rel).split("/")
    vd = os.path.join(base_dir, "GameVersions", VANILLA_VERSION)
    if parts[0] in ("Script", "Motion", "00HIGH", "01MIDDLE", "02LOW"):
        out.append(os.path.join(vd, *parts))
    out.append(os.path.join(vd, "Root", *parts))
    if _norm(rel).lower() == EXE_NAME.lower():
        out.append(os.path.join(base_dir, "Clean_EXE", EXE_NAME))
    out.append(os.path.join(game_path, "_launcher_vanilla_backup", *parts))
    return [p for p in out if os.path.isfile(p)]


def _top(rel):
    return _norm(rel).split("/")[0]


def _keepable(keep):
    """The names of keep (a vanilla plus version's "keep") this module keeps: PLUGIN_STATE's, matched exactly."""
    return set(k for k in (keep or ()) if isinstance(k, str) and k in PLUGIN_STATE)


def plan(base_dir, game_path, steam, ours=None, hasher=None, progress=None, keep=()):
    """Read only. See the module docstring. keep: the plugin state a vanilla plus start leaves (PLUGIN_STATE)."""
    ours = ours if ours is not None else ours_index(base_dir)
    keep = _keepable(keep)
    hasher = hasher or Hasher()
    pl = Plan()
    pl.notes.append("authority: " + steam.source)
    backup_root = os.path.join(game_path, "_launcher_vanilla_backup")
    backed = set()
    if os.path.isdir(backup_root):
        for dirpath, _d, files in os.walk(backup_root):
            for f in files:
                backed.add(os.path.relpath(os.path.join(dirpath, f), backup_root).replace("\\", "/").lower())
    # 1. stock: which paths are checked by hash, and their total, for the progress
    always = set(x.lower() for x in ALWAYS_CHECK)
    check = [k for k in steam.files if k in ours or k in backed or k in always] if steam.hashed else []
    total = sum(steam.files[k][1] for k in check)
    done = [0]

    def tick(n):
        done[0] += n
        if progress:
            progress("Checking the game files", done[0], total)

    if progress:
        progress("Checking the game files", 0, total)
    check = set(check)
    for k, (rel, size, sha) in sorted(steam.files.items()):
        p = _join(game_path, rel)
        try:
            st = os.stat(p)
        except OSError:
            pl.restore.append((rel, "missing", None))
            continue
        if st.st_size != size:
            pl.restore.append((rel, "size %d, Steam's %d" % (st.st_size, size), None))
            continue
        if k in check and sha:
            pl.checked += 1
            if hasher.sha1(p, tick) != sha:
                pl.restore.append((rel, "not Steam's bytes", None))
                continue
        pl.ok_stock += 1
    # sources for what has to be restored, each proven by its SHA-1
    fixed = []
    for rel, why, _s in pl.restore:
        want = steam.files[rel.lower()]
        src = None
        for c in _stock_sources(base_dir, game_path, rel):
            try:
                if os.path.getsize(c) != want[1]:
                    continue
            except OSError:
                continue
            if want[2] is None or hasher.sha1(c) == want[2]:
                src = c
                break
        fixed.append((rel, why, src))
    pl.restore = fixed
    # 2. the rest of the game folder: ours (remove / clear) or the player's (keep)
    for dirpath, dirs, files in os.walk(game_path):
        reld = os.path.relpath(dirpath, game_path).replace("\\", "/")
        reld = "" if reld == "." else reld
        top = _top(reld) if reld else ""
        if not reld:
            for d in list(dirs):
                if d in KEEP_DIRS:
                    dirs.remove(d)
                    pl.notes.append("kept: %s\\ (%s)" % (d, KEEP_DIRS[d]))
                elif d in RUNTIME_CLEAR_DIRS:
                    dirs.remove(d)
                    pl.clear.append((d, RUNTIME_CLEAR_DIRS[d], True))
                elif d in LAUNCHER_DIRS:
                    dirs.remove(d)          # handled after the proof
        for f in files:
            rel = (reld + "/" + f) if reld else f
            k = rel.lower()
            if f.endswith(TMP_SUFFIX):
                pl.remove.append((rel, "an unfinished copy of this module's", False))
                continue
            if k in steam.files:
                continue
            if k in _RUNTIME_PATHS_LOWER:
                pl.remove.append((rel, RUNTIME_REMOVE_PATHS[_RUNTIME_PATHS_LOWER[k]], False))
                continue
            if not reld and f in keep:
                # a vanilla plus version's own plugin state: its start keeps it (2026-11-14)
                pl.keep.append(rel)
                pl.notes.append("kept for this version: %s (%s)" % (rel, PLUGIN_STATE[f]))
                continue
            if not reld and f in RUNTIME_REMOVE:
                # made by our code, so no copy -- but a loader that is none of the repo's may be another mod's, and a
                # settings file a player may edit by hand (RESCUE_RUNTIME) is copied first
                rescue = (f == "dinput8.dll" and not (k in ours and _same_as_any(hasher, rel, game_path, ours[k][1]))) \
                    or f in RESCUE_RUNTIME
                pl.remove.append((rel, RUNTIME_REMOVE[f], rescue))
                continue
            if not reld and f in RUNTIME_CLEAR:
                pl.clear.append((rel, RUNTIME_CLEAR[f], False))
                continue
            if not reld and (f in LAUNCHER_STATE or f == LAUNCHER_REPORT):
                continue                    # the state after the proof; the report in finalize()
            if top == PLUGIN_DIR and reld == PLUGIN_DIR and (f.lower().endswith(".dll") or f in PLUGIN_DIR_REMOVE):
                why = PLUGIN_DIR_REMOVE.get(f, "a plugin")
                rescue = f.lower().endswith(".dll") and not (k in ours and _same_as_any(hasher, rel, game_path,
                                                                                        ours[k][1]))
                pl.remove.append((rel, why, rescue))
                continue
            if k in ours:
                # a copy first only for a text file the player may have edited by hand (TEXT_EXT); a binary at a
                # path only the patch uses is the patch's, from this commit or an older one: no copy, no hashing
                text = os.path.splitext(f)[1].lower() in TEXT_EXT
                rescue = text and not _same_as_any(hasher, rel, game_path, ours[k][1])
                pl.remove.append((rel, "a file the repo ships here", rescue))
                continue
            pl.keep.append(rel)
    return pl


def _same_as_any(hasher, rel, game_path, sources):
    p = _join(game_path, rel)
    try:
        size = os.path.getsize(p)
    except OSError:
        return True
    cands = [s for s in sources if os.path.isfile(s) and os.path.getsize(s) == size]
    if not cands:
        return False
    d = hasher.sha1(p)
    return any(hasher.sha1(s) == d for s in cands)


# ---------------------------------------------------------------------------------------- the actions
def _copy_in(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + TMP_SUFFIX
    shutil.copyfile(src, tmp)
    try:
        shutil.copystat(src, tmp)
    except OSError:
        pass
    os.replace(tmp, dst)


def _rescue(game_path, rel):
    """A copy of the player's bytes in _launcher_user_overwrites\\<path>, before they go. True when kept."""
    src = _join(game_path, rel)
    dst = os.path.join(game_path, "_launcher_user_overwrites", *_norm(rel).split("/"))
    try:
        if os.path.exists(dst):
            base, ext = os.path.splitext(dst)
            dst = "%s.%s%s" % (base, time.strftime("%Y%m%d-%H%M%S"), ext)
        _copy_in(src, dst)
        return True
    except OSError:
        return False


def exe_locked(game_path):
    """True when the game is running: Windows does not let a running exe be opened for writing."""
    p = os.path.join(game_path, EXE_NAME)
    if not os.path.exists(p) or not os.access(p, os.W_OK):
        return False                    # no exe, or a read-only one: not a running game
    try:
        with open(p, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def apply(base_dir, game_path, steam, pl, hasher, clear_root, progress=None, log=print):
    """Carry the plan out. Returns a dict of what happened."""
    res = dict(restored=[], restore_failed=[], unrestorable=[], removed=[], remove_failed=[], rescued=[],
               cleared=[], clear_failed=[])
    n = len(pl.restore) + len(pl.remove) + len(pl.clear)
    i = 0
    for rel, why, src in pl.restore:
        i += 1
        if progress:
            progress("Restoring the game files", i, n)
        dst = _join(game_path, rel)
        if src is None:
            res["unrestorable"].append((rel, why))
            continue
        want = steam.files[rel.lower()]
        try:
            if os.path.exists(dst):
                # bytes that are neither stock nor any repo file's for this path: the player's edit, kept first
                repo_files = ours_cache(base_dir).get(rel.lower(), (rel, []))[1]
                if not _same_as_any(hasher, rel, game_path, repo_files) and _rescue(game_path, rel):
                    res["rescued"].append(rel)
            _copy_in(src, dst)
            hasher.forget(dst)
            ok = os.path.getsize(dst) == want[1] and (want[2] is None or hasher.sha1(dst) == want[2])
            (res["restored"] if ok else res["restore_failed"]).append(rel)
        except OSError as e:
            res["restore_failed"].append(rel)
            log("[vanilla] could not restore %s: %s" % (rel, e))
    for rel, why, rescue in pl.remove:
        i += 1
        if progress:
            progress("Removing the patch's files", i, n)
        p = _join(game_path, rel)
        try:
            if rescue and _rescue(game_path, rel):
                res["rescued"].append(rel)
            os.remove(p)
            res["removed"].append(rel)
        except FileNotFoundError:
            res["removed"].append(rel)
        except OSError as e:
            res["remove_failed"].append(rel)
            log("[vanilla] could not remove %s: %s" % (rel, e))
    for rel, why, is_dir in pl.clear:
        i += 1
        if progress:
            progress("Moving the logs out", i, n)
        src = _join(game_path, rel)
        dst = os.path.join(clear_root, *_norm(rel).split("/"))
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            res["cleared"].append(rel)
        except (OSError, shutil.Error) as e:
            res["clear_failed"].append(rel)
            log("[vanilla] could not move %s out: %s" % (rel, e))
    # ReBalanceOfSouls\ goes when nothing but ours was in it
    pd = os.path.join(game_path, PLUGIN_DIR)
    try:
        if os.path.isdir(pd) and not os.listdir(pd):
            os.rmdir(pd)
    except OSError:
        pass
    return res


_OURS_CACHE = {}


def ours_cache(base_dir):
    if base_dir not in _OURS_CACHE:
        _OURS_CACHE[base_dir] = ours_index(base_dir)
    return _OURS_CACHE[base_dir]


# ---------------------------------------------------------------------------------------- the proof
def prove(base_dir, game_path, steam, hasher, checked_keys, keep=()):
    """[(path, what is wrong)]: every Steam path with its size, the checked ones with their SHA-1, nothing of ours
    left at the game root or in ReBalanceOfSouls\\ -- but the plugin state a vanilla plus start keeps (keep)."""
    bad = []
    keep = _keepable(keep)
    for k, (rel, size, sha) in steam.files.items():
        p = _join(game_path, rel)
        try:
            st = os.stat(p)
        except OSError:
            bad.append((rel, "missing"))
            continue
        if st.st_size != size:
            bad.append((rel, "size %d, Steam's %d" % (st.st_size, size)))
        elif k in checked_keys and sha and hasher.sha1(p) != sha:
            bad.append((rel, "not Steam's bytes"))
    for f in list(RUNTIME_REMOVE) + list(RUNTIME_CLEAR) + list(RUNTIME_REMOVE_PATHS):
        if f not in keep and os.path.exists(_join(game_path, f)):
            bad.append((f, "still in the game folder"))
    for d in RUNTIME_CLEAR_DIRS:
        if os.path.exists(os.path.join(game_path, d)):
            bad.append((d + "/", "still in the game folder"))
    pd = os.path.join(game_path, PLUGIN_DIR)
    if os.path.isdir(pd):
        for f in os.listdir(pd):
            if f.lower().endswith(".dll") or f in PLUGIN_DIR_REMOVE:
                bad.append((PLUGIN_DIR + "/" + f, "still in the game folder"))
    return bad


# ---------------------------------------------------------------------------------------- the whole revert
def _write_report(base_dir, text, data):
    d = os.path.join(base_dir, "Json")
    try:
        os.makedirs(d, exist_ok=True)
        for name, body in (("vanilla_report.txt", text), ("vanilla_report.json", json.dumps(data, indent=1))):
            p = os.path.join(d, name)
            with open(p + TMP_SUFFIX, "w", encoding="utf-8") as f:
                f.write(body)
            os.replace(p + TMP_SUFFIX, p)
        return os.path.join(d, "vanilla_report.txt")
    except OSError:
        return None


def revert(base_dir, game_path, progress=None, log=print, cache_path=None, clear_root=None, steam_dirs=None, keep=()):
    """plan -> apply -> prove -> (state and backups out when the proof passes). Returns (ok, report text, data).
    keep: a vanilla plus version's own plugin state (PLUGIN_STATE names), left where it is."""
    if exe_locked(game_path):
        return False, "The game is running: close it, then start Vanilla again. Nothing was changed.", {}
    steam = steam_list(base_dir, game_path, steam_dirs)
    hasher = Hasher(cache_path if cache_path is not None else os.path.join(app_data_dir(), CACHE_NAME), progress)
    ours = ours_cache(base_dir)
    pl = plan(base_dir, game_path, steam, ours, hasher, progress, keep)
    stamp = time.strftime("%Y%m%d-%H%M%SZ", time.gmtime())
    clear_root = clear_root or os.path.join(app_data_dir(), "cleared", stamp)
    res = apply(base_dir, game_path, steam, pl, hasher, clear_root, progress, log)
    always = set(x.lower() for x in ALWAYS_CHECK)
    checked = set(k for k in steam.files if k in ours or k in always) if steam.hashed else set()
    checked |= set(r[0].lower() for r in pl.restore)
    if progress:
        progress("Proving the game folder stock", 0, 0)
    bad = prove(base_dir, game_path, steam, hasher, checked, keep)
    removed_state = []
    if not bad:
        for f in LAUNCHER_STATE:
            p = os.path.join(game_path, f)
            if os.path.exists(p):
                try:
                    os.remove(p)
                    removed_state.append(f)
                except OSError:
                    pass
        for d in LAUNCHER_DIRS:
            p = os.path.join(game_path, d)
            if os.path.isdir(p):
                try:
                    shutil.rmtree(p)
                    removed_state.append(d + "/")
                except OSError:
                    pass
    hasher.save()
    c = pl.counts()
    lines = ["Vanilla revert, %s UTC" % time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
             "Game folder: %s" % game_path, "Authority: %s" % steam.source,
             "Stock files: %d listed, %d already right (%d checked by SHA-1), %d restored, %d could not be restored"
             % (len(steam.files), c["ok_stock"], c["checked"], len(res["restored"]),
                len(res["unrestorable"]) + len(res["restore_failed"])),
             "Files of ours removed: %d; logs and recordings moved out: %d (to %s)"
             % (len(res["removed"]), len(res["cleared"]), clear_root if res["cleared"] else "-"),
             "Copies of edited files kept in _launcher_user_overwrites: %d" % len(res["rescued"]),
             "The player's files, kept: %d" % len(pl.keep),
             "The launcher's state and backups removed: %s" % (", ".join(removed_state) or "none")]
    for rel, why in res["unrestorable"]:
        lines.append("  NOT RESTORED (no proven source): %s (%s)" % (rel, why))
    for rel in res["restore_failed"]:
        lines.append("  NOT RESTORED (the copy failed): %s" % rel)
    for rel in res["remove_failed"] + res["clear_failed"]:
        lines.append("  NOT REMOVED: %s" % rel)
    for rel, why in bad[:40]:
        lines.append("  PROOF FAILED: %s -- %s" % (rel, why))
    if bad:
        lines.append("The game folder is NOT proven stock. Steam can repair the files above: %s" % VERIFY_URL)
    else:
        lines.append("The game folder is proven stock (then the extras you chose in the launcher are applied).")
    for rel in pl.keep[:25]:
        lines.append("  kept (yours): %s" % rel)
    if len(pl.keep) > 25:
        lines.append("  ... and %d more kept (the full list: Json\\vanilla_report.json)" % (len(pl.keep) - 25))
    lines += ["  note: " + n for n in pl.notes]
    text = "\n".join(lines) + "\n"
    data = dict(when=time.time(), game=game_path, authority=steam.source, counts=c, result=res, proof_failed=bad,
                kept=pl.keep, removed_state=removed_state, notes=pl.notes)
    rp = _write_report(base_dir, text, data)
    if rp:
        text += "Report: %s\n" % rp
    log(text.rstrip())
    return not bad, text, data


def finalize(base_dir, game_path, log=print):
    """Last, just before the Steam start: the launcher's own report of this start goes to the repo's Json\\, the
    quarantine folder install_guard may have just made goes out with the logs. Never fails a start."""
    try:
        p = os.path.join(game_path, LAUNCHER_REPORT)
        if os.path.exists(p):
            d = os.path.join(base_dir, "Json")
            os.makedirs(d, exist_ok=True)
            dst = os.path.join(d, "launcher_install_report_vanilla.txt")
            if os.path.exists(dst):
                os.remove(dst)
            shutil.move(p, dst)
        q = os.path.join(game_path, "_launcher_quarantine")
        if os.path.isdir(q):
            dst = os.path.join(app_data_dir(), "cleared", time.strftime("%Y%m%d-%H%M%SZ", time.gmtime()),
                               "_launcher_quarantine")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(q, dst)
    except Exception as e:
        log("[vanilla] finalize: %s" % e)


def run(base_dir, game_path, parent=None, title="Bleach Rebirth of Souls: Vanilla", log=print, ask=None,
        label="Vanilla", keep=()):
    """The revert with a progress window (launcher/update_window's) when tkinter is there. Returns True when the
    game may start: the proof passed, or it failed and ask(title, text) -- the launcher's dialog -- said start
    anyway. A running game (the exe locked) is always False. label: the version the messages name. keep: a vanilla
    plus version's own plugin state (its vanilla_plus.json "keep", PLUGIN_STATE names), left where it is."""
    if exe_locked(game_path):
        msg = "The game is running: close it, then start %s again. Nothing was changed." % label
        log("[vanilla] " + msg)
        if ask:
            ask(title, msg, True)
        return False
    box = {}
    try:
        from launcher import update_window as uw
    except Exception:
        uw = None
    prog = uw.Progress() if uw else None

    def progress(phase, done, total):
        if prog:
            prog.set(phase=phase, detail=("%d of %d MB" % (done >> 20, total >> 20)) if total > (64 << 20) else "",
                     done=done, total=total)

    def work():
        try:
            box["r"] = revert(base_dir, game_path, progress, log, keep=keep)
        except BaseException as e:
            box["e"] = e

    win = None
    if uw:
        try:
            win = uw._Window(parent, title, prog)
            if not win.ok:
                win = None
        except Exception:
            win = None
    if win:
        prog.set(phase="Checking the game files")
        win.show_now()
        win.run(work)
    else:
        work()
    if "e" in box:
        log("[vanilla] the revert failed: %r" % (box["e"],))
        if ask:
            return bool(ask(title, "The vanilla revert failed: %r\n\nThe game folder may not be stock." % (box["e"],),
                            True))
        return False
    ok, text, _data = box["r"]
    if ok:
        return True
    if ask:
        return bool(ask(title, text, True))
    return False


if __name__ == "__main__":
    # python launcher\vanilla_revert.py plan [<game folder>]   what a vanilla start would do (changes nothing)
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["plan"])
    ap.add_argument("game", nargs="?", default=r"D:\SteamLibrary\steamapps\common\BLEACH Rebirth of Souls")
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--cache")
    a = ap.parse_args()
    st = steam_list(a.repo, a.game)
    hs = Hasher(a.cache)
    p = plan(a.repo, a.game, st, None, hs, None)
    hs.save()
    print(json.dumps(dict(authority=st.source, counts=p.counts(), restore=p.restore[:200], remove=p.remove[:400],
                          clear=p.clear, keep=p.keep[:400], notes=p.notes), indent=1))
