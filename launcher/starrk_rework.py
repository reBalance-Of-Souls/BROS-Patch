"""starrk_rework.py -- the launcher's Starrk rework switch (beta; KOMAMURA_REWORK's pattern, launcher/komamura_rework.py).

RETIRED ON 2026-11-22. The rework is in the game for everyone now, as a character of his own: the reborn Coyote Starrk
(Primera), id 54 -- his pl054 files, rows and registry entries in GameVersions/ReBalance of Souls V2.0 (as Ryuken's,
pl053) and Files/Matchmaking/Plugins/pl054rw.dll, pl033rw.dll's rules for id 54 (Files/Matchmaking/pl054rw_plugin.c,
made from Reworks/Starrk/Plugin/pl033rw_plugin.c by mv_rw54_make.py) -- beside Starrk (33) as the version ships him.
Berg, 2026-11-22 16:58 CET: "reworked starrk should work exactly like the launcher switch, but simply in game"; the
launcher's card was removed on his word the same day. What is left of the switch:
  * load_choice() and wanted() are False whatever Json/starrk_rework.json says, and save_choice() refuses: the
    launcher never asks for preflight() or overlay_pairs() again;
  * install_data(base_dir, game, False, version), at every launch of a patched version, takes away what a launch with
    the switch ON left in the game folder: the rework's files at paths the Steam game does not have that still hold its
    bytes -- except a path the version installs a file at itself (the reborn shares 42 of them, with the same bytes:
    the rework's effects, models and summons' ObjectConfig files). Without a version named, nothing is removed;
  * launch_step() removes ReBalanceOfSouls\\pl033rw.dll where it is the rework's build.
Reworks/Starrk stays in the repo: the reborn's files were made from it, and the clean-up reads its manifest.

THE SWITCH AS IT WAS (2026-11-15 .. 2026-11-22):

IN THE LAUNCHER. The Advanced settings page has a "Starrk rework (beta)" card with one switch, ON unless switched off
(Berg, 2026-11-15: "replace the current Starrk character with the work done on him ... Place an option in the dev
patch launcher menu to return him to the usual starrk, but the rework is on by default, the opposite of komamura";
pass sr, STARRK_REWORK_2026-11-15):

  ON (the default): the Starrk rework, as built and tested on the branch starrk-rework (the dev environment, its
      version folder GameVersions/Bleach Rebalance of Souls V1.7 Starrk Rework, its README.md and Plugin/README.md say
      what each change does and why): three forms -- Base with Lilynette as a summon, Gun Form (Awakening) and the
      Wolf / Sword Form (Reawakening) -- with his moves, combo tables, stats, CPU, cutscenes, voice lines and music,
      and his plugin (Reworks/Starrk/Plugin/pl033rw.dll) for the rules his data cannot carry. Starrk only: every other
      character, table row and file is the version's.
  OFF: Coyote Starrk (pl033) as the version ships him -- nothing of this module reaches the game folder.
A choice saved before the default changed keeps its meaning: "ON" stays ON, "OFF" stays OFF; no saved choice is ON.

WHAT A LAUNCH DOES WHILE IT IS ON (the same steps, at the same places in launch(), as the Komamura rework's):
  * preflight(), before anything is installed: every rework file as its manifest names it (Reworks/Starrk/manifest.json:
    game path, md5, size), its row spec (rows.json), its registry spec (fnames.json), the plugin, the game folder and
    its two registries; and not with the Komamura rework ON while its plugin is round 2's build (14b2a335): that
    build's stand wraps every fighter's update and weapon visibility in the OPlayableBase / OOnlinePlayable vtable
    slots 37 and 148, which pl033rw.dll wraps too, and the host refuses the second claim. The Komamura rework's round
    2c plugin (pass kr, KOMAMURA_REWORK_2026-11-14, hist kr067-kr069) hooks inside those functions instead and runs
    beside this one, so the two reworks can be ON together;
  * install_data(), after the version, the reworks and the game mode's files: copies Reworks/Starrk/Script and Motion
    over the game's (his action, combo and motion packages, his CPU table, his summons' ObjectConfig rows) -- the
    version's Script / Motion are mirrored at every launch, so an OFF launch puts the version's own back by itself;
    edits Starrk's rows of the shared tables the version installed (rows.json: CharaStatus, CharaModelVisible,
    MdlDefaultVisible, WepVisible, additional_status_effect, chara_bgm), each re-encoded with the table's OWN version,
    key and tail; registers his files at paths the Steam game does not have in Fnames\\file_exist.htable and his model
    and icon names in Fnames\\filename.bin (the version installs both tables again at every launch);
  * the files outside Script / Motion (Reworks/Starrk/Overlay: his cutscenes, his CPU's per-act attack data, his
    effects, models and HUD files in both quality tiers, his two voice banks, the music bank) go through the launcher's
    overlay pairs (overlay_pairs): the stock file is backed up the first time and put back by the first launch that
    no longer installs it; a file at a path the Steam game does not have is removed by the first launch with the
    switch OFF (remove_own_new). The music bank is the version's own (V1.5's) plus his themes: when the version's
    bank is not the one it was built from, or the checkout holds an LFS placeholder, it is left out -- with his
    chara_bgm row, so his Awakening theme stays the version's -- and the launch says so;
  * launch_step(), once the plugins are in (after setup_matchmaking): copies Reworks/Starrk/Plugin/pl033rw.dll to
    <game>\\ReBalanceOfSouls\\ (OFF: removes it there). It is NOT in Files/Matchmaking/Plugins: with the switch OFF it
    is not in the game at all, so OFF is the version exactly. The content pool counts the DLL (launcher/
    content_pool.py: ReBalanceOfSouls/*.dll), so ON players meet only ON players; a vanilla start removes it (launcher/
    vanilla_revert.py walks Reworks/<r>/Plugin/*.dll).
A click on the card only keeps the choice (Json/starrk_rework.json): the data and the plugin change together at the
next launch. Never for the Steam game or a vanilla plus version (wanted()).

BY HAND:   python launcher\\starrk_rework.py status [<game folder>]
"""
import hashlib
import json
import os
import re
import struct
import sys
import zlib

