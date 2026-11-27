"""komamura_rework.py -- the launcher's Komamura rework switch (pass kr, KOMAMURA_REWORK_2026-11-14).

IN THE LAUNCHER. The Advanced settings page has a "Komamura rework" card with one switch, OFF unless switched on:

  OFF (the default): Komamura (pl023) as the version ships him -- nothing of this module reaches the game folder.
  ON: Komamura has two forms. His base form is the vanilla game's Reawakened (weakened) Komamura -- its moves,
      combo table, stats, CPU -- and his Awakened form is the vanilla game's base Komamura, with the giant (his
      Bankai) as a stand behind him, 1.75 times his height (round 2c): it copies his moves and vanishes while he
      is hit, thrown, grabbed or knocked down (round 2: pl023rework.dll shows it only in his own acts). He awakens
      through the vanilla awakening cutscene -- the giant in it at the stand's size, the fight staying in the stage
      (round 2b) -- and has spirit drive as every character without a Reawakened form; his kikons: base = the
      vanilla Reawakened one, Awakened = the vanilla base one, sublimation (break02, in spirit drive) = the vanilla
      giant's (at its full size). HP 10000 / 11500. Built from the vanilla game's files, not from the version's
      Komamura.

Berg, 2026-11-14: "removing the giant form/current evo from komamura, changing his base form's moveset and
everything to that of his rev form, and his evo form gets the base form moveset and everything, so he effectively
loses a form ... We will be using the vanilla game's stats and combo tree and everything, except his base form
health will be 10000, and evo form will be 11500 ... Turn this new rework off by default in the launcher's advanced
settings, so it can be toggled on."
Berg, 2026-11-15 (round 2): "We will put in his normal evo cutscene for his evo. However, the giant will be
detached from him ... this giant will be like a stand ... that stands behind him and mirror his move ... He
will get spirit drive like all other characters without a rev form ... His sublimation kikon (break02) will
simply be the old evo kikon"; asked what the stand does while he is hit, knocked down, thrown or grabbed:
"Vanish, then return". After his test (round 2b): "the komamura giant is simply too big here ... the stage
transition still happens here ... the size of the giant during the evo cutscene has to be changed to match the
new size of the giant"; the size: "2.5x his height"; the sublimation kikon's cut: "Keep the full-size giant". After
his test of round 2b (round 2c): "it is simply still too big. It needs to be changed to be no more than double the
size of komamura's in game model"; then "make komamura giant 1.75 instead of 2.0".

WHAT A LAUNCH DOES WHILE IT IS ON (install_data, after the version's files, the reworks and the game mode's files,
before the game mode's CharaStatus cells; launch_step after the plugins are in):
  * copies <repo>/Reworks/Komamura/Script and Motion over the game's (pl023.tadjpkg / .tcmbpkg / .tactpkg): the
    version's Script / Motion are mirrored at every launch, so an OFF launch puts the version's own back by itself;
  * the files outside Script / Motion (Reworks/Komamura/Overlay: the CPU's per-act attack data and his cutscenes'
    demos) go through the launcher's overlay pairs (overlay_pairs): the stock file is backed up the first time and
    put back by the first launch that no longer installs it (launcher_patch_state.json); a file at a path the Steam
    game does not have is removed by the first launch with the switch OFF (remove_own_new), and by a Vanilla start
    (vanilla_revert);
  * edits pl023's rows of the shared tables the version installed (Reworks/Komamura/rows.json: CharaStatus,
    WepVisible, CharaAttackHitColl) and remaps pl023's CPU tables (AiParam/AiActList_pl023, AiParam_pl023) by form,
    each re-encoded with the table's OWN version, key and tail -- the same bytes at every launch, so the online pool
    (launcher/content_pool.py) gives every ON player the same code;
  * registers the rework's files at paths the Steam game does not have (four CPU files) in the game's installed
    Fnames\\file_exist.htable -- the game sees no file without a row, and the version's table (the overlay installs
    it again at every launch) has none for them (register_new; pass kr r2, kr017); OFF drops such a row whose file is
    gone (unregister_absent: a no-op when the version installs its own table);
  * once the plugins are in (launch_step, after setup_matchmaking): copies Reworks/Komamura/Plugin/pl023rework.dll to
    <game>\\ReBalanceOfSouls\\ and writes ReBalanceOfSouls\\komamura_rework.txt ("komamura_rework 1"), the plugin's
    switch (it turns off the exe's built-in giant code for pl023 and, since round 2, shows the giant -- his weapon
    slot 2, the stand -- only while his running act is one of his own, pl023_stand_acts.h; since round 2c its
    stand hooks inside the engine's functions -- Update's exit, the weapon visibility's exit -- not in the
    fighter vtables' entries, so it runs beside the Starrk rework's pl033rw.dll and the two reworks can be ON
    together). The DLL is NOT in
    Files/Matchmaking/Plugins: with the switch OFF it is not in the game at all (setup_matchmaking removes a DLL it
    does not ship, and nothing puts it back), so OFF is the version exactly, online pool included (pass kr r2,
    kr017). Its source is Files/Matchmaking/pl023rework_plugin.c (since round 2 with pl023_stand_acts.h beside it),
    built by `Files/Matchmaking/build_plugin.sh pl023rework`, which never stages it into Plugins/ (it is not in
    PLUGINS, like rbk). The content pool counts the DLL and the switch, so ON players meet only ON players; the
    public launcher's leftovers step moves an unknown ReBalanceOfSouls\\*.txt out, so a beta game never runs ON; a
    vanilla start removes both (launcher/vanilla_revert.py).
A click on the card only keeps the choice (Json/komamura_rework.json): the data, the plugin and the switch change
together at the next launch. ON with no pl023rework.dll installed refuses the launch (the giant code would run on the
new evo).
Never for the Steam game or a vanilla plus version (wanted()); preflight() checks the rework's files before any of it
is installed.

BY HAND:   python launcher\\komamura_rework.py status [<game folder>]
"""
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import zlib

