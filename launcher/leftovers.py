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

PLAYER PROGRESS (content_pool.PLUGIN_STATE: dcbossrush_records.txt, dcbossrush_events.txt ...)
  Not counted, so never moved. Launchers before 2026-11-15 counted and moved them at every launch (Adventure LEVEL 2
  locked again after LEVEL 1, event clears gone): clean() first puts the newest quarantined copy back for any of them
  the game folder no longer has (copied; the quarantine keeps its own).

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
  A launcher without the other versions' Overlays (the public beta, launcher/beta.py) passes known_other_demos(): the
  same cutscenes by size and SHA-256, made from the Dev repo's GameVersions (session mv, 2026-11-23, after a beta
  player on V2.0 kept V1.7's Demo/pl015_evo_ct_sp_break01_2.tdemopkg, which V2.0's registry still lists, and with it
  a pool of his own: Berg, "Do said change yes"). Without Steam's list it moves only KNOWN_OTHER_DEMOS (V1.7's
  Yumichika cutscenes, paths Steam does not ship) and returns KNOWN_OVER_STEAM's (another version's cutscene where the
  game's own should be: Steam's verify puts those back).

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

# Other versions' cutscenes by size and SHA-256 (the module docstring, CUTSCENES), from the Dev repo's GameVersions
# Overlay/Demo (2026-11-23): paths V2.0 does not ship. KNOWN_OTHER_DEMOS: V1.7's (Yumichika, pl015), paths Steam does
# not ship -- moved to the quarantine. KNOWN_OVER_STEAM: V1.6's (Orihime, pl034) and V1.7's over the game's own files
# -- only Steam's verify (or the Dev launcher's backup) puts the game's own back.
KNOWN_OTHER_DEMOS = {
    "Demo/pl015_ct_evolve.tdemopkg": ((1180303, "b794f6fad9fcea8acc2740587b3d736ff3c4ce9acbbf8dfd3fb86151cc50a5e3"),),
    "Demo/pl015_ct_revolut.tdemopkg": ((5727376, "3347e90f4b331122793b625639ab2ddcbdf85f69b4bccbff9ebd490e892bf153"),),
    "Demo/pl015_ct_sp_break01.tdemopkg": ((1995287, "614bda08a161eac447430e16e48c9853e2c78562fb6ee0e52ceaca7030d77b37"),),
    "Demo/pl015_ct_start.tdemopkg": ((1152329, "7a7a9cdd2831b0e61ac04fcb254180b24d712d32f32f0c6352ad97d29c062489"),),
    "Demo/pl015_ct_syunpo_out_just.tdemopkg": ((430923, "c04a1ff9f050508129408cd4c3e38d75d7341068d29b995ab66ef8ba911b0aac"),),
    "Demo/pl015_ct_win_y.tdemopkg": ((483066, "556d60f9d71d0771fd8755b86e5ae79963c25f7f9e6ba0d591862ed8caa7cc9e"),),
    "Demo/pl015_evo_ct_revolut.tdemopkg": ((5684592, "d41c2fa7328198ed68fecab3cbcaaa56906d60c3de4935e72f7e984644fa70aa"),),
    "Demo/pl015_evo_ct_sp_break01.tdemopkg": ((2080329, "2ac58dcac560d72bde62e83a6ebd88f831f693c030fd45a9b1dc39ca0685ebc3"),),
    "Demo/pl015_evo_ct_sp_break01_2.tdemopkg": ((1854068, "1cb1900d6aa74b9f1ff6891c149db458d3b1b2496b01ab22e2177d01e6031df9"),),
    "Demo/pl015_evo_ct_sp_break01_maxout.tdemopkg": ((356369, "f0cb89605e47a7353c09b3603e524800a8bc7a79ee17ca8a46bdf8fdd867f191"),),
    "Demo/pl015_evo_ct_sp_break02.tdemopkg": ((1854068, "1cb1900d6aa74b9f1ff6891c149db458d3b1b2496b01ab22e2177d01e6031df9"),),
    "Demo/pl015_evo_ct_sp_break02_maxout.tdemopkg": ((316228, "c7319cf484a0e3c1e1779cd39ef7ea9376e5a0203eb97ec010a9e9316c3f0e68"),),
    "Demo/pl015_evo_ct_syunpo_out_just.tdemopkg": ((431243, "3102399e628ad0b7b3b5fdeb77ed00b846084727bc7a20caeb9b5044e56ace0e"),),
    "Demo/pl015_evo_ct_win_y.tdemopkg": ((506567, "13529bf780313add7bcbf6f015a14f72ce543d084b7f37fc3dc5864c7b10a49b"),),
    "Demo/pl015_rev_ct_reset.tdemopkg": ((2276943, "ca5ac4cafedee913efe57ab3794319c64d9b5fffe0a185fa9011223422b7eb16"),),
    "Demo/pl015_rev_ct_sp_break01.tdemopkg": ((6082642, "940e37e7803def9900c53f51da1c536bdde5e516ddd12588b986b7c1a9089e85"),),
    "Demo/pl015_rev_ct_sp_break01_maxout.tdemopkg": ((241288, "be182e4d1d8cd7fc349386c4970e3a52397f83a2fae09c239b60dd80f5de7ff2"),),
    "Demo/pl015_rev_ct_syunpo_out_just.tdemopkg": ((404153, "16f24a346689792ce306ec5fd7135090518b4529f20168dcb6b207f7860c6d91"),),
    "Demo/pl015_rev_ct_win_y.tdemopkg": ((1241431, "f344b7667b9314b2097545c55cd156389c7d1fef85960e14711a2b2e1381dd57"),),
}
KNOWN_OVER_STEAM = {
    "Demo/pl015_ct_sp_break01_maxout.tdemopkg": ((216620, "2e79d376f85d6ce6c9eb7ef844517f67bc50cd7311ad1dc53d4258f8ea29b178"),),
    "Demo/pl034_ct_evolve.tdemopkg": ((1435402, "7b52993f8058ebf96f3573925e58bc3acb6c922095e182b99e55a4b3c5f80a7a"),),
    "Demo/pl034_ct_sp_break01.tdemopkg": ((847697, "4e7a3a0f0d699a7c0b029aae5e2e603e822e8d4dbb3246cf7e28f989f1e31e22"),),
    "Demo/pl034_ct_sp_break01_maxout.tdemopkg": ((437304, "f447cd3211410e962f5385c18caeb59d08b3366b875c839b3354271c951635a9"),),
    "Demo/pl034_ct_stage_atk_r_out.tdemopkg": ((74508, "c1bb9202092c1ab8399af77f6a4593a3fa01cfd8bb2627fb548e781a6bfddf65"),),
    "Demo/pl034_ct_stage_atk_u_out.tdemopkg": ((74612, "929aa0de7594db0db48660dd0002780a5e53b872d70f7cdcfc41814557a5df0f"),),
    "Demo/pl034_ct_stage_dam_r_out.tdemopkg": ((74913, "627fc42e99bb96a052adcb5881dea4476615558484f550d5580d01e871a14649"),),
    "Demo/pl034_ct_stage_dam_u_out.tdemopkg": ((75849, "92c2a1bfe5471ed0852aa97393d161a234a9da89323077b85cc51a4d4d3f21db"),),
    "Demo/pl034_ct_start.tdemopkg": ((1304107, "dabc8c47b304493890702ed42123f798f2fdea9ab8fe1b6db73e5346df71a8c5"),),
    "Demo/pl034_ct_syunpo_out_just.tdemopkg": ((291091, "489a9a2afd81dce76f1a7e1b12787c0698be383a7474ddda7cdcf5d58c2a06b1"),),
    "Demo/pl034_ct_win_y.tdemopkg": ((813414, "0298dd10d44b9cd8e8be6159740487da7fd0b7aca2dcef3461bd5c626cd22e96"),),
    "Demo/pl034_evo_ct_sp_break01.tdemopkg": ((847061, "971212b1473c59e26966150079f2e105af105b22feac017398c6899ac1e94998"),),
    "Demo/pl034_evo_ct_sp_break01_maxout.tdemopkg": ((437373, "1bd2f188c38c74d1251c3bcecf44d3508de68d04e98e9e66d65fa509ee441be3"),),
    "Demo/pl034_evo_ct_sp_break02.tdemopkg": ((1189929, "e53835423a45da3979f3b2919178c9a1737e42dc5216b8ac30d5cc2b4bba40da"),),
    "Demo/pl034_evo_ct_sp_break02_maxout.tdemopkg": ((206905, "70e275ca03a0732b995f186141a069d4facd5fa9a452c0dce60c1d441b320fbb"),),
    "Demo/pl034_evo_ct_stage_atk_r_out.tdemopkg": ((74566, "bef956d818981ced0d0424ad03c92682abbc0352bbe981e3d0f7d4cf2e1abc26"),),
    "Demo/pl034_evo_ct_stage_atk_u_out.tdemopkg": ((74657, "a79cd14e33ad76f6781005503c61a9f089ae0e69e4a243dd16632680ddb2b08b"),),
    "Demo/pl034_evo_ct_stage_dam_r_out.tdemopkg": ((75062, "e2440ece6ccc23cbd930c1f47a355036c0bea97aa4ad45d6b587ed82030bfef3"),),
    "Demo/pl034_evo_ct_stage_dam_u_out.tdemopkg": ((75855, "966e739045434a81ab0d388a6fe7a2ac979ea91f5b52683805f9dc90b873ce64"),),
    "Demo/pl034_evo_ct_syunpo_out_just.tdemopkg": ((290510, "8fec800c3fcedd342a6655b9be3fd0d6800f634e203af981319dfc9deb341d80"),),
    "Demo/pl034_evo_ct_win_y.tdemopkg": ((391688, "90e62a90e3ce1aeb0f1134c586d3cf82b13875e0144cb54c0eb481e159925f1c"),),
}

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