DEFAULT_GAME = r"D:\SteamLibrary\steamapps\common\BLEACH Rebirth of Souls"
EXE = "BLEACH_Rebirth_of_Souls.exe"
DIR = "ReBalanceOfSouls"
PLUGIN = os.path.join(DIR, "pl033rw.dll")
CHOICE_NAME = "starrk_rework.json"            # Json/starrk_rework.json: {"STARRK_REWORK": "ON"|"OFF"}
DEFAULT_ON = False                            # retired 2026-11-22 (ON by default from 2026-11-15, Berg)
RETIRED = "2026-11-22"                        # the switch is retired: the module's docstring, first part
REWORK = ("Reworks", "Starrk")                # <repo>/Reworks/Starrk (the .gitattributes Reworks/** rules)
MANIFEST = "manifest.json"                    # every rework file: game path, md5, size, steam_path, register
ROWS = "rows.json"                            # Starrk's rows of the shared tables
FNAMES = "fnames.json"                        # his names in Fnames/filename.bin
HTABLE = "Fnames/file_exist.htable"           # the game's registry: a file it should see needs a row here
FILENAME_BIN = "Fnames/filename.bin"          # the loader's name list (models and icons are looked up here first)
PLUGIN_SRC = ("Reworks", "Starrk", "Plugin", "pl033rw.dll")
KOMAMURA_PLUGIN_SRC = ("Reworks", "Komamura", "Plugin", "pl023rework.dll")
# The Komamura rework's plugin builds whose stand wraps the fighter vtables' entries 37 / 148 -- the entries pl033rw.dll
# wraps: with both ON the host would refuse pl033rw.dll's claims and Starrk would play his rework's data without his
# rules. Round 2's (pass kr, 2026-11-15 morning) is the only one; round 2c's hooks inside the functions.
KOMAMURA_CONFLICTING = {"14b2a335e6f7eca0fb9ad874901b2480"}
VANILLA_VERSION = "Bleach Rebirth of Souls"   # the Steam game: never reworked

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class StarrkReworkError(Exception):
    """The rework could not be applied as asked; the game must not start."""


# ---------------------------------------------------------------------------------------------------------------------
# The launcher's choice
# ---------------------------------------------------------------------------------------------------------------------

def choice_path(base_dir):
    return os.path.join(base_dir, "Json", CHOICE_NAME)


def load_choice(base_dir):
    """Retired (2026-11-22): always False. The rework is the reborn Starrk (54) in the version, for everyone; a choice
    saved in Json/starrk_rework.json is not read any more. (It was: True = ON; missing, unreadable or unexpected read
    as the default, ON; only "OFF" was OFF.)"""
    return False


def save_choice(base_dir, on):
    """Retired (2026-11-22): there is no switch to keep any more; refused, nothing written."""
    raise StarrkReworkError("the Starrk rework switch was retired on %s: the rework is the reborn Coyote Starrk "
                            "(Primera), id 54, in the version for everyone" % RETIRED)


def wanted(base_dir, game_version):
    """Retired (2026-11-22): never -- no launch puts the rework over Starrk (33) any more. (It was: the switch ON and a
    patched version, not the Steam game, not a vanilla plus version -- GameVersions/<v>/vanilla_plus.json.)"""
    return False