DEFAULT_GAME = r"D:\SteamLibrary\steamapps\common\BLEACH Rebirth of Souls"
EXE = "BLEACH_Rebirth_of_Souls.exe"
DIR = "ReBalanceOfSouls"
NAME = "komamura_rework.txt"
PLUGIN = os.path.join(DIR, "pl023rework.dll")
CHOICE_NAME = "komamura_rework.json"          # Json/komamura_rework.json: {"KOMAMURA_REWORK": "ON"|"OFF"}
DEFAULT_ON = False                            # Berg: off by default
KEY = b"komamura_rework"
REWORK = ("Reworks", "Komamura")              # <repo>/Reworks/Komamura (the .gitattributes Reworks/** rules)
MANIFEST = "manifest.json"                    # every rework file: game path, md5, size
ROWS = "rows.json"                            # the shared-table row edits
AI_TABLES = ("Script/AiParam/AiActList_pl023.fsv", "Script/AiParam/AiParam_pl023.fsv")
HTABLE = "Fnames/file_exist.htable"           # the game's registry: a file it should see needs a row here

VANILLA_VERSION = "Bleach Rebirth of Souls"      # the Steam game: never reworked
PLUGIN_SRC = ("Reworks", "Komamura", "Plugin", "pl023rework.dll")   # installed by launch_step while ON (r2)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class KomamuraReworkError(Exception):
    """The rework could not be applied as asked; the game must not start."""


# ---------------------------------------------------------------------------------------------------------------------
# The switch file and the launcher's choice
# ---------------------------------------------------------------------------------------------------------------------

def text():
    return ("# komamura_rework.txt -- the launcher's Komamura rework switch (Advanced settings > Komamura rework, or\n"
            "# launcher\\komamura_rework.py). Read at game start by pl023rework.dll. While this file says 1 the\n"
            "# exe's built-in giant (Bankai) code is off for Komamura; the launch that wrote it also installed the\n"
            "# rework's data. Do not edit it: the next launch writes or removes it again.\n"
            "komamura_rework 1\n")


