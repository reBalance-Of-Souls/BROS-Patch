"""leftovers.py -- files other builds left in the game folder that put a player in an online pool of his own, moved
out at every launch (pass rt, 2026-11-09).

THE SAME FILE SITS IN BOTH REPOSITORIES (Dev Environment and BROS-Patch, launcher/leftovers.py), byte for byte.

WHY (Berg, 2026-11-09 12:18 CET: "sure we know why now, but how do we just make it so that it launches the same exact
version that I have right now for other people, like a default so we avoid having to do this 1 by 1")
  The Room Match check (launcher/room_check.py) showed two testers on Berg's own commit who could not find his rooms:
  one had V1.6/V1.7's bros_pl015_rework.txt and bros_roster_v13.txt beside the exe, the other an old
  ReBalanceOfSouls/dcbossrush_events.txt that no build ships any more. The pool code counts every ReBalanceOfSouls/*.txt
  and the bros_*.txt beside the exe (content_pool.py FORMAT 2), and an install never removes what another build left
  (both launchers keep such orphans on purpose, so that a stock file is never lost). Plugin DLLs, Script/ and Motion/
  were already mirrored at every launch; the plugins' rule files and the version markers were not.

WHAT MOVES -- to <game>/_launcher_quarantine/leftovers/<time>/<the same path>; nothing is ever deleted
  - ReBalanceOfSouls/*.txt that the version being launched does not ship, that the launcher does not make itself
    (gamemodes.txt and tag2v2_hudclone.txt, launcher/room_modes.py) and that this launch did not write;
  - beside the exe, version markers that the version being launched does not ship: bros_roster_v<N>.txt,
    bros_pl015_rework.txt, and any other counted .txt a version's Overlay puts at the game root.
  Only files the pool code counts are ever moved (content_pool.counts), so a move can only make the code the build's.

NEVER MOVED
  The player's own switches beside the exe (bros_zangetsu.txt, bros_tools.txt, bros_fulldiag.txt, bros_net.txt,
  bros_diag.txt, ...): their launcher modules write and remove them from the player's choices. A developer's own
  switches beside the plugins (HAND_MADE: trainlab_probe.txt, cpuai_rec.txt -- made by hand, read by trainlab.dll and
  cpuai.dll). Anything the version ships, anything written during this launch, anything outside those two places.

CUTSCENES (fix_demo; the Dev launcher, which has every version's Overlay)
  A Demo/ file counts when the installed Fnames/file_exist.htable lists it. V1.6 writes its own Orihime cutscenes over
  20 of the game's (pl034), V1.7 one of Yumichika's (pl015) and new ones the V1.5 htable lists too. A switch back puts
  the game's own back only from the backup the launcher took the first time; a PC that lost that record keeps another
  version's cutscene, and its player another pool. So, for a counted Demo/ file that another version's Overlay ships,
  the version being launched does not, and whose bytes ARE that other version's (size, then SHA-256):
  - a path Steam does not ship: moved to the quarantine, as above (the game has no file of its own there);
  - a path Steam ships: replaced by a copy whose SHA-1 is Steam's (vanilla_revert's sources: the launcher's backup);
  - else left as it is and returned: only Steam's verify can put it back (the launcher asks the player).
  Steam's list (vanilla_revert.steam_list) is read only when such a file is found. A cutscene that is neither the game's
  nor a current version's (an older build's) is not recognised here: a vanilla start proves every file against Steam.

USE
  mark_start() when a launch begins (before anything is installed); clean(game, keep_plugin_txt, keep_root,
  other_root_markers, log) and fix_demo(game, others, steam, sources, log) after everything is installed and before
  content_pool.write_code(). Never raise: a file that cannot be moved is reported and the launch goes on (its pool is
  then what it would have been before).

  python launcher/leftovers.py <game folder>     what a launch of the current V1.5 would move, without moving it
"""

import hashlib
import os
import re
import shutil
import sys
import time

QUARANTINE = ("_launcher_quarantine", "leftovers")
PLUGINS = "ReBalanceOfSouls"
LAUNCHER_MADE = ("gamemodes.txt", "tag2v2_hudclone.txt")       # launcher/room_modes.py, beside the plugins
HAND_MADE = ("trainlab_probe.txt", "cpuai_rec.txt")             # a developer's switches (trainlab.dll, cpuai.dll)
MARKER_RX = re.compile(r"bros_roster_v\d+\.txt\Z")
MARKERS = ("bros_pl015_rework.txt",)
FRESH_S = 2.0                                                   # written this close to the start: this launch's
VERIFY_URL = "steam://validate/1689620"                         # Steam: Verify integrity of game files
DEMO = "Demo"

