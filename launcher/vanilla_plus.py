"""vanilla_plus.py -- a version that is the Steam game plus plugins that change no simulation ("vanilla plus").

Berg, 2026-11-13: "add another copy of rebirth of souls (vanilla) to the dev patch, but give it the frame data display
in game for training mode". GameVersions/Bleach Rebirth of Souls Frame Data is the first such version: the Steam
game, unchanged, and framedata.dll (Training > pause > Display Settings > Framedata: Startup / Active / Recovery /
Advantage) and, since 2026-11-14, hitbox.dll (the hit / hurt display: Training > pause > Hitbox Display, drawn by
framedata.dll from the engine's own collision volumes).

A VERSION IS VANILLA PLUS when its folder holds vanilla_plus.json and its base.txt names the vanilla version (so a
launch installs the Steam game's data: launch()'s chain is the vanilla folder, then this one, which ships no data):

    {"format": 1,
     "loader": "Loader/dinput8.dll",                        beside the exe; must carry LOADER_MARKER
     "plugins": ["Loader/ReBalanceOfSouls/framedata.dll",   into <game>/ReBalanceOfSouls/, the only DLLs there
                 "Loader/ReBalanceOfSouls/hitbox.dll"],
     "keep": ["hitbox.txt", "hitbox_reach.txt"],            optional: its plugins' state beside the exe, which its
                                                            start keeps (launcher/vanilla_revert.py PLUGIN_STATE)
     "about": "..."}

The loader is Files/Matchmaking/vanilla_loader.c (built by Files/Matchmaking/build_vanilla_plus.sh): the master's proxy,
log, crash reporting, matchmaking hook and boot shortcut, nothing that changes the game, and it loads only the plugins
it was built for. The master (Files/Matchmaking/dinput8.dll) would change the game, so a version's "loader" that does
not carry LOADER_MARKER is refused.

WHAT A LAUNCH DOES (the main launcher's launch()): vanilla's path up to its proof -- vanilla_revert.run: every Steam
file proven, every file of ours removed but the version's "keep" (its plugins' settings and what they learned: what a
player chose in the version stays from one start to the next) -- then the player's performance choices as for vanilla,
no game mode; then
install() below, then the content pool (launcher/content_pool.py: this version's own, its loader and plugins counted),
then the exe, started directly as for every version with a loader. Quick Launch offers it the three boots.

    read(base_dir, version) -> Info          the version's manifest, checked; VanillaPlusError when it is not right
    install(base_dir, game_path, info, log)  the loader and the plugins, each read back; VanillaPlusError -> no start
    is_vanilla_plus(base_dir, version)       does the folder hold vanilla_plus.json

Python 3.8, standard library only. Every copy: <file>.vp_tmp, then os.replace, then the file is read again.
"""
import hashlib
import json
import os
import shutil
import time

MANIFEST = "vanilla_plus.json"
FORMAT = 1
LOADER_MARKER = b"BROS_VANILLA_LOADER=1"
HOST_MARKER = b"BROS_PLUGIN_HOST_ABI=1"
VANILLA_VERSION = "Bleach Rebirth of Souls"
PLUGIN_DIR = "ReBalanceOfSouls"
LOADER_NAME = "dinput8.dll"
TMP_SUFFIX = ".vp_tmp"
# Where files of other builds go (launcher/leftovers.py's quarantine; a vanilla start clears it out of the game folder)
QUARANTINE = ("_launcher_quarantine", "leftovers")
# A developer's hand-made switches beside the plugins (launcher/leftovers.py HAND_MADE): never moved
HAND_MADE = ("trainlab_probe.txt", "cpuai_rec.txt")


class VanillaPlusError(Exception):
    """The version cannot be installed as it is. A launcher must not start the game on this."""


class Info(object):
    def __init__(self, version, loader, plugins, about, keep=()):
        self.version = version
        self.loader = loader            # absolute path of the version's loader
        self.plugins = plugins          # [(name, absolute path)]
        self.about = about
        self.keep = list(keep)          # file names beside the exe its start keeps (vanilla_revert.run(keep=))

    def files(self):
        """[(game-relative path, absolute source)] of what install() puts down."""
        return [(LOADER_NAME, self.loader)] + [(PLUGIN_DIR + "/" + n, p) for n, p in self.plugins]


def version_dir(base_dir, version):
    return os.path.join(base_dir, "GameVersions", version)


