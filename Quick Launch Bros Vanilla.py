import os
import json
import hashlib
import re
import shutil
import subprocess
import sys
import platform
import zlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

GAME_VERSION = "Bleach Rebirth of Souls" 

config_path = os.path.join(BASE_DIR, "Json", "config.json")
with open(config_path, "r") as f:
    config = json.load(f)

game_path = config.get("GAME_PATH", "")
if game_path == "":
    input("Your game path is empty, please run the normal launcher first to set a game path,press Enter to quit")
    exit()
gameMode = "DEFAULT"
reworks = ["OFF"]

# Dev leftovers that sit in the content folders and are not game assets. The
# old injection copied every one of them into players' game folders: 22 .bak,
# 4 .bat, the fsv2csv toolchain including its two zero-byte "fsv2csv.py to_csv"
# artifacts, and Explorer's "pl018_cos00_00 (2).lds" duplicates.
#
# Matching is on the file name only, never the path, so a real asset such as
# COM_tm_HitSlash_00.desktop.vfxt is untouched by the desktop.ini rule. There is
# deliberately no .csv rule: the game genuinely loads .csv assets --
# Script/ObjectConfig/pl027_menu_minion00.csv is referenced by the exe.
_EXCLUDE_EXACT = {"thumbs.db", "desktop.ini", ".gitkeep", ".gitignore", ".ds_store"}
_EXCLUDE_PATTERNS = (
    re.compile(r"\.bak$", re.I),
    re.compile(r"_bak$", re.I),
    re.compile(r"\s\(\d+\)\.", re.I),
    re.compile(r"\.(bat|py)(\s|$)", re.I),
)


def _is_excluded(name):
    """True for dev leftovers that should never reach the game."""
    if name.lower() in _EXCLUDE_EXACT:
        return True
    return any(p.search(name) for p in _EXCLUDE_PATTERNS)


