"""Graphics add-ons in the game folder, checked before the patched game starts (session mv, 2026-11-17; the same file
in the Dev launcher and the public one).

A tester's game died as it started, some of the time, with nothing on screen. His crash log (2026-11-16) showed why:
ReShade sat in his game folder as dxgi.dll (with a ShaderToggler add-on), and the game's call that creates its
swapchain went through the patch's drawing plugins (online.dll, framedata.dll) into ReShade, which called a null
pointer. A DLL beside the exe that the game loads in place of a Windows graphics DLL hooks the same calls the patch's
on-screen displays use; the two can collide, and the game then closes without a word.

This module only LOOKS at the game folder: it lists the files that load into the game's graphics and are neither the
game's own nor the patch's. launch_patched asks the player once per set of such files; the answer "start anyway" is
remembered for exactly that set (%LOCALAPPDATA%\\BROS Launcher\\injector_check.json, outside the repository;
BROS_INJECTOR_CHOICE names another file), so the question comes back only when the files change. Nothing in the game
folder is moved, renamed or deleted here.

BROS_INJECTOR_FOUND="dxgi.dll" in the environment stands in for the folder, to see the message on a clean PC.
"""
from __future__ import annotations

import json
import os

# DLL names Windows itself provides and a game loads by name: a copy beside the exe is loaded INSTEAD (a proxy).
# dinput8.dll is the patch's own loader and is not in this list.
PROXY_NAMES = ("dxgi.dll", "d3d12.dll", "d3d12core.dll", "d3d11.dll", "d3d10.dll", "d3d10core.dll", "d3d9.dll",
               "opengl32.dll")
ADDON_SUFFIXES = (".addon64", ".addon32", ".addon")
MARKERS = (("reshade.ini", "ReShade"), ("reshade.log", "ReShade"), ("reshade64.dll", "ReShade"),
           ("specialk64.dll", "Special K"), ("specialk.ini", "Special K"), ("enbseries.ini", "ENB"),
           ("optiscaler.ini", "OptiScaler"), ("nvngx.ini", "OptiScaler"), ("dxvk.conf", "DXVK"))
# what a binary says about itself (looked for in its bytes, plain and 16-bit text)
SIGNATURES = ((b"ReShade", "ReShade"), (b"Special K", "Special K"), (b"SpecialK", "Special K"),
              (b"OptiScaler", "OptiScaler"), (b"ENBSeries", "ENB"), (b"DXVK", "DXVK"), (b"3Dmigoto", "3Dmigoto"))
OVERRIDE = "BROS_INJECTOR_FOUND"
CHOICE_ENV = "BROS_INJECTOR_CHOICE"
WIDTH = 50                                    # the longest line the message may have

TITLE = "A graphics add-on is in the game folder"


def _product(path):
    """What a DLL says it is ("ReShade", ...), or None. Reads at most 8 MB; never raises."""
    try:
        with open(path, "rb") as f:
            b = f.read(8 << 20)
    except OSError:
        return None
    for sig, name in SIGNATURES:
        if sig in b or sig.decode("ascii").encode("utf-16-le") in b:
            return name
    return None


def scan(game_path):
    """The files beside the exe that load into the game's graphics and are not the game's or the patch's:
    [{"name", "bytes", "mtime", "what"}], sorted by name. An unreadable folder gives []."""
    forced = os.environ.get(OVERRIDE, "").strip()
    if forced:
        return [{"name": n.strip(), "bytes": 0, "mtime": 0, "what": "ReShade"} for n in forced.split(",") if n.strip()]
    try:
        names = os.listdir(game_path)
    except OSError:
        return []
    low = {n.lower(): n for n in names}
    product = None
    for marker, what in MARKERS:
        if marker in low:
            product = product or what
    found = []
    for n in sorted(names, key=str.lower):
        ln = n.lower()
        p = os.path.join(game_path, n)
        if not os.path.isfile(p):
            continue
        kind = None
        if ln in PROXY_NAMES:
            kind = _product(p) or product or "a graphics add-on"
        elif ln.endswith(ADDON_SUFFIXES):
            kind = "a ReShade add-on"
        if kind is None:
            continue
        try:
            st = os.stat(p)
            size, mtime = st.st_size, int(st.st_mtime)
        except OSError:
            size, mtime = 0, 0
        found.append({"name": n, "bytes": size, "mtime": mtime, "what": kind})
    return found


def _key(found):
    return sorted("%s|%d|%d" % (f["name"].lower(), f["bytes"], f["mtime"]) for f in found)


def _choice_path():
    p = os.environ.get(CHOICE_ENV)
    if p:
        return p
    root = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(root, "BROS Launcher", "injector_check.json")


def accepted(found):
    """True when the player already chose "start anyway" for exactly these files."""
    try:
        with open(_choice_path(), "r", encoding="utf-8") as f:
            return json.load(f).get("accepted") == _key(found)
    except Exception:
        return False


def remember(found):
    try:
        p = _choice_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"accepted": _key(found)}, f)
        os.replace(p + ".tmp", p)
        return True
    except Exception as e:
        print("[injector] the choice could not be kept: %s" % e)
        return False


def describe(found):
    """One line per file, for the message and the log."""
    return ["%s (%s)" % (f["name"], f["what"]) for f in found]


def text(found):
    names = describe(found)[:6]
    lines = ["These files in the game folder load into the",
             "game's graphics, and are not part of the game",
             "or of the patch:",
             ""]
    lines += ["   " + n[:WIDTH - 3] for n in names]
    if len(found) > 6:
        lines.append("   ... and %d more" % (len(found) - 6))
    lines += ["",
              "Add-ons like these can make the patched game",
              "close as it starts, with no message.",
              "",
              "If the game does not start, rename or move",
              "these files out of the game folder.",
              "",
              "Yes: open the game folder (game not started)",
              "No: start the game anyway (do not ask again)",
              "Cancel: do nothing"]
    return "\n".join(lines)


def open_folder(game_path):
    try:
        os.startfile(game_path)
        return True
    except Exception as e:        # not Windows, or the folder is gone
        print("[injector] could not open %s: %s" % (game_path, e))
        return False


def ok_to_start(messagebox, game_path):
    """Asked by launch_patched before the game starts: True starts it, False does not start it now.

    messagebox is tkinter.messagebox (askyesnocancel). Nothing is asked when the folder holds no such file, or when
    the player already chose to start anyway with exactly these files. Never raises."""
    try:
        found = scan(game_path)
        if not found:
            return True
        print("[injector] in the game folder: " + ", ".join(describe(found)))
        if accepted(found):
            print("[injector] the player chose to start with these files before: not asked again")
            return True
        answer = messagebox.askyesnocancel(TITLE, text(found), icon="warning")
        if answer is True:
            open_folder(game_path)
            print("[injector] the game folder was opened; the game was NOT started")
            return False
        if answer is False:
            remember(found)
            print("[injector] the player starts the game anyway")
            return True
        print("[injector] cancelled; the game was NOT started")
        return False
    except Exception as e:
        try:
            print("[injector] the check failed (%s): the game starts as before" % e)
        except Exception:
            pass
        return True
