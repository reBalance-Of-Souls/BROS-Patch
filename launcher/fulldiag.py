"""fulldiag.py -- the launcher side of the advanced diagnostics (fulldiag.dll). Pass fd, 2026-10-31.

WHAT IT IS. A thorough recorder for the question "why does the game play differently on this PC": every battle frame
of both fighters and the commands each one executed, the raw pad and keyboard state and the bindings, the timing of
every frame (menus too) with the stutters, where a slow frame's time went (a sampling profiler), the PC once a second,
every thread and every module in the game -- a foreign proxy DLL is named by its version information. Berg,
2026-10-31: "an advanced diagnostic option that is off by default and on when you turn it on, and it would collect ALL
possible data".

THE SWITCH. The launcher's Diagnostics page, card "Advanced diagnostics": OFF by default, kept in Json/fulldiag.json
({"FULLDIAG": "ON"} or "OFF"). At every launch that installs the loader (the launcher and its right-click Quick
Launch), launch_step() writes <game>\\bros_fulldiag.txt with `on 1` while it is ON and removes the file while it is
OFF -- a file, not an environment variable, so a game started from the exe follows the switch too (the bros_tools.txt
pattern, launcher/devtools_mode.py). The file is written through a temporary file (wholly old or wholly new) and read
back with parse(), this module's copy of fulldiag.dll's own reader. If the switch cannot be applied the launch stops,
as for the netcode, developer-tools and Zangetsu switches: a game that records while the switch shows OFF (or the
reverse) is the "works for me" bug, and recording while OFF would break the player's choice. While ON, every launch
also leaves a snapshot of the launcher's side beside the recordings, BROS_FullDiag\\launcher_<UTC>.json (the
checkout, the version and mode launched, the launcher's switches without secrets, Steam's settings for the game,
known input / overlay / frame-pacing tools running); the snapshot never stops a launch.

THE DATA. fulldiag.dll writes one folder per game start, <game>\\BROS_FullDiag\\<yyyymmdd-hhmmss>Z_p<pid>\\ (UTC):
session.json, modules.jsonl, events.jsonl, sys.jsonl, threads.jsonl, timing.bin, and per battle e1_bNN.bin,
fx_bNN.bin, bind_bNN.bin, prof_bNN.bin, prof_bNN_top.csv (Diagnostics\\FULLDIAG_DATA.md says what each holds;
Diagnostics\\fulldiag_read.py reads them). Nothing is ever deleted on its own (Berg, 2026-10-31: "Keep everything,
but give the option to 'delete older sessions' when needed"), and nothing leaves the PC by itself.

SENDING. "Send" packs the chosen sessions (by default every one not sent yet), the launcher snapshot taken before
each, and a fresh report of this PC made by Diagnostics\\brosdiag_collect.py (machine, displays, controllers, Steam
and Steam Input, the checkout, the game folder's file list with checksums, the patch's log and crash logs), into zips
of about 8 MB (PART_LIMIT) written one after the other to a temporary folder beside the recordings -- a recording is never held
in memory whole -- and posts them in order to the relay with X-BROS-Tournament "fulldiag": the relay files every part
under inbox/fulldiag/, apart from the tournaments (Berg, 2026-10-31: "under a different folder so they don't get
mixed up"; the tournament recordings the collector would copy are left out for the same reason). The relay's address
is Diagnostics/fulldiag.txt's `upload` line when that file exists, otherwise Diagnostics/tournament.txt's. "Save zips
to Desktop" writes the same parts locally. A file larger than a part is cut into numbered chunks, each with its offset
and checksum (fulldiag_read.py join puts them back). A session the game is still writing goes as far as it was
written, and is offered again once it has grown.

PRIVACY. fulldiag.dll writes no name, Steam ID, IP address or user folder, and no local time. Before packing, its
text files are scrubbed again here, in their values only (the keys are the plugin's): this PC's Windows user and
computer name, the Steam account and persona names found on it (3 letters or more), Steam IDs and any other run of 15
or more digits, user folders in paths, access tokens, URL credentials, lobby data, salt and upload lines; the files
beside the exe that fulldiag recorded, the environment values and the player's comment also lose IP addresses and
base64-like strings. Binary records carry game state only. The PC report is scrubbed by the collector itself. Unlike
the tournament data, this send says which time zone the PC is in: the report and the game's own logs keep the PC's
clock, and meta.json carries the offset so log lines can be put on the recordings' UTC clock; the consent text says so.

BY HAND:
    python launcher\\fulldiag.py status   [<game folder>]     the switch, the file, the sessions (changes nothing)
    python launcher\\fulldiag.py on|off   [<game folder>]     set the switch and write / remove the file now
    python launcher\\fulldiag.py pack     [<game folder>] [--out <folder>] [--no-report]
                                                              the zips Send would post, saved locally

Standard library only, Python 3.6 or newer. Windows; the non-UI parts also run elsewhere (the tests).
"""
import datetime
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
import zlib

NAME = "bros_fulldiag.txt"
EXE = "BLEACH_Rebirth_of_Souls.exe"
PLUGIN = os.path.join("ReBalanceOfSouls", "fulldiag.dll")
CHOICE_NAME = "fulldiag.json"             # Json/fulldiag.json: {"FULLDIAG": "ON"} or {"FULLDIAG": "OFF"}
DEFAULT_ON = False
DATA_DIR = "BROS_FullDiag"
SEND_TMP = "_send_tmp"                    # BROS_FullDiag\_send_tmp\<batch>\: the parts while a send is being made
SENT_MARK = ".fulldiag_sent.json"         # inside a session folder: what was sent, file by file
TOURNAMENT = "fulldiag"                   # X-BROS-Tournament: the relay files the parts under inbox/fulldiag/
BUNDLE_FORMAT = "fulldiag-bundle 1"       # meta.json's own format (the relay checks diagnostics.BUNDLE_FORMAT)
MAX_UPLOAD = 20 * 1024 * 1024             # the relay refuses more
# A part is aimed at 8 MB, not the tournament's 18: the relay (cloudflare\worker.js) turns the whole upload into a
# base64 JSON string in memory before it stores it, and a Worker has 128 MB in all -- an 18 MB part needs roughly
# 18 + 18 + 24 + 24 + 24 MB of copies on the way, too close to that to rely on; 8 MB keeps it near half.
PART_LIMIT = 8 * 1024 * 1024
RESERVE = 1024 * 1024                     # kept free in a part for meta.json and the zip directory
MARGIN = 256 * 1024                       # what deflate may still hold back while an entry is being written
BLOCK = 256 * 1024                        # the raw block a binary file is read in
MAX_BLOCK = 1024 * 1024                   # no block written into a chunk is longer (a longer text block is split)
SMALL = 8 * 1024 * 1024                   # a file up to this size is measured exactly before it is placed
CHUNK_RAW_MAX = 1024 * 1024 * 1024        # a chunk never holds more than this raw (no zip64 anywhere)
BIG_SEND = 2 * 1024 * 1024 * 1024         # a send larger than this before packing is confirmed once more
COLLECTOR = os.path.join("Diagnostics", "brosdiag_collect.py")
COLLECTOR_TIMEOUT = 900
SESSION_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})Z_p(\d+)$")
SNAP_RE = re.compile(r"^launcher_(\d{8})-(\d{6})Z(?:_(\d+))?\.json$")   # _<n>: a second launch in the same second
ZIP_DATE = (1980, 1, 1, 0, 0, 0)          # every entry's date: a zip stores local clock time
TEXT_EXT = (".json", ".jsonl", ".csv", ".txt")

# fulldiag.dll's defaults (p1_head.c FdCfg) and its clamps (cfg_set)
CFG_DEFAULTS = {"on": 0, "e1": 1, "timing": 1, "sys": 1, "modules": 1, "long_ms": 25, "min_free_mb": 2048,
                "prof_hz": 100, "prof_long_ms": 25, "prof_max_mb": 64, "prof_render": 1, "prof_stop_ms": 20}
_BOOL_KEYS = ("on", "e1", "timing", "sys", "modules", "prof_render")
_CLAMP = {"long_ms": (5, 1000), "min_free_mb": (256, 1000000), "prof_hz": (0, 1000), "prof_long_ms": (5, 1000),
          "prof_max_mb": (4, 1024), "prof_stop_ms": (5, 1000)}

# the launcher checkout, when this module sits in <repo>/launcher/
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FulldiagError(Exception):
    """Something the player should read; nothing was changed by the call that raised it."""


# =====================================================================================================================
# The game's file: what fulldiag.dll reads
# =====================================================================================================================

def text(on):
    return ("# bros_fulldiag.txt -- written by the launcher (Diagnostics > Advanced diagnostics, or launcher\\fulldiag.py)\n"
            "# at every launch while the switch is ON, removed while it is OFF. fulldiag.dll reads it once, at game\n"
            "# start: on 1 records everything into BROS_FullDiag\\. Do not edit: the next launch rewrites or removes it.\n"
            "on %d\n" % (1 if on else 0))