_t0 = [None]


def mark_start(now=None):
    """A launch begins: anything written from now on is this launch's."""
    _t0[0] = time.time() if now is None else now


def _cp():
    try:
        from launcher import content_pool as cp
    except Exception:
        import content_pool as cp
    return cp


def _counts(rel):
    return _cp().counts(rel)


def _fresh(path):
    if _t0[0] is None:
        return False
    try:
        return os.path.getmtime(path) >= _t0[0] - FRESH_S
    except OSError:
        return False


def plan(game, keep_plugin_txt, keep_root, other_root_markers=()):
    """[(game-relative path, why)] that clean() would move. keep_plugin_txt: the ReBalanceOfSouls/*.txt names the
    version ships; keep_root: the names it ships beside the exe; other_root_markers: names other versions put there
    (all names compared in lower case)."""
    keep_txt = {n.lower() for n in keep_plugin_txt} | set(LAUNCHER_MADE) | set(HAND_MADE)
    keep_r = {n.lower() for n in keep_root}
    others = {n.lower() for n in other_root_markers}
    out = []
    pd = os.path.join(game, PLUGINS)
    try:
        names = sorted(os.listdir(pd)) if os.path.isdir(pd) else []
    except OSError:
        names = []
    for n in names:
        low = n.lower()
        rel = PLUGINS + "/" + n
        if not low.endswith(".txt") or low in keep_txt or not os.path.isfile(os.path.join(pd, n)):
            continue
        if not _counts(rel) or _fresh(os.path.join(pd, n)):
            continue
        out.append((rel, "a plugin rule file this version does not ship"))
    try:
        names = sorted(os.listdir(game))
    except OSError:
        names = []
    for n in names:
        low = n.lower()
        if not low.endswith(".txt") or low in keep_r or not (MARKER_RX.match(low) or low in MARKERS or low in others):
            continue
        p = os.path.join(game, n)
        if not os.path.isfile(p) or not _counts(n) or _fresh(p):
            continue
        out.append((n, "another version's marker"))
    return out


def clean(game, keep_plugin_txt, keep_root, other_root_markers=(), log=print):
    """Move plan()'s files to the quarantine. Returns the game-relative paths moved."""
    moved = []
    todo = plan(game, keep_plugin_txt, keep_root, other_root_markers)
    if not todo:
        return moved
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for rel, why in todo:
        src = os.path.join(game, *rel.split("/"))
        dst = os.path.join(game, *QUARANTINE, stamp, *rel.split("/"))
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            moved.append(rel)
            log("[leftovers] moved %s out of the game folder (%s): it gave this PC an online pool of its own -- "
                "kept in %s" % (rel, why, "/".join(QUARANTINE + (stamp,))))
        except OSError as e:
            log("[leftovers] could not move %s (%s): %s -- the pool may not be the build's" % (rel, why, e))
    return moved


def _hash(path, algo):
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def demo_plan(game, others):
    """others: {game-relative 'Demo/...' path: [another version's Overlay copy, ...]} -- cutscenes other versions ship
    and the version being launched does not. -> the game-relative paths that count in the pool (the installed htable
    lists them), were not written by this launch, and hold one of those copies' bytes."""
    try:
        cp = _cp()
        reg = cp.read_registry(game)
    except Exception:
        return []
    out = []
    for rel in sorted(others):
        p = os.path.join(game, *rel.split("/"))
        try:
            if not os.path.isfile(p) or _fresh(p) or not cp.demo_registered(rel, reg):
                continue
            size = os.path.getsize(p)
            same = [c for c in others[rel] if os.path.isfile(c) and os.path.getsize(c) == size]
            if same:
                mine = _hash(p, "sha256")
                if any(_hash(c, "sha256") == mine for c in same):
                    out.append(rel)
        except OSError:
            continue
    return out