def describe(on):
    return ("Starrk rework ON (beta: Base with Lilynette, Gun Form, the Wolf / Sword Form; his data and pl033rw.dll)"
            if on else
            "Starrk rework retired (the reborn Coyote Starrk (Primera), 54, is the rework, in the version; Starrk as "
            "the version ships him)")


def _komamura_on(base_dir, game_version):
    try:
        from launcher import komamura_rework as kr
    except Exception:
        try:
            import komamura_rework as kr
        except Exception:
            return False
    try:
        return bool(kr.wanted(base_dir, game_version))
    except Exception:
        return False


def _komamura_plugin_conflicts(base_dir):
    """The md5 of this checkout's Komamura rework plugin when it is a build that cannot run beside pl033rw.dll, else
    None (round 2c's, or none in the checkout: the Komamura rework's own preflight refuses a missing one)."""
    try:
        m = _md5(os.path.join(base_dir, *KOMAMURA_PLUGIN_SRC))
    except OSError:
        return None
    return m if m in KOMAMURA_CONFLICTING else None


def preflight(base_dir, game, game_version):
    """Before anything of the rework is installed: its files as its manifest names them (the plugin among them), its
    row and registry specs, the game folder and its two registries, and not the Komamura rework at the same time
    while its plugin is one that wraps the same vtable entries. Raises StarrkReworkError."""
    bad = _komamura_plugin_conflicts(base_dir) if _komamura_on(base_dir, game_version) else None
    if bad:
        raise StarrkReworkError(
            "the Komamura rework is ON too, with its round 2 plugin (Reworks/Komamura/Plugin/pl023rework.dll %s): its "
            "stand wraps every fighter's update and weapon visibility in the same vtable entries as pl033rw.dll, and "
            "the plugin host refuses the second one. Update this checkout (the Komamura rework's round 2c plugin runs "
            "beside the Starrk rework's) or switch one of the two reworks OFF" % bad[:8])
    for name in (ROWS, FNAMES):
        try:
            with open(os.path.join(rework_root(base_dir), name), "r", encoding="utf-8") as f:
                json.load(f)
        except Exception as e:
            raise StarrkReworkError("Reworks/Starrk/%s cannot be read (%s)" % (name, e))
    man = load_manifest(base_dir)
    if not os.path.isfile(os.path.join(base_dir, *PLUGIN_SRC)) or \
            not any(e["src"] == "Plugin/pl033rw.dll" for e in man["files"]):
        raise StarrkReworkError("%s is not in this checkout: without it his data would run without his rules"
                                % "/".join(PLUGIN_SRC))
    if not os.path.isfile(os.path.join(game, EXE)):
        raise StarrkReworkError("%s is not the game folder (no %s)" % (game, EXE))
    _read_htable(game)
    _read_filename_bin(game)


# ---------------------------------------------------------------------------------------------------------------------
# The game's encoded tables (.fsv, chara_bgm.tbl): "_cso_<ver>_<key>\n" + the bytes, each shifted by a key byte; 16
# more bytes at the end, 16 raw NULs or 16 encoded bytes. The codec of launcher/komamura_rework.py: the same version,
# key and tail in -> the same bytes out.
# ---------------------------------------------------------------------------------------------------------------------

def _key_bytes(key):
    k32 = ((key + 2 ** 31) % 2 ** 32) - 2 ** 31
    ks = [(i + (k32 >> (4 * i))) & 0xFF for i in range(8)]
    return [(k if k & 1 else (-k) & 0xFF) for k in ks]


def table_decode(raw):
    nl = raw.find(b"\n")
    m = re.match(rb"_cso_(\d+)_(-?\d+)\Z", raw[:nl].strip()) if nl > 0 else None
    if not m or len(raw) < nl + 1 + 16:
        raise StarrkReworkError("not an encoded table")
    ver, key = int(m.group(1)), int(m.group(2))
    d = _key_bytes(key)
    body = raw[nl + 1:]
    plain = bytes((b - d[i & 7]) & 0xFF for i, b in enumerate(body))
    tail = "nul" if raw[-16:] == b"\0" * 16 else plain[-16:]
    return ver, key, plain[:-16], tail


def table_encode(ver, key, text, tail):
    d = _key_bytes(key)
    plain = text + (b"" if tail == "nul" else bytes(tail))
    enc = bytes((b + d[i & 7]) & 0xFF for i, b in enumerate(plain))
    return ("_cso_%d_%d\n" % (ver, key)).encode("ascii") + enc + (b"\0" * 16 if tail == "nul" else b"")


def _split_rows(text):
    """[(row bytes, terminator)] keeping each row's own line end (CRLF or LF; the last may have none)."""
    out = []
    for m in re.finditer(rb"([^\n]*?)(\r?\n|\Z)", text):
        if m.group(0) == b"" and m.start() == len(text):
            break
        out.append([m.group(1), m.group(2)])
    return out


