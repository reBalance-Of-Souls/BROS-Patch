"""content_pool.py -- the online pool of ReBalance of Souls (Dev launcher) and its public beta, made from what is
installed.

THE SAME FILE SITS IN BOTH REPOSITORIES (Dev Environment and BROS-Patch, launcher/content_pool.py), byte for byte.
Change one, change both, bump FORMAT, and change online.dll's twin (Files/Matchmaking/online_pool.c, the plugin's
folder check) so that the same test vectors still agree (launcher/tests: test_content_pool2.py; the plugin's test
t_online_pool.py, MATCHFIND 2026-11-06).

WHY (Berg, 2026-10-24: "make sure that there would be no chance of desync between public beta and dev patch CP")
  The public beta ("ReBalance of Souls V1.5 (beta)", BROS-Patch launcher/beta.py) is the Dev launcher's install of
  "ReBalance of Souls V1.5", captured and encrypted. A fixed shared pool (603966, 2026-10-16) also paired DIFFERENT
  builds, and where those differ a match desyncs. So both launchers derive the code from the installed game itself,
  with this one function: the same content gives the same code; any difference gives another code, so two different
  builds never meet.

WHY FORMAT 2 (Berg, 2026-11-06: "a lot of time even people on the same build ... can't find each other";
  MATCHFIND_2026-11-06, hist mf002 / mf008)
  FORMAT 1 counted every file under Demo/, also files nothing reads. Installs never delete a file another version
  created (the Dev launcher's install_overlay and the beta's install keep such "orphans"), so two PCs on the SAME
  build got different codes. Proven on Berg's PC: seven pl009 demos of 2026-07-23, in no version and in no registry,
  gave 102652 where a clean install of the same commit gives 787458. FORMAT 2 counts under Demo/ only what the game
  can read (listed in the installed Fnames/file_exist.htable -- an unregistered demo is inert, zh002) or what this
  launch installed (the plan, which keeps a build's own unregistered demos counted). Script/ and Motion/ are mirrored
  at every launch (robocopy /MIR semantics, in both launchers), so nothing can linger there. And the game exe itself is
  counted: two different Steam builds of the game never share a pool.

WHAT COUNTS (FORMAT 2): everything that decides what happens in a match
  <exe>                                              BLEACH_Rebirth_of_Souls.exe's sha256, as its own first line
  Script/**  Motion/**  Fnames/**                    every file, recursively
  Demo/**                                            a file listed in Fnames/file_exist.htable, or one in the plan
                                                     (a cutscene's length is game time)
  dinput8.dll                                        the loader
  ReBalanceOfSouls/*.dll  ReBalanceOfSouls/*.txt     the plugins the loader loads, and the rule files they read
  bros_*.txt  pl005_stacks.txt   (beside the exe)    the switches and data files the loader and plugins read
                                                     (bros_zangetsu.txt: manual Reawakening; bros_tools.txt: BRoS
                                                     Studio; the roster markers; bros_pl015_rework.txt)
  except, by name: what the game never loads -- dev leftovers (launcher/layers.py's rule: *.bak, *_bak, "name (2).ext",
  *.bat, *.py, thumbs.db, desktop.ini, .git*), work products (*_modded*, *.tmp, *~, *.off, *.orig, *.log), the
  fsv2csv dumps at the top of Script/ (Script/<name>.csv; the game's own .csv live in Script/ObjectConfig/), and
  ReBalanceOfSouls/studio.dll (BRoS Studio: a developer tool, inert unless bros_tools.txt arms it, which counts).
  Left out on purpose: bros_net.txt (each launcher's own network pacing), bros_diag.txt (the recorder),
  patch_ranked.txt (this code), and the Effect, sound, model, UI and text trees (looks, not rules; a player's effect
  choices write into Effect/).

REGISTERED  A demo's game path is "Demo\\<path under Demo, backslashes>"; it is registered when the htable holds
  crc(path) -- crc = zlib.crc32(b, len(b) ^ 0xFFFFFFFF) ^ 0xFFFFFFFF over the UTF-8 bytes -- for the path with the
  file's own case or all in lower case (the folder written "Demo" either way). The htable: u32 count, then count
  pairs (crc of the path, crc of the folder).

THE PLAN  The game-relative paths this launch installed under Demo/ (Dev launcher: install_guard's record of the
  launch; beta: its manifest). Kept in the cache; a call without a plan uses the cache's.

THE CODE
  first line:  "<exe>\\0<sha256 of the exe>\\n"
  each file:   "<path, lower case, />\\0<sha256 of the bytes>\\n", sorted by path
  a game mode: "<mode>\\0<its name>\\n" after the first line, for any mode but DEFAULT (a mode armed only at run
               time -- BROS_GAME_MODE, a plugin's switch -- changes no file, and its players must never meet DEFAULT
               players: before FORMAT 2 the launcher's seed carried the mode for exactly this reason)
  digest:      sha256("BROS-CONTENT-POOL\\0" FORMAT "\\n" + the first line [+ the mode line] + those lines)
  code:        100000 + (first 8 bytes of the digest, big endian) % 800000   -- the range of every other pool
  The loader adds ROOM3's +4003 when it makes the lobby tag, as for any code. Since FORMAT 2, online.dll makes this
  code again when the game starts (from the folder and the cache below) and says in patch_ranked.log when
  patch_ranked.txt no longer matches the folder -- a start from Steam or from the exe after the folder changed. It
  does not change the code the loader plays under: only a launcher start does.

THE CACHE  launcher_content_pool.json beside the exe: {"format", "files": {rel: [size, mtime_ns, sha256]}, "exe":
  [size, mtime_ns, sha256], "plan_demo": [rel, ...], "version", "mode", "built", "code", "digest"}. A file whose size
  and modification time are unchanged is not read again. The installers (robocopy, copy2, the beta's decryption) give
  a changed file a new time. "version" / "mode" / "built" (the build's time, seconds since 1970) let the loader tell
  other builds of the same version apart for its online counts; "version" and "built" do not enter the code, "mode"
  does unless it is DEFAULT (THE CODE). A call without a mode takes the cache's.

  python launcher/content_pool.py <game folder>            the code (the cache's plan), and how many files counted
  python launcher/content_pool.py <game folder> --list     every counted file with its sha256, then what was left out
"""