# strtol (base 10) skips leading white space; in a value only \v and \f can occur (blanks, CR and LF end it)
_INT_RE = re.compile(rb"^[\x0b\x0c]*[+-]?[0-9]+$")
_STOP = (b" ", b"\t", b"\r", b"\n")


def parse(data):
    """fulldiag.dll's cfg_read (p1_head.c), chunk for chunk, on the bytes it would read. fopen(..., "r") is the CRT's
    TEXT mode: a Ctrl-Z ends the file, CR LF reads as LF. fgets into 256 bytes: at most 255 characters a chunk, ending
    after a LF; a chunk is a C string (it ends at a NUL); a chunk whose C string holds no LF marks the next chunk as the
    tail of the same line, and a tail is skipped. In a chunk: '#' starts a comment; blanks (space, tab); a key of up to
    31 characters, lower-cased (A-Z only), ending at a blank, CR or LF -- a longer key runs on into the value; blanks; a
    value of up to 31 characters, lower-cased; no key or no value: skipped. "on" / "yes" / "true" read 1, "off" / "no"
    / "false" 0, otherwise strtol base 10, which must use the whole value (leading \\v \\f allowed, an optional sign),
    capped at +-100,000,000, then the key's own clamp. Unknown keys are ignored; a later line wins. Returns the 12
    settings as a dict."""
    b = bytes(data).split(b"\x1a", 1)[0].replace(b"\r\n", b"\n")
    cfg = dict(CFG_DEFAULTS)
    tail = False
    p = 0
    while p < len(b):
        e = b.find(b"\n", p, p + 255)
        chunk = b[p:e + 1] if e >= 0 else b[p:p + 255]
        p += len(chunk)
        s = chunk.split(b"\0", 1)[0]
        was_tail, tail = tail, b"\n" not in s
        if was_tail:
            continue
        h = s.find(b"#")
        if h >= 0:
            s = s[:h]
        i = 0
        while i < len(s) and s[i:i + 1] in (b" ", b"\t"):
            i += 1
        k0 = i
        while i < len(s) and s[i:i + 1] not in _STOP and i - k0 < 31:
            i += 1
        key = s[k0:i].lower()
        while i < len(s) and s[i:i + 1] in (b" ", b"\t"):
            i += 1
        v0 = i
        while i < len(s) and s[i:i + 1] not in _STOP and i - v0 < 31:
            i += 1
        val = s[v0:i].lower()
        if not key or not val:
            continue
        if val in (b"on", b"yes", b"true"):
            v = 1
        elif val in (b"off", b"no", b"false"):
            v = 0
        elif _INT_RE.match(val):
            v = max(-100000000, min(100000000, int(val.lstrip(b"\x0b\x0c"))))
        else:
            continue
        k = key.decode("latin-1")
        if k in _BOOL_KEYS:
            cfg[k] = 1 if v != 0 else 0
        elif k in _CLAMP:
            lo, hi = _CLAMP[k]
            cfg[k] = max(lo, min(hi, v))
    return cfg


def current(game):
    """(state, cfg, raw bytes or the error): state is 'absent', 'unreadable', 'launcher' (a file this module writes)
    or 'hand' (anything else). fulldiag.dll treats a file it cannot open as absent: OFF."""
    path = os.path.join(game, NAME)
    if not os.path.exists(path):
        return "absent", dict(CFG_DEFAULTS), None
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return "unreadable", dict(CFG_DEFAULTS), e
    cfg = parse(raw)
    return ("launcher" if raw in (text(True).encode(), text(False).encode()) else "hand"), cfg, raw


# =====================================================================================================================
# The launcher's switch
# =====================================================================================================================

def choice_path(base_dir):
    return os.path.join(base_dir, "Json", CHOICE_NAME)


def load_choice(base_dir):
    """True = ON. A missing, unreadable or unexpected Json/fulldiag.json reads as DEFAULT_ON (OFF)."""
    try:
        with open(choice_path(base_dir), "r", encoding="utf-8") as f:
            v = json.load(f).get("FULLDIAG")
    except Exception:
        return DEFAULT_ON
    return True if v == "ON" else False if v == "OFF" else DEFAULT_ON


def save_choice(base_dir, on):
    """Keep the switch in Json/fulldiag.json (through a temporary file). Raises FulldiagError if it does not read back."""
    path = choice_path(base_dir)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"FULLDIAG": "ON" if on else "OFF"}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise FulldiagError("could not save the advanced diagnostics switch in %s (%s)" % (path, e))
    if load_choice(base_dir) != bool(on):
        raise FulldiagError("the advanced diagnostics switch did not read back from %s" % path)


def _write(path, data):
    """Write through <path>.fulldiag_tmp and os.replace (wholly old or wholly new), then read back."""
    tmp = path + ".fulldiag_tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        with open(tmp, "rb") as f:
            if f.read() != data:
                raise OSError("the temporary file did not read back")
        os.replace(tmp, path)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise
    with open(path, "rb") as f:
        if f.read() != data:
            raise OSError("%s did not read back as written" % os.path.basename(path))


def is_game(game):
    return bool(game) and os.path.isfile(os.path.join(game, EXE))


def apply(game, on):
    """Write <game>/bros_fulldiag.txt (ON) or remove it (OFF). Returns one line. Raises FulldiagError -- with the file
    as it was -- if the folder is not the game's, or the file cannot be read, written or removed."""
    if not is_game(game):
        raise FulldiagError("%s is not the game folder (no %s)" % (game, EXE))
    path = os.path.join(game, NAME)
    state, cfg, raw = current(game)
    if state == "unreadable":
        raise FulldiagError("%s cannot be read (%s) -- close whatever holds it, or remove it by hand" % (path, raw))
    if on:
        want = text(True).encode()
        if raw != want:
            try:
                _write(path, want)
            except OSError as e:
                raise FulldiagError("could not write %s (%s)" % (path, e))
        if current(game)[1]["on"] != 1:
            raise FulldiagError("%s reads back as OFF -- check it" % NAME)
        line = "ON: every game start records into %s\\" % DATA_DIR + ("" if raw != want else " (already in place)")
        if state == "hand":
            line += "; the hand-edited %s was replaced" % NAME
        if not os.path.isfile(os.path.join(game, PLUGIN)):
            line += " -- note: %s is not installed, so nothing is recorded this time" % PLUGIN
        return line
    if state == "absent":
        return "OFF: nothing is recorded"
    try:
        os.remove(path)
    except OSError as e:
        raise FulldiagError("could not remove %s (%s) -- the game would record although the switch is OFF" % (path, e))
    if os.path.exists(path):
        raise FulldiagError("%s is still there after its removal" % path)
    return "OFF: nothing is recorded (%s removed%s)" % (NAME, ", it said ON" if cfg["on"] else "")


def launch_step(base_dir, game, version=None, mode=None):
    """The launch-time step, after the loader and the plugins are in (setup_matchmaking): applies the switch, prints
    what it did and returns that line. While ON it also writes the launcher snapshot (never stops a launch). Raises
    FulldiagError when the switch cannot be applied -- the caller must then not start the game."""
    on = load_choice(base_dir)
    line = apply(game, on)
    if on:
        try:
            p = write_snapshot(base_dir, game, version, mode)
            line += "; launcher snapshot %s" % os.path.basename(p)
        except Exception as e:                     # extra data: never a reason to stop a launch
            line += "; the launcher snapshot could not be written (%s)" % e
    print("[fulldiag] " + line)
    return line


def set_choice(base_dir, game, on):
    """The Diagnostics page's toggle: keep the choice and apply it to the game folder now, so a game started from the
    exe follows it too. Raises FulldiagError only when the choice itself could not be saved; returns what was done to
    the game folder (a failure there is said, and the next launch applies the switch or stops)."""
    save_choice(base_dir, on)
    try:
        return apply(game, on)
    except FulldiagError as e:
        return "the switch is saved, but the game folder could not follow it now (%s); the next launch applies it" % e


# =====================================================================================================================
# Privacy: what is replaced before anything is packed
# =====================================================================================================================

