"""match_pool.py -- the online match pool of the BROS-Patch launchers (2026-10-04; history BROS-PATCH n219-n221).

Patched players only meet players with the same pool code. The launchers write it to <game>\\patch_ranked.txt and
the loader turns it into the Steam lobby "issuer" tag, search filter and join guard (Files/Matchmaking/
dinput8_proxy.c, PART 2; a game mode's own loader adds its pool tag on top).

WHY NOT THE COMMIT HASH (the rule until 2026-10-04)
  The code was crc32("<git rev-parse --short HEAD>|<game version>"). Two faults, measured in n220:
  1. Every push made a new pool -- also the pushes that change nothing the game loads (launcher scripts, docs,
     .gitignore: 8 of the 28 pushes from 2026-09-15 to 10-03). Two players who launched a few hours apart were in
     different pools, saw no rooms, and nothing said why; "apply again / vanilla then patch / reinstall" worked only
     because each one pulled the newest commit.
  2. `--short` is not the same on every machine: git sizes it from the number of objects in the LOCAL packs
     (duplicates counted) and from the user's core.abbrev, so one commit can read 7, 8 or 12 characters on two PCs --
     two different codes.

THE RULE NOW
  The pool comes from what the launchers install into the game, identified by git's own content ids at HEAD --
  identical on every clone, whatever its packs or settings:
      GameVersions/<the selected version>   that version's data (Script, Motion, 00HIGH, 01MIDDLE, Demo, ...)
      GameModes                             the modes' data and loaders, Team Battle's table
      Reworks                               (when the folder exists)
      Files/Spec Mod                        the performance-mode effect files
      Files/Matchmaking/dinput8.dll         the loader
      Files/Matchmaking/Plugins/*.dll       the plugins (their sources and README are not installed: not counted)
  plus the version's name and POOL_REV. The same content gives the same pool, whatever the commit; any change to what
  the game loads gives a new pool, exactly as before (mixed builds would desync).

POOL_REV
  Bump it when a change to the launchers alters WHAT gets installed into the game or HOW (a new folder copied, a copy
  rule changed, a file rewritten on the way): the content ids cannot see the launchers' own logic.
"""
import hashlib
import os
import subprocess
import zlib

POOL_REV = 1

LOADER = "Files/Matchmaking/dinput8.dll"
PLUGINS = "Files/Matchmaking/Plugins/"
SHARED = ("GameModes", "Reworks", "Files/Spec Mod", LOADER)


class PoolError(Exception):
    """The pool code cannot be determined or put in place: the launch must stop, not start in a wrong pool."""


def _ls_tree(base_dir, rev, paths):
    """[(path, type, object id)] from `git ls-tree -z <rev> -- <paths>` (paths that do not exist are left out)."""
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        r = subprocess.run(["git", "-C", base_dir, "ls-tree", "-z", rev, "--"] + list(paths),
                           capture_output=True, timeout=60, **kw)
    except Exception as e:
        raise PoolError("git could not be run in %s (%s)" % (base_dir, e))
    if r.returncode != 0:
        raise PoolError("git ls-tree %s failed in %s: %s"
                        % (rev, base_dir, r.stderr.decode("utf-8", "replace").strip()))
    out = []
    for rec in r.stdout.split(b"\0"):
        if rec:
            meta, path = rec.split(b"\t", 1)
            _mode, typ, oid = meta.split(b" ")
            out.append((path.decode("utf-8", "surrogateescape"), typ.decode("ascii"), oid.decode("ascii")))
    return out


def content_lines(base_dir, game_version, rev="HEAD"):
    """The sorted 'type id path' lines the pool is made of (shown in the launcher's log, compared in tests)."""
    version = "GameVersions/" + game_version
    top = _ls_tree(base_dir, rev, [version] + list(SHARED))
    plugins = [e for e in _ls_tree(base_dir, rev, [PLUGINS]) if e[1] == "blob" and e[0].lower().endswith(".dll")]
    names = set(p for p, _t, _o in top)
    if LOADER not in names:
        raise PoolError("%s is not in the launcher's repository at %s" % (LOADER, rev))
    lines = ["%s %s %s" % (t, o, p) for p, t, o in top + plugins]
    if version not in names:
        # A version folder git does not track (made by hand): named, but its content cannot be identified.
        lines.append("untracked %s" % version)
    return sorted(lines)


def content_id(base_dir, game_version, rev="HEAD"):
    return hashlib.sha1("\n".join(content_lines(base_dir, game_version, rev)).encode("utf-8")).hexdigest()


def match_code(base_dir, game_version, rev="HEAD"):
    """(code, content id). The code range is the old one: 100000-899999 (0, 1, 8 and 256 are reserved)."""
    cid = content_id(base_dir, game_version, rev)
    seed = "pool%d|%s|%s" % (POOL_REV, cid, game_version)
    return 100000 + (zlib.crc32(seed.encode("utf-8")) % 800000), cid


def write_code(game_dir, code):
    """<game>\\patch_ranked.txt = "<code>\\n" (the loader reads line 1 with atoi), through a temporary file, read back."""
    path = os.path.join(game_dir, "patch_ranked.txt")
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write("%d\n" % code)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        with open(path) as f:
            back = f.read()
    except OSError as e:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise PoolError("the match code could not be written to %s (%s)" % (path, e))
    if back.strip() != str(code):
        raise PoolError("the match code did not read back from %s" % path)
