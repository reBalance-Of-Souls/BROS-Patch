"""content_pool.py -- the online pool of the Dev Community Patch and the public beta, made from what is installed.

THE SAME FILE SITS IN BOTH REPOSITORIES (Dev Environment and BROS-Patch, launcher/content_pool.py), byte for byte.
Change one, change both, and bump FORMAT.

WHY (Berg, 2026-10-24: "make sure that there would be no chance of desync between public beta and dev patch CP")
  The public beta ("Zangetsu Beta (dev build)", BROS-Patch launcher/beta.py) is the Dev launcher's install of the
  version "Bleach Rebirth of Souls Community Patch", captured and encrypted. Since 2026-10-16 the two shared ONE fixed
  pool, 603966. A fixed pool also pairs DIFFERENT builds -- a beta built before a Dev push, a Dev player with Team
  Battle on or the Zangetsu switch off -- and where those differ, a match desyncs.
  Now both launchers derive the code from the installed game itself, with this one function: the same content gives
  the same code, so testers and Dev players still meet; any difference gives another code, so they never meet, and a
  match between two different builds cannot happen.

WHAT COUNTS (FORMAT 1): everything that decides what happens in a match
  Script/**  Motion/**  Demo/**  Fnames/**          every file, recursively (Demo: a cutscene's length is game time)
  dinput8.dll                                         the loader
  ReBalanceOfSouls/*.dll  ReBalanceOfSouls/*.txt      the plugins the loader loads, and the rule files they read
  bros_*.txt  pl005_stacks.txt   (beside the exe)     the switches and data files the loader and plugins read
                                                      (bros_zangetsu.txt: manual Reawakening; bros_tools.txt: BRoS
                                                      Studio; the roster markers; bros_pl015_rework.txt)
  except, by name: what the game never loads -- dev leftovers (launcher/layers.py's rule: *.bak, *_bak, "name (2).ext",
  *.bat, *.py, thumbs.db, desktop.ini, .git*), work products (*_modded*, *.tmp, *~, *.off, *.orig, *.log), the
  fsv2csv dumps at the top of Script/ (Script/<name>.csv; the game's own .csv live in Script/ObjectConfig/), and
  ReBalanceOfSouls/studio.dll (BRoS Studio: a developer tool, inert unless bros_tools.txt arms it, which counts).
  Left out on purpose: bros_net.txt (each launcher's own network pacing), bros_diag.txt (the recorder),
  patch_ranked.txt (this code), and the Effect, sound, model, UI and text trees (looks, not rules; a player's effect
  choices write into Effect/).

THE CODE
  each file:   "<path, lower case, />\\0<sha256 of the bytes>\\n", sorted by path
  digest:      sha256("BROS-CONTENT-POOL\\0" FORMAT "\\n" + those lines)
  code:        100000 + (first 8 bytes of the digest, big endian) % 800000   -- the range of every other pool
  The loader adds ROOM3's +4003 when it makes the lobby tag, as for any code.

SPEED  Every file is read once; after that a cache beside the exe (launcher_content_pool.json) keeps each file's
  size, modification time and sha256, and a file whose size and time are unchanged is not read again. The installers
  (robocopy, copy2, the beta's decryption) give a changed file a new time.

  python launcher/content_pool.py <game folder>            the code, and how many files went into it
  python launcher/content_pool.py <game folder> --list     every counted file with its sha256
"""

import hashlib
import json
import os
import re
import sys

FORMAT = 1
CACHE_NAME = "launcher_content_pool.json"
CODE_FILE = "patch_ranked.txt"
TREES = ("script", "motion", "demo", "fnames")
PLUGINS = "rebalanceofsouls"
ROOT_EXACT = ("dinput8.dll", "pl005_stacks.txt")
ROOT_NOT = ("bros_net.txt", "bros_diag.txt")
_ROOT_RX = re.compile(r"bros_[^/]*\.txt\Z")
_SKIP_EXACT = {"thumbs.db", "desktop.ini", ".gitkeep", ".gitignore", ".ds_store"}
_SKIP_RX = (
    re.compile(r"\.bak$", re.I),
    re.compile(r"_bak$", re.I),
    re.compile(r"\s\(\d+\)\.", re.I),
    re.compile(r"\.(bat|py)(\s|$)", re.I),
    re.compile(r"_modded", re.I),
    re.compile(r"\.(tmp|off|orig|log)$", re.I),
    re.compile(r"~$"),
)
_PLUGIN_SKIP = ("studio.dll",)


class PoolError(Exception):
    """The code could not be made or written. A launcher must not start the game on this."""


