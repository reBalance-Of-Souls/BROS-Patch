"""Detecting a game folder the old installer wrote into, and healing it.

Every build before this one applied the patch with `robocopy /MIR` against
the live game directory. That overwrote stock files in place and, because
/MIR mirrors, deleted whatever the source tree did not have. There is no
undo, and a player who has run any previous build has a game folder whose
contents no longer match what Steam shipped.

The VFS cannot paper over that. It serves the patch's files for the paths
it covers, but a stock file the old installer overwrote and the current
patch does *not* overlay just stays wrong. Worse, a Vanilla launch runs
under EasyAntiCheat with the loader removed, so no redirection happens at
all and the player gets a silently patched "vanilla" game.

So the folder has to be genuinely restored, once. This module finds out
whether that is necessary and hands the player the one-click Steam action
that does it.

Detection leans on something the repo already has: GameVersions/ holds a
vanilla snapshot alongside the patched one. Comparing the two tells us
exactly which files the patch changes, and those files are then a
fingerprint -- if the game's copy matches the patched snapshot, a previous
installer wrote it.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

STEAM_APPID = "1689620"

VANILLA_SNAPSHOT = "Bleach Rebirth of Souls"
PATCHED_SNAPSHOT = "ReBalance of Souls V2.0"        # the main version (the Community Patch until the V1.5 rework)

# Cap the work. Detection has to feel instant on the launcher's startup
# path; conclusive evidence turns up in the first handful of files or the
# folder is almost certainly clean.
MAX_HASHED = 40
MAX_ADDED_CHECKED = 400


def _sha(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


@dataclass
class DirtReport:
    """What a scan of the game folder found."""

    dirty: bool = False
    leftovers: list = field(default_factory=list)   # patch-only files sitting in the game
    modified: list = field(default_factory=list)    # stock files matching the patched snapshot
    checked: int = 0
    game_updated_suspected: bool = False
    error: str = ""

    @property
    def evidence(self) -> list:
        """A few concrete paths, for showing the player why we think this."""
        return (self.leftovers + self.modified)[:6]

    def summary(self) -> str:
        if self.error:
            return f"Could not check the game folder: {self.error}"
        if not self.dirty:
            return "Game folder looks clean -- nothing from an older installer found."
        bits = []
        if self.leftovers:
            bits.append(f"{len(self.leftovers)} patch file(s) left in the game folder")
        if self.modified:
            bits.append(f"{len(self.modified)} stock file(s) overwritten")
        return "Older installer detected: " + ", ".join(bits) + "."


def scan(base_dir: Path, game_root: Path) -> DirtReport:
    """Look for traces of a copy-based install in the game folder."""
    base_dir, game_root = Path(base_dir), Path(game_root)
    report = DirtReport()

    van_root = base_dir / "GameVersions" / VANILLA_SNAPSHOT
    pat_root = base_dir / "GameVersions" / PATCHED_SNAPSHOT
    if not van_root.is_dir() or not pat_root.is_dir():
        report.error = "the GameVersions snapshots are missing from this repo"
        return report
    if not game_root.is_dir():
        report.error = f"game folder not found: {game_root}"
        return report

    van_files, pat_files = _index(van_root), _index(pat_root)

    # --- pass 1: files the patch adds ----------------------------------
    # A path that exists in the patched snapshot but not the vanilla one is
    # not a Steam file. If it is sitting in the game folder, something
    # copied it there. This is nearly free -- just a stat per candidate --
    # and it is conclusive, so it runs first.
    added = [rel for rel in pat_files if rel not in van_files]
    for rel in sorted(added)[:MAX_ADDED_CHECKED]:
        if (game_root / rel).exists():
            report.leftovers.append(rel)

    # --- pass 2: stock files the patch replaces -------------------------
    # For paths in both snapshots whose contents differ, the game's copy
    # should match vanilla. If it matches the patched snapshot instead, an
    # installer overwrote it. Cheap size-mismatch candidates are used first
    # so most scans never hash a large file.
    candidates = []
    for rel, van_size in van_files.items():
        pat_size = pat_files.get(rel)
        if pat_size is None:
            continue
        if pat_size != van_size:
            candidates.append((0, van_size, rel))   # differ by size: cheap and certain
        else:
            candidates.append((1, van_size, rel))   # same size: needs hashing to tell
    candidates.sort()   # size-differing first, then smallest-first

    hashed = 0
    neither = 0
    for _tier, _size, rel in candidates:
        if hashed >= MAX_HASHED:
            break
        game_file = game_root / rel
        if not game_file.is_file():
            continue
        try:
            van_h = _sha(van_root / rel)
            pat_h = _sha(pat_root / rel)
            if van_h == pat_h:
                continue                       # not a discriminating file after all
            hashed += 1
            report.checked += 1
            game_h = _sha(game_file)
            if game_h == pat_h:
                report.modified.append(rel)
            elif game_h != van_h:
                neither += 1
        except OSError:
            continue

    report.dirty = bool(report.leftovers or report.modified)

    # A game copy matching neither snapshot, consistently, points at a game
    # that has been updated past both of them rather than at a dirty
    # install. Worth distinguishing: "verify your files" is bad advice when
    # the real answer is "this repo's snapshots are stale".
    if report.checked >= 10 and neither >= report.checked * 0.9:
        report.game_updated_suspected = True

    return report


def _index(root: Path) -> dict:
    """Map game-relative path -> size for every file under a snapshot."""
    out = {}
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            p = Path(dirpath) / name
            try:
                out[p.relative_to(root).as_posix()] = p.stat().st_size
            except OSError:
                pass
    return out


def open_steam_verify() -> bool:
    """Ask Steam to verify the game's files.

    steam://validate runs the same check as Properties -> Installed Files ->
    Verify integrity, without making the player navigate there. Steam
    re-downloads only the files whose hashes do not match, so an overwritten
    Script folder costs megabytes, not the whole 35 GB install.
    """
    url = f"steam://validate/{STEAM_APPID}"
    try:
        if sys.platform == "win32":
            os.startfile(url)
        elif sys.platform == "darwin":
            subprocess.run(["open", url], check=False)
        else:
            subprocess.run(["xdg-open", url], check=False)
        return True
    except Exception:
        return False


def instructions() -> str:
    """Fallback wording for players whose Steam does not take the URL."""
    return (
        "In Steam: right-click BLEACH Rebirth of Souls -> Properties ->\n"
        "Installed Files -> Verify integrity of game files.\n\n"
        "Steam only re-downloads files that do not match, so this is usually\n"
        "a few hundred megabytes rather than the full install."
    )