def _join_rows(rows):
    return b"".join(r + t for r, t in rows)


def _key(row):
    return row.split(b",", 1)[0].decode("utf-8", "replace")


def apply_rows(raw, spec):
    """(new raw, [(row, column, old, new)]) -- spec: {row key: {"cells": {column: value}}} sets those cells of that row
    (the row keeps its key, its line end and any fields past the header's -- additional_status_effect's rows are wider
    than its header), or {"replace": [[column, value], ...]} puts a whole row (every column of
    the header, in order; its key may be another) in that row's place -- found once by its own key, or already there
    under the new key (a table this module edited before): then nothing changes. Keys starting with _ are not rows.
    Only the rows the spec names change; the table keeps its version, key, tail and row count (_prove)."""
    ver, key, text, tail = table_decode(raw)
    rows = _split_rows(text)
    header = rows[0][0].decode("utf-8").split(",")
    changes = []
    allowed = set()
    for rk, sp in spec.items():
        if rk.startswith("_"):
            continue
        if "replace" in sp:
            cols = [c for c, _v in sp["replace"]]
            if cols != header:
                raise StarrkReworkError("the %r row spec does not match the table's columns" % rk)
            new = [v for _c, v in sp["replace"]]
            hits = [i for i, (r, _t) in enumerate(rows[1:], 1) if _key(r) == rk]
            done = [i for i, (r, _t) in enumerate(rows[1:], 1) if _key(r) == new[0]]
            if not hits and len(done) == 1 and rows[done[0]][0] == ",".join(new).encode("utf-8"):
                continue                                  # already the rework's row
            if len(hits) != 1 or (new[0] != rk and done):
                raise StarrkReworkError("row %r found %d times (the new key %r %d)" % (rk, len(hits), new[0],
                                                                                         len(done)))
            i = hits[0]
            fields = rows[i][0].decode("utf-8").split(",")
            if len(fields) != len(header):
                raise StarrkReworkError("row %r has %d fields, the header %d" % (rk, len(fields), len(header)))
            for c, o, n in zip(header, fields, new):
                if o != n:
                    changes.append((rk, c, o, n))
            rows[i][0] = ",".join(new).encode("utf-8")
            allowed |= {rk, new[0]}
            continue
        hits = [i for i, (r, _t) in enumerate(rows[1:], 1) if _key(r) == rk]
        if len(hits) != 1:
            raise StarrkReworkError("row %r found %d times" % (rk, len(hits)))
        i = hits[0]
        fields = rows[i][0].decode("utf-8").split(",")
        if len(fields) < len(header):                     # wider rows are the table's own (additional_status_effect)
            raise StarrkReworkError("row %r has %d fields, the header %d" % (rk, len(fields), len(header)))
        new = list(fields)
        for c, v in sp["cells"].items():
            if c not in header or header.index(c) == 0:
                raise StarrkReworkError("no column %r to set" % c)
            new[header.index(c)] = v
        for c, o, n in zip(header, fields, new):
            if o != n:
                changes.append((rk, c, o, n))
        rows[i][0] = ",".join(new).encode("utf-8")
        allowed.add(rk)
    out = table_encode(ver, key, _join_rows(rows), tail)
    _prove(raw, out, allowed)
    return out, changes


def _prove(raw, out, allowed_rows):
    """Decode both again: same version, key and tail; only the allowed rows differ; same row count."""
    a, b = table_decode(raw), table_decode(out)
    if a[:2] != b[:2] or a[3] != b[3]:
        raise StarrkReworkError("re-encoding changed the table's version, key or tail")
    ra, rb = _split_rows(a[2]), _split_rows(b[2])
    if len(ra) != len(rb):
        raise StarrkReworkError("re-encoding changed the row count")
    for (x, xt), (y, yt) in zip(ra, rb):
        if (x, xt) != (y, yt) and (_key(x) not in allowed_rows or xt != yt):
            raise StarrkReworkError("re-encoding changed a row it was not asked to")


# ---------------------------------------------------------------------------------------------------------------------
# The rework's files
# ---------------------------------------------------------------------------------------------------------------------

def rework_root(base_dir):
    return os.path.join(base_dir, *REWORK)


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_files(base_dir):
    with open(os.path.join(rework_root(base_dir), MANIFEST), "r", encoding="utf-8") as f:
        return json.load(f)["files"]


def _entry_ok(base_dir, ent):
    src = os.path.join(rework_root(base_dir), ent["src"].replace("/", os.sep))
    return os.path.isfile(src) and os.path.getsize(src) == ent["size"] and _md5(src) == ent["md5"]