def parse(data):
    """(on, how) for the bytes of the switch file: the last komamura_rework line wins; 1 / on / yes / true is ON,
    anything else -- and no line, no file -- OFF (the default). Comment lines start with # or ;."""
    on, how = DEFAULT_ON, "no line"
    for line in bytes(data).replace(b"\r\n", b"\n").split(b"\n"):
        s = line.lstrip(b" \t")
        if s[:3] == b"\xef\xbb\xbf":
            s = s[3:]
        if not s or s[:1] in (b"#", b";"):
            continue
        k = 0
        while k < len(s) and s[k:k + 1] not in (b" ", b"\t", b"=", b":"):
            k += 1
        if s[:k].lower() == KEY:
            v = s[k:].lstrip(b" \t=:").lower()
            on = v[:1] == b"1" or v.startswith((b"on", b"yes", b"true"))
            how = "file"
    return on, how


def switch_path(game):
    return os.path.join(game, DIR, NAME)


def choice_path(base_dir):
    return os.path.join(base_dir, "Json", CHOICE_NAME)


def load_choice(base_dir):
    """True = ON. Missing, unreadable or unexpected reads as the default, OFF; only "ON" is ON."""
    try:
        with open(choice_path(base_dir), "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return DEFAULT_ON
    return isinstance(d, dict) and d.get("KOMAMURA_REWORK") == "ON"


def save_choice(base_dir, on):
    path = choice_path(base_dir)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"KOMAMURA_REWORK": "ON" if on else "OFF"}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise KomamuraReworkError("could not save the Komamura rework switch in %s (%s)" % (path, e))
    if load_choice(base_dir) != bool(on):
        raise KomamuraReworkError("the Komamura rework switch did not read back from %s" % path)


def wanted(base_dir, game_version):
    """The rework goes into this launch: the switch is ON and the version is a patched one (not the Steam game, not a
    vanilla plus version -- GameVersions/<v>/vanilla_plus.json, launcher/vanilla_plus.py)."""
    if game_version == VANILLA_VERSION:
        return False
    if os.path.isfile(os.path.join(base_dir, "GameVersions", game_version, "vanilla_plus.json")):
        return False
    return load_choice(base_dir)


def preflight(base_dir, game):
    """Before anything of the rework is installed: its files as its manifest names them (the plugin among them,
    Reworks/Komamura/Plugin/pl023rework.dll, which launch_step installs), its row spec, the game folder and its
    registry table. Raises KomamuraReworkError."""
    try:
        with open(os.path.join(rework_root(base_dir), ROWS), "r", encoding="utf-8") as f:
            json.load(f)["tables"]
    except Exception as e:
        raise KomamuraReworkError("Reworks/Komamura/%s cannot be read (%s)" % (ROWS, e))
    man = load_manifest(base_dir)
    if not os.path.isfile(os.path.join(base_dir, *PLUGIN_SRC)) or \
            not any(e["src"] == "Plugin/pl023rework.dll" for e in man["files"]):
        raise KomamuraReworkError("%s is not in this checkout: without it the exe's own giant code would run on the "
                                  "new Awakened form" % "/".join(PLUGIN_SRC))
    if not os.path.isfile(os.path.join(game, EXE)):
        raise KomamuraReworkError("%s is not the game folder (no %s)" % (game, EXE))
    _read_htable(game)                            # the registry the rework adds its rows to (r2)


def describe(on):
    return ("Komamura rework ON (two forms: base = vanilla Reawakened, evo = vanilla base with the giant as a stand)"
            if on else
            "Komamura rework OFF (Komamura as the version ships him)")


# ---------------------------------------------------------------------------------------------------------------------
# The game's encoded tables (.fsv): "_cso_<ver>_<key>\n" + the bytes, each shifted by a key byte; 16 more bytes at
# the end: 16 raw NULs (243 of the Steam game's tables) or 16 encoded NULs (69 of them); V1.5's AiParam_pl023 carries
# the decoded garbage of the stock NULs there, encoded again. A raw-NUL tail stays raw NULs; any other tail keeps its 16
# decoded bytes. Same version, key and tail in -> same bytes out.
# ---------------------------------------------------------------------------------------------------------------------

