"""stock_revert.py -- a Vanilla start puts the game back to stock without touching anything that is not ours.

The careful return to vanilla that "Quick Launch Bros Vanilla.py" carried, moved here when the Quick Launch scripts
were baked into the launcher (MATCHFIND, 2026-11-06): the launcher's Vanilla start -- its Launch button and its
right-click Quick Launch entry alike -- now does what that script did, and the script is gone. The code is the
script's own (restore_stock and its helpers), with the script's globals made arguments; nothing else changed.

Why not a mirror. A `robocopy /MIR` from the vanilla snapshot deletes by omission: anything in the game folder the
snapshot does not list is removed. That is wrong twice over for a return to vanilla:

  * the player's own files -- costume mods and the like -- are in no snapshot, so a mirror destroys them
  * so would a stock file the snapshot happens to lack

and a merge of the snapshot installs what the snapshot carries that the game has never had (dev leftovers: .bak
copies, the fsv2csv toolchain, *_modded packages). So: no mirror. Two passes that never guess.

  pass 1  copy in only what the stock manifest confirms is a real game file, and only where the bytes differ
  pass 2  delete only what the manifest proves the patch created, leave a stock path this version cannot replace,
          and never touch a file that is in no manifest and in no version -- that file is the player's

With no manifest on disk, pass 2 does nothing at all. Every deletion that rests on a guess is the guess that removed
Fnames/filename.bin on 2026-09-09 and left the game faulting at exe+0x1C8187 with no crashlog.

    restore_stock(base_dir, game_path, game_version)    prints what it did; never raises for one file

The launcher puts a development launch's overlay files and patched exe back first (its revert_foreign_overlay and
revert_foreign_exe, which the script called at the top of its restore_stock), then calls this.
"""
import hashlib
import os
import re
import shutil

# The trees a version folder maps onto the game root.
VERSION_SUBTREES = ("Script", "Motion", "00HIGH", "01MIDDLE", "02LOW", "Demo")

# Stock copies of game files that live at the game root rather than in one of the trees above. Not in Overlay/, whose
# bookkeeping is shared with the other launchers.
ROOT_SUBTREE = "Root"

# Where a file goes before stock overwrites it. Returning to vanilla means stock wins, including over a mod that
# edited a stock file in place rather than adding a new one. That player does not lose the file, but they would lose
# their edit silently. So a copy is kept first.
USER_OVERWRITES = "_launcher_user_overwrites"

# Dev leftovers that sit in the content folders and are not game assets (the script's list). Matching is on the file
# name only, never the path, so a real asset such as COM_tm_HitSlash_00.desktop.vfxt is untouched by the desktop.ini
# rule. There is deliberately no .csv rule: the game genuinely loads .csv assets --
# Script/ObjectConfig/pl027_menu_minion00.csv is referenced by the exe.
_EXCLUDE_EXACT = {"thumbs.db", "desktop.ini", ".gitkeep", ".gitignore", ".ds_store"}
_EXCLUDE_PATTERNS = (
    re.compile(r"\.bak$", re.I),
    re.compile(r"_bak$", re.I),
    re.compile(r"\s\(\d+\)\.", re.I),
    re.compile(r"\.(bat|py)(\s|$)", re.I),
)


def stock_manifest_path(base_dir):
    return os.path.join(base_dir, "Files", "Stock", "stock_manifest_sha256.txt")


def _is_excluded(name):
    """True for dev leftovers that should never reach the game."""
    if name.lower() in _EXCLUDE_EXACT:
        return True
    return any(p.search(name) for p in _EXCLUDE_PATTERNS)


def _load_stock_manifest(base_dir):
    """{game-relative path: (sha256 or '-', size)}, or {} when absent.

    An empty manifest is not an error: every caller degrades to "change nothing" rather than acting on a guess.
    """
    out = {}
    try:
        with open(stock_manifest_path(base_dir), "r", encoding="utf-8") as f:
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