import hashlib
import json
import os
import re
import struct
import sys
import zlib

FORMAT = 2
CACHE_NAME = "launcher_content_pool.json"
CODE_FILE = "patch_ranked.txt"
EXE_NAME = "BLEACH_Rebirth_of_Souls.exe"
REGISTRY = ("Fnames", "file_exist.htable")
TREES = ("script", "motion", "demo", "fnames")
REGISTRY_TREE = "demo"
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
    """True when a game-relative path ('/'-separated) can be part of the pool's content (by name and place; a demo
    must also be registered or planned, see entries())."""
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


def norm_rel(rel):
    """A game-relative path as the cache and the plan keep it: '/', no leading or trailing '/', lower case."""
    return rel.replace("\\", "/").strip("/").lower()


def _walk(game):
    """Every file counts() accepts: {lower-case rel: (real path, rel with the disk's own case)}."""
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
                out[low] = (full, n)
        elif os.path.isdir(full) and (low in TREES or low == PLUGINS):
            for dp, dn, fn in os.walk(full):
                dn.sort()
                for f in fn:
                    p = os.path.join(dp, f)
                    rel = os.path.relpath(p, game).replace(os.sep, "/")
                    if counts(rel):
                        out[rel.lower()] = (p, rel)
    return out


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def reg_crc(s):
    """The registry's hash of a game path (str)."""
    b = s.encode("utf-8")
    return zlib.crc32(b, len(b) ^ 0xFFFFFFFF) ^ 0xFFFFFFFF


def read_registry(game):
    """The set of path hashes in the installed Fnames/file_exist.htable."""
    p = os.path.join(game, *REGISTRY)
    try:
        with open(p, "rb") as f:
            data = f.read()
    except OSError as e:
        raise PoolError("%s cannot be read (%s)" % ("/".join(REGISTRY), e))
    if len(data) < 4:
        raise PoolError("%s is empty" % "/".join(REGISTRY))
    n = struct.unpack_from("<I", data, 0)[0]
    if 4 + 8 * n != len(data):
        raise PoolError("%s is not a registry (%d entries announced, %d bytes)" % ("/".join(REGISTRY), n, len(data)))
    return set(struct.unpack_from("<%dI" % (2 * n), data, 4)[0::2])


def demo_registered(disk_rel, reg):
    """disk_rel: 'Demo/...' with the disk's own case (any case for the folder)."""
    parts = disk_rel.replace("\\", "/").strip("/").split("/")
    rest = "\\".join(parts[1:])
    return reg_crc("Demo\\" + rest) in reg or reg_crc("Demo\\" + rest.lower()) in reg