def _key_bytes(key):
    k32 = ((key + 2 ** 31) % 2 ** 32) - 2 ** 31
    ks = [(i + (k32 >> (4 * i))) & 0xFF for i in range(8)]
    return [(k if k & 1 else (-k) & 0xFF) for k in ks]


def table_decode(raw):
    nl = raw.find(b"\n")
    m = re.match(rb"_cso_(\d+)_(-?\d+)\Z", raw[:nl].strip()) if nl > 0 else None
    if not m or len(raw) < nl + 1 + 16:
        raise KomamuraReworkError("not an encoded table")
    ver, key = int(m.group(1)), int(m.group(2))
    d = _key_bytes(key)
    body = raw[nl + 1:]
    plain = bytes((b - d[i & 7]) & 0xFF for i, b in enumerate(body))
    if raw[-16:] == b"\0" * 16:
        tail = "nul"                                       # raw NULs (the game's own tables)
    else:
        tail = plain[-16:]                                 # 16 encoded bytes, kept as their decoded bytes
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


def apply_rows(raw, spec):
    """(new raw, [(row, column, old, new)]) -- spec: {row key: {"row": [[col, value]...]} or {"cells": {col: value}}}.
    A "row" spec must name every column of the table's header, in order; the row keeps its own line end."""
    ver, key, text, tail = table_decode(raw)
    rows = _split_rows(text)
    header = rows[0][0].decode("utf-8").split(",")
    changes = []
    for rk, sp in spec.items():
        hits = [i for i, (r, _t) in enumerate(rows[1:], 1) if r.split(b",", 1)[0].decode("utf-8", "replace") == rk]
        if len(hits) != 1:
            raise KomamuraReworkError("row %r found %d times" % (rk, len(hits)))
        i = hits[0]
        fields = rows[i][0].decode("utf-8").split(",")
        if len(fields) != len(header):
            raise KomamuraReworkError("row %r has %d fields, the header %d" % (rk, len(fields), len(header)))
        if "row" in sp:
            cols = [c for c, _v in sp["row"]]
            if cols != header:
                raise KomamuraReworkError("the %r row spec does not match the table's columns" % rk)
            new = [v for _c, v in sp["row"]]
        else:
            new = list(fields)
            for c, v in sp["cells"].items():
                if c not in header:
                    raise KomamuraReworkError("no column %r" % c)
                new[header.index(c)] = v
        if new[0] != rk:
            raise KomamuraReworkError("the %r row spec renames the row" % rk)
        for c, o, n in zip(header, fields, new):
            if o != n:
                changes.append((rk, c, o, n))
        rows[i][0] = ",".join(new).encode("utf-8")
    out = table_encode(ver, key, _join_rows(rows), tail)
    _prove(raw, out, set(spec))
    return out, changes


def _prove(raw, out, allowed_rows):
    """Decode both again: same version, key and tail; only the allowed rows differ; same row count."""
    a, b = table_decode(raw), table_decode(out)
    if a[:2] != b[:2] or a[3] != b[3]:
        raise KomamuraReworkError("re-encoding changed the table's version, key or tail")
    ra, rb = _split_rows(a[2]), _split_rows(b[2])
    if len(ra) != len(rb):
        raise KomamuraReworkError("re-encoding changed the row count")
    for (x, xt), (y, yt) in zip(ra, rb):
        if (x, xt) != (y, yt) and x.split(b",", 1)[0].decode("utf-8", "replace") not in allowed_rows:
            raise KomamuraReworkError("re-encoding changed a row it was not asked to")


def _remap_name(v, src_mode):
    """An act name in a CPU row of vanilla form src_mode, for the row's new form."""
    if v in ("", "none"):
        return v
    if src_mode == "2":
        return v[4:] if v.startswith("rev_") else v
    return v if v.startswith("evo_") else "evo_" + v


def _body(rows, table):
    """The data rows as [fields]; a blank row is refused (a remap would move it)."""
    out = []
    for r, _t in rows[1:]:
        if not r.strip():
            raise KomamuraReworkError("%s has a blank row" % table)
        out.append(r.decode("utf-8").split(","))
    return out