def _skipped_name(name):
    low = name.lower()
    return low in _SKIP_EXACT or any(r.search(name) for r in _SKIP_RX)


def counts(rel):
    """True when a game-relative path ('/'-separated) is part of the pool's content."""
    low = rel.replace("\\", "/").strip("/").lower()
    parts = low.split("/")
    name = parts[-1]
    if _skipped_name(name):
        return False
    if len(parts) == 1:
        return low in ROOT_EXACT or (bool(_ROOT_RX.match(low)) and low not in ROOT_NOT)
    if parts[0] in TREES:
        if parts[0] == "script" and len(parts) == 2 and name.endswith(".csv"):
            return False                     # fsv2csv dumps; the game's own .csv are under Script/ObjectConfig/
        return True
    if parts[0] == PLUGINS and len(parts) == 2:
        return (name.endswith(".dll") and name not in _PLUGIN_SKIP) or name.endswith(".txt")
    return False


def _walk(game):
    """Every counted file: {lower-case rel: real path}."""
    out = {}
    try:
        top = os.listdir(game)
    except OSError as e:
        raise PoolError("the game folder cannot be read (%s)" % e)
    for n in top:
        full = os.path.join(game, n)
        low = n.lower()
        if os.path.isfile(full):
            if counts(n):
                out[low] = full
        elif os.path.isdir(full) and (low in TREES or low == PLUGINS):
            for dp, dn, fn in os.walk(full):
                dn.sort()
                for f in fn:
                    p = os.path.join(dp, f)
                    rel = os.path.relpath(p, game).replace(os.sep, "/")
                    if counts(rel):
                        out[rel.lower()] = p
    return out


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _load_cache(game):
    try:
        with open(os.path.join(game, CACHE_NAME), "r", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("format") == FORMAT and isinstance(d.get("files"), dict):
            return d["files"]
    except Exception:
        pass
    return {}


def _save_cache(game, files):
    path = os.path.join(game, CACHE_NAME)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"format": FORMAT, "files": files}, f, separators=(",", ":"), sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass                              # a cache that cannot be written only costs time next launch


def entries(game, use_cache=True):
    """[(lower-case rel, sha256)] of every counted file, sorted."""
    found = _walk(game)
    cache = _load_cache(game) if use_cache else {}
    new = {}
    out = []
    for rel in sorted(found):
        p = found[rel]
        try:
            st = os.stat(p)
        except OSError as e:
            raise PoolError("%s cannot be read (%s)" % (rel, e))
        c = cache.get(rel)
        if c and c[0] == st.st_size and c[1] == st.st_mtime_ns and isinstance(c[2], str) and len(c[2]) == 64:
            d = c[2]
        else:
            try:
                d = _sha256(p)
            except OSError as e:
                raise PoolError("%s cannot be read (%s)" % (rel, e))
        new[rel] = [st.st_size, st.st_mtime_ns, d]
        out.append((rel, d))
    if use_cache:
        _save_cache(game, new)
    return out


def digest(ents):
    h = hashlib.sha256(b"BROS-CONTENT-POOL\0%d\n" % FORMAT)
    for rel, d in ents:
        h.update(rel.encode("utf-8") + b"\0" + d.encode("ascii") + b"\n")
    return h.hexdigest()


def code_of(hexdigest):
    return 100000 + int(hexdigest[:16], 16) % 800000


def code(game, use_cache=True):
    """(code, number of files counted, digest)."""
    ents = entries(game, use_cache)
    if not ents:
        raise PoolError("nothing to count in %s: is it the game folder?" % game)
    d = digest(ents)
    return code_of(d), len(ents), d


def write_code(game, use_cache=True):
    """Make the code and write it to patch_ranked.txt (through a .tmp file, then read back). Returns (code, n, digest).
    Raises PoolError: the caller must then not start the game."""
    c, n, d = code(game, use_cache)
    path = os.path.join(game, CODE_FILE)
    tmp = path + ".tmp"
    data = b"%d\n" % c
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        with open(path, "rb") as f:
            back = f.read()
    except OSError as e:
        raise PoolError("could not write %s (%s)" % (path, e))
    if back != data:
        raise PoolError("%s did not read back as written" % path)
    return c, n, d


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    game = argv[0]
    ents = entries(game, use_cache=False)
    d = digest(ents)
    if "--list" in argv:
        for rel, h in ents:
            print("%s  %s" % (h, rel))
    print("content pool %d  (%d files, digest %s, format %d)" % (code_of(d), len(ents), d[:16], FORMAT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