def get_snapshot():
    try:
        result = subprocess.run(
            ["git", "-C", BASE_DIR, "rev-parse", "--short", "HEAD"],
            check=True, capture_output=True, text=True
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def pulling_from_git():
    # Ensure git can write the deep Effect/spfx/... paths that blow past the
    # legacy 260-char Windows limit. core.longpaths makes git use \\?\ extended
    # paths internally -- no admin, no registry change, no reboot. A partial
    # "Filename too long" clone then self-heals on launch: the objects are
    # already downloaded, so the reset --hard below writes the missing
    # long-path files with zero action from the user.
    subprocess.run(["git", "-C", BASE_DIR, "config", "core.longpaths", "true"], capture_output=True, text=True)
    if not os.path.exists(os.path.join(BASE_DIR, "BalanceLeadTools", "DevToken.txt")):
        subprocess.run(["git", "-C", BASE_DIR, "fetch"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", BASE_DIR, "reset", "--hard", "origin/main"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", BASE_DIR, "clean", "-fd", "-e", "Json"], check=True, capture_output=True, text=True)
    return subprocess.run(["git", "-C", BASE_DIR, "pull"], check=True, capture_output=True, text=True)


def _relaunch_if_code_changed(result):
    """A pull that lands new launcher code cannot take effect in this process.

    Python already holds the old module in memory, so the run that fetches an
    update would execute the PREVIOUS code against the new files -- which is
    exactly how new data can land while the code that installs it does not. So
    re-exec once, marked, so a pull that keeps reporting changes cannot loop."""
    try:
        if result is None or "Already up to date." in (result.stdout or ""):
            return
        if os.environ.get("BROS_LAUNCHER_RELAUNCHED") == "1":
            return
        child_env = dict(os.environ)
        child_env["BROS_LAUNCHER_RELAUNCHED"] = "1"
        cmd = [sys.executable] if getattr(sys, "frozen", False)               else [sys.executable, os.path.abspath(__file__)]
        subprocess.Popen(cmd, env=child_env, cwd=BASE_DIR)
        sys.exit()
    except SystemExit:
        raise
    except Exception as e:
        print("Auto-relaunch failed, continuing with the code already loaded:", e)


def open_file(path):
    if platform.system() == "Windows":
        os.startfile(path)
    elif platform.system() == "Darwin":
        subprocess.run(["open", path])
    else:
        subprocess.run(["xdg-open", path])


# ---------------------------------------------------------------------------
# Restoring stock, instead of mirroring a snapshot
#
# This launcher used to call an injectFolder() that ran `robocopy /MIR` for
# Script and Motion. A mirror deletes by omission: anything in the game folder
# the snapshot does not list is removed. That is wrong twice over for a return
# to vanilla.
#
#   * the player's own files -- costume mods and the like -- are in no
#     snapshot, so a mirror destroys them
#   * so would a stock file the snapshot happens to lack
#
# And it installed 42 files the game has never had, because the snapshot itself
# carries dev leftovers: .bak copies, the fsv2csv toolchain, *_modded packages,
# and two modded animation packages under stock names.
#
# So: no mirror. Two passes that never guess.
#
#   pass 1  copy in only what the stock manifest confirms is a real game file,
#           and only where the bytes actually differ
#   pass 2  delete only what the manifest proves the patch created, leave a
#           stock path this version cannot replace, and never touch a file that
#           is in no manifest and in no version -- that file is the player's
#
# With no manifest on disk, pass 2 does nothing at all. Every deletion that
# rests on a guess is the guess that removed Fnames/filename.bin on 2026-09-09
# and left the game faulting at exe+0x1C8187 with no crashlog.
# ---------------------------------------------------------------------------

STOCK_MANIFEST = os.path.join(BASE_DIR, "Files", "Stock", "stock_manifest_sha256.txt")

# The trees a version folder maps onto the game root.
VERSION_SUBTREES = ("Script", "Motion", "00HIGH", "01MIDDLE", "02LOW", "Demo")

# Stock copies of game files that live at the game root rather than in one of
# the trees above. Not in Overlay/, whose bookkeeping is shared with the other
# launchers.
ROOT_SUBTREE = "Root"

# Where a file goes before stock overwrites it. Returning to vanilla means
# stock wins, including over a mod that edited a stock file in place rather
# than adding a new one. That player does not lose the file, but they would
# lose their edit silently. So a copy is kept first.
USER_OVERWRITES = "_launcher_user_overwrites"


def _load_stock_manifest():
    """{game-relative path: (sha256 or '-', size)}, or {} when absent.

    An empty manifest is not an error: every caller degrades to "change
    nothing" rather than acting on a guess.
    """
    out = {}
    try:
        with open(STOCK_MANIFEST, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 3:
                    out[parts[2].replace("\\", "/")] = (parts[0].lower(), int(parts[1]))
    except FileNotFoundError:
        print("[stock] no stock manifest on disk -- nothing will be deleted")
    except Exception as e:
        print(f"[stock] could not read the stock manifest ({e}) -- nothing will be deleted")
    return out


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _version_files(gameVersion):
    """[(absolute source, game-relative destination)] for one version's content
    trees, with the dev leftovers already filtered out."""
    out = []
    for sub in VERSION_SUBTREES + (ROOT_SUBTREE,):
        root = os.path.join(BASE_DIR, "GameVersions", gameVersion, sub)
        if not os.path.isdir(root):
            continue
        # Root/ already holds game-root-relative paths; the others are a prefix.
        prefix = "" if sub == ROOT_SUBTREE else f"{sub}/"
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if _is_excluded(f):
                    continue
                src = os.path.join(dirpath, f)
                rel = os.path.relpath(src, root).replace("\\", "/")
                out.append((src, prefix + rel))
    return out


def _other_version_sources(gameVersion):
    """{game-relative path: [absolute source, ...]} for every OTHER version.

    The keys answer "does the patch write here at all". The values answer the
    harder question of whether the bytes now on disk are the patch's own, which
    is what tells a launcher's file apart from something the player made.
    """
    out = {}
    root = os.path.join(BASE_DIR, "GameVersions")
    try:
        names = os.listdir(root)
    except Exception:
        return out
    for v in names:
        if v == gameVersion or not os.path.isdir(os.path.join(root, v)):
            continue
        for src, rel in _version_files(v):
            out.setdefault(rel, []).append(src)
        ov = os.path.join(root, v, "Overlay")
        for dirpath, _dirs, files in os.walk(ov):
            for f in files:
                if f == "_overlay_manifest.json" or _is_excluded(f):
                    continue
                src = os.path.join(dirpath, f)
                rel = os.path.relpath(src, ov).replace("\\", "/")
                out.setdefault(rel, []).append(src)
    return out


def _is_patch_content(dst, candidates):
    """True when what is on disk is byte-identical to what some version ships
    for that path -- so a launcher put it there, and it needs no rescue copy."""
    try:
        size = os.path.getsize(dst)
    except Exception:
        return False
    same_size = [c for c in candidates if os.path.exists(c) and os.path.getsize(c) == size]
    if not same_size:
        return False
    digest = _sha256(dst)
    return any(_sha256(c) == digest for c in same_size)


def _rescue(rel, dst):
    """Keep a copy of what is about to be overwritten. Best effort: failing to
    save must never stop the restore, or a full disk would leave the game half
    reverted."""
    try:
        keep = os.path.join(game_path, USER_OVERWRITES, *rel.split("/"))
        os.makedirs(os.path.dirname(keep), exist_ok=True)
        shutil.copy2(dst, keep)
        return True
    except Exception as e:
        print(f"[stock] could not keep a copy of {rel}: {e}")
        return False


def _report_unexplained(stock, sources, limit=12):
    """Name the files in the game's own folders that are neither stock nor
    anything a version ships. They are not deleted: some are the player's, and
    nothing can tell those from an orphan of an older launcher by their bytes.
    A leftover file is recoverable, a deleted one is not."""
    if not stock:
        return
    roots = set(rel.split("/")[0] for rel in stock if "/" in rel)
    found = []
    for top in sorted(roots):
        base = os.path.join(game_path, top)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for f in files:
                rel = os.path.relpath(os.path.join(dirpath, f), game_path).replace("\\", "/")
                if rel not in stock and rel not in sources:
                    found.append(rel)
    if found:
        print(f"[stock] {len(found)} file(s) in the game's folders are neither stock nor "
              f"from any version, and were left alone:")
        for rel in found[:limit]:
            print(f"[stock]     {rel}")
        if len(found) > limit:
            print(f"[stock]     ... and {len(found) - limit} more")


def restore_stock(gameVersion):
    """Put the game back to stock without touching anything that is not ours."""
    stock = _load_stock_manifest()
    mine = _version_files(gameVersion)
    sources = _other_version_sources(gameVersion)

    # What pass 2 must leave alone is what pass 1 actually installs, not
    # everything the folder happens to contain. Counting a non-game file as
    # "wanted" would make pass 1 skip it AND pass 2 spare it, so a patch run
    # that put it in the game folder would leave it there for good.
    wanted = set(rel for _s, rel in mine if not stock or rel in stock)

    # ---- pass 1: restore the stock files this version carries -------------
    restored = skipped_unknown = rescued = 0
    rescued_names = []
    for src, rel in mine:
        if stock and rel not in stock:
            skipped_unknown += 1
            continue
        dst = os.path.join(game_path, *rel.split("/"))
        try:
            if os.path.exists(dst):
                s_st, d_st = os.stat(src), os.stat(dst)
                if s_st.st_size == d_st.st_size:
                    # shutil.copy2 preserves the timestamp, so a file an earlier
                    # run restored matches on both size and mtime and needs no
                    # hashing. Only a timestamp mismatch pays for a hash, and
                    # the two-second slack is for filesystems that store mtime
                    # at coarser resolution.
                    if abs(s_st.st_mtime - d_st.st_mtime) <= 2:
                        continue
                    if _sha256(dst) == _sha256(src):
                        continue
                # About to overwrite a game file whose bytes are not stock. If
                # they are not some version's bytes either, nobody here put
                # them there -- a mod edited a stock file in place -- so a copy
                # is kept before stock wins. Checking first keeps this folder
                # small: a patched install has a thousand drifted files and
                # every one of them belongs to a launcher.
                if not _is_patch_content(dst, sources.get(rel, ())):
                    if _rescue(rel, dst):
                        rescued += 1
                        if len(rescued_names) < 8:
                            rescued_names.append(rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            restored += 1
        except Exception as e:
            print(f"[stock] could not restore {rel}: {e}")

    # ---- pass 2: remove what the patch created -----------------------------
    removed = kept_stock = 0
    if stock:
        for rel in sorted(set(sources) - wanted):
            dst = os.path.join(game_path, *rel.split("/"))
            if not os.path.exists(dst):
                continue
            if rel in stock:
                # A stock path another version overwrites, and this version
                # ships no replacement. Deleting it would destroy a game file,
                # so it stays -- and gets counted, because the real fix is to
                # add the stock copy to the vanilla snapshot.
                kept_stock += 1
                continue
            try:
                os.remove(dst)
                removed += 1
            except Exception as e:
                print(f"[stock] could not remove {rel}: {e}")

    print(f"[stock] {restored} file(s) restored, {removed} patch file(s) removed")
    if rescued:
        print(f"[stock] {rescued} file(s) matched neither stock nor any version and were "
              f"copied to {USER_OVERWRITES}/ before being replaced:")
        for rel in rescued_names:
            print(f"[stock]     {rel}")
        if rescued > len(rescued_names):
            print(f"[stock]     ... and {rescued - len(rescued_names)} more")
    if skipped_unknown:
        print(f"[stock] {skipped_unknown} file(s) in the '{gameVersion}' folder are not "
              f"game files and were not installed")
    if kept_stock:
        print(f"[stock] {kept_stock} stock path(s) are still patched and '{gameVersion}' "
              f"ships no replacement -- add their stock copy to that folder")
    _report_unexplained(stock, sources)


def injectPerformanceFiles(folderName, lowspecmodornot):
    try:
        shutil.copytree(os.path.join(BASE_DIR, "Files", "Spec Mod", f"{folderName}", f"{lowspecmodornot}"),
                         os.path.join(game_path, "00HIGH", "Effect", "spfx", "com"), dirs_exist_ok=True)
        shutil.copytree(os.path.join(BASE_DIR, "Files", "Spec Mod", f"{folderName}", f"{lowspecmodornot}"),
                         os.path.join(game_path, "01MIDDLE", "Effect", "spfx", "com"), dirs_exist_ok=True)
    except Exception as e:
        print(f"Error injecting performance files: {e}")


def setup_matchmaking(target_path, gameVersion):
    src = os.path.join(BASE_DIR, "Files", "Matchmaking", "dinput8.dll")
    try:
        shutil.copy(src, os.path.join(target_path, "dinput8.dll"))
    except Exception as e:
        print(f"[matchmaking] could not install dinput8.dll: {e}")
        return
    build = get_snapshot() or "unknown"
    seed = f"{build}|{gameVersion}"
    code = 100000 + (zlib.crc32(seed.encode("utf-8")) % 800000)
    try:
        with open(os.path.join(target_path, "patch_ranked.txt"), "w") as f:
            f.write(str(code) + "\n")
    except Exception as e:
        print(f"[matchmaking] could not write match code: {e}")


def remove_matchmaking(target_path):
    p = os.path.join(target_path, "dinput8.dll")
    try:
        if os.path.exists(p):
            os.remove(p)
    except Exception as e:
        print(f"[matchmaking] could not remove dinput8.dll: {e}")

    # A vanilla run must not leave a folder of added-character DLLs behind.
    # They are inert while dinput8.dll is gone, since the master loader is what
    # loads them, but "vanilla" should mean the folder is clean.
    try:
        pdst = os.path.join(target_path, "ReBalanceOfSouls")
        if os.path.isdir(pdst):
            gone = []
            for f in os.listdir(pdst):
                if f.lower().endswith(".dll"):
                    os.remove(os.path.join(pdst, f))
                    gone.append(f)
            if gone:
                print(f"[plugins] removed {len(gone)} plugin(s) for a vanilla run: "
                      f"{', '.join(gone)}")
    except Exception as e:
        print(f"[plugins] could not clear plugins: {e}")


def launch_patched(target_path):
    # On Windows start the .exe directly (needed so EasyAntiCheat doesn't block
    # the injected dinput8.dll). On Linux/macOS a Windows .exe can't be exec'd
    # directly (OSError: [Errno 8] Exec format error) -- it only runs through
    # Steam/Proton -- so launch it via Steam's app URL instead.
    exe = os.path.join(target_path, "BLEACH_Rebirth_of_Souls.exe")
    try:
        if platform.system() == "Windows":
            subprocess.Popen([exe], cwd=target_path)
        else:
            open_file("steam://rungameid/1689620")
    except Exception as e:
        print(f"Error launching patched game: {e}")


def launch(gameVersion):
    _relaunch_if_code_changed(pulling_from_git())
    if not os.path.exists(os.path.join(BASE_DIR,"GameModes","TeamBattle","TokenOpen.txt")):
        config["TEAM_BATTLE"] = "OFF"
    try:
        # Script, Motion, 00HIGH, 01MIDDLE and Demo all go through this now.
        # Vanilla ships the STOCK Demo/ so that picking it undoes the shortened
        # intros and stage cameras the patch installs.
        restore_stock(gameVersion)

        # The perf toggles write into 00HIGH/Effect/spfx/com and its 01MIDDLE
        # twin. "original" means the game's own file, and restore_stock() has
        # just put those back from the vanilla snapshot -- so re-applying it is
        # at best redundant.
        #
        # It is worse than redundant for the five toggles with no high/middle
        # split: injectPerformanceFiles() copies ONE folder into BOTH tiers,
        # and Files/Spec Mod/<toggle>/original holds the 00HIGH bytes. Every
        # launch therefore replaced nine 01MIDDLE effects with their
        # high-quality twin -- COM_tm_EvolveAura00.desktop.vfxt went from its
        # stock 1,482,020 bytes to 00HIGH's 6,401,101, and stayed there.
        # Measured against a clean install on 2026-09-21. reverse_globe is the
        # only toggle that ships the two tiers separately and the only one that
        # was ever correct.
        #
        # A non-default toggle is the player's own performance choice, so it is
        # still applied.
        for folder in os.listdir(os.path.join(BASE_DIR, "Files", "Spec Mod")):
            value = config.get(folder, "original")
            if value == "original":
                continue
            if folder == "reverse_globe":
                for tier, dest in (("high", "00HIGH"), ("middle", "01MIDDLE")):
                    shutil.copytree(
                        os.path.join(BASE_DIR, "Files", "Spec Mod", "reverse_globe", value, tier),
                        os.path.join(game_path, dest, "Effect", "spfx", "com"),
                        dirs_exist_ok=True)
            else:
                injectPerformanceFiles(folder, value)

        reworkPath = os.path.join(BASE_DIR, "Reworks")
        for rework in reworks:
            if rework != "OFF":
                scriptPath = os.path.join(reworkPath, rework, "Script")
                motionPath = os.path.join(reworkPath, rework, "Motion")
                if os.path.exists(scriptPath):
                    shutil.copytree(scriptPath, os.path.join(game_path, "Script"), dirs_exist_ok=True)
                if os.path.exists(motionPath):
                    shutil.copytree(motionPath, os.path.join(game_path, "Motion"), dirs_exist_ok=True)

        if gameMode != "DEFAULT":
            srcPath = os.path.join(BASE_DIR, "GameModes", f"{gameMode}", "Script")
            dstPath = os.path.join(game_path, "Script")
            shutil.copytree(srcPath, dstPath, dirs_exist_ok=True)

        if config["TEAM_BATTLE"] == "ON":
            print("here")
            srcPath = os.path.join(BASE_DIR, "GameModes", "TeamBattle")
            dstPath = os.path.join(game_path, "Script")
            shutil.copy(os.path.join(srcPath, "CharaStatus.fsv"), os.path.join(dstPath, "CharaStatus.fsv"))

      
        remove_matchmaking(game_path)
        try:
            open_file("steam://rungameid/1689620")
        except Exception:
            print("Error launching game")

    except Exception as e:
        print(f"Launch Error while preparing '{gameVersion}' for launch:\n{e}")
        return


if __name__ == "__main__":
    launch(GAME_VERSION)