def _version_files(base_dir, game_version):
    """[(absolute source, game-relative destination)] for one version's content trees, with the dev leftovers already
    filtered out."""
    out = []
    for sub in VERSION_SUBTREES + (ROOT_SUBTREE,):
        root = os.path.join(base_dir, "GameVersions", game_version, sub)
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


def _other_version_sources(base_dir, game_version):
    """{game-relative path: [absolute source, ...]} for every OTHER version.

    The keys answer "does the patch write here at all". The values answer the harder question of whether the bytes
    now on disk are the patch's own, which is what tells a launcher's file apart from something the player made.
    """
    out = {}
    root = os.path.join(base_dir, "GameVersions")
    try:
        names = os.listdir(root)
    except Exception:
        return out
    for v in names:
        if v == game_version or not os.path.isdir(os.path.join(root, v)):
            continue
        for src, rel in _version_files(base_dir, v):
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
    """True when what is on disk is byte-identical to what some version ships for that path -- so a launcher put it
    there, and it needs no rescue copy."""
    try:
        size = os.path.getsize(dst)
    except Exception:
        return False
    same_size = [c for c in candidates if os.path.exists(c) and os.path.getsize(c) == size]
    if not same_size:
        return False
    digest = _sha256(dst)
    return any(_sha256(c) == digest for c in same_size)


def _rescue(game_path, rel, dst):
    """Keep a copy of what is about to be overwritten. Best effort: failing to save must never stop the restore, or a
    full disk would leave the game half reverted."""
    try:
        keep = os.path.join(game_path, USER_OVERWRITES, *rel.split("/"))
        os.makedirs(os.path.dirname(keep), exist_ok=True)
        shutil.copy2(dst, keep)
        return True
    except Exception as e:
        print(f"[stock] could not keep a copy of {rel}: {e}")
        return False


def _report_unexplained(game_path, stock, sources, limit=12):
    """Name the files in the game's own folders that are neither stock nor anything a version ships. They are not
    deleted: some are the player's, and nothing can tell those from an orphan of an older launcher by their bytes. A
    leftover file is recoverable, a deleted one is not."""
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


def restore_stock(base_dir, game_path, game_version):
    """Put the game back to stock without touching anything that is not ours."""
    stock = _load_stock_manifest(base_dir)
    mine = _version_files(base_dir, game_version)
    sources = _other_version_sources(base_dir, game_version)

    # What pass 2 must leave alone is what pass 1 actually installs, not everything the folder happens to contain.
    # Counting a non-game file as "wanted" would make pass 1 skip it AND pass 2 spare it, so a patch run that put it in
    # the game folder would leave it there for good.
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
                    # shutil.copy2 preserves the timestamp, so a file an earlier run restored matches on both size and
                    # mtime and needs no hashing. Only a timestamp mismatch pays for a hash, and the two-second slack
                    # is for filesystems that store mtime at coarser resolution.
                    if abs(s_st.st_mtime - d_st.st_mtime) <= 2:
                        continue
                    if _sha256(dst) == _sha256(src):
                        continue
                # About to overwrite a game file whose bytes are not stock. If they are not some version's bytes
                # either, nobody here put them there -- a mod edited a stock file in place -- so a copy is kept before
                # stock wins. Checking first keeps this folder small: a patched install has a thousand drifted files
                # and every one of them belongs to a launcher.
                if not _is_patch_content(dst, sources.get(rel, ())):
                    if _rescue(game_path, rel, dst):
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
                # A stock path another version overwrites, and this version ships no replacement. Deleting it would
                # destroy a game file, so it stays -- and gets counted, because the real fix is to add the stock copy
                # to the vanilla snapshot.
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
        print(f"[stock] {skipped_unknown} file(s) in the '{game_version}' folder are not "
              f"game files and were not installed")
    if kept_stock:
        print(f"[stock] {kept_stock} stock path(s) are still patched and '{game_version}' "
              f"ships no replacement -- add their stock copy to that folder")
    _report_unexplained(game_path, stock, sources)