_USERPATH = re.compile(r"(?i)([a-z]:[\\/]+(?:users|documents and settings)[\\/]+)(?!<user>)[^\\/\r\n\"'<>|]+")
_HOMEPATH = re.compile(r"(?i)([\\/](?:home|users|var[\\/]home)[\\/]+)(?!<user>)[^\\/\r\n\"'<>|]+")
_STEAMID = re.compile(r"7656119\d{10}")
_LONGNUM = re.compile(r"(?<![0-9A-Za-z.])\d{15,}(?![0-9A-Za-z])")
_TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_\-]{20,})")
_URLCRED = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/@\s\"']+@")
_LOBBY = re.compile(r'(SetLobby\w*Data\s*\(?\s*"[^"\r\n]*"\s*[=,]\s*")[^"\r\n]*')
_SALT = re.compile(r"(?im)^([ \t]*(?:salt|upload)[ \t]+)\S[^\r\n]*")       # keeps the line end (CR LF too)
_B64 = re.compile(r"[A-Za-z0-9+]{32,}={0,2}")
_IPV4 = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])")
_IPV6 = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{1,4}:){4,7}[0-9A-Fa-f]{1,4}(?![0-9A-Fa-f:])")
_KEEP_IP = ("0.0.0.0", "127.0.0.1", "255.255.255.255")
_STOPWORDS = {"user", "users", "admin", "administrator", "owner", "guest", "default", "public", "steam", "game", "games",
              "home", "root", "steamuser", "crossover", "deck", "windows", "desktop", "player", "bleach", "local", "system"}
_SECRET_KEY = re.compile(r"(?i)token|secret|passw|apikey|api_key|^key$|hash_value|admin_id|salt|upload")


def _b64_repl(m):
    s = m.group(0)
    return "<b64>" if re.search(r"\d", s) and re.search(r"[A-Z]", s) and re.search(r"[a-z]", s) else s


def _ip_repl(m):
    return "<ip>" if all(int(g) <= 255 for g in m.groups()) and m.group(0) not in _KEEP_IP else m.group(0)


class Scrubber(object):
    """Replaces this PC's names (Windows user, computer, Steam account and persona; 3 letters or more), user folders
    in paths, Steam IDs and other runs of 15+ digits, tokens, URL credentials, lobby data, salt and upload lines.
    free=True (free text: switch files, environment values, the player's comment) also replaces IP addresses and
    base64-like strings -- not in the recordings' own fields, where version numbers look like addresses."""

    def __init__(self):
        self.words = []
        self._wre = None

    def add(self, word):
        w = (word or "").strip()
        if len(w) >= 3 and w.lower() not in _STOPWORDS and w not in self.words:
            self.words.append(w)
            self.words.sort(key=len, reverse=True)
            self._wre = re.compile("|".join(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(x) for x in self.words), re.I)

    def __call__(self, s, free=False):
        if not s:
            return s
        s = _URLCRED.sub(r"\1<cred>@", s)
        s = _TOKEN.sub("<token>", s)
        s = _LOBBY.sub(r"\1<lobbydata>", s)
        s = _SALT.sub(r"\1<removed>", s)
        s = _USERPATH.sub(r"\1<user>", s)
        s = _HOMEPATH.sub(r"\1<user>", s)
        if self._wre is not None:
            s = self._wre.sub("<name>", s)
        s = _STEAMID.sub("<steamid>", s)
        s = _LONGNUM.sub("<id>", s)
        if free:
            s = _B64.sub(_b64_repl, s)
            s = _IPV4.sub(_ip_repl, s)
            s = _IPV6.sub("<ip6>", s)
        return s


_COLLECTOR_CACHE = {}


def _collector_module(base_dir):
    """Diagnostics/brosdiag_collect.py loaded as a module (its Steam and process probes), or None."""
    p = os.path.join(base_dir or "", COLLECTOR)
    try:
        key = (p, os.path.getmtime(p))
    except OSError:
        return None
    if key in _COLLECTOR_CACHE:
        return _COLLECTOR_CACHE[key]
    try:
        spec = importlib.util.spec_from_file_location("brosdiag_collect_fd", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:
        mod = None
    _COLLECTOR_CACHE[key] = mod
    return mod


def make_scrubber(base_dir=None):
    """A Scrubber that knows this PC's names: the Windows user and computer name, and the Steam account and persona
    names in every Steam installation's loginusers.vdf (read with the collector's own VDF reader when it is there)."""
    sc = Scrubber()
    for w in (os.environ.get("USERNAME"), os.environ.get("USER"), os.environ.get("LOGNAME"), os.environ.get("COMPUTERNAME"),
              os.environ.get("USERDOMAIN")):
        sc.add(w)
    try:
        import socket
        sc.add(socket.gethostname().split(".")[0])
    except Exception:
        pass
    try:
        import getpass
        sc.add(getpass.getuser())
    except Exception:
        pass
    mod = _collector_module(base_dir) if base_dir else None
    if mod is not None:
        try:
            for root in mod.steam_roots():
                p = os.path.join(root, "config", "loginusers.vdf")
                if not os.path.isfile(p):
                    continue
                for u in (mod.vget(mod.vdf_load(p), "users") or {}).values():
                    if isinstance(u, dict):
                        sc.add(mod.vget(u, "AccountName"))
                        sc.add(mod.vget(u, "PersonaName"))
        except Exception:
            pass
    return sc


def drop_secrets(o):
    if isinstance(o, dict):
        return dict((k, "<removed>" if _SECRET_KEY.search(str(k)) else drop_secrets(v)) for k, v in o.items())
    if isinstance(o, list):
        return [drop_secrets(v) for v in o]
    return o


def scrub_obj(o, sc, free=False, keys=True):
    """Scrub every string of a JSON value (and its keys when keys=True); an integer that is a Steam ID becomes
    "<steamid>"."""
    if isinstance(o, str):
        return sc(o, free)
    if isinstance(o, bool) or o is None or isinstance(o, float):
        return o
    if isinstance(o, int):
        return "<steamid>" if 76561190000000000 <= o <= 76561199999999999 else o
    if isinstance(o, dict):
        return dict(((sc(k, free) if keys and isinstance(k, str) else k), scrub_obj(v, sc, free, keys)) for k, v in o.items())
    if isinstance(o, (list, tuple)):
        return [scrub_obj(v, sc, free, keys) for v in o]
    return o


def scrub_jsonl_line(line, sc):
    """One line of a fulldiag .jsonl file as it is packed, and whether it changed: its values scrubbed (the keys are
    the plugin's own); a line that is not JSON (the last one, while the game writes it) is scrubbed as text."""
    body = line.rstrip(b"\r\n")
    end = line[len(body):]
    if not body.strip():
        return line, False
    try:
        o = json.loads(body.decode("utf-8"))
    except Exception:
        t = body.decode("utf-8", "replace")
        out = sc(t).encode("utf-8") + end
        return out, out != line
    o2 = scrub_obj(o, sc, keys=False)
    if o2 == o:
        return line, False
    return json.dumps(o2, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + end, True


def scrub_session_json(data, sc):
    """session.json as it is packed, and whether it changed: values scrubbed; the texts of the files beside the exe
    and the environment values as free text (IPs and base64-like strings too)."""
    try:
        s = json.loads(data.decode("utf-8"))
    except Exception:
        out = sc(data.decode("utf-8", "replace"), True).encode("utf-8")
        return out, out != data
    s2 = scrub_obj(s, sc, keys=False)
    if isinstance(s2, dict):
        for f in s2.get("beside_exe") or []:
            if isinstance(f, dict) and isinstance(f.get("text"), str):
                f["text"] = sc(f["text"], True)
        if isinstance(s2.get("env"), dict):
            s2["env"] = dict((k, sc(v, True) if isinstance(v, str) else v) for k, v in s2["env"].items())
    if s2 == s:
        return data, False
    return json.dumps(s2, indent=1, ensure_ascii=False).encode("utf-8"), True


def scrub_text(data, sc):
    t = data.decode("utf-8", "replace")
    out = sc(t).encode("utf-8")
    return out, out != data


# =====================================================================================================================
# The launcher snapshot (at every launch while ON)
# =====================================================================================================================

def _run(cmd, timeout=15, cwd=None):
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}       # CREATE_NO_WINDOW
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=timeout,
                           cwd=cwd, env=env, **kw)
        return r.returncode, r.stdout.decode("utf-8", "replace").strip(), r.stderr.decode("utf-8", "replace").strip()
    except Exception as e:
        return -1, "", str(e)


def _git(base_dir, *args):
    rc, out, _err = _run(["git", "-C", base_dir] + list(args))
    return out if rc == 0 else ""


def _running_tools(mod):
    """{category: [program, ...]} of the running programs the collector's fixed TOOLS list names (no other program is
    named), or {"error": ...}."""
    if mod is None:
        return {"error": "Diagnostics/brosdiag_collect.py not found"}
    try:
        if os.name == "nt":
            procs, _mods = mod.win_snapshot()
            names = [n for _pid, n in procs]
        else:
            names = [a0 for _pid, a0, _args in mod.posix_processes()]
        out = {}
        for n in names:
            cat, base = mod.classify_proc(n)
            if cat and base not in out.setdefault(cat, []):
                out[cat].append(base)
        return dict((k, sorted(v)) for k, v in out.items() if v)
    except Exception as e:
        return {"error": type(e).__name__}