def load_manifest(base_dir):
    """{"files": [...]} -- every file under Reworks/Starrk/Script, Motion, Overlay and Plugin that a launch installs,
    checked against the bytes on disk (a git-LFS placeholder or a half-pulled file is refused). An entry marked
    "optional" (the music bank) is not required: it is checked when it is installed (overlay_pairs)."""
    try:
        files = _manifest_files(base_dir)
    except Exception as e:
        raise StarrkReworkError("Reworks/Starrk/%s cannot be read (%s)" % (MANIFEST, e))
    for ent in files:
        if ent.get("optional"):
            continue
        if not _entry_ok(base_dir, ent):
            raise StarrkReworkError("the rework's file %s is missing or not the one its manifest names (a git-LFS "
                                    "placeholder or an unfinished pull?)" % ent["src"])
    return {"files": files}


def _version_chain(base_dir, game_version):
    """[the version, its base, ... the root] by GameVersions/<v>/base.txt."""
    chain, v = [], game_version
    while v and v not in chain and len(chain) < 16:
        chain.append(v)
        try:
            with open(os.path.join(base_dir, "GameVersions", v, "base.txt"), "r", encoding="utf-8-sig") as f:
                v = f.read().strip().split("\n")[0].strip()
        except OSError:
            v = ""
    return chain


def version_file(base_dir, game_version, game_path):
    """The file the version's chain installs at game_path (an Overlay/ file wins over a root folder's), or None."""
    chain = _version_chain(base_dir, game_version)
    for v in chain:
        p = os.path.join(base_dir, "GameVersions", v, "Overlay", *game_path.split("/"))
        if os.path.isfile(p):
            return p
    for v in chain:
        p = os.path.join(base_dir, "GameVersions", v, *game_path.split("/"))
        if os.path.isfile(p):
            return p
    return None


def skipped(base_dir, game_version):
    """{src: why} for the optional entries this launch leaves out: the music bank when it is not in the checkout as
    its manifest names it, or the version's own bank is not the one it was built from ("base_md5")."""
    out = {}
    try:
        files = _manifest_files(base_dir)
    except Exception:
        return out
    for ent in files:
        if not ent.get("optional"):
            continue
        if not _entry_ok(base_dir, ent):
            out[ent["src"]] = "not in this checkout as its manifest names it (git lfs pull?)"
            continue
        base_md5 = ent.get("base_md5")
        if base_md5:
            vf = version_file(base_dir, game_version, ent["path"])
            got = _md5(vf) if vf else None
            if got != base_md5:
                out[ent["src"]] = ("the version's %s is not the one it was built from (%s, the rework's base %s)"
                                   % (ent["path"], (got or "none")[:8], base_md5[:8]))
    return out


def overlay_pairs(base_dir, game_version):
    """[(absolute source, game path with /)] of the rework's files outside Script / Motion / Plugin, for the launcher's
    _overlay_pairs while the switch is ON (the optional ones skipped() leaves out, out). Raises StarrkReworkError if the
    rework's files are not right."""
    man = load_manifest(base_dir)
    skip = skipped(base_dir, game_version)
    root = rework_root(base_dir)
    for src, why in sorted(skip.items()):
        print("[starrk] %s left out: %s" % (src, why))
    return [(os.path.join(root, e["src"].replace("/", os.sep)), e["path"]) for e in man["files"]
            if e["src"].startswith("Overlay/") and e["src"] not in skip]


def _write(path, data):
    tmp = path + ".starrk_rework_tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    with open(path, "rb") as f:
        if f.read() != data:
            raise OSError("%s did not read back as written" % path)


def remove_own_new(base_dir, game, log=print, keep=None):
    """The rework's files at paths the Steam game does not have (manifest: steam_path false) -- Overlay, Script and
    Motion ones -- removed from the game folder when they hold the rework's own bytes: the overlay revert puts back the
    stock files it backed up but leaves a file it created, and the version's mirror does not know his new Script
    files. A file there with other bytes is not ours: left. keep(game path) true leaves that path alone (the retired
    switch's clean-up: a path the version installs a file at). Never raises; returns the paths removed."""
    try:
        files = _manifest_files(base_dir)
    except Exception:
        return []
    gone = []
    for e in files:
        if e.get("steam_path", True) or not e["src"].startswith(("Overlay/", "Script/", "Motion/")):
            continue
        try:
            if keep and keep(e["path"]):
                continue
        except Exception as ex:
            log("[starrk] %s left: could not tell whether the version installs it (%s)" % (e["path"], ex))
            continue
        p = os.path.join(game, *e["path"].split("/"))
        try:
            if os.path.isfile(p) and os.path.getsize(p) == e["size"] and _md5(p) == e["md5"]:
                os.remove(p)
                gone.append(e["path"])
        except OSError as ex:
            log("[starrk] could not remove %s (%s)" % (e["path"], ex))
    return gone