def _rejoin(rows, new_body):
    """The header, then the new rows: every row ends as the table's rows end (the header's line end), the last one as
    the table's last row ended (vanilla: no line end)."""
    sep = rows[0][1]
    lines = [rows[0]] + [[",".join(f).encode("utf-8"), sep] for f in new_body]
    lines[-1][1] = rows[-1][1]
    return _join_rows(lines)


def remap_actlist(raw):
    """AiActList_pl023: mode 2 rows -> mode 0 (rev_X -> X), mode 0 rows -> mode 1 (X -> evo_X), mode 1 rows dropped;
    keys renumbered pl023_actlist_<n> in that order. Refuses a table with no mode 2 row (already remapped)."""
    ver, key, text, tail = table_decode(raw)
    rows = _split_rows(text)
    header = rows[0][0].decode("utf-8").split(",")
    im, ia, ip = header.index("mode"), header.index("act_name"), header.index("pre_actname")
    body = _body(rows, "AiActList_pl023")
    if not any(f[im] == "2" for f in body):
        raise KomamuraReworkError("AiActList_pl023 has no mode 2 row: it still holds an earlier launch's remap (the "
                                  "version's Script/ was not mirrored over it). Reinstall the version and launch "
                                  "again")
    if any(f[im] not in ("0", "1", "2") for f in body):
        raise KomamuraReworkError("AiActList_pl023 has a row of a mode other than 0, 1, 2")
    out = []
    for want, new_mode in (("2", "0"), ("0", "1")):
        for f in body:
            if f[im] != want:
                continue
            g = list(f)
            g[0] = "pl023_actlist_%d" % len(out)
            g[im] = new_mode
            g[ia] = _remap_name(f[ia], want)
            g[ip] = _remap_name(f[ip], want)
            out.append(g)
    return table_encode(ver, key, _rejoin(rows, out), tail), len(out)


def remap_param(raw):
    """AiParam_pl023: rows pl023_2_* -> pl023_0_* (mode 0), pl023_0_* -> pl023_1_* (mode 1), pl023_1_* dropped.
    Refuses a table with no pl023_2_ row (already remapped)."""
    ver, key, text, tail = table_decode(raw)
    rows = _split_rows(text)
    header = rows[0][0].decode("utf-8").split(",")
    im = header.index("mode")
    body = _body(rows, "AiParam_pl023")
    if not any(f[0].startswith("pl023_2_") for f in body):
        raise KomamuraReworkError("AiParam_pl023 has no pl023_2_ row: it still holds an earlier launch's remap (the "
                                  "version's Script/ was not mirrored over it). Reinstall the version and launch "
                                  "again")
    out = []
    for f in body:
        if f[0][:8] not in ("pl023_0_", "pl023_1_", "pl023_2_") or f[im] != f[0][6]:
            raise KomamuraReworkError("AiParam row %s is not pl023_<mode>_ of its mode" % f[0])
    for want, new_mode in (("2", "0"), ("0", "1")):
        for f in body:
            if f[0][6] != want:
                continue
            g = list(f)
            g[0] = "pl023_%s_%s" % (new_mode, f[0][8:])
            g[im] = new_mode
            out.append(g)
    return table_encode(ver, key, _rejoin(rows, out), tail), len(out)


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


def load_manifest(base_dir):
    """{"files": [{"path": game path with /, "md5", "size"}...]} -- every file under Reworks/Komamura/Script,
    Motion and Overlay, checked against the bytes on disk (a git-LFS placeholder or a half-pulled file is refused)."""
    root = rework_root(base_dir)
    try:
        with open(os.path.join(root, MANIFEST), "r", encoding="utf-8") as f:
            man = json.load(f)
    except Exception as e:
        raise KomamuraReworkError("Reworks/Komamura/%s cannot be read (%s)" % (MANIFEST, e))
    for ent in man["files"]:
        src = os.path.join(root, ent["src"].replace("/", os.sep))
        if not os.path.isfile(src):
            raise KomamuraReworkError("the rework's file %s is missing" % ent["src"])
        if os.path.getsize(src) != ent["size"] or _md5(src) != ent["md5"]:
            raise KomamuraReworkError("the rework's file %s is not the one its manifest names (a git-LFS placeholder "
                                      "or an unfinished pull?)" % ent["src"])
    return man


