"""A launch leaves the game folder holding exactly what the chosen version ships -- and says so when it cannot.

WHY (INSTALL_SYNC, 2026-10-11; D:\\Development Log\\history.md entries i02-i11)
---------------------------------------------------------------------------
Berg's report: new effects -- Zangetsu's, Yumichika's, Zangetsu's rev enhanced-EX cero -- were missing on other
developers' machines while his own game showed them. The repository installs them on a clean machine, at High and
at Medium, byte-identical to his game. What differs is the state a machine is in. Four ways a machine got into such
a state without anybody seeing it are closed here:

1. A STRAY BACKUP HID THE REAL EFFECT. The game's effect loaders (exe 0x168510 for the characters, 0x650e20 for the
   stages) enumerate <tier>/Effect/spfx/<owner>/*.*, take every name that CONTAINS ".vfxb" (or ".vfxt"), key it by
   the text before its first '.', and keep the LAST one found. "X.vfxb.preomote_bak" is therefore loaded instead of
   "X.vfxb". Sixteen such backups were committed in V1.2 and V1.3, and the launcher never cleaned 00HIGH/01MIDDLE, so
   they stayed on every machine that ever installed those versions. P022_com_senkei_00.vfxb.preemit_bak, the winner
   among its three, has no named trigger: Senkei could not play anywhere V1.2 had been installed.
   Now nothing dev-shaped is installed (excluded()), and every launch moves every non-canonical effect-bank file out
   of the game's Effect trees into _launcher_quarantine/ (sweep_effect_strays()). Canonical means "<name>.vfxb" or
   "<name>.desktop.vfxt" with no other dot -- which every one of the 3,346 stock effect files is.

2. A VERSION SWITCH PUT OLD FILES BACK. install_overlay() restores its "stock" backup of every path the previous
   version's overlay wrote and the new one does not. It did that even when the new version had just installed that
   same path through its own subtrees, and the backup was an older mod file anyway: an overlay captures whatever is
   on disk the first time it writes a path, and what is on disk is often another version's file. Switching from the
   Community Patch (Zangetsu in its Overlay) to V1.2 or V1.3 (Zangetsu in their 00HIGH/01MIDDLE) restored ten
   Zangetsu effects over the ones just installed. Now installed_by_this_launch(rel) is asked first: such a path is
   neither restored nor captured, and its backup and its state entry are kept for the next switch.

3. A REFUSED PULL WAS INVISIBLE. With a DevToken, a refused `git pull` printed one line to a console nobody sees and
   the game started from the old checkout. Now the player is told -- on screen in the main launcher; in the Quick
   Launch console, which then waits for Enter -- that the pull was refused and why, how far the checkout is behind
   its upstream, which tracked files are missing from the working tree, and which files are git-LFS placeholders
   rather than the real thing (placeholders are never merged or overlaid over a real file).

4. NOTHING CHECKED THE COPY. robocopy's exit code is ignored and install_overlay's per-file failures went to the same
   hidden console. Now verify_and_repair() compares every file the install put down -- the chain's mirror, its
   merges and its overlay, last writer wins, exactly as the launch did it -- with its source: size and modification
   time (shutil.copy2 and robocopy both preserve it; within 2 s, as FAT and exFAT drives round it), and the content
   when those differ. A mismatch is copied again once; what is still wrong is a problem.

5. AN INSTALLED EFFECT THE GAME IS NOT TOLD ABOUT (added 2026-10-11, i14-). The game takes a file to exist only if
   Fnames/file_exist.htable lists it ("unregistered files are invisible", PROJECT_MASTER_INDEX); a version's registry
   is a whole-roster file that nothing merges. Eleven of Zangetsu's own banks, two of pl022's and V1.3's eleven
   Yumichika banks were in no version's registry. Now check_registration() reads the htable this launch installed and
   names every effect bank this launch installed that it does not list -- a problem, shown like the others, because
   it is the same on every machine that installs that version until the repo is fixed (launcher/effect_registry.py,
   which the pre-commit hook runs, keeps it fixed). Leftovers of earlier launches are not this launch's files and are
   not checked.

Every launch writes <game>/launcher_install_report.txt.

THE MEDIUM PRESET. The character loader passes each folder through exe 0x696070 with the current resource level
before it enumerates (0x168e26), so on Medium the game reads 01MIDDLE/Effect/spfx/, not 00HIGH. Both tiers are swept
and verified alike, and the commit check wants every bank in both.

SCRIPT/ AND MOTION/. The chain root's Script/ and Motion/ are still mirrored by `robocopy /MIR`, unfiltered: the
game opens those files by exact name, so a backup beside one is inert, and robocopy's mirror (which also removes
what the version no longer ships) is kept as it is. A git-LFS placeholder among them is reported as installed.

NOTHING IS DELETED. A quarantined file keeps its game-relative path under _launcher_quarantine/ (".1", ".2", ...
appended when the name is taken by different bytes; moved onto a byte-identical copy already kept there, so a stray
that something keeps putting back does not pile up) and is listed in _launcher_quarantine/QUARANTINE_LOG.txt.

USE (every function is safe to call when begin() was not: it then does nothing, or what the old code did)
--------------------------------------------------------------------------------------------------------
    begin(base_dir, game_path, version, pull=<CompletedProcess or None>, devtoken=<bool or None>)
                                            right after the pull, BEFORE the syncs (they delete and write tracked
                                            files on purpose; the checkout's own state is what is reported)
    note_mirror(src_dir, "Script")          after `robocopy /MIR` of a chain root's Script/ or Motion/
    merge_tree(src_dir, dst_dir, "00HIGH")  instead of shutil.copytree(src, dst, dirs_exist_ok=True)
    overlay_skip(src, rel)                  in _overlay_pairs(): True = not an overlay file (a dev leftover)
    lfs_skip(src, rel)                      in install_overlay's write loop: True = do not install (placeholder)
    installed_by_this_launch(rel)           in install_overlay: the revert and the stock capture ask this first
    note_kept(rel) / note_not_captured(rel) / note_overlay(src, rel)
    verify_and_repair()                     right after install_overlay()
    sweep_effect_strays(game_path=None)     after every copy of the launch (Spec Mod, modes, reworks)
    finish(show=None)                       checks the registry (check_registration()), writes the report;
                                            False = the player chose not to start the game

    python launcher/install_guard.py --commit-check     the pre-commit hook: staged paths (added, modified and
                                                        deleted, renames as delete + add), NUL-separated, on stdin;
                                                        exit 3 with a REFUSED line on stdout = refused, 0 = fine,
                                                        anything else = could not check
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import time
import zlib

try:
    from launcher.layers import is_excluded as _layers_is_excluded
except Exception:                                   # an older checkout, or run as a script from inside launcher/
    try:
        from layers import is_excluded as _layers_is_excluded
    except Exception:
        _layers_is_excluded = None

# launcher/layers.py's own list, for a checkout that lacks it.
_FALLBACK_EXACT = {"thumbs.db", "desktop.ini", ".gitkeep", ".gitignore", ".ds_store"}
_FALLBACK_PATTERNS = (
    re.compile(r"\.bak$", re.I),
    re.compile(r"_bak$", re.I),
    re.compile(r"\s\(\d+\)\.", re.I),
    re.compile(r"\.(bat|py)(\s|$)", re.I),
)
# The subset that marks a BACKUP (the commit check refuses these; the .bat/.py toolchain is allowed in git).
_BACKUP_PATTERNS = _FALLBACK_PATTERNS[:3]

_TIERS = ("00high", "01middle", "02low")
_BANK_CANONICAL = re.compile(r"[^.]+\.(?:vfxb|desktop\.vfxt)\Z", re.I)
LFS_MAGIC = b"version https://git-lfs.github.com/spec/"
QUARANTINE = "_launcher_quarantine"
REPORT = "launcher_install_report.txt"
_WATCHED = ("GameVersions", "Files", "launcher")     # where a missing tracked file changes what gets installed
_MTIME_SLACK_NS = 2_000_000_000     # NTFS keeps copy2's and robocopy's time exactly; FAT and exFAT round it
COMMIT_REFUSED = 3                  # the commit check's exit code for "refused" (anything else: could not check)
# THE INSTALL RECORD (2026-11-26). Beside the exe: {"format": 1, "files": {rel lower: [size, mtime_ns, git blob id]}} --
# which bytes each file this launcher put down holds, while it keeps that size and time. Two checkouts of one commit
# (the dev environment, the testers' and staging launchers, a re-clone) write the same bytes with other times, and a
# size-and-time rule re-copied the whole V2.0 install (7 GB, 16 min on a USB disk) at every switch between them. Now
# a file whose bytes are already the source's only gets the source's time (os.utime): robocopy, the verification and
# the content pool's cache (retimed too) then see it as copied. The id is git's, read from the index for the clean
# tracked files of the version trees, which .gitattributes keeps byte for byte (-text): a modified, untracked or
# LFS-placeholder source has none and is copied as before.
IDS = "launcher_install_ids.json"
_ID_TREES = ("script", "motion", "00high", "01middle", "02low", "overlay")    # GameVersions/<v>/<tree>/...


# ------------------------------------------------------------------ what never reaches the game
def _norm(rel):
    return rel.replace("\\", "/").strip("/")


def in_effect_tree(rel):
    """True for a game-relative path inside <tier>/Effect/ or the root Effect/ -- the folders the loaders enumerate."""
    p = _norm(rel).lower().split("/")
    if len(p) >= 3 and p[0] in _TIERS and p[1] == "effect":
        return True
    return len(p) >= 2 and p[0] == "effect"


def is_bank_stray(name):
    """A name the effect loader takes as a bank ("...vfxb..." / "...vfxt...") that is not <name>.vfxb or
    <name>.desktop.vfxt. It is keyed by the text before its first '.', so it competes with the real bank."""
    low = name.lower()
    return (".vfxb" in low or ".vfxt" in low) and not _BANK_CANONICAL.match(name)


def _dev_leftover(name):
    if _layers_is_excluded is not None:
        try:
            return bool(_layers_is_excluded(name))
        except Exception:
            pass
    return name.lower() in _FALLBACK_EXACT or any(p.search(name) for p in _FALLBACK_PATTERNS)


def excluded(rel):
    """True if this game-relative path must never be installed: a dev leftover (launcher/layers.py), or anything in
    an Effect tree that the loader would take for a bank without being one."""
    rel = _norm(rel)
    name = rel.rsplit("/", 1)[-1]
    return _dev_leftover(name) or (in_effect_tree(rel) and is_bank_stray(name))


def is_lfs_pointer(path):
    """True for a git-LFS placeholder: the file git leaves when git-lfs is not installed or not pulled."""
    try:
        if os.path.getsize(path) > 1024:
            return False
        with open(path, "rb") as f:
            return f.read(len(LFS_MAGIC)) == LFS_MAGIC
    except OSError:
        return False


# ------------------------------------------------------------------ the launch record
class Launch:
    def __init__(self, base_dir, game_path, version):
        self.base = base_dir
        self.game = game_path
        self.version = version
        self.started = time.time()
        self.expected = {}            # rel.lower() -> (rel, src): what this launch put there, last writer wins
        self.installed = set()        # rel.lower() written by the mirror or the merges (not the overlay)
        self.counts = {"mirror": 0, "merge": 0, "overlay": 0}
        self.skipped_leftover = {}    # rel.lower() -> (rel, src): not merged / not overlaid
        self.skipped_lfs = {}         # rel.lower() -> (rel, src): placeholders not merged / not overlaid
        self.mirrored_lfs = {}        # rel.lower() -> (rel, src): placeholders the Script/Motion mirror installed
        self.kept = []                # rels whose stock backup was kept: this launch installed them
        self.not_captured = []        # rels not captured as "stock": this launch installed them
        self.verify = None
        self.quarantined = []         # (rel, quarantine rel, size): new to the quarantine
        self.requarantined = []       # (rel, quarantine rel, size): put back again by something, moved again
        self.move_failed = []         # (rel, error): strays that still sit in an Effect tree
        self.git = {}
        self.registry = None          # check_registration(): {"table", "checked", "unregistered"} or {"error"}
        self.errors = []              # what the guard itself could not do
        self.ids = None               # normcase source path -> git blob id (_src_id(), read at the first copy)
        self.rec = None               # the install record's files (_rec())
        self.retimed = {}             # rel lower -> (size, old mtime_ns, new mtime_ns): given the source's time


_cur = None


def current():
    return _cur


def begin(base_dir, game_path, version, pull=None, devtoken=None):
    """Start the record of one launch and read the checkout's state. Never raises."""
    global _cur
    _cur = Launch(base_dir, game_path, version)
    try:
        _cur.git = git_report(base_dir, pull, devtoken)
    except Exception as e:                               # pragma: no cover - git_report catches its own
        _cur.errors.append("git state: %s" % e)
    return _cur