def restore_progress(game, log=print):
    """Put back the newest quarantined copy of each player-progress file the game folder lacks. Returns the names."""
    back = []
    qroot = os.path.join(game, *QUARANTINE)
    for name in getattr(_cp(), "PLUGIN_STATE", ()):
        dst = os.path.join(game, PLUGINS, name)
        if os.path.exists(dst) or not os.path.isdir(qroot):
            continue
        best = None
        try:
            stamps = os.listdir(qroot)
        except OSError:
            stamps = []
        for st in stamps:
            src = os.path.join(qroot, st, PLUGINS, name)
            try:
                m = os.path.getmtime(src)
            except OSError:
                continue
            if best is None or m > best[0]:
                best = (m, src)
        if best is None:
            continue
        try:
            shutil.copy2(best[1], dst)
            back.append(name)
            log("leftovers: put back %s/%s (the player's progress; an older launcher had moved it)" % (PLUGINS, name))
        except OSError as e:
            log("leftovers: could not put back %s/%s: %s" % (PLUGINS, name, e))
    return back


def clean(game, keep_plugin_txt, keep_root, other_root_markers=(), log=print):
    """Move plan()'s files to the quarantine. Returns the game-relative paths moved."""
    restore_progress(game, log)
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
    """others: {game-relative 'Demo/...' path: [another version's Overlay copy, or its (size, SHA-256), ...]} --
    cutscenes other versions ship and the version being launched does not. -> the game-relative paths that count in the pool (the installed htable
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
            same = [c for c in others[rel] if (c[0] == size if isinstance(c, tuple)
                                               else os.path.isfile(c) and os.path.getsize(c) == size)]
            if same:
                mine = _hash(p, "sha256")
                if any((c[1] if isinstance(c, tuple) else _hash(c, "sha256")) == mine for c in same):
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


def known_other_demos():
    """others (for demo_plan / fix_demo) from the built-in tables: for a launcher without the other versions' Overlays."""
    out = {}
    for tab in (KNOWN_OTHER_DEMOS, KNOWN_OVER_STEAM):
        for rel, copies in tab.items():
            out.setdefault(rel, []).extend(copies)
    return out


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
            # no Steam list (the public beta): the built-in tables decide -- a path Steam does not ship is moved, one
            # over the game's own is returned; any other is not checked
            known = [r for r in todo if r in KNOWN_OTHER_DEMOS]
            over = [r for r in todo if r in KNOWN_OVER_STEAM and r not in KNOWN_OTHER_DEMOS]
            rest = [r for r in todo if r not in known and r not in over]
            if rest:
                log("[leftovers] %d cutscene(s) of another version, not checked against Steam's list: %s"
                    % (len(rest), ", ".join(rest[:3])))
            left.extend(over)
            if over:
                log("[leftovers] %d cutscene(s) of another version where the game's own should be: %s -- Steam's "
                    "verify puts them back" % (len(over), ", ".join(over[:3])))
            todo = known
            if not todo:
                return left
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for rel in todo:
            dst = os.path.join(game, *rel.split("/"))
            ent = lst.files.get(rel.lower()) if lst is not None else None
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
    ov = os.path.join(here, "GameVersions", "ReBalance of Souls V2.0", "Overlay")
    keep_txt = os.listdir(os.path.join(ov, PLUGINS)) if os.path.isdir(os.path.join(ov, PLUGINS)) else []
    keep_root = [n for n in os.listdir(ov) if os.path.isfile(os.path.join(ov, n))] if os.path.isdir(ov) else []
    todo = plan(game, keep_txt, keep_root)
    for rel, why in todo:
        print("would move %s (%s)" % (rel, why))
    print("%d file(s)" % len(todo))
    gv = os.path.join(here, "GameVersions")
    others = other_demos(gv, ["ReBalance of Souls V2.0"])
    cut = demo_plan(game, others)
    for rel in cut:
        print("another version's cutscene: %s (put back from a proven copy, else Steam's verify)" % rel)
    print("%d cutscene(s) of another version (of %d paths other versions ship)" % (len(cut), len(others)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