def other_demos(versions_dir, chain):
    """{game-relative 'Demo/...' path: [Overlay copy, ...]} for the cutscenes the versions under versions_dir (the
    repo's GameVersions) ship outside the chain (the names of the versions the launch installs), minus any path the
    chain ships."""
    out, mine = {}, set()
    try:
        names = sorted(os.listdir(versions_dir))
    except OSError:
        return out
    for v in names:
        d = os.path.join(versions_dir, v, "Overlay", DEMO)
        for dp, _ds, fs in os.walk(d):
            for f in fs:
                src = os.path.join(dp, f)
                rel = DEMO + "/" + os.path.relpath(src, d).replace(os.sep, "/")
                if v in chain:
                    mine.add(rel.lower())
                else:
                    out.setdefault(rel, []).append(src)
    return {r: c for r, c in out.items() if r.lower() not in mine}


def fix_demo(game, others, steam=None, sources=None, log=print):
    """Another version's cutscenes out of the way (the module docstring, CUTSCENES). steam: a callable returning
    vanilla_revert.steam_list()'s object (.files {lower path: (path, size, sha1 or None)}, .hashed), called once and
    only when demo_plan() finds something; sources: a callable rel -> [candidate copies of the game's own file]
    (vanilla_revert._stock_sources). Returns the game-relative paths only Steam's verify can put back. Never raises."""
    left = []
    try:
        todo = demo_plan(game, others)
        if not todo:
            return left
        try:
            lst = steam() if steam is not None else None
        except Exception as e:
            lst = None
            log("[leftovers] Steam's file list could not be read (%s)" % e)
        if lst is None:
            log("[leftovers] %d cutscene(s) of another version, not checked against Steam's list: %s"
                % (len(todo), ", ".join(todo[:3])))
            return left
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for rel in todo:
            dst = os.path.join(game, *rel.split("/"))
            ent = lst.files.get(rel.lower())
            if ent is None:
                q = os.path.join(game, *QUARANTINE, stamp, *rel.split("/"))
                try:
                    os.makedirs(os.path.dirname(q), exist_ok=True)
                    shutil.move(dst, q)
                    log("[leftovers] moved %s out of the game folder (another version's cutscene, not a game file): "
                        "it gave this PC an online pool of its own -- kept in %s"
                        % (rel, "/".join(QUARANTINE + (stamp,))))
                except OSError as e:
                    log("[leftovers] could not move %s (another version's cutscene): %s" % (rel, e))
                continue
            want = ent[2] if lst.hashed else None
            done = False
            for src in ((sources(rel) if sources is not None else []) if want else []):
                try:
                    if os.path.abspath(src) == os.path.abspath(dst) or _hash(src, "sha1") != want:
                        continue
                    tmp = dst + ".lo_tmp"
                    shutil.copy2(src, tmp)
                    os.replace(tmp, dst)
                    if _hash(dst, "sha1") == want:
                        done = True
                        log("[leftovers] %s: another version's cutscene replaced by the game's own (from %s, "
                            "SHA-1 as Steam's)" % (rel, os.path.relpath(src, game).replace(os.sep, "/")))
                        break
                except OSError as e:
                    log("[leftovers] %s: the game's own copy could not be put back from %s (%s)" % (rel, src, e))
            if not done:
                left.append(rel)
        if left:
            log("[leftovers] %d cutscene(s) of another version where the game's own should be, and no proven copy of "
                "the game's own: %s -- Steam's verify puts them back" % (len(left), ", ".join(left[:3])))
    except Exception as e:
        log("[leftovers] cutscenes not checked: %s" % e)
    return left


def main(argv):
    if len(argv) < 1 or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    game = argv[0]
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ov = os.path.join(here, "GameVersions", "ReBalance of Souls V1.5", "Overlay")
    keep_txt = os.listdir(os.path.join(ov, PLUGINS)) if os.path.isdir(os.path.join(ov, PLUGINS)) else []
    keep_root = [n for n in os.listdir(ov) if os.path.isfile(os.path.join(ov, n))] if os.path.isdir(ov) else []
    todo = plan(game, keep_txt, keep_root)
    for rel, why in todo:
        print("would move %s (%s)" % (rel, why))
    print("%d file(s)" % len(todo))
    gv = os.path.join(here, "GameVersions")
    others = other_demos(gv, ["ReBalance of Souls V1.5"])
    cut = demo_plan(game, others)
    for rel in cut:
        print("another version's cutscene: %s (put back from a proven copy, else Steam's verify)" % rel)
    print("%d cutscene(s) of another version (of %d paths other versions ship)" % (len(cut), len(others)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