def overlay_pairs(base_dir):
    """[(absolute source, game path with /)] of the rework's files outside Script / Motion, for the launcher's
    _overlay_pairs while the switch is ON. Raises KomamuraReworkError if the rework's files are not right."""
    man = load_manifest(base_dir)
    root = rework_root(base_dir)
    return [(os.path.join(root, e["src"].replace("/", os.sep)), e["path"]) for e in man["files"]
            if e["src"].startswith("Overlay/")]


def _write(path, data):
    tmp = path + ".komamura_rework_tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    with open(path, "rb") as f:
        if f.read() != data:
            raise OSError("%s did not read back as written" % path)


def remove_own_new(base_dir, game, log=print):
    """The rework's Overlay files at paths the Steam game does not have (manifest: steam_path false), removed from the
    game folder when they hold the rework's own bytes: the launcher's overlay revert puts back the stock files it backed
    up but leaves a file it created. A file there with other bytes is not ours: left. Never raises; returns the paths
    removed."""
    try:
        with open(os.path.join(rework_root(base_dir), MANIFEST), "r", encoding="utf-8") as f:
            files = json.load(f)["files"]
    except Exception:
        return []
    gone = []
    for e in files:
        if e.get("steam_path", True) or not e["src"].startswith("Overlay/"):
            continue
        p = os.path.join(game, *e["path"].split("/"))
        try:
            if os.path.isfile(p) and os.path.getsize(p) == e["size"] and _md5(p) == e["md5"]:
                os.remove(p)
                gone.append(e["path"])
        except OSError as ex:
            log("[komamura] could not remove %s (%s)" % (e["path"], ex))
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
        raise KomamuraReworkError("the game has no readable %s (%s)" % (HTABLE, e))
    n = struct.unpack_from("<I", raw, 0)[0] if len(raw) >= 4 else -1
    if n < 0 or 4 + 8 * n != len(raw):
        raise KomamuraReworkError("%s is not a registry table (%d bytes)" % (HTABLE, len(raw)))
    return p, raw, [struct.unpack_from("<II", raw, 4 + 8 * i) for i in range(n)]


def _new_paths(base_dir):
    """Game paths of the rework's files at paths the Steam game does not have (manifest steam_path false)."""
    try:
        with open(os.path.join(rework_root(base_dir), MANIFEST), "r", encoding="utf-8") as f:
            files = json.load(f)["files"]
    except Exception:
        return []
    return [e["path"] for e in files if e["src"].startswith("Overlay/") and not e.get("steam_path", True)]


def register_new(base_dir, game):
    """ON, after the overlay put the rework's files down: a row in the game's registry for each of its files at a new
    path (in manifest order, those missing only: a second call adds nothing). Returns (rows added, the table's md5)."""
    paths = _new_paths(base_dir)
    p, raw, rows = _read_htable(game)
    have = set(rows)
    add = []
    for gp in paths:
        if not os.path.isfile(os.path.join(game, *gp.split("/"))):
            raise KomamuraReworkError("the rework's file %s is not in the game folder (the overlay did not install "
                                      "it)" % gp)
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
            raise KomamuraReworkError("could not write %s (%s)" % (p, e))
    return len(add), hashlib.md5(out).hexdigest()


def unregister_absent(base_dir, game, log=print):
    """OFF: the registry rows of the rework's new-path files whose file is no longer in the game folder are dropped
    (a version that installs its own table has none: then nothing changes). Never raises; returns the rows dropped."""
    paths = _new_paths(base_dir)
    if not paths:
        return 0
    try:
        p, raw, rows = _read_htable(game)
        drop = {reg_key(gp) for gp in paths if not os.path.isfile(os.path.join(game, *gp.split("/")))}
        keep = [r for r in rows if r not in drop]
        if len(keep) != len(rows):
            _write(p, struct.pack("<I", len(keep)) + b"".join(struct.pack("<II", a, b) for a, b in keep))
        return len(rows) - len(keep)
    except (KomamuraReworkError, OSError) as e:
        log("[komamura] the registry was not checked for the rework's rows (%s)" % e)
        return 0