def _steam_settings(mod):
    """Steam's per-account settings for the game (Steam Input, launch options, ...), without the account's id:
    the plain values of every app block for the game in every localconfig.vdf, as the collector reads them."""
    if mod is None:
        return None
    out = []
    try:
        for root in mod.steam_roots():
            for lc in sorted(glob.glob(os.path.join(root, "userdata", "*", "config", "localconfig.vdf"))):
                try:
                    for blk in mod.vdf_app_blocks(mod.vdf_load(lc)):
                        out.append(dict((k, v) for k, v in blk.items() if not isinstance(v, dict)))
                except Exception as e:
                    out.append({"error": type(e).__name__})
    except Exception as e:
        return {"error": type(e).__name__}
    return out


def _utc_stamp(t=None):
    return datetime.datetime.fromtimestamp(t if t is not None else time.time(), datetime.timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def _utc_iso(t=None):
    return datetime.datetime.fromtimestamp(t if t is not None else time.time(), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def snapshot(base_dir, game, version=None, mode=None):
    """The launcher's side of one game start, as a dict (scrubbed)."""
    mod = _collector_module(base_dir)
    sc = make_scrubber(base_dir)
    choices = {}
    for p in sorted(glob.glob(os.path.join(base_dir, "Json", "*.json"))):
        n = os.path.basename(p)
        try:
            if os.path.getsize(p) > 256 * 1024:
                choices[n] = "(not read: %d bytes)" % os.path.getsize(p)
                continue
            with open(p, "r", encoding="utf-8") as f:
                choices[n] = drop_secrets(json.load(f))
        except Exception as e:
            choices[n] = "(unreadable: %s)" % type(e).__name__
    plug = os.path.join(game, PLUGIN)
    state, cfg, _raw = current(game)
    snap = {"format": "fulldiag-launcher 1", "utc": _utc_iso(), "version": version, "game_mode": mode,
            "checkout": {"head": _git(base_dir, "rev-parse", "HEAD"), "branch": _git(base_dir, "rev-parse", "--abbrev-ref", "HEAD"),
                         "upstream": _git(base_dir, "rev-parse", "@{u}"),
                         "head_date": _git(base_dir, "log", "-1", "--format=%cI")},
            "launcher_json": choices,
            "game_file": {"state": state, "cfg": cfg},
            "plugin": {"installed": os.path.isfile(plug), "md5": _md5(plug) if os.path.isfile(plug) else None},
            "steam_app_settings": _steam_settings(mod),
            "running_tools": _running_tools(mod),
            "python": sys.version.split()[0], "platform": sys.platform}
    return scrub_obj(snap, sc)


def write_snapshot(base_dir, game, version=None, mode=None):
    """BROS_FullDiag\\launcher_<UTC>Z.json (launcher_<UTC>Z_<n>.json for a second launch within the same second: a
    snapshot is never overwritten)."""
    d = data_dir(game)
    os.makedirs(d, exist_ok=True)
    data = json.dumps(snapshot(base_dir, game, version, mode), indent=1, ensure_ascii=False).encode("utf-8")
    base = os.path.join(d, "launcher_%s" % _utc_stamp())
    p, k = base + ".json", 1
    while os.path.exists(p):
        p, k = "%s_%d.json" % (base, k), k + 1
    _write(p, data)
    return p


# =====================================================================================================================
# The sessions
# =====================================================================================================================

def data_dir(game):
    return os.path.join(game, DATA_DIR)


def _session_files(path):
    """{name: size} of a session folder's files as they are now (no temporaries, no sent marker)."""
    out = {}
    for n in sorted(os.listdir(path)):
        p = os.path.join(path, n)
        if n == SENT_MARK or n.endswith((".tmp", ".fulldiag_tmp")) or not os.path.isfile(p):
            continue
        out[n] = os.path.getsize(p)
    return out


def _session_complete(path):
    """True when events.jsonl ends with the session_end line (the game process ended normally)."""
    p = os.path.join(path, "events.jsonl")
    try:
        with open(p, "rb") as f:
            f.seek(max(0, os.path.getsize(p) - 1024))
            tail = f.read().strip().splitlines()
        return bool(tail) and b'"t":"session_end"' in tail[-1]
    except OSError:
        return False


def _session_sent(path):
    try:
        with open(os.path.join(path, SENT_MARK), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def sessions(game):
    """Every session folder, oldest first: dicts with name, path, stamp (yyyymmdd-hhmmss), start (readable, UTC),
    bytes, files {name: size}, complete (ended normally), sent ('no', 'yes', 'grown': sent before and written to
    since), recent (written to within the last 30 s: the game may be on it)."""
    d = data_dir(game)
    out = []
    if not os.path.isdir(d):
        return out
    now = time.time()
    for n in sorted(os.listdir(d)):
        p = os.path.join(d, n)
        m = SESSION_RE.match(n)
        if not m or not os.path.isdir(p):
            continue
        try:
            files = _session_files(p)
            newest = max([os.path.getmtime(os.path.join(p, f)) for f in files] or [os.path.getmtime(p)])
        except OSError:
            continue
        mark = _session_sent(p)
        sent = "no"
        if mark and isinstance(mark.get("files"), dict):
            sent = "yes" if all(mark["files"].get(f) == s for f, s in files.items()) else "grown"
        y, mo, da, h, mi, s, pid = m.groups()
        out.append({"name": n, "path": p, "stamp": "%s%s%s-%s%s%s" % (y, mo, da, h, mi, s),
                    "start": "%s-%s-%s %s:%s UTC" % (y, mo, da, h, mi), "pid": int(pid),
                    "bytes": sum(files.values()), "files": files, "complete": _session_complete(p), "sent": sent,
                    "recent": now - newest < 30})
    return out


def snapshots(game):
    """The launcher snapshots, oldest first: [(stamp yyyymmdd-hhmmss, file name)]."""
    d = data_dir(game)
    if not os.path.isdir(d):
        return []
    out = []
    for n in os.listdir(d):
        m = SNAP_RE.match(n)
        if m:
            out.append(("%s-%s" % m.groups()[:2], int(m.group(3) or 0), n))
    return [(st, n) for st, _k, n in sorted(out)]


def snapshot_for(stamp, snaps):
    """The newest snapshot written at or before a session's start (the launcher writes it just before the game
    starts), or None."""
    best = None
    for s, n in snaps:
        if s <= stamp:
            best = n
    return best


def human(n):
    for unit, k in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= k:
            return "%.1f %s" % (n / float(k), unit)
    return "%d B" % n


def status_text(base_dir, game):
    """(one line for the Diagnostics page, highlight): highlight while sessions wait to be sent."""
    try:
        on = load_choice(base_dir)
        ss = sessions(game)
    except Exception:
        return "", False
    unsent = [s for s in ss if s["sent"] != "yes"]
    head = "ON -- every game start records everything." if on else "OFF -- nothing is recorded."
    if not ss:
        return head + " No recordings on this PC.", False
    return ("%s %d recording%s on this PC (%s), %d not sent yet." % (head, len(ss), "" if len(ss) == 1 else "s",
                                                                       human(sum(s["bytes"] for s in ss)), len(unsent)),
            bool(unsent))


def delete_sessions(game, names):
    """Delete the named session folders (never one the game is still writing), and the launcher snapshots no
    remaining session needs (a snapshot newer than every session is kept: a launch in progress). Returns
    (deleted names, bytes freed, [(name, why) not deleted], snapshots removed)."""
    all_ss = sessions(game)
    by = dict((s["name"], s) for s in all_ss)
    done, freed, kept = [], 0, []
    for n in names:
        s = by.get(n)
        if not s:
            kept.append((n, "no such recording"))
            continue
        if s["recent"] and not s["complete"]:
            kept.append((n, "the game is still writing it"))
            continue
        try:
            shutil.rmtree(s["path"])
            done.append(n)
            freed += s["bytes"]
        except OSError as e:
            kept.append((n, str(e)))
    snaps = snapshots(game)
    remaining = [s for s in all_ss if s["name"] not in done]
    need = set(snapshot_for(s["stamp"], snaps) for s in remaining)
    newest = max([s["stamp"] for s in all_ss] or [""])
    removed = 0
    if done:
        for stamp, n in snaps:
            if n in need or stamp > newest:
                continue
            try:
                p = os.path.join(data_dir(game), n)
                size = os.path.getsize(p)
                os.remove(p)
                freed += size
                removed += 1
            except OSError:
                pass
    return done, freed, kept, removed


# =====================================================================================================================
# The parts: zips of at most PART_LIMIT, streamed to a folder, then posted one by one
# =====================================================================================================================

def relay_url(base_dir):
    """Diagnostics/fulldiag.txt's `upload` line, else Diagnostics/tournament.txt's, else ''."""
    for name in ("fulldiag.txt", "tournament.txt"):
        p = os.path.join(base_dir, "Diagnostics", name)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    parts = line.strip().split(None, 1)
                    if len(parts) == 2 and parts[0].lower() == "upload" and parts[1].strip().lower().startswith("https://"):
                        return parts[1].strip()
        except OSError:
            pass
    return ""


def _deflate_bound(n):
    return n + (n >> 12) + (n >> 14) + (n >> 25) + 1024        # zlib's deflateBound, plus the entry's headers


def _deflated_size(data):
    c = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
    return len(c.compress(data)) + len(c.flush())


def utc_offset_min():
    """This PC's offset from UTC now, in minutes (local = UTC + offset)."""
    try:
        return int(time.localtime().tm_gmtoff or 0) // 60
    except Exception:
        return 0


class Parts(object):
    """part001.zip, part002.zip, ... in `folder`, each at most `limit` bytes: entries are streamed in, and meta.json is
    added to every part at the end, when the number of parts is known."""

    def __init__(self, folder, limit=PART_LIMIT, common=None):
        if limit < RESERVE + MARGIN + _deflate_bound(MAX_BLOCK) + 64 * 1024 or limit > MAX_UPLOAD:
            raise ValueError("a part of %d bytes cannot hold a block (at least %d, at most %d)"
                             % (limit, RESERVE + MARGIN + _deflate_bound(MAX_BLOCK) + 64 * 1024, MAX_UPLOAD))
        self.folder, self.limit = folder, limit
        self.common = dict(common or {})
        self.paths, self.metas = [], []
        self.fp = self.z = None

    def _new(self):
        self._close()
        p = os.path.join(self.folder, "part%03d.zip" % (len(self.paths) + 1))
        self.fp = open(p, "w+b")
        self.z = zipfile.ZipFile(self.fp, "w", zipfile.ZIP_DEFLATED)
        self.paths.append(p)
        self.metas.append([])

    def _close(self):
        if self.z is not None:
            self.z.close()
            self.fp.close()
            self.z = self.fp = None

    def room(self):
        """Bytes still free in the current part (a fresh part's when none is open)."""
        if self.z is None:
            return self.limit - RESERVE
        return self.limit - RESERVE - self.fp.tell()

    @staticmethod
    def _info(name):
        zi = zipfile.ZipInfo(name, date_time=ZIP_DATE)
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = 0o600 << 16
        return zi

    def fits_empty(self, size_z):
        return size_z <= self.limit - RESERVE

    def put(self, name, data, meta, size_z=None):
        """A whole entry, in the current part or a new one; in chunks when it cannot fit even an empty part.
        size_z: its packed size (+ headers) if already known. Returns (size, [the meta entries made])."""
        size_z = _deflated_size(data) + 1024 if size_z is None else size_z
        if not self.fits_empty(size_z):
            return self.put_stream(name, (data[i:i + BLOCK] for i in range(0, len(data), BLOCK)), meta)
        if self.z is None or size_z > self.room():
            self._new()
        self.z.writestr(self._info(name), data)
        sha = hashlib.sha256(data).hexdigest()
        e = dict(meta)
        e.update({"zip_name": name, "offset": 0, "bytes": len(data), "sha256": sha, "chunk": 0, "last": True,
                  "file_bytes": len(data), "file_sha256": sha})
        self.metas[-1].append(e)
        return len(data), [e]

    def put_stream(self, base, blocks, meta):
        """A file given as an iterator of byte blocks, written as chunks <base>.chunkNNNN that fill the parts. Every
        chunk carries its offset and checksum; the last also the file's size and checksum. A block never exceeds
        MAX_BLOCK (longer ones are split), a chunk starts in a new part when its first block could not fit the current
        one, and a chunk ends before a block could push the part past its limit (or the chunk past CHUNK_RAW_MAX).
        Returns (the file's size, [the meta entries made])."""
        whole = hashlib.sha256()
        off, k = 0, 0
        it = _split_blocks(blocks, MAX_BLOCK)
        pending = next(it, None)
        made = []
        while True:
            if self.z is None or self.room() < MARGIN + _deflate_bound(len(pending) if pending is not None else 0):
                self._new()
            k += 1
            name = "%s.chunk%04d" % (base, k)
            h = hashlib.sha256()
            n = 0
            with self.z.open(self._info(name), "w") as w:
                while pending is not None:
                    if n and (self.room() < MARGIN + _deflate_bound(len(pending)) or n + len(pending) > CHUNK_RAW_MAX):
                        break
                    w.write(pending)
                    h.update(pending)
                    whole.update(pending)
                    n += len(pending)
                    pending = next(it, None)
            done = pending is None
            e = dict(meta)
            e.update({"zip_name": name, "offset": off, "bytes": n, "sha256": h.hexdigest(), "chunk": k, "last": done})
            off += n
            if done:
                e.update({"file_bytes": off, "file_sha256": whole.hexdigest()})
            self.metas[-1].append(e)
            made.append(e)
            if self.fp.tell() > self.limit:
                raise FulldiagError("internal: part %d overran its limit while writing %s" % (len(self.paths), name))
            if done:
                return off, made

    def finish(self):
        """meta.json into every part; returns the part paths. Each part is checked against the relay's limit."""
        self._close()
        n = len(self.paths)
        for i, (p, entries) in enumerate(zip(self.paths, self.metas), 1):
            meta = dict(self.common)
            meta.update({"part": i, "parts": n, "files": entries})
            with zipfile.ZipFile(p, "a", zipfile.ZIP_DEFLATED) as z:
                z.writestr(self._info("meta.json"), json.dumps(meta, indent=1, sort_keys=True))
            if os.path.getsize(p) > MAX_UPLOAD:
                raise FulldiagError("Part %d came out too large to upload (%.1f MB). Save the zips instead."
                                    % (i, os.path.getsize(p) / 1048576.0))
        return list(self.paths)

    def abort(self):
        try:
            self._close()
        except Exception:
            pass


def _split_blocks(blocks, maxlen):
    """The blocks, none empty, none longer than maxlen."""
    for b in blocks:
        for i in range(0, len(b), maxlen):
            yield b[i:i + maxlen]


def _text_blocks(path, size, scrub_line, changed):
    """A text file's first `size` bytes, line by line through scrub_line, in blocks of about BLOCK bytes that end at
    line ends; changed[0] becomes True when a line was changed."""
    buf, n = [], 0
    with open(path, "rb") as f:
        left = size
        while left > 0:
            line = f.readline(min(left, 1 << 24))
            if not line:
                break
            left -= len(line)
            out, ch = scrub_line(line)
            if ch:
                changed[0] = True
            buf.append(out)
            n += len(out)
            if n >= BLOCK:
                yield b"".join(buf)
                buf, n = [], 0
    if buf:
        yield b"".join(buf)


def _bin_blocks(path, size):
    with open(path, "rb") as f:
        left = size
        while left > 0:
            b = f.read(min(BLOCK, left))
            if not b:
                break
            left -= len(b)
            yield b


def _kind(name):
    if name == "session.json":
        return "session_json"
    if name.endswith(".jsonl"):
        return "jsonl"
    if name.endswith(TEXT_EXT):
        return "text"
    return "bin"


def _scrub_whole(kind, raw, sc):
    if kind == "session_json":
        return scrub_session_json(raw, sc)
    if kind == "jsonl":
        outs = [scrub_jsonl_line(l, sc) for l in raw.splitlines(True)]
        return b"".join(o for o, _c in outs), any(c for _o, c in outs)
    if kind == "text":
        return scrub_text(raw, sc)
    return raw, False


def put_file(parts, zip_name, path, size, kind, sc, meta):
    """One recording file into the parts (its first `size` bytes: as far as it was written when the send began):
    whole when it fits a part, else in chunks; text scrubbed on the way. Records 'scrubbed' in its entries. Returns
    the meta entries made."""
    if kind == "session_json" or size <= SMALL:
        with open(path, "rb") as f:
            raw = f.read(size)
        data, ch = _scrub_whole(kind, raw, sc)
        return parts.put(zip_name, data, dict(meta, scrubbed=ch))[1]
    changed = [False]
    if kind == "jsonl":
        blocks = _text_blocks(path, size, lambda l: scrub_jsonl_line(l, sc), changed)
    elif kind == "text":
        blocks = _text_blocks(path, size, lambda l: scrub_text(l, sc), changed)
    else:
        blocks = _bin_blocks(path, size)
    _n, made = parts.put_stream(zip_name, blocks, dict(meta, scrubbed=False))
    for e in made:                                   # only known once the whole file went through
        e["scrubbed"] = changed[0]
    return made


def run_collector(base_dir, game, out_dir, progress=None, timeout=COLLECTOR_TIMEOUT):
    """Diagnostics/brosdiag_collect.py for this game folder and checkout, its output followed line by line (progress
    gets each line). Returns (zip path or None, its whole output, exit code or None)."""
    p = os.path.join(base_dir, COLLECTOR)
    if not os.path.isfile(p):
        return None, "%s is not in this checkout" % COLLECTOR, None
    os.makedirs(out_dir, exist_ok=True)
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
    env = dict(os.environ, PYTHONIOENCODING="utf-8", GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    exe = sys.executable
    if os.name == "nt" and os.path.basename(exe).lower() == "pythonw.exe":
        cand = os.path.join(os.path.dirname(exe), "python.exe")
        exe = cand if os.path.isfile(cand) else exe
    lines = []
    try:
        proc = subprocess.Popen([exe, "-B", p, game, "--repo", base_dir, "--out", out_dir, "--no-pause"], cwd=out_dir,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, **kw)
    except OSError as e:
        return None, "the collector could not start: %s" % e, None
    killed = []

    def watchdog():
        if proc.poll() is None:
            killed.append(1)
            proc.kill()
    timer = threading.Timer(timeout, watchdog)
    timer.daemon = True
    timer.start()
    try:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            lines.append(line)
            if progress and line.strip():
                progress(line.strip())
        rc = proc.wait()
    finally:
        timer.cancel()
        try:
            proc.stdout.close()
        except Exception:
            pass
    if killed:
        lines.append("(stopped after %d s)" % timeout)
    zips = sorted(f for f in os.listdir(out_dir) if f.startswith("brosdiag_") and f.endswith(".zip"))
    return (os.path.join(out_dir, zips[-1]) if zips and not killed else None), "\n".join(lines), rc


README = """BROS advanced diagnostics (fulldiag) -- one send, in one or more parts

meta.json        this part: the send's batch id, part k of n, the player's comment, the PC's UTC offset in minutes,
                 and every entry in the part (its file, offset, size, sha256; a file cut into chunks: chunk k, the last
                 one with the whole file's size and sha256)
sessions/<UTC>Z_p<pid>/   one game start each, as fulldiag.dll wrote it (text files scrubbed of names, IDs and user
                 folders): session.json, modules.jsonl, events.jsonl, sys.jsonl, threads.jsonl, timing.bin, and per
                 battle e1_bNN.bin, fx_bNN.bin, bind_bNN.bin, prof_bNN.bin, prof_bNN_top.csv
launcher/        the launcher's snapshot taken at the launch before each session
machine/         Diagnostics/brosdiag_collect.py's report of this PC, made when the send was made (report.json,
                 inventory.tsv, files/: the patch's log, crash logs, the files beside the exe; scrubbed by the
                 collector; the tournament recordings left out)

Put the parts back together and read them with Diagnostics/fulldiag_read.py (join, then summary / frames / diff); the
record layouts are in Diagnostics/FULLDIAG_DATA.md.
"""


def pack(base_dir, game, selected, folder, comment="", report=True, progress=None, scrubber=None, part_limit=None):
    """Write the parts for the chosen sessions into `folder`. Returns (part paths, sent, batch) where sent =
    {session: {file: size packed}} for mark_sent(). progress(text) is called as it goes, from the calling thread."""
    def say(t):
        if progress:
            progress(t)
    sc = scrubber or make_scrubber(base_dir)
    batch = uuid.uuid4().hex
    os.makedirs(folder, exist_ok=True)
    common = {"format": BUNDLE_FORMAT, "batch": batch, "created_utc": _utc_iso(), "pc_utc_offset_min": utc_offset_min(),
              "launcher_commit": _git(base_dir, "rev-parse", "HEAD"), "comment": sc((comment or "").strip()[:4000], True),
              "relay_folder": "inbox/%s/" % TOURNAMENT, "sessions": [s["name"] for s in selected]}
    machine = {"included": False, "asked": bool(report)}
    tmp_collect = os.path.join(folder, "_collector")
    cz = None
    if report:
        say("Making a report of this PC (about two minutes)...")
        cz, clog, rc = run_collector(base_dir, game, tmp_collect, lambda l: say("Report of this PC: " + l[:90]))
        cp = os.path.join(base_dir, COLLECTOR)
        machine.update({"included": bool(cz), "exit": rc, "collector": COLLECTOR.replace(os.sep, "/"),
                        "collector_md5": _md5(cp) if os.path.isfile(cp) else None, "left_out": []})
    common["machine"] = machine
    parts = Parts(folder, part_limit or PART_LIMIT, common)
    sent = {}
    try:
        parts.put("README.txt", README.encode("utf-8"), {"kind": "readme", "name": "README.txt"})
        snaps = snapshots(game)
        for n in sorted(set(filter(None, (snapshot_for(s["stamp"], snaps) for s in selected)))):
            with open(os.path.join(data_dir(game), n), "rb") as f:
                d = f.read()
            parts.put("launcher/" + n, d, {"kind": "snapshot", "name": n})
        if report:
            if cz:
                with zipfile.ZipFile(cz) as zin:
                    for zi in zin.infolist():
                        if zi.filename.endswith("/"):
                            continue
                        if zi.filename.replace("\\", "/").lower().startswith("files/bros_diagnostics/"):
                            machine["left_out"].append(zi.filename)
                            continue
                        parts.put("machine/" + zi.filename, zin.read(zi), {"kind": "machine", "name": zi.filename})
            parts.put("machine/collector_output.txt", sc(clog, True).encode("utf-8"), {"kind": "machine", "name": "collector_output.txt"})
        for i, s in enumerate(selected, 1):
            files = _session_files(s["path"])
            sent[s["name"]] = files
            for fname, size in sorted(files.items()):
                say("Packing recording %d of %d: %s (%s)..." % (i, len(selected), fname, human(size)))
                put_file(parts, "sessions/%s/%s" % (s["name"], fname), os.path.join(s["path"], fname), size, _kind(fname), sc,
                         {"kind": "session", "session": s["name"], "name": fname})
        say("Finishing the zips...")
        paths = parts.finish()
    except Exception:
        parts.abort()
        raise
    finally:
        shutil.rmtree(tmp_collect, ignore_errors=True)
    return paths, sent, batch


def mark_sent(game, sent, batch, receipts):
    """sent: {session: {file: size sent}}. Writes each session's marker; a session written to after this is offered
    again."""
    for sname, files in sent.items():
        p = os.path.join(data_dir(game), sname)
        if not os.path.isdir(p):
            continue
        rec = {"files": files, "batch": batch, "receipts": receipts, "utc": _utc_iso()}
        try:
            _write(os.path.join(p, SENT_MARK), json.dumps(rec, indent=1).encode("utf-8"))
        except OSError:
            pass


def _diagnostics_module():
    """launcher/diagnostics.py from this module's own folder (its upload(): the relay's protocol and answers)."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diagnostics.py")
    if os.path.isfile(p):
        spec = importlib.util.spec_from_file_location("bros_diagnostics_for_fulldiag", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    from launcher import diagnostics as d
    return d


def upload_parts(paths, url, progress=None):
    """Every part to the relay, in order, as tournament "fulldiag". Returns the receipts; raises FulldiagError saying
    how many got through (nothing is then marked sent; the next Send sends everything again)."""
    d = _diagnostics_module()
    receipts = []
    for i, p in enumerate(paths, 1):
        if progress:
            progress("Sending part %d of %d..." % (i, len(paths)))
        with open(p, "rb") as f:
            b = f.read()
        try:
            receipts.append(d.upload(b, url, TOURNAMENT))
        except Exception as e:
            raise FulldiagError(("Part %d of %d did not get through: %s" % (i, len(paths), e)) if len(paths) > 1 else str(e))
    return receipts


def desktop_dir():
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and os.path.isdir(buf.value):
                return buf.value
        except Exception:
            pass
    d = os.path.join(os.path.expanduser("~"), "Desktop")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def save_parts(paths, folder=None):
    """Copy the parts to `folder` (the Desktop) as BROS_fulldiag_<UTC>_part<k>of<n>.zip; returns the new paths."""
    folder = folder or desktop_dir()
    os.makedirs(folder, exist_ok=True)
    stamp = _utc_stamp()
    out = []
    for i, p in enumerate(paths, 1):
        dst = os.path.join(folder, "BROS_fulldiag_%s_part%dof%d.zip" % (stamp, i, len(paths)))
        shutil.copyfile(p, dst + ".tmp")
        os.replace(dst + ".tmp", dst)
        out.append(dst)
    return out


def check_space(game, selected):
    """Raise FulldiagError when the drive holding the recordings has too little room to make the parts."""
    need = 512 * 1024 * 1024 + sum(s["bytes"] for s in selected) // 2
    try:
        free = shutil.disk_usage(data_dir(game) if os.path.isdir(data_dir(game)) else game).free
    except OSError:
        return
    if free < need:
        raise FulldiagError("Not enough free space to make the zips: %s free, about %s needed. Free some space, or send "
                            "fewer recordings." % (human(free), human(need)))


def clean_send_tmp(game, older_than=3600):
    """After a send: remove what earlier, interrupted sends left in BROS_FullDiag\\_send_tmp\\ (folders not written to
    for an hour -- a send running in another launcher window is left alone), and the folder itself once empty."""
    d = os.path.join(data_dir(game), SEND_TMP)
    if not os.path.isdir(d):
        return
    now = time.time()
    for n in os.listdir(d):
        p = os.path.join(d, n)
        try:
            newest = max([os.path.getmtime(os.path.join(dp, f)) for dp, _dn, fn in os.walk(p) for f in fn] + [os.path.getmtime(p)])
        except OSError:
            continue
        if now - newest > older_than:
            shutil.rmtree(p, ignore_errors=True)
    try:
        os.rmdir(d)
    except OSError:
        pass


# =====================================================================================================================
# The dialogs (tkinter; the launcher's theme passed in)
# =====================================================================================================================

CONSENT = (
    "Advanced diagnostics record everything a game session does on this PC, so a difference between two PCs, a "
    "move that works when it should not (or the reverse), or a stutter can be traced to its cause.\n\n"
    "What is included: every battle frame of both fighters (moves, the commands each executed, gauges, positions); "
    "your pad and keyboard state per frame and your button bindings; the timing of every frame and where slow frames "
    "spent their time; this PC's CPU, memory, disk and display state once a second; every thread and module in the "
    "game (file names, versions, checksums); the launcher's settings; and a report of this PC (Windows, CPU, GPU, "
    "displays, language and number format, controllers, Steam Input, the patch files' checksums, the patch's log and "
    "crash logs). The logs keep your PC's clock, so the send shows your time zone.\n\n"
    "What is NOT included: your name, Steam name or Steam ID, IP address, your folders' names, or any program "
    "outside a fixed list of tools that change input, overlays or frame pacing. These are removed before anything "
    "is packed.\n\n"
    "It is stored privately for the patch developers, in its own folder apart from the tournament data. Nothing is "
    "sent until you click Send.")


def _theme(theme):
    th = {"bg": "#241129", "panel": "#2e1736", "fg": "#f1e4f5", "muted": "#b9a3c4", "gold": "#e6b450",
          "button_bg": "#3a2144", "font": ("Segoe UI", 10), "small": ("Segoe UI", 9), "title": ("Segoe UI", 13, "bold")}
    th.update(theme or {})
    return th


def _place(win, parent):
    win.update_idletasks()
    try:
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - win.winfo_reqwidth()) // 2)
        y = parent.winfo_rooty() + 30
        win.geometry("+%d+%d" % (x, y))
    except Exception:
        pass


def session_line(s):
    return "%s   %9s   %s%s" % (s["start"], human(s["bytes"]),
                                 {"yes": "sent", "no": "not sent", "grown": "grown since it was sent"}[s["sent"]],
                                 "" if s["complete"] else ("   (still being written)" if s["recent"] else "   (ended abruptly)"))


def open_send_dialog(parent, base_dir, game, theme=None, on_done=None):
    """The "Send advanced diagnostics" window (modal)."""
    import tkinter as tk
    from tkinter import messagebox
    th = _theme(theme)
    url = relay_url(base_dir)
    pend = [s for s in sessions(game) if s["sent"] != "yes"]
    win = tk.Toplevel(parent)
    win.title("Send advanced diagnostics")
    win.configure(bg=th["bg"])
    win.transient(parent)
    win.resizable(False, False)
    pad = {"padx": 14}
    tk.Label(win, text="Send advanced diagnostics", font=th["title"], bg=th["bg"], fg=th["gold"]).pack(anchor="w", pady=(12, 4), **pad)
    tk.Label(win, text=CONSENT, font=th["small"], bg=th["bg"], fg=th["fg"], wraplength=560, justify="left").pack(anchor="w", **pad)
    box = tk.Frame(win, bg=th["panel"], padx=10, pady=6)
    box.pack(fill="x", pady=(10, 6), **pad)
    lb = None
    total = tk.Label(box, text="", font=th["small"], bg=th["panel"], fg=th["muted"], justify="left", wraplength=540)
    if pend:
        tk.Label(box, text="Recordings to send (click one to leave it out):", font=th["small"], bg=th["panel"], fg=th["gold"]).pack(anchor="w")
        lb = tk.Listbox(box, selectmode="multiple", height=min(8, len(pend)), width=78, font=th["small"], bg=th["panel"],
                        fg=th["fg"], selectbackground=th["gold"], selectforeground="#241129", highlightthickness=0,
                        borderwidth=0, activestyle="none", exportselection=False)
        for s in pend:
            lb.insert("end", session_line(s))
        lb.select_set(0, "end")
        lb.pack(anchor="w", fill="x")
        total.pack(anchor="w", pady=(4, 0))
    else:
        tk.Label(box, text="No recording is waiting to be sent.", font=th["small"], bg=th["panel"], fg=th["muted"]).pack(anchor="w")
    tk.Label(win, text="What happened? Which character, what you pressed, what you expected (optional):", font=th["small"],
             bg=th["bg"], fg=th["muted"]).pack(anchor="w", **pad)
    comment = tk.Text(win, height=4, width=70, font=th["small"], wrap="word")
    comment.pack(anchor="w", **pad)
    status = tk.Label(win, text="" if url else "No upload address is set: you can save the zips and send them by hand.",
                      font=th["small"], bg=th["bg"], fg=th["muted"], wraplength=560, justify="left")
    status.pack(anchor="w", pady=(8, 2), **pad)
    buttons = tk.Frame(win, bg=th["bg"])
    buttons.pack(fill="x", pady=(4, 12), **pad)
    state = {"busy": False, "result": None, "progress": "", "done": False}

    def chosen():
        return [pend[i] for i in lb.curselection()] if lb is not None else []

    def set_busy(b):
        state["busy"] = b
        for w in (send_btn, save_btn, close_btn):
            w.config(state="disabled" if b else "normal")
        if state["done"] or not chosen():
            send_btn.config(state="disabled")
            save_btn.config(state="disabled")
        if not url:
            send_btn.config(state="disabled")

    def refresh_total(_e=None):
        if lb is None:
            return
        c = chosen()
        total.config(text="%d of %d chosen, %s before packing. A report of this PC is made first (about two minutes); "
                          "the zips are sent in parts of about 8 MB." % (len(c), len(pend), human(sum(s["bytes"] for s in c))))
        set_busy(state["busy"])

    def poll():
        r = state["result"]
        if r is None:
            if state["progress"]:
                status.config(text=state["progress"], fg=th["muted"])
            win.after(200, poll)
            return
        state["result"] = None
        kind, value, sent, batch = r
        if kind in ("sent", "saved"):
            state["done"] = True
            mark_sent(game, sent, batch, value if kind == "sent" else ["saved: " + os.path.basename(v) for v in value])
            if kind == "sent":
                status.config(text="Sent -- thank you! %d part%s, receipt%s: %s" % (
                    len(value), "" if len(value) == 1 else "s", "" if len(value) == 1 else "s", ", ".join(value)), fg=th["gold"])
            else:
                status.config(text="Saved %d zip%s to %s -- please send %s to Berg on Discord." % (
                    len(value), "" if len(value) == 1 else "s", os.path.dirname(value[0]), "it" if len(value) == 1 else "them all"),
                    fg=th["gold"])
        else:
            status.config(text=value, fg="#ff8a80")
            if lb is not None:
                lb.config(state="normal")
        set_busy(False)

    def work(action, note, picked):
        # A worker thread: no tkinter object is touched here (Tk is single-threaded); progress goes through state.
        batch_dir = os.path.join(data_dir(game), SEND_TMP, uuid.uuid4().hex[:12])
        try:
            check_space(game, picked)

            def prog(t):
                state["progress"] = t
            paths, sent, batch = pack(base_dir, game, picked, batch_dir, note, progress=prog)
            if action == "send":
                state["result"] = ("sent", upload_parts(paths, url, prog), sent, batch)
            else:
                state["progress"] = "Copying the zips to the Desktop..."
                state["result"] = ("saved", save_parts(paths), sent, batch)
        except FulldiagError as e:
            state["result"] = ("error", str(e), None, None)
        except Exception as e:
            state["result"] = ("error", "Something went wrong (%s). Save the zips instead." % e, None, None)
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)
            clean_send_tmp(game)

    def start(action):
        if state["busy"]:
            return
        picked = chosen()
        if not picked:
            return
        size = sum(s["bytes"] for s in picked)
        if size > BIG_SEND and not messagebox.askyesno(
                "Send advanced diagnostics",
                "This is a large send: %s before packing, %d recordings. It takes a long time and fills the patch team's "
                "storage. Send all of it?\n\n(Click No, then leave some out to send less.)" % (human(size), len(picked)),
                parent=win):
            return
        set_busy(True)
        state["progress"] = ""
        status.config(text="Working...", fg=th["muted"])
        if lb is not None:
            lb.config(state="disabled")
        threading.Thread(target=work, args=(action, comment.get("1.0", "end"), picked), daemon=True).start()
        win.after(200, poll)

    def close():
        if state["busy"]:
            return
        win.grab_release()
        win.destroy()
        if on_done:
            try:
                on_done()
            except Exception:
                pass

    send_btn = tk.Button(buttons, text="Send", font=th["font"], bg=th["gold"], fg="#241129", relief="flat", padx=16, pady=4,
                         command=lambda: start("send"))
    save_btn = tk.Button(buttons, text="Save zips to Desktop", font=th["font"], bg=th["button_bg"], fg=th["fg"], relief="flat",
                         padx=12, pady=4, command=lambda: start("save"))
    close_btn = tk.Button(buttons, text="Close", font=th["font"], bg=th["button_bg"], fg=th["fg"], relief="flat", padx=12, pady=4,
                          command=close)
    send_btn.pack(side="left")
    save_btn.pack(side="left", padx=8)
    close_btn.pack(side="right")
    if lb is not None:
        lb.bind("<<ListboxSelect>>", refresh_total)
    refresh_total()
    set_busy(False)
    win.protocol("WM_DELETE_WINDOW", close)
    _place(win, parent)
    win.grab_set()
    return win


def open_delete_dialog(parent, base_dir, game, theme=None, on_done=None):
    """"Delete older recordings...": every session with its size and whether it was sent; keeps the newest N (1 by
    default) and deletes the others after a confirmation. Nothing is deleted without it."""
    import tkinter as tk
    from tkinter import messagebox
    th = _theme(theme)
    ss = sessions(game)
    win = tk.Toplevel(parent)
    win.title("Delete older recordings")
    win.configure(bg=th["bg"])
    win.transient(parent)
    win.resizable(False, False)
    pad = {"padx": 14}
    tk.Label(win, text="Delete older recordings", font=th["title"], bg=th["bg"], fg=th["gold"]).pack(anchor="w", pady=(12, 4), **pad)
    box = tk.Frame(win, bg=th["panel"], padx=10, pady=6)
    box.pack(fill="x", pady=(6, 6), **pad)
    if not ss:
        tk.Label(box, text="There are no recordings on this PC.", font=th["small"], bg=th["panel"], fg=th["muted"]).pack(anchor="w")
    for s in reversed(ss[-20:]):
        tk.Label(box, text="  " + session_line(s), font=th["small"], bg=th["panel"],
                 fg=th["fg"] if s["sent"] == "yes" else th["gold"]).pack(anchor="w")
    if len(ss) > 20:
        tk.Label(box, text="  ... and %d older" % (len(ss) - 20), font=th["small"], bg=th["panel"], fg=th["muted"]).pack(anchor="w")
    row = tk.Frame(win, bg=th["bg"])
    row.pack(fill="x", pady=(4, 4), **pad)
    tk.Label(row, text="Keep the newest", font=th["small"], bg=th["bg"], fg=th["fg"]).pack(side="left")
    keep = tk.Spinbox(row, from_=0, to=max(1, len(ss)), width=4, font=th["small"])
    keep.delete(0, "end")
    keep.insert(0, "1")
    keep.pack(side="left", padx=6)
    tk.Label(row, text="recording(s) and delete the older ones.", font=th["small"], bg=th["bg"], fg=th["fg"]).pack(side="left")
    status = tk.Label(win, text="", font=th["small"], bg=th["bg"], fg=th["muted"], wraplength=540, justify="left")
    status.pack(anchor="w", pady=(4, 2), **pad)
    buttons = tk.Frame(win, bg=th["bg"])
    buttons.pack(fill="x", pady=(4, 12), **pad)

    def do_delete():
        try:
            n = int(keep.get())
            if n < 0:
                raise ValueError
        except ValueError:
            status.config(text="Type how many recordings to keep (0 or more).", fg="#ff8a80")
            return
        victims = ss[:max(0, len(ss) - n)]
        if not victims:
            status.config(text="Nothing to delete with that setting.", fg=th["muted"])
            return
        unsent = [s for s in victims if s["sent"] != "yes"]
        msg = "Delete %d recording%s (%s)? This cannot be undone.%s" % (
            len(victims), "" if len(victims) == 1 else "s", human(sum(s["bytes"] for s in victims)),
            ("\n\n%d of them %s never been sent." % (len(unsent), "has" if len(unsent) == 1 else "have")) if unsent else "")
        if not messagebox.askyesno("Delete older recordings", msg, parent=win):
            return
        done, freed, kept, snaps = delete_sessions(game, [s["name"] for s in victims])
        status.config(text="Deleted %d recording%s%s, %s freed.%s" % (
            len(done), "" if len(done) == 1 else "s", (" and %d launcher snapshot%s" % (snaps, "" if snaps == 1 else "s")) if snaps else "",
            human(freed), (" Not deleted: " + "; ".join("%s (%s)" % k for k in kept)) if kept else ""), fg=th["gold"])
        del_btn.config(state="disabled")

    def close():
        win.grab_release()
        win.destroy()
        if on_done:
            try:
                on_done()
            except Exception:
                pass

    del_btn = tk.Button(buttons, text="Delete", font=th["font"], bg=th["gold"], fg="#241129", relief="flat", padx=16, pady=4,
                        command=do_delete, state="normal" if ss else "disabled")
    close_btn = tk.Button(buttons, text="Close", font=th["font"], bg=th["button_bg"], fg=th["fg"], relief="flat", padx=12, pady=4,
                          command=close)
    del_btn.pack(side="left")
    close_btn.pack(side="right")
    win.protocol("WM_DELETE_WINDOW", close)
    _place(win, parent)
    win.grab_set()
    return win


def open_folder(game):
    d = data_dir(game)
    os.makedirs(d, exist_ok=True)
    if os.name == "nt":
        os.startfile(d)                           # noqa: the launcher runs on Windows
    else:
        _run(["xdg-open", d])
    return d


# =====================================================================================================================
# By hand
# =====================================================================================================================

def _repo_json():
    j = os.path.join(REPO, "Json")
    return j if os.path.isdir(j) else None


def default_game():
    j = _repo_json()
    if j:
        try:
            with open(os.path.join(j, "config.json"), "r", encoding="utf-8") as f:
                g = json.load(f).get("GAME_PATH", "")
            if g and os.path.isdir(g):
                return g
        except Exception:
            pass
    return r"D:\SteamLibrary\steamapps\common\BLEACH Rebirth of Souls"


def main(argv):
    argv = list(argv)
    out = None
    if "--out" in argv:
        i = argv.index("--out")
        if i + 1 >= len(argv):
            print(__doc__)
            return 2
        out = argv[i + 1]
        del argv[i:i + 2]
    report = "--no-report" not in argv
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args or args[0] not in ("status", "on", "off", "pack"):
        print(__doc__)
        return 2
    game = args[1] if len(args) > 1 else default_game()
    if not os.path.isdir(game):
        print("no such folder: %s -- pass the game folder" % game)
        return 2
    if args[0] == "status":
        state, cfg, _raw = current(game)
        print("game folder: %s%s" % (game, "" if is_game(game) else "   !! %s not found here" % EXE))
        print("  %s: %s -> the next game start records: %s" % (NAME, state, "YES" if cfg["on"] else "no"))
        print("  %s installed: %s" % (PLUGIN, "yes" if os.path.isfile(os.path.join(game, PLUGIN)) else "NO"))
        if _repo_json():
            print("  the launcher's switch: %s" % ("ON" if load_choice(REPO) else "OFF"))
        print("  relay address: %s" % ("set" if relay_url(REPO) else "(none set)"))
        for s in sessions(game):
            print("  %s  %s" % (s["name"], session_line(s)))
        return 0
    if args[0] in ("on", "off"):
        if not is_game(game):
            print("NOTHING CHANGED: %s is not the game folder (no %s)" % (game, EXE))
            return 1
        try:
            if _repo_json():
                print("[fulldiag] " + set_choice(REPO, game, args[0] == "on"))
            else:
                print("[fulldiag] " + apply(game, args[0] == "on"))
        except FulldiagError as e:
            print("NOTHING CHANGED: %s" % e)
            return 1
        return 0
    pend = [s for s in sessions(game) if s["sent"] != "yes"]
    if not pend:
        print("no recording waiting to be sent")
        return 0
    try:
        check_space(game, pend)
    except FulldiagError as e:
        print(e)
        return 1
    batch_dir = os.path.join(data_dir(game), SEND_TMP, uuid.uuid4().hex[:12])
    try:
        paths, _sent, _batch = pack(REPO, game, pend, batch_dir, "", report=report, progress=lambda t: print("  " + t))
        for p in save_parts(paths, out):
            print("wrote %s" % p)
    finally:
        shutil.rmtree(batch_dir, ignore_errors=True)
        clean_send_tmp(game)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