def _record(rel, src, kind):
    key = rel.lower()
    _cur.expected[key] = (rel, src)
    if kind != "overlay":
        _cur.installed.add(key)
    _cur.counts[kind] += 1


def _rel_join(prefix, sub, name):
    parts = [prefix] + ([] if sub == "." else sub.replace(os.sep, "/").split("/")) + [name]
    return "/".join(p for p in parts if p)


def note_mirror(src_dir, rel_prefix):
    """After `robocopy src dst /MIR`: every file of src_dir is now expected at <rel_prefix>/<path>."""
    if _cur is None:
        return
    try:
        for dirpath, _dirs, files in os.walk(src_dir, onerror=lambda e: _cur.errors.append("mirror: %s" % e)):
            sub = os.path.relpath(dirpath, src_dir)
            for f in files:
                rel, src = _rel_join(rel_prefix, sub, f), os.path.join(dirpath, f)
                _record(rel, src, "mirror")
                if is_lfs_pointer(src):
                    _cur.mirrored_lfs[rel.lower()] = (rel, src)
                else:
                    _note_in_place(src, os.path.join(_cur.game, *rel.split("/")))
    except Exception as e:
        _cur.errors.append("mirror record of %s: %s" % (rel_prefix, e))


# ------------------------------------------------------------------ the install record (IDS above)
def _load_src_ids(base):
    """{normcase path: blob id} of the clean tracked files of GameVersions/<v>/<_ID_TREES>/; {} when git cannot say."""
    out = {}
    try:
        r = subprocess.run(["git", "-C", base, "ls-files", "-s", "-z", "--", "GameVersions"],
                           capture_output=True, timeout=120)
        m = subprocess.run(["git", "-C", base, "ls-files", "-m", "-z", "--", "GameVersions"],
                           capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return out
    if r.returncode or m.returncode:
        return out
    modified = set(m.stdout.split(b"\0"))
    for ent in r.stdout.split(b"\0"):
        meta, _tab, path = ent.partition(b"\t")
        f = meta.split()
        if len(f) != 3 or f[0] not in (b"100644", b"100755") or f[2] != b"0" or path in modified:
            continue
        seg = path.decode("utf-8", "surrogateescape").split("/")
        if len(seg) > 3 and seg[2].lower() in _ID_TREES:
            out[os.path.normcase(os.path.join(base, *seg))] = f[1].decode("ascii")
    return out


def _src_id(src):
    if _cur is None:
        return None
    if _cur.ids is None:
        _cur.ids = _load_src_ids(_cur.base)
    return _cur.ids.get(os.path.normcase(os.path.abspath(src)))


def _rec():
    if _cur.rec is None:
        _cur.rec = {}
        try:
            with open(os.path.join(_cur.game, IDS), "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and d.get("format") == 1 and isinstance(d.get("files"), dict):
                _cur.rec = d["files"]
        except (OSError, ValueError):
            pass
    return _cur.rec


def _rec_key(dst):
    try:
        rel = os.path.relpath(dst, _cur.game).replace("\\", "/")
    except ValueError:
        return None
    return None if rel.startswith("../") or rel == ".." else rel.lower()


def _put_rec(dst, blob):
    key = _rec_key(dst)
    if key is None:
        return
    if blob is None:
        _rec().pop(key, None)
        return
    try:
        d = os.stat(dst)
    except OSError:
        _rec().pop(key, None)
        return
    _rec()[key] = [d.st_size, d.st_mtime_ns, blob]


def _blob_id(path, size):
    h = hashlib.sha1(b"blob %d\0" % size)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _holds(dst, d, blob):
    """True when dst (os.stat d) holds the bytes of git blob `blob`: the record says so for this size and time, or,
    with no such entry, its bytes do (read once)."""
    key = _rec_key(dst)
    if key is None:
        return False
    e = _rec().get(key)
    if isinstance(e, list) and len(e) == 3 and e[0] == d.st_size and e[1] == d.st_mtime_ns:
        return e[2] == blob
    try:
        return _blob_id(dst, d.st_size) == blob
    except OSError:
        return False


def _retime_if_same(src, dst):
    """dst gets src's time instead of its bytes when it already holds them. True when it did."""
    if _cur is None:
        return False
    try:
        s, d = os.stat(src), os.stat(dst)
        if not stat.S_ISREG(d.st_mode) or s.st_size != d.st_size or s.st_mtime_ns == d.st_mtime_ns:
            return False
        blob = _src_id(src)
        if not blob or not _holds(dst, d, blob):
            return False
        os.utime(dst, ns=(s.st_atime_ns, s.st_mtime_ns))
        n = os.stat(dst)
    except OSError:
        return False
    key = _rec_key(dst)
    _cur.retimed[key] = (d.st_size, d.st_mtime_ns, n.st_mtime_ns)
    _rec()[key] = [n.st_size, n.st_mtime_ns, blob]
    return True


def _note_in_place(src, dst, s=None, d=None):
    """dst has src's size and time (a skipped copy, robocopy's mirror): recorded as holding src's bytes. False when
    the record knows other bytes at that size and time (two files of one size written in one clock tick)."""
    try:
        s, d = s or os.stat(src), d or os.stat(dst)
    except OSError:
        return True
    key = _rec_key(dst)
    if key is not None and s.st_size == d.st_size and s.st_mtime_ns == d.st_mtime_ns:
        blob = _src_id(src)
        if blob:
            e = _rec().get(key)
            if isinstance(e, list) and len(e) == 3 and e[0] == d.st_size and e[1] == d.st_mtime_ns and e[2] != blob:
                return False
            _rec()[key] = [d.st_size, d.st_mtime_ns, blob]
    return True


def retime_tree(src_dir, dst_dir):
    """Before `robocopy src dst /MIR`: every file of dst that holds its source's bytes with another time gets the
    source's time, so robocopy leaves it. Never raises."""
    if _cur is None:
        return
    try:
        for dirpath, _dirs, files in os.walk(src_dir):
            sub = os.path.relpath(dirpath, src_dir)
            out = dst_dir if sub == "." else os.path.join(dst_dir, sub)
            for f in files:
                _retime_if_same(os.path.join(dirpath, f), os.path.join(out, f))
    except Exception as e:
        _cur.errors.append("retime of %s: %s" % (dst_dir, e))


def save_record():
    """Write the install record, and give the content pool's cache entries of the retimed files their new time (the
    bytes did not change, nor their sha256). Never raises."""
    if _cur is None or _cur.rec is None:
        return
    try:
        p = os.path.join(_cur.game, IDS)
        with open(p + ".tmp", "w", encoding="utf-8", newline="\n") as f:
            json.dump({"format": 1, "files": _cur.rec}, f, separators=(",", ":"), sort_keys=True)
        os.replace(p + ".tmp", p)
    except OSError as e:
        _cur.errors.append("install record: %s" % e)
    if not _cur.retimed:
        return
    try:
        try:
            from launcher import content_pool as cp
        except ImportError:
            import content_pool as cp
        cache = cp._load_cache(_cur.game)
        files = cache.get("files") if cache else None
        if isinstance(files, dict):
            n = 0
            for key, (size, old, new) in _cur.retimed.items():
                e = files.get(cp.norm_rel(key))
                if isinstance(e, list) and len(e) == 3 and e[0] == size and e[1] == old:
                    e[1] = new
                    n += 1
            if n:
                cp._save_cache(_cur.game, cache)
    except Exception as e:
        _cur.errors.append("content pool cache retime: %s" % e)


def copy_if_changed(src, dst):
    """shutil.copy2(src, dst), skipped when dst is a file of src's size and EXACT modification time -- what copy2 left
    there last launch (robocopy's own skip rule). 2026-11-19: every launch re-copied the 4.3 GB V2.0 Overlay, 3856 of
    its 3866 files unchanged -- 5+ minutes on a USB disk, the launcher greyed out "Not responding" all along.
    2026-11-26: also skipped when dst already holds src's bytes with another time (another checkout's copy): it only
    gets src's time (the install record, IDS)."""
    try:
        s, d = os.stat(src), os.stat(dst)
        if stat.S_ISREG(d.st_mode) and s.st_size == d.st_size and s.st_mtime_ns == d.st_mtime_ns:
            if _cur is None or _note_in_place(src, dst, s, d):
                return
    except OSError:
        pass
    if _retime_if_same(src, dst):
        return
    shutil.copy2(src, dst)
    if _cur is not None:
        _put_rec(dst, _src_id(src))


def merge_tree(src_dir, dst_dir, rel_prefix):
    """shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True), less the dev leftovers and the git-LFS placeholders,
    recorded for the revert and the verification. Like copytree it raises FileNotFoundError when src_dir is not
    there, and otherwise copies every file it can and then raises shutil.Error listing what it could not -- a
    folder it could not read or make included."""
    if not os.path.isdir(src_dir):
        raise FileNotFoundError(2, "No such file or directory", src_dir)
    errors = []

    def _walk_error(e):
        errors.append((getattr(e, "filename", src_dir), dst_dir, str(e)))

    for dirpath, _dirs, files in os.walk(src_dir, onerror=_walk_error):
        sub = os.path.relpath(dirpath, src_dir)
        out = dst_dir if sub == "." else os.path.join(dst_dir, sub)
        try:
            os.makedirs(out, exist_ok=True)
        except OSError as e:
            errors.append((dirpath, out, str(e)))
            continue
        for f in files:
            src = os.path.join(dirpath, f)
            rel = _rel_join(rel_prefix, sub, f)
            if excluded(rel):
                if _cur is not None:
                    _cur.skipped_leftover[rel.lower()] = (rel, src)
                continue
            if is_lfs_pointer(src):
                if _cur is not None:
                    _cur.skipped_lfs[rel.lower()] = (rel, src)
                continue
            if _cur is not None:
                _record(rel, src, "merge")      # before the copy: a copy that fails is still checked
            try:
                copy_if_changed(src, os.path.join(out, f))
            except OSError as e:
                errors.append((src, os.path.join(out, f), str(e)))
    if errors:
        raise shutil.Error(errors)


def overlay_skip(src, rel):
    """In _overlay_pairs(): True when this Overlay file is a dev leftover and is not an overlay file at all."""
    if not excluded(rel):
        return False
    if _cur is not None:
        _cur.skipped_leftover[_norm(rel).lower()] = (_norm(rel), src)
    return True


def lfs_skip(src, rel):
    """In install_overlay's write loop: True when the source is a git-LFS placeholder. The game's own file stays."""
    if not is_lfs_pointer(src):
        return False
    if _cur is not None:
        _cur.skipped_lfs[_norm(rel).lower()] = (_norm(rel), src)
    return True


def installed_by_this_launch(rel):
    """True when this launch's mirror or merges wrote rel: its revert must not restore over it, and what is on disk
    there is the version's own file, not a stock file to capture."""
    return _cur is not None and _norm(rel).lower() in _cur.installed


def note_kept(rel):
    if _cur is not None:
        _cur.kept.append(_norm(rel))


def note_not_captured(rel):
    if _cur is not None:
        _cur.not_captured.append(_norm(rel))


def note_overlay(src, rel):
    """In install_overlay's write loop, before the copy: rel is expected to hold src's bytes."""
    if _cur is not None:
        _record(_norm(rel), src, "overlay")


# ------------------------------------------------------------------ verification
def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _same(src, dst):
    """None when dst holds src's bytes, else why not."""
    try:
        s = os.stat(src)
    except OSError as e:
        return "source unreadable (%s)" % e.strerror
    try:
        d = os.stat(dst)
    except OSError:
        return "missing"
    if os.path.isdir(dst):
        return "a folder is in the way"
    if s.st_size != d.st_size:
        return "size %d, should be %d" % (d.st_size, s.st_size)
    if abs(s.st_mtime_ns - d.st_mtime_ns) <= _MTIME_SLACK_NS:
        return None
    try:
        return None if _md5(src) == _md5(dst) else "different content"
    except OSError as e:
        return "unreadable (%s)" % e.strerror


def verify_and_repair():
    """Compare every file this launch installed with its source; copy a mismatch again once. Never raises."""
    if _cur is None:
        return None
    res = {"checked": 0, "repaired": [], "failed": []}
    for key in sorted(_cur.expected):
        rel, src = _cur.expected[key]
        dst = os.path.join(_cur.game, *rel.split("/"))
        res["checked"] += 1
        why = _same(src, dst)
        if why is None:
            continue
        if why == "a folder is in the way":
            res["failed"].append((rel, why))
            continue
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            again = _same(src, dst)
        except OSError as e:
            again = "could not copy (%s)" % (e.strerror or e)
        if again is None:
            res["repaired"].append((rel, why))
        else:
            res["failed"].append((rel, again))
    _cur.verify = res
    return res


# ------------------------------------------------------------------ the registry
FNAMES_HTABLE = "Fnames/file_exist.htable"


def _game_hash(s):
    """The engine's file-name hash (launcher/effect_registry.py's): reflected CRC-32 seeded with the length, no final
    xor."""
    b = s.encode("utf-8")
    return zlib.crc32(b, len(b) ^ 0xFFFFFFFF) ^ 0xFFFFFFFF


_TOP = {"00high": "00HIGH", "01middle": "01MIDDLE"}


def _ht_key(rel):
    """The row the game looks for: launcher/effect_registry.py's key() -- the path as the game spells it (00HIGH /
    01MIDDLE, Effect, spfx), backslashes -- repeated here so this module stands alone."""
    p = rel.replace("\\", "/").split("/")
    if p and p[0].lower() in _TOP:
        p[0] = _TOP[p[0].lower()]
        if len(p) > 1 and p[1].lower() == "effect":
            p[1] = "Effect"
            if len(p) > 2 and p[2].lower() == "spfx":
                p[2] = "spfx"
    p = "\\".join(p)
    return _game_hash(p), _game_hash(p.rsplit("\\", 1)[0] if "\\" in p else "")


def check_registration():
    """Every effect bank this launch installed (<tier>/Effect/.../<name>.vfxb or .desktop.vfxt, 00HIGH and 01MIDDLE)
    must be listed in the Fnames/file_exist.htable now in the game folder. Never raises."""
    if _cur is None:
        return None
    path = os.path.join(_cur.game, *FNAMES_HTABLE.split("/"))
    try:
        with open(path, "rb") as f:
            raw = f.read()
        n = struct.unpack_from("<I", raw, 0)[0] if len(raw) >= 4 else -1
        if n < 0 or 4 + 8 * n != len(raw):
            raise ValueError("not a file_exist.htable (%d bytes)" % len(raw))
        rows = set(struct.iter_unpack("<II", raw[4:]))
    except (OSError, ValueError, struct.error) as e:
        _cur.registry = {"error": "%s could not be read: %s" % (FNAMES_HTABLE, e)}
        return _cur.registry
    checked, gone = 0, []
    for k in sorted(_cur.expected):
        rel, _src = _cur.expected[k]
        p = rel.split("/")
        if (len(p) >= 4 and p[0].lower() in _TIERS[:2] and p[1].lower() == "effect"
                and _BANK_CANONICAL.match(p[-1])):
            checked += 1
            if _ht_key(rel) not in rows:
                gone.append(rel)
    shipped = FNAMES_HTABLE.lower() in _cur.expected
    failed = any(r.lower() == FNAMES_HTABLE.lower() for r, _w in ((_cur.verify or {}).get("failed") or []))
    _cur.registry = {"table": "%s (%d entries, md5 %s; %s)" % (
                         FNAMES_HTABLE, n, hashlib.md5(raw).hexdigest(),
                         "NOT installed correctly by this launch" if failed else
                         "installed by this launch" if shipped else "this version ships none: left by an earlier launch"),
                     "checked": checked, "unregistered": gone, "shipped": shipped, "failed": failed}
    return _cur.registry


# ------------------------------------------------------------------ the stray sweep
def _effect_roots(game):
    roots = []
    for name in os.listdir(game):
        low = name.lower()
        full = os.path.join(game, name)
        if not os.path.isdir(full):
            continue
        if low in _TIERS:
            for sub in os.listdir(full):
                if sub.lower() == "effect" and os.path.isdir(os.path.join(full, sub)):
                    roots.append((os.path.join(full, sub), name + "/" + sub))
        elif low == "effect":
            roots.append((full, name))
    return roots


def _quarantine_target(path, src):
    """(target, already kept?): the quarantine path for src -- a byte-identical copy already kept there if there is
    one (the stray then moves onto it), else the first free name: path, path.1, path.2, ..."""
    size, digest = None, None
    n = 0
    cand = path
    while os.path.lexists(cand):
        try:
            if os.path.isfile(cand):
                if size is None:
                    size = os.path.getsize(src)
                if os.path.getsize(cand) == size:
                    if digest is None:
                        digest = _md5(src)
                    if _md5(cand) == digest:
                        return cand, True
        except OSError:
            pass
        n += 1
        cand = "%s.%d" % (path, n)
    return cand, False


def sweep_effect_strays(game_path=None):
    """Move every non-canonical effect-bank file out of the game's Effect trees into _launcher_quarantine/, keeping
    its game-relative path. Returns [(rel, quarantine rel, size)] -- everything moved. Never raises."""
    game = game_path or (_cur.game if _cur is not None else None)
    if not game or not os.path.isdir(game):
        return []
    moved, log = [], []
    try:
        roots = _effect_roots(game)
    except OSError as e:
        if _cur is not None:
            _cur.errors.append("effect folders unreadable: %s" % e)
        return []
    for root, rel_root in roots:
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if not is_bank_stray(f):
                    continue
                src = os.path.join(dirpath, f)
                rel = rel_root + "/" + os.path.relpath(src, root).replace(os.sep, "/")
                try:
                    size = os.path.getsize(src)
                    dst, again = _quarantine_target(os.path.join(game, QUARANTINE, *rel.split("/")), src)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    os.replace(src, dst)
                except OSError as e:
                    if _cur is not None:
                        _cur.move_failed.append((rel, str(e)))
                    continue
                qrel = os.path.relpath(dst, game).replace(os.sep, "/")
                moved.append((rel, qrel, size))
                if _cur is not None:
                    (_cur.requarantined if again else _cur.quarantined).append((rel, qrel, size))
                log.append("%s  %s  ->  %s  (%d bytes%s)" % (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
                                                             rel, qrel, size, ", identical to the kept copy" if again else ""))
    if log:
        try:
            os.makedirs(os.path.join(game, QUARANTINE), exist_ok=True)
            with open(os.path.join(game, QUARANTINE, "QUARANTINE_LOG.txt"), "a", encoding="utf-8") as f:
                f.write("\n".join(log) + "\n")
        except OSError as e:
            if _cur is not None:
                _cur.errors.append("quarantine log: %s" % e)
    return moved


# ------------------------------------------------------------------ the checkout
def _git(base, *args, timeout=30):
    kw = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    r = subprocess.run(["git", "-C", base] + list(args), capture_output=True, timeout=timeout, **kw)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def pull_reason(text):
    """The part of a refused pull's output that says why: from the first "error:" / "fatal:" line on, with the
    indented lines that follow it (the files git names). The fetch's "From <remote>" lines are not the reason."""
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    for i, ln in enumerate(lines):
        if re.match(r"\s*(error|fatal):", ln, re.I):
            out = [ln.strip()]
            for nxt in lines[i + 1:]:
                if nxt.startswith(("\t", " ")) and nxt.strip():
                    out.append(nxt.strip())
                    if len(out) >= 7:
                        break
                else:
                    break
            return "\n".join(out)
    rest = [ln.strip() for ln in lines if ln.strip()]
    return rest[-1] if rest else "no reason given"


def git_report(base_dir, pull=None, devtoken=None):
    """What the checkout is, after the launch's pull. Every field is None when git could not say."""
    g = {"devtoken": devtoken, "pull_rc": None, "pull_text": "", "head": None, "upstream": None, "ahead": None,
         "behind": None, "missing": None, "modified": None, "lfs": None, "error": None}
    if pull is not None:
        g["pull_rc"] = getattr(pull, "returncode", None)
        txt = "\n".join(t if isinstance(t, str) else (t or b"").decode("utf-8", "replace")
                        for t in (getattr(pull, "stderr", ""), getattr(pull, "stdout", "")) if t)
        g["pull_text"] = txt.strip()
    try:
        rc, out, _ = _git(base_dir, "rev-parse", "--short", "HEAD")
        g["head"] = out.strip() if rc == 0 else None
        rc, out, _ = _git(base_dir, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if rc == 0 and out.strip():
            g["upstream"] = out.strip()
            rc, out, _ = _git(base_dir, "rev-list", "--left-right", "--count", "HEAD...@{u}")
            if rc == 0 and len(out.split()) == 2:
                g["ahead"], g["behind"] = (int(x) for x in out.split())
        rc, out, _ = _git(base_dir, "ls-files", "-d", "-z", "--", *_WATCHED)
        if rc == 0:
            g["missing"] = sorted(set(p for p in out.split("\0") if p))
        rc, out, _ = _git(base_dir, "status", "--porcelain", "-uno")
        if rc == 0:
            g["modified"] = len([ln for ln in out.splitlines() if ln.strip()])
        rc, _, _ = _git(base_dir, "lfs", "version")
        g["lfs"] = (rc == 0)
    except Exception as e:
        g["error"] = str(e)
    return g


# ------------------------------------------------------------------ the report
def _lines(title, items, limit=40, fmt=str):
    items = list(items)
    out = ["%s: %d" % (title, len(items))]
    for x in items[:limit]:
        out.append("  " + fmt(x))
    if len(items) > limit:
        out.append("  ... and %d more" % (len(items) - limit))
    return out


def notes():
    """[(problem?, text)] -- what the player has to know about this launch."""
    if _cur is None:
        return []
    out = []
    g = _cur.git or {}
    up = g.get("upstream") or "its upstream"
    if g.get("pull_rc"):
        behind = g.get("behind")
        out.append((True,
                    "Your checkout could not be updated -- git pull was refused:\n%s\n"
                    "This launch uses the files you already have%s. Other players on the current version will "
                    "see things you do not, and the other way round.\n"
                    "Fix: commit, stash or discard the local changes git names, then launch again."
                    % (pull_reason(g.get("pull_text")),
                       "" if behind is None else ", %d commit(s) behind %s" % (behind, up))))
    elif g.get("behind"):
        out.append((True, "Your checkout is %d commit(s) behind %s. Pull, then launch again." % (g["behind"], up)))
    if g.get("missing"):
        m = g["missing"]
        shown = "\n".join('  git checkout -- "%s"' % p for p in m[:3])
        out.append((True,
                    "%d tracked file(s) are missing from your checkout, so they were not installed:\n%s%s\n"
                    "If you deleted them on purpose, commit the deletion. If not, restore just those files (the "
                    "commands above; the full list is in %s)." % (len(m), shown, "\n  ..." if len(m) > 3 else "",
                                                                   REPORT)))
    if _cur.skipped_lfs or _cur.mirrored_lfs:
        how = ("install git-lfs (https://git-lfs.com), then run  git lfs install  and  git lfs pull"
               if g.get("lfs") is False else "run  git lfs pull")
        parts = []
        if _cur.skipped_lfs:
            ex = sorted(r for r, _ in _cur.skipped_lfs.values())
            bad = [r for r in ex if is_lfs_pointer(os.path.join(_cur.game, *r.split("/")))]
            parts.append("%d file(s) were NOT installed because your checkout holds git-LFS placeholders instead of "
                         "them (first: %s).%s" % (len(ex), ex[0], (
                             " %d of them are placeholders in the game folder too, put there by an earlier launch: "
                             "those sounds are missing until this is fixed." % len(bad)) if bad else ""))
        if _cur.mirrored_lfs:
            ex = sorted(r for r, _ in _cur.mirrored_lfs.values())
            parts.append("%d git-LFS placeholder(s) were installed by the Script/Motion mirror (first: %s)."
                         % (len(ex), ex[0]))
        out.append((True, " ".join(parts) + "\nFix: in the repo folder %s, then launch again." % how))
    v = _cur.verify or {}
    if v.get("failed"):
        rel, why = v["failed"][0]
        out.append((True,
                    "%d file(s) could not be installed correctly (first: %s -- %s). The game would run with old "
                    "or missing data.\nFix: close the game if it is running and launch again; if it persists, "
                    "send %s from the game folder." % (len(v["failed"]), rel, why, REPORT)))
    reg = _cur.registry or {}
    if reg.get("unregistered"):
        gone = reg["unregistered"]
        head = ("%d effect file(s) this launch installed are not listed in the game's %s, so the game does not load "
                "them (first: %s).\n" % (len(gone), FNAMES_HTABLE, gone[0]))
        if reg.get("failed"):
            why = ("The registry itself could not be installed (see the note above), so the game kept an older one."
                   "\nFix: close the game if it is running and launch again.")
        elif not reg.get("shipped"):
            why = ("This version ships no registry of its own, so the game kept the one an earlier launch left.\n"
                   "The version needs one: in the repo,  python launcher/effect_registry.py --check  names it.")
        else:
            why = ("They are missing from the version's own registry in the repo, so every machine on this version "
                   "has the same problem.\nFix (in the repo):  python launcher/effect_registry.py --fix , then "
                   "commit -- or send %s to whoever maintains the version." % REPORT)
        out.append((True, head + why))
    if _cur.move_failed:
        rel, why = _cur.move_failed[0]
        out.append((True,
                    "%d stray backup file(s) could not be moved out of the game's effect folders (first: %s -- %s), "
                    "so the game still shows them instead of the real effect.\nFix: close the game if it is "
                    "running and launch again." % (len(_cur.move_failed), rel, why)))
    if _cur.quarantined:
        ex = [r for r, _q, _s in _cur.quarantined]
        out.append((False,
                    "%d stray backup file(s) were moved out of the game's effect folders into %s\\ (the game was "
                    "showing them instead of the real effects; nothing was deleted). First: %s"
                    % (len(ex), QUARANTINE, ex[0])))
    if v.get("repaired"):
        out.append((False, "%d installed file(s) did not match the repo and were copied again (first: %s)."
                    % (len(v["repaired"]), v["repaired"][0][0])))
    if _cur.errors:
        out.append((False, "The install check itself could not do everything: %s" % _cur.errors[0]))
    return out


def report_text():
    c = _cur
    g = c.git or {}
    L = ["Launcher install report -- %s UTC" % time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
         "Version: %s" % c.version, "Repo: %s" % c.base, "Game: %s" % c.game, "",
         "== Checkout (as the pull left it, before the launch's syncs)",
         "HEAD %s, upstream %s, ahead %s, behind %s; dev token %s; modified tracked files %s; git-lfs %s" % (
             g.get("head"), g.get("upstream"), g.get("ahead"), g.get("behind"), g.get("devtoken"),
             g.get("modified"), {True: "installed", False: "NOT installed", None: "unknown"}[g.get("lfs")]),
         "git pull: %s" % {None: "not run", 0: "ok"}.get(g.get("pull_rc"), "REFUSED (exit %s)" % g.get("pull_rc"))]
    if g.get("pull_rc"):
        L += ["  " + ln for ln in pull_reason(g.get("pull_text")).splitlines()]
    if g.get("error"):
        L.append("git could not be read: %s" % g["error"])
    L += _lines("Tracked files missing from the working tree", g.get("missing") or [], limit=200)
    L += ["", "== Install",
          "mirrored %d, merged %d, overlay %d file(s)" % (c.counts["mirror"], c.counts["merge"], c.counts["overlay"])]
    L += _lines("Dev leftovers not installed", sorted(r for r, _ in c.skipped_leftover.values()))
    L += _lines("git-LFS placeholders not installed", sorted(r for r, _ in c.skipped_lfs.values()))
    L += _lines("git-LFS placeholders installed by the mirror", sorted(r for r, _ in c.mirrored_lfs.values()))
    L += _lines("Stock backups kept, not restored over this launch's own file", c.kept)
    L += _lines("Not captured as stock (this launch's own file)", c.not_captured)
    v = c.verify
    L += ["", "== Verification"]
    if v is None:
        L.append("not run")
    else:
        L.append("checked %d file(s): %d repaired, %d still wrong" % (v["checked"], len(v["repaired"]), len(v["failed"])))
        L += _lines("Repaired", v["repaired"], fmt=lambda x: "%s (%s)" % x)
        L += _lines("STILL WRONG", v["failed"], fmt=lambda x: "%s (%s)" % x)
    L += ["", "== Effect registration"]
    reg = c.registry
    if reg is None:
        L.append("not run")
    elif reg.get("error"):
        L.append(reg["error"])
    else:
        L.append("%s: %d installed effect file(s) checked" % (reg["table"], reg["checked"]))
        L += _lines("NOT REGISTERED (the game does not load these)", reg["unregistered"])
    L += ["", "== Effect folders"]
    L += _lines("Moved to %s" % QUARANTINE, c.quarantined, fmt=lambda x: "%s -> %s (%d bytes)" % x)
    L += _lines("Put back by something and moved again", c.requarantined, fmt=lambda x: "%s -> %s (%d bytes)" % x)
    L += _lines("COULD NOT BE MOVED", c.move_failed, fmt=lambda x: "%s (%s)" % x)
    if c.errors:
        L += [""] + _lines("Install check errors", c.errors)
    L += ["", "== For the player"]
    ns = notes()
    L += ["%s %s" % ("PROBLEM:" if p else "info:", t.replace("\n", " | ")) for p, t in ns] or ["nothing to report"]
    L.append("(%.1f s)" % (time.time() - c.started))
    return "\n".join(L) + "\n"


def _interactive():
    try:
        return (sys.stdin is not None and sys.stdin.isatty() and sys.stdout is not None and sys.stdout.isatty()
                and not os.environ.get("BROS_NO_PAUSE"))
    except Exception:
        return False


def console(title, text, problem):
    """The screen of a start with no window (finish() with no show; the Quick Launch scripts' until 2026-11-06):
    printed; a problem waits for Enter when someone is at the console (the same rule as their pause after a
    failure). Ctrl+C there means: do not start the game."""
    print("\n[%s]\n%s\n" % (title, text))
    if problem and _interactive():
        try:
            input("Press Enter to start the game anyway -- or close this window to stop.")
        except KeyboardInterrupt:
            return False
        except EOFError:
            pass
    return True


def finish(show=None):
    """Write the report; then tell the player. show(title, text, problem) -> True to start the game, False not to;
    without show, console(). Returns False only if the player chose not to start the game."""
    if _cur is None:
        return True
    save_record()
    try:
        check_registration()
    except Exception as e:                               # pragma: no cover - check_registration catches its own
        _cur.errors.append("registry check: %s" % e)
    try:
        text = report_text()
        p = os.path.join(_cur.game, REPORT)
        with open(p + ".tmp", "w", encoding="utf-8", newline="\r\n") as f:
            f.write(text)
        os.replace(p + ".tmp", p)
    except Exception as e:
        print("[install check] could not write %s: %s" % (REPORT, e))
    ns = notes()
    if not ns:
        return True
    problem = any(p for p, _ in ns)
    body = "\n\n".join(t for _, t in ns) + "\n\nDetails: %s in the game folder." % REPORT
    title = "Install check" + (" -- needs your attention" if problem else "")
    try:
        return bool((show or console)(title, body, problem))
    except Exception as e:
        print("[install check] %s\n(%s)" % (body, e))
        return True


# ------------------------------------------------------------------ the commit check (.githooks/pre-commit)
_INSTALL_TREES = ("00high", "01middle", "02low", "script", "motion")


def _game_rel(path):
    """GameVersions/<v>/<...> -> (v, rel inside the game, via Overlay?) for a path a launch installs, else None."""
    p = _norm(path).split("/")
    if len(p) < 4 or p[0] != "GameVersions":
        return None
    v, rest = p[1], p[2:]
    if rest[0] == "Overlay":
        return (v, "/".join(rest[1:]), True) if len(rest) > 1 else None
    if rest[0].lower() in _INSTALL_TREES:
        return v, "/".join(rest), False
    return None


def _chain(version, base_of):
    out, seen = [], set()
    while version and version not in seen:
        seen.add(version)
        out.append(version)
        version = base_of(version) if base_of else None
    return out


def _bank_files(v, rel, base_of, idx):
    """For a bank file at <tier>/<sub>/<stem>.<ext> in version v: {needed rel: present?} over v's chain."""
    parts = rel.split("/")
    stem = parts[-1].split(".", 1)[0]
    sub = "/".join(parts[1:-1])
    chain = _chain(v, base_of)
    out = {}
    for tier in ("00HIGH", "01MIDDLE"):
        for ext in (".vfxb", ".desktop.vfxt"):
            rp = "%s/%s/%s%s" % (tier, sub, stem, ext)
            out[rp] = any(("GameVersions/%s/%s%s" % (c, pre, rp)).lower() in idx for c in chain
                          for pre in ("", "Overlay/"))
    return stem, out


def commit_check(staged, index, base_of=None):
    """[(path, problem)] for the staged paths (added, modified or deleted; a rename is a delete and an add):
      * no backup -- or anything the effect loader would take for a bank -- in what a launch installs (a version's
        00HIGH, 01MIDDLE, 02LOW, Script, Motion, Overlay) or in Files/Spec Mod/ (copied into the effect folders);
      * every effect bank as <name>.vfxb + <name>.desktop.vfxt in 00HIGH and 01MIDDLE of its version or of a version
        its base.txt chain installs first (subtree or Overlay); a deletion may remove a bank, not part of one.
    base_of(version) -> the parent's folder name, or None."""
    idx = {p.lower() for p in index}
    bad = []
    for path in staged:
        name = _norm(path).rsplit("/", 1)[-1]
        present = _norm(path).lower() in idx
        if _norm(path).startswith("Files/Spec Mod/"):
            if present and (any(p.search(name) for p in _BACKUP_PATTERNS) or is_bank_stray(name)):
                bad.append((path, "a backup in Files/Spec Mod/ (every launch copies those folders into the effect "
                                  "folders, where the game takes '%s' for the real bank)" % name))
            continue
        g = _game_rel(path)
        if g is None:
            continue
        v, rel, _ov = g
        if present and (any(p.search(name) for p in _BACKUP_PATTERNS) or (in_effect_tree(rel) and is_bank_stray(name))):
            why = ("the game's effect loader takes '%s' for the real bank, and nothing ever removes it from a "
                   "player's game" % name if in_effect_tree(rel) else
                   "'%s' would be copied into every player's game" % name)
            bad.append((path, "a backup in a folder the launcher installs (%s); keep backups outside GameVersions/"
                              % why))
            continue
        if not (in_effect_tree(rel) and _BANK_CANONICAL.match(name) and rel.split("/")[0].lower() in _TIERS):
            continue
        stem, files = _bank_files(v, rel, base_of, idx)
        missing = [rp for rp, ok in files.items() if not ok]
        if present and missing:
            bad.append((path, "effect bank %s is incomplete in '%s': %s missing (High graphics reads 00HIGH, "
                              "Medium reads 01MIDDLE, and a bank needs its .desktop.vfxt)"
                              % (stem, v, ", ".join(missing))))
        elif not present and missing and len(missing) < len(files):
            bad.append((path, "deleting this leaves effect bank %s incomplete in '%s' (%s still there): delete "
                              "the whole bank, or none of it" % (stem, v, ", ".join(rp for rp, ok in files.items()
                                                                                       if ok))))
    return bad


def _base_of_worktree(version):
    p = os.path.join("GameVersions", version, "base.txt")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _main(argv):
    if argv[1:2] != ["--commit-check"]:
        print(__doc__)
        return 2
    staged = [p for p in sys.stdin.buffer.read().decode("utf-8", "replace").split("\0") if p.strip()]
    r = subprocess.run(["git", "ls-files", "-z"], capture_output=True)
    if r.returncode:
        print("install_guard: git ls-files failed; the effects check did not run", file=sys.stderr)
        return 1
    index = [p for p in r.stdout.decode("utf-8", "replace").split("\0") if p]
    bad = commit_check(staged, index, _base_of_worktree)
    for path, why in bad:
        print("   %s\n      %s" % (path, why), file=sys.stderr)
    if bad:
        print("REFUSED", flush=True)          # the hook refuses on this line, not on the exit code alone (a crashing
        return COMMIT_REFUSED                 # python can exit 3 too)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