def install_data(base_dir, game, on, log=print):
    """The launch-time data step of a patched version (after the version, the reworks and the game mode's files;
    before mode_status). ON: copy the rework's Script / Motion files, edit pl023's shared rows, remap pl023's CPU
    tables. OFF: the version's mirror has just put its own Script / Motion back and the overlay revert its stock files;
    only the rework's files at paths the Steam game does not have are removed here. Returns the lines it logged."""
    lines = []
    def say(s):
        lines.append(s)
        log("[komamura] " + s)
    if not on:
        gone = remove_own_new(base_dir, game, log)
        unreg = unregister_absent(base_dir, game, log)
        say(describe(False) + (" (%d file(s) of the rework removed)" % len(gone) if gone else "")
            + (" (%d registry row(s) of absent rework files dropped)" % unreg if unreg else ""))
        return lines
    man = load_manifest(base_dir)
    root = rework_root(base_dir)
    for e in man["files"]:
        if not e["src"].startswith(("Script/", "Motion/")):
            continue                                       # Overlay/: the overlay pairs; Plugin/: launch_step
        src = os.path.join(root, e["src"].replace("/", os.sep))
        dst = os.path.join(game, *e["path"].split("/"))
        if not os.path.isdir(os.path.dirname(dst)):
            raise KomamuraReworkError("the game folder has no %s" % os.path.dirname(e["path"]))
        with open(src, "rb") as f:
            data = f.read()
        try:
            _write(dst, data)
        except OSError as ex:
            raise KomamuraReworkError("could not write %s (%s)" % (dst, ex))
        say("%s (%s)" % (e["path"], e["md5"][:8]))
    try:
        with open(os.path.join(root, ROWS), "r", encoding="utf-8") as f:
            rows = json.load(f)["tables"]
    except Exception as ex:
        raise KomamuraReworkError("Reworks/Komamura/%s cannot be read (%s)" % (ROWS, ex))
    for gp, spec in rows.items():
        p = os.path.join(game, *gp.split("/"))
        raw = _read_table(p, gp)
        new, ch = apply_rows(raw, spec)
        if new != raw:
            _write_table(p, new)
        say("%s: %d cell(s) of pl023 set (%s)" % (gp, len(ch), hashlib.md5(new).hexdigest()[:8]))
    for gp, fn in zip(AI_TABLES, (remap_actlist, remap_param)):
        p = os.path.join(game, *gp.split("/"))
        new, n = fn(_read_table(p, gp))
        _write_table(p, new)
        say("%s: %d row(s) by form (%s)" % (gp, n, hashlib.md5(new).hexdigest()[:8]))
    # the registry last: rows for the rework's files at new paths (the version's table has none for them)
    nreg, mreg = register_new(base_dir, game)
    say("%s: %d row(s) for the rework's files at new paths (%s)" % (HTABLE, nreg, mreg[:8]))
    say(describe(True))
    return lines


def _read_table(path, gp):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        raise KomamuraReworkError("the game has no readable %s (%s): the version did not install it" % (gp, e))


def _write_table(path, data):
    try:
        _write(path, data)
    except OSError as e:
        raise KomamuraReworkError("could not write %s (%s)" % (path, e))