def is_vanilla_plus(base_dir, version):
    return bool(version) and os.path.isfile(os.path.join(version_dir(base_dir, version), MANIFEST))


def _inside(vd, rel, what):
    """The absolute path of a version-relative path that must stay inside the version's folder."""
    if not isinstance(rel, str) or not rel.strip():
        raise VanillaPlusError("%s: %s is not a path" % (MANIFEST, what))
    if os.path.isabs(rel) or ".." in rel.replace("\\", "/").split("/"):
        raise VanillaPlusError("%s: %s (%s) must be a path inside the version's folder" % (MANIFEST, what, rel))
    p = os.path.normpath(os.path.join(vd, *rel.replace("\\", "/").split("/")))
    if not os.path.isfile(p):
        raise VanillaPlusError("%s: %s (%s) is not in the version's folder -- pull again" % (MANIFEST, what, rel))
    return p


def read(base_dir, version):
    """The version's manifest, checked: format, the loader (a file inside the folder, with LOADER_MARKER), the plugins
    (.dll files inside the folder, names unique and not the loader's), base.txt naming the vanilla version."""
    vd = version_dir(base_dir, version)
    mp = os.path.join(vd, MANIFEST)
    try:
        with open(mp, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise VanillaPlusError("GameVersions/%s/%s cannot be read (%s)" % (version, MANIFEST, e))
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise VanillaPlusError("GameVersions/%s/%s: format %r, this launcher reads %d -- update the launcher"
                               % (version, MANIFEST, data.get("format") if isinstance(data, dict) else None, FORMAT))
    try:
        with open(os.path.join(vd, "base.txt"), "r", encoding="utf-8") as f:
            base = f.read().strip()
    except OSError:
        base = None
    if base != VANILLA_VERSION:
        raise VanillaPlusError("GameVersions/%s/base.txt names %r: a vanilla plus version sits on '%s' (the Steam "
                               "game's data), nothing else" % (version, base, VANILLA_VERSION))
    for sub in ("Script", "Motion", "00HIGH", "01MIDDLE", "02LOW", "Overlay"):
        if os.path.isdir(os.path.join(vd, sub)):
            raise VanillaPlusError("GameVersions/%s/%s: a vanilla plus version ships no game data of its own (it "
                                   "would be installed over the Steam game's)" % (version, sub))
    loader = _inside(vd, data.get("loader"), "the loader")
    with open(loader, "rb") as f:
        lb = f.read()
    if LOADER_MARKER not in lb or HOST_MARKER not in lb:
        raise VanillaPlusError("%s is not the vanilla loader (no %s in it) -- the master or another dinput8.dll "
                               "would change the game" % (data.get("loader"), LOADER_MARKER.decode()))
    plugins, seen = [], set()
    raw = data.get("plugins")
    if not isinstance(raw, list):
        raise VanillaPlusError("%s: \"plugins\" must be a list" % MANIFEST)
    for rel in raw:
        p = _inside(vd, rel, "a plugin")
        name = os.path.basename(p)
        if not name.lower().endswith(".dll") or name.lower() in seen or name.lower() == LOADER_NAME:
            raise VanillaPlusError("%s: plugin %s -- a .dll, once, not named %s" % (MANIFEST, rel, LOADER_NAME))
        seen.add(name.lower())
        plugins.append((name, p))
    keep = data.get("keep", [])
    if not isinstance(keep, list):
        raise VanillaPlusError("%s: \"keep\" must be a list of file names" % MANIFEST)
    for k in keep:
        # a file the version's plugins write beside the exe: a plain name, never a DLL, the loader or a path
        if not isinstance(k, str) or not k.strip() or k != os.path.basename(k.replace("\\", "/")) or ".." in k or \
                k.lower().endswith(".dll") or k.lower() == LOADER_NAME:
            raise VanillaPlusError("%s: \"keep\" entry %r -- a file name beside the exe (no folder, not a DLL)"
                                   % (MANIFEST, k))
    return Info(version, loader, plugins, data.get("about") or "", keep)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _put(src, dst):
    """Copy src to dst through dst + TMP_SUFFIX, then read dst back. VanillaPlusError when it does not hold."""
    want = _sha256(src)
    tmp = dst + TMP_SUFFIX
    try:
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            for chunk in iter(lambda: fi.read(1 << 20), b""):
                fo.write(chunk)
        os.replace(tmp, dst)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise VanillaPlusError("%s could not be written (%s). Windows locks a DLL the game has loaded: close the "
                               "game completely and launch again." % (dst, e))
    got = _sha256(dst) if os.path.isfile(dst) else ""
    if got != want:
        raise VanillaPlusError("%s did not read back as installed (built %s, on disk %s)"
                               % (dst, want[:16], got[:16] or "MISSING"))
    return want


def _counts():
    """content_pool.counts: which game paths the online pool's code is made from (None without the module)."""
    try:
        from launcher import content_pool as cp
    except Exception:
        try:
            import content_pool as cp
        except Exception:
            return None
    return cp.counts


def install(base_dir, game_path, info, log=print):
    """The loader beside the exe and the plugins in ReBalanceOfSouls/, each read back; any other .dll in that folder
    removed (the loader would ignore it). Then the files the content pool counts that this version does not ship and
    nothing of it reads -- a rule file another build's plugin or the launcher wrote beside the plugins (gamemodes.txt,
    ...), a switch another build left beside the exe -- are moved to the quarantine (_launcher_quarantine/leftovers/),
    so the pool code is this build's on every PC: the vanilla revert keeps them as the player's, not knowing them.
    A developer's hand-made switches (HAND_MADE) stay, as launcher/leftovers.py leaves them. Returns the lines logged."""
    lines = []

    def say(s):
        lines.append(s)
        log("[vanilla+] " + s)

    if not os.path.isfile(os.path.join(game_path, "BLEACH_Rebirth_of_Souls.exe")):
        raise VanillaPlusError("%s holds no BLEACH_Rebirth_of_Souls.exe" % game_path)
    h = _put(info.loader, os.path.join(game_path, LOADER_NAME))
    say("%s installed (the vanilla loader, sha256 %s)" % (LOADER_NAME, h[:16]))
    pd = os.path.join(game_path, PLUGIN_DIR)
    os.makedirs(pd, exist_ok=True)
    keep = set(n.lower() for n, _p in info.plugins)
    for f in sorted(os.listdir(pd)):
        if f.lower().endswith(".dll") and f.lower() not in keep and os.path.isfile(os.path.join(pd, f)):
            try:
                os.remove(os.path.join(pd, f))
            except OSError as e:
                raise VanillaPlusError("%s/%s could not be removed (%s): close the game and launch again"
                                       % (PLUGIN_DIR, f, e))
            say("%s/%s removed (not a plugin of %s)" % (PLUGIN_DIR, f, info.version))
    for name, src in info.plugins:
        h = _put(src, os.path.join(pd, name))
        say("%s/%s installed (sha256 %s)" % (PLUGIN_DIR, name, h[:16]))
    counts = _counts()
    if counts is None:
        say("launcher/content_pool.py is missing: other builds' files beside the plugins are left as they are")
        return lines
    ours = set([LOADER_NAME]) | set(PLUGIN_DIR.lower() + "/" + n for n in keep)
    todo = []
    for rel_dir in ("", PLUGIN_DIR):
        d = os.path.join(game_path, rel_dir) if rel_dir else game_path
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            rel = (rel_dir + "/" + f) if rel_dir else f
            if (os.path.isfile(os.path.join(d, f)) and counts(rel) and rel.lower() not in ours and
                    not rel.lower().endswith(".dll") and f.lower() not in HAND_MADE):
                todo.append(rel)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for rel in todo:
        src = os.path.join(game_path, *rel.split("/"))
        dst = os.path.join(game_path, *(QUARANTINE + (stamp,) + tuple(rel.split("/"))))
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
        except OSError as e:
            raise VanillaPlusError("%s could not be moved out of the game folder (%s): it would give this PC an online "
                                   "pool of its own" % (rel, e))
        say("%s moved to %s (another build's file: it would give this PC an online pool of its own)"
            % (rel, "/".join(QUARANTINE + (stamp,))))
    return lines


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("python launcher/vanilla_plus.py <repo> <version>    reads and checks the version's manifest")
        sys.exit(2)
    try:
        i = read(sys.argv[1], sys.argv[2])
    except VanillaPlusError as e:
        print("NOT a vanilla plus version as it stands: %s" % e)
        sys.exit(1)
    for rel, src in i.files():
        print("%-40s <- %s" % (rel, src))
    sys.exit(0)