def reg_hash(s):
    """The game's registry hash: CRC-32 (reflected, 0xEDB88320) seeded with the length, no final xor."""
    b = s.encode("latin1")
    return zlib.crc32(b, len(b) ^ 0xFFFFFFFF) ^ 0xFFFFFFFF


def reg_key(game_rel):
    """(hash of the backslash path, hash of its folder): one row of Fnames/file_exist.htable."""
    p = game_rel.replace("/", "\\")
    return reg_hash(p), reg_hash(p.rsplit("\\", 1)[0])


def _read_htable(game):
    p = os.path.join(game, *HTABLE.split("/"))
    try:
        with open(p, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise StarrkReworkError("the game has no readable %s (%s)" % (HTABLE, e))
    n = struct.unpack_from("<I", raw, 0)[0] if len(raw) >= 4 else -1
    if n < 0 or 4 + 8 * n != len(raw):
        raise StarrkReworkError("%s is not a registry table (%d bytes)" % (HTABLE, len(raw)))
    return p, raw, [struct.unpack_from("<II", raw, 4 + 8 * i) for i in range(n)]


def _registered_paths(base_dir, skip=()):
    """Game paths of the rework's files the manifest marks register (paths the Steam game does not have that the
    rework's version folder registered), those this launch installs."""
    try:
        files = _manifest_files(base_dir)
    except Exception:
        return []
    return [e["path"] for e in files if e.get("register") and e["src"] not in skip]


def register_new(base_dir, game, skip=()):
    """ON, after the overlay and install_data put the rework's files down: a row in the game's registry for each file
    marked register (in manifest order, those missing only: a second call adds nothing). Returns (rows added, md5)."""
    paths = _registered_paths(base_dir, skip)
    p, raw, rows = _read_htable(game)
    have = set(rows)
    add = []
    for gp in paths:
        if not os.path.isfile(os.path.join(game, *gp.split("/"))):
            raise StarrkReworkError("the rework's file %s is not in the game folder (it was not installed)" % gp)
        k = reg_key(gp)
        if k not in have:
            add.append(k)
            have.add(k)
    out = raw
    if add:
        out = struct.pack("<I", len(rows) + len(add)) + raw[4:] + b"".join(struct.pack("<II", a, b) for a, b in add)
        try:
            _write(p, out)
        except OSError as e:
            raise StarrkReworkError("could not write %s (%s)" % (p, e))
    return len(add), hashlib.md5(out).hexdigest()


def unregister_absent(base_dir, game, log=print):
    """OFF: the registry rows of the rework's files whose file is no longer in the game folder are dropped (a version
    that installs its own table has none: then nothing changes). Never raises; returns the rows dropped."""
    paths = _registered_paths(base_dir)
    if not paths:
        return 0
    try:
        p, raw, rows = _read_htable(game)
        drop = {reg_key(gp) for gp in paths if not os.path.isfile(os.path.join(game, *gp.split("/")))}
        keep = [r for r in rows if r not in drop]
        if len(keep) != len(rows):
            _write(p, struct.pack("<I", len(keep)) + b"".join(struct.pack("<II", a, b) for a, b in keep))
        return len(rows) - len(keep)
    except (StarrkReworkError, OSError) as e:
        log("[starrk] the registry was not checked for the rework's rows (%s)" % e)
        return 0


# ---------------------------------------------------------------------------------------------------------------------
# Fnames/filename.bin (ADDING_CHARACTERS_MASTER_GUIDE 7a): a 13-byte header, then a flat list of nodes to EOF. node :=
# u32 len; name; NUL; u32 count; payload -- count file triples when the name is a directory (empty, or ending in '\'
# or '/'), else count child nodes. triple := basename, extension, logical name (each u32 len; bytes; NUL).
# ---------------------------------------------------------------------------------------------------------------------

FN_HDR = 13


def _fn_str(b, o):
    n = struct.unpack_from("<I", b, o)[0]
    s = b[o + 4:o + 4 + n]
    if b[o + 4 + n:o + 5 + n] != b"\0":
        raise StarrkReworkError("%s: a name without its NUL at %d" % (FILENAME_BIN, o))
    return s, o + 4 + n + 1


def _fn_isdir(name):
    return name == b"" or name.endswith(b"\\") or name.endswith(b"/")


def _fn_node(b, o):
    name, o = _fn_str(b, o)
    cnt = struct.unpack_from("<I", b, o)[0]
    o += 4
    items = []
    if _fn_isdir(name):
        for _ in range(cnt):
            a, o = _fn_str(b, o)
            e, o = _fn_str(b, o)
            lg, o = _fn_str(b, o)
            items.append((a, e, lg))
        return [name, items, True], o
    for _ in range(cnt):
        c, o = _fn_node(b, o)
        items.append(c)
    return [name, items, False], o


def filename_parse(raw):
    o, nodes = FN_HDR, []
    try:
        while o < len(raw):
            n, o = _fn_node(raw, o)
            nodes.append(n)
    except struct.error:
        raise StarrkReworkError("%s is cut short" % FILENAME_BIN)
    if o != len(raw):
        raise StarrkReworkError("%s does not end where its nodes do" % FILENAME_BIN)
    return raw[:FN_HDR], nodes


def _fn_w(s):
    return struct.pack("<I", len(s)) + s + b"\0"


def _fn_emit_node(n):
    name, items, isdir = n
    out = [_fn_w(name), struct.pack("<I", len(items))]
    if isdir:
        for a, e, lg in items:
            out += [_fn_w(a), _fn_w(e), _fn_w(lg)]
    else:
        for c in items:
            out.append(_fn_emit_node(c))
    return b"".join(out)


def filename_emit(hdr, nodes):
    return hdr + b"".join(_fn_emit_node(n) for n in nodes)


def _fn_dirs(nodes, path=()):
    for n in nodes:
        if n[2]:
            yield path + (n[0],), n
        else:
            yield from _fn_dirs(n[1], path + (n[0],))


def _read_filename_bin(game):
    p = os.path.join(game, *FILENAME_BIN.split("/"))
    try:
        with open(p, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise StarrkReworkError("the game has no readable %s (%s)" % (FILENAME_BIN, e))
    hdr, nodes = filename_parse(raw)
    return p, raw, hdr, nodes


def add_names(base_dir, game):
    """ON: his names in the game's filename.bin (fnames.json: each directory -- its path of node names -- and the
    triples to add, each after the one it follows in the rework's table, or at the end): those missing only, so a
    second call adds nothing; a directory the table does not have is refused. Returns (names added, md5)."""
    with open(os.path.join(rework_root(base_dir), FNAMES), "r", encoding="utf-8") as f:
        spec = json.load(f)["dirs"]
    p, raw, hdr, nodes = _read_filename_bin(game)
    dirs = {path: n for path, n in _fn_dirs(nodes)}
    added = 0
    for d in spec:
        path = tuple(x.encode("latin1") for x in d["path"])
        if path not in dirs:
            raise StarrkReworkError("%s has no directory %s" % (FILENAME_BIN, "/".join(d["path"])))
        items = dirs[path][1]
        for t in d["add"]:
            trip = tuple(x.encode("latin1") for x in t["name"])
            if trip in items:
                continue
            after = tuple(x.encode("latin1") for x in t["after"]) if t.get("after") else None
            at = items.index(after) + 1 if after in items else len(items)
            items.insert(at, trip)
            added += 1
    out = filename_emit(hdr, nodes) if added else raw
    if added:
        if filename_parse(out)[0] != hdr:
            raise StarrkReworkError("%s did not parse back" % FILENAME_BIN)
        try:
            _write(p, out)
        except OSError as e:
            raise StarrkReworkError("could not write %s (%s)" % (p, e))
    return added, hashlib.md5(out).hexdigest()


# ---------------------------------------------------------------------------------------------------------------------
# The launch steps
# ---------------------------------------------------------------------------------------------------------------------

def _read_table(path, gp):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        raise StarrkReworkError("the game has no readable %s (%s): the version did not install it" % (gp, e))


def _write_table(path, data):
    try:
        _write(path, data)
    except OSError as e:
        raise StarrkReworkError("could not write %s (%s)" % (path, e))


def install_data(base_dir, game, on, game_version=None, log=print):
    """The launch-time data step of a patched version (after the version, the reworks and the game mode's files;
    before mode_status). ON (only a direct call since the switch was retired): copy the rework's Script / Motion files,
    edit Starrk's shared rows, register his new files and names. OFF (every launch): the version's mirror has just put
    its own Script / Motion back and the overlay revert its stock files; the rework's files a launch with the switch ON
    left at paths the Steam game does not have are removed here -- but never a path the version (game_version) installs
    a file at itself: the reborn Starrk's own files share 42 of those paths, with the rework's bytes. Without
    game_version, nothing is removed. Returns the lines it logged."""
    lines = []

    def say(s):
        lines.append(s)
        log("[starrk] " + s)
    if not on:
        gone = (remove_own_new(base_dir, game, log,
                               keep=lambda gp: version_file(base_dir, game_version, gp) is not None)
                if game_version else [])
        unreg = unregister_absent(base_dir, game, log)
        say(describe(False) + (" (%d file(s) of the rework removed)" % len(gone) if gone else "")
            + (" (%d registry row(s) of absent rework files dropped)" % unreg if unreg else ""))
        return lines
    man = load_manifest(base_dir)
    skip = skipped(base_dir, game_version) if game_version else {}
    root = rework_root(base_dir)
    for e in man["files"]:
        if not e["src"].startswith(("Script/", "Motion/")):
            continue                                       # Overlay/: the overlay pairs; Plugin/: launch_step
        src = os.path.join(root, e["src"].replace("/", os.sep))
        dst = os.path.join(game, *e["path"].split("/"))
        if not os.path.isdir(os.path.dirname(dst)):
            raise StarrkReworkError("the game folder has no %s" % os.path.dirname(e["path"]))
        with open(src, "rb") as f:
            data = f.read()
        try:
            _write(dst, data)
        except OSError as ex:
            raise StarrkReworkError("could not write %s (%s)" % (dst, ex))
        say("%s (%s)" % (e["path"], e["md5"][:8]))
    try:
        with open(os.path.join(root, ROWS), "r", encoding="utf-8") as f:
            tables = json.load(f)["tables"]
    except Exception as ex:
        raise StarrkReworkError("Reworks/Starrk/%s cannot be read (%s)" % (ROWS, ex))
    for gp, spec in tables.items():
        need = [s for s in spec.get("_needs", []) if s in skip]
        if need:
            say("%s: Starrk's row left as the version's (it needs %s, left out)" % (gp, ", ".join(need)))
            continue
        p = os.path.join(game, *gp.split("/"))
        raw = _read_table(p, gp)
        new, ch = apply_rows(raw, spec)
        if new != raw:
            _write_table(p, new)
        say("%s: %d cell(s) of Starrk's set (%s)" % (gp, len(ch), hashlib.md5(new).hexdigest()[:8]))
    # the registries last: rows for his files at new paths, his names (the version's tables have none of them)
    nreg, mreg = register_new(base_dir, game, skip)
    say("%s: %d row(s) for the rework's files at new paths (%s)" % (HTABLE, nreg, mreg[:8]))
    nnam, mnam = add_names(base_dir, game)
    say("%s: %d name(s) of his models and icon (%s)" % (FILENAME_BIN, nnam, mnam[:8]))
    say(describe(True))
    return lines


def install_plugin(base_dir, game, on):
    """ON: Reworks/Starrk/Plugin/pl033rw.dll -> <game>/ReBalanceOfSouls/ (the manifest's bytes, read back). OFF: a
    pl033rw.dll there with those bytes is removed (setup_matchmaking has normally done it already)."""
    dst = os.path.join(game, PLUGIN)
    if on:
        man = load_manifest(base_dir)
        ent = [e for e in man["files"] if e["src"] == "Plugin/pl033rw.dll"]
        if len(ent) != 1:
            raise StarrkReworkError("Reworks/Starrk/manifest.json names no Plugin/pl033rw.dll")
        with open(os.path.join(rework_root(base_dir), "Plugin", "pl033rw.dll"), "rb") as f:
            data = f.read()
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            cur = open(dst, "rb").read() if os.path.isfile(dst) else None
            if cur != data:
                _write(dst, data)
        except OSError as e:
            raise StarrkReworkError("could not install %s (%s)" % (dst, e))
        if hashlib.md5(open(dst, "rb").read()).hexdigest() != ent[0]["md5"]:
            raise StarrkReworkError("%s does not read back as the rework's plugin" % dst)
        return "pl033rw.dll installed (%s)" % ent[0]["md5"][:8]
    try:
        ent = [e for e in _manifest_files(base_dir) if e["src"] == "Plugin/pl033rw.dll"]
    except Exception:
        ent = []
    if ent and os.path.isfile(dst) and _md5(dst) == ent[0]["md5"]:
        try:
            os.remove(dst)
        except OSError as e:
            raise StarrkReworkError("could not remove %s (%s)" % (dst, e))
        return "pl033rw.dll removed"
    return None


def launch_step(base_dir, game, game_version=None):
    """After the plugins are in (setup_matchmaking): the plugin follows the saved choice for a patched version -- since
    the switch was retired, always OFF: a pl033rw.dll a launch with the switch ON left is removed."""
    on = wanted(base_dir, game_version) if game_version else load_choice(base_dir)
    x = install_plugin(base_dir, game, on)
    line = x or describe(on)
    print("[starrk] " + line)
    return line


# ---------------------------------------------------------------------------------------------------------------------
# By hand
# ---------------------------------------------------------------------------------------------------------------------

def status(game, base_dir=REPO):
    print("game folder: %s" % game)
    print("  pl033rw.dll: %s" % ("installed (the next launch removes it)" if os.path.isfile(os.path.join(game, PLUGIN))
                                 else "not installed"))
    print("  the launcher's switch: %s" % describe(load_choice(base_dir)))
    print("  a launch takes away what a launch with the switch ON left (install_data, launch_step)")
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "status":
        return status(argv[2] if len(argv) > 2 else DEFAULT_GAME)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