def apply_switch(game, on):
    """Write (ON) or remove (OFF) <game>/ReBalanceOfSouls/komamura_rework.txt. ON needs pl023rework.dll installed."""
    if not os.path.isfile(os.path.join(game, EXE)):
        raise KomamuraReworkError("%s is not the game folder (no %s)" % (game, EXE))
    path = switch_path(game)
    if on:
        if not os.path.isfile(os.path.join(game, PLUGIN)):
            raise KomamuraReworkError("the Komamura rework is ON but %s is not installed: without it the exe's own "
                                      "giant code would run on the new Awakened form. Switch the rework OFF, or "
                                      "install a build that ships the plugin" % PLUGIN)
        want = text().encode()
        try:
            cur = open(path, "rb").read() if os.path.exists(path) else None
            if cur != want:
                _write(path, want)
        except OSError as e:
            raise KomamuraReworkError("could not write %s (%s)" % (path, e))
        if parse(open(path, "rb").read()) != (True, "file"):
            raise KomamuraReworkError("%s does not read back as ON" % path)
        return describe(True)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError as e:
            raise KomamuraReworkError("could not remove %s (%s)" % (path, e))
        if os.path.exists(path):
            raise KomamuraReworkError("%s is still there after its removal" % path)
        return describe(False) + " (%s\\%s removed)" % (DIR, NAME)
    return describe(False)


def install_plugin(base_dir, game, on):
    """ON: Reworks/Komamura/Plugin/pl023rework.dll -> <game>/ReBalanceOfSouls/ (the manifest's bytes, read back).
    OFF: a pl023rework.dll there with those bytes is removed (setup_matchmaking has normally done it already)."""
    man = load_manifest(base_dir) if on else None
    dst = os.path.join(game, PLUGIN)
    if on:
        ent = [e for e in man["files"] if e["src"] == "Plugin/pl023rework.dll"]
        if len(ent) != 1:
            raise KomamuraReworkError("Reworks/Komamura/manifest.json names no Plugin/pl023rework.dll")
        with open(os.path.join(rework_root(base_dir), "Plugin", "pl023rework.dll"), "rb") as f:
            data = f.read()
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            cur = open(dst, "rb").read() if os.path.isfile(dst) else None
            if cur != data:
                _write(dst, data)
        except OSError as e:
            raise KomamuraReworkError("could not install %s (%s)" % (dst, e))
        if hashlib.md5(open(dst, "rb").read()).hexdigest() != ent[0]["md5"]:
            raise KomamuraReworkError("%s does not read back as the rework's plugin" % dst)
        return "pl023rework.dll installed (%s)" % ent[0]["md5"][:8]
    try:
        with open(os.path.join(rework_root(base_dir), MANIFEST), "r", encoding="utf-8") as f:
            ent = [e for e in json.load(f)["files"] if e["src"] == "Plugin/pl023rework.dll"]
    except Exception:
        ent = []
    if ent and os.path.isfile(dst) and _md5(dst) == ent[0]["md5"]:
        try:
            os.remove(dst)
        except OSError as e:
            raise KomamuraReworkError("could not remove %s (%s)" % (dst, e))
        return "pl023rework.dll removed"
    return None


def launch_step(base_dir, game):
    """After the plugins are in (setup_matchmaking): the plugin and the switch file follow the saved choice -- the
    plugin first, so the switch never names a plugin that is not there."""
    on = load_choice(base_dir)
    lines = []
    if on:
        lines.append(install_plugin(base_dir, game, True))
        lines.append(apply_switch(game, True))
    else:
        lines.append(apply_switch(game, False))
        x = install_plugin(base_dir, game, False)
        if x:
            lines.append(x)
    for l in lines:
        print("[komamura] " + l)
    return lines[-1] if len(lines) == 1 else "; ".join(lines)


# ---------------------------------------------------------------------------------------------------------------------
# By hand
# ---------------------------------------------------------------------------------------------------------------------

def status(game, base_dir=REPO):
    p = switch_path(game)
    on = parse(open(p, "rb").read())[0] if os.path.exists(p) else False
    print("game folder: %s" % game)
    state = ("present, ON" if on else "present, OFF") if os.path.exists(p) else "none (OFF)"
    print("  %s\\%s: %s" % (DIR, NAME, state))
    print("  pl023rework.dll: %s" % ("installed" if os.path.isfile(os.path.join(game, PLUGIN)) else "not installed"))
    print("  the launcher's switch: %s" % describe(load_choice(base_dir)))
    print("  the switch, the data and the plugin change together at the next launch")
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "status":
        return status(argv[2] if len(argv) > 2 else DEFAULT_GAME)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