def _load_cache(game):
    try:
        with open(os.path.join(game, CACHE_NAME), "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and d.get("format") in (1, FORMAT) and isinstance(d.get("files"), dict):
            return d
    except Exception:
        pass
    return {}


def _save_cache(game, d):
    path = os.path.join(game, CACHE_NAME)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(d, f, separators=(",", ":"), sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass                              # a cache that cannot be written only costs time next launch


def _cached_sha(entry, st):
    if (isinstance(entry, list) and len(entry) == 3 and entry[0] == st.st_size and entry[1] == st.st_mtime_ns
            and isinstance(entry[2], str) and len(entry[2]) == 64):
        return entry[2]
    return None


def scan(game, use_cache=True, plan=None):
    """-> dict: ents [(lower rel, sha256)] sorted, exe sha256, left_out [lower rel], plan_demo [lower rel], and the
    cache dict to save. plan: game-relative paths this launch installed (None: the cache's)."""
    cache = _load_cache(game) if use_cache else {}
    cfiles = cache.get("files", {}) if cache else {}
    if plan is None:
        plan_demo = sorted(set(norm_rel(p) for p in cache.get("plan_demo", []) if isinstance(p, str))) \
            if cache.get("format") == FORMAT else []
    else:
        plan_demo = sorted(set(r for r in (norm_rel(p) for p in plan) if r.split("/")[0] == REGISTRY_TREE))
    plan_set = set(plan_demo)
    exe = os.path.join(game, EXE_NAME)
    try:
        st = os.stat(exe)
    except OSError as e:
        raise PoolError("%s cannot be read (%s)" % (EXE_NAME, e))
    exe_sha = _cached_sha(cache.get("exe"), st) if cache.get("format") == FORMAT else None
    if not exe_sha:
        try:
            exe_sha = _sha256(exe)
        except OSError as e:
            raise PoolError("%s cannot be read (%s)" % (EXE_NAME, e))
    exe_entry = [st.st_size, st.st_mtime_ns, exe_sha]
    found = _walk(game)
    reg = None
    new, ents, left_out = {}, [], []
    for rel in sorted(found):
        p, disk_rel = found[rel]
        if rel.split("/")[0] == REGISTRY_TREE and rel not in plan_set:
            if reg is None:
                reg = read_registry(game)
            if not demo_registered(disk_rel, reg):
                left_out.append(rel)
                continue
        try:
            st = os.stat(p)
        except OSError as e:
            raise PoolError("%s cannot be read (%s)" % (rel, e))
        d = _cached_sha(cfiles.get(rel), st)
        if not d:
            try:
                d = _sha256(p)
            except OSError as e:
                raise PoolError("%s cannot be read (%s)" % (rel, e))
        new[rel] = [st.st_size, st.st_mtime_ns, d]
        ents.append((rel, d))
    return {"ents": ents, "exe": exe_sha, "left_out": left_out, "plan_demo": plan_demo,
            "cache": {"format": FORMAT, "files": new, "exe": exe_entry, "plan_demo": plan_demo}}


def digest(ents, exe_sha, mode=None):
    h = hashlib.sha256(b"BROS-CONTENT-POOL\0%d\n" % FORMAT)
    h.update(b"<exe>\0" + exe_sha.encode("ascii") + b"\n")
    if mode not in (None, "", "DEFAULT"):
        h.update(b"<mode>\0" + mode.encode("utf-8") + b"\n")
    for rel, d in ents:
        h.update(rel.encode("utf-8") + b"\0" + d.encode("ascii") + b"\n")
    return h.hexdigest()


def code_of(hexdigest):
    return 100000 + int(hexdigest[:16], 16) % 800000


def code(game, use_cache=True, plan=None, version=None, mode=None, built=None):
    """(code, number of files counted, digest). Saves the cache (with the plan and the build's labels) when
    use_cache."""
    s = scan(game, use_cache, plan)
    if not s["ents"]:
        raise PoolError("nothing to count in %s: is it the game folder?" % game)
    old = _load_cache(game) if use_cache else {}
    mode = mode if mode is not None else old.get("mode")
    d = digest(s["ents"], s["exe"], mode)
    c = code_of(d)
    if use_cache:
        cache = s["cache"]
        cache["version"] = version if version is not None else old.get("version")
        cache["mode"] = mode
        cache["built"] = built if built is not None else old.get("built")
        cache["code"] = c
        cache["digest"] = d
        _save_cache(game, cache)
    return c, len(s["ents"]), d


def write_code(game, use_cache=True, plan=None, version=None, mode=None, built=None):
    """Make the code and write it to patch_ranked.txt (through a .tmp file, then read back). Returns (code, n, digest).
    Raises PoolError: the caller must then not start the game. plan: the game-relative paths this launch installed
    (only those under Demo/ matter); version / mode / built: the build's labels for the loader's online counts."""
    c, n, d = code(game, use_cache, plan, version, mode, built)
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
    cache = _load_cache(game)                 # only its plan and mode: every file is read again here
    s = scan(game, use_cache=False, plan=cache.get("plan_demo", []) if cache.get("format") == FORMAT else [])
    d = digest(s["ents"], s["exe"], cache.get("mode") if cache.get("format") == FORMAT else None)
    if "--list" in argv:
        print("%s  <exe> %s" % (s["exe"], EXE_NAME))
        for rel, h in s["ents"]:
            print("%s  %s" % (h, rel))
        for rel in s["left_out"]:
            print("%-64s  %s   (left out: unregistered, not installed by this build)" % ("-", rel))
    mode = cache.get("mode") if cache.get("format") == FORMAT else None
    print("content pool %d  (%d files, %d demo file(s) left out, digest %s, format %d%s)"
          % (code_of(d), len(s["ents"]), len(s["left_out"]), d[:16], FORMAT,
             (", game mode " + mode) if mode not in (None, "", "DEFAULT") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
