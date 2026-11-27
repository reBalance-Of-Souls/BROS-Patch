"""Starting the game, and keeping patched players in their own match pool.

This logic existed in three separate copies -- the main launcher and both
Quick Launch scripts -- which had already drifted apart: only one of them
handled an elevation prompt, only one handled non-Windows, and the Vanilla
quick launcher ran a full patch install before removing the loader again.
It lives here once now.
"""

from __future__ import annotations

import os
import platform
import subprocess
import zlib
from pathlib import Path

STEAM_APPID = "1689620"
STEAM_RUN_URL = f"steam://rungameid/{STEAM_APPID}"
EXE_NAME = "BLEACH_Rebirth_of_Souls.exe"
LOADER_NAME = "dinput8.dll"
MATCH_CODE_FILE = "patch_ranked.txt"


def open_url(url: str) -> None:
    system = platform.system()
    if system == "Windows":
        os.startfile(url)
    elif system == "Darwin":
        subprocess.run(["open", url], check=False)
    else:
        subprocess.run(["xdg-open", url], check=False)


def match_code(build: str, game_version: str) -> int:
    """Derive this build's matchmaking pool.

    An unpatched client and a patched client desync against each other, so
    segregating the pool is a correctness requirement, not a nicety. The
    seed is the current commit hash plus the selected game version, so
    every push yields a fresh pool automatically and two different custom
    versions never share one. Nothing to bump by hand.
    """
    return 100000 + (zlib.crc32(f"{build}|{game_version}".encode("utf-8")) % 800000)


def setup_matchmaking(game_root, game_version: str, build: str) -> None:
    """Stamp the match code next to the exe for the loader to read."""
    try:
        with open(Path(game_root) / MATCH_CODE_FILE, "w") as f:
            f.write(f"{match_code(build, game_version)}\n")
    except OSError as e:
        print(f"[matchmaking] could not write match code: {e}")


def remove_matchmaking(game_root) -> None:
    """Remove the loader so vanilla starts cleanly under EasyAntiCheat."""
    p = Path(game_root) / LOADER_NAME
    try:
        if p.exists():
            p.unlink()
    except OSError as e:
        print(f"[matchmaking] could not remove {LOADER_NAME}: {e}")


def launch_patched(game_root, env=None) -> None:
    """Start the patched game.

    On Windows the exe is started directly and deliberately: going through
    Steam would bring EasyAntiCheat up with it, and EAC kills a process
    carrying the injected loader. On Linux/macOS a Windows exe cannot be
    exec'd at all ([Errno 8] Exec format error) -- it only runs under
    Proton -- so there the Steam URL is the only option.
    """
    game_root = Path(game_root)
    exe = game_root / EXE_NAME

    if platform.system() != "Windows":
        try:
            open_url(STEAM_RUN_URL)
        except Exception as e:
            print(f"Error launching patched game: {e}")
        return

    try:
        subprocess.Popen([str(exe)], cwd=str(game_root), env=env)
        return
    except OSError as e:
        if getattr(e, "winerror", None) != 740:
            print(f"Error launching patched game: {e}")
            return
    except Exception as e:
        print(f"Error launching patched game: {e}")
        return

    # winerror 740: the exe's manifest asks for elevation, which
    # CreateProcess cannot prompt for. ShellExecuteW can -- but it takes no
    # environment block, so the manifest location has to reach the child
    # through this process's own environment instead.
    try:
        import ctypes

        if env and env.get("BROS_VFS_MANIFEST"):
            os.environ["BROS_VFS_MANIFEST"] = env["BROS_VFS_MANIFEST"]
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", str(exe), None, str(game_root), 1
        )
    except Exception as e:
        print(f"Error launching patched game (elevated): {e}")


def launch_vanilla() -> None:
    """Start the stock game through Steam, with EasyAntiCheat active."""
    try:
        open_url(STEAM_RUN_URL)
    except Exception as e:
        print(f"Error launching game: {e}")
