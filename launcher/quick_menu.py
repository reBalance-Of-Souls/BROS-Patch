"""quick_menu.py -- Quick Launch inside the launcher: its command line and its right-click menu.

Pass mf (MATCHFIND_2026-11-06). Berg, 2026-11-06: "Can we instead have quick launchers be a sub menu when you right
click the launcher file with the option to "quick launch V1.5 room match" for example? Windows and Linux, but priority
to windows. This should be a better and cleaner alternative that reduces clutter, and allows us to rewrite the quick
launchers properly and bake them into the launcher". His choices (hist mf017, mf020): every version, no game modes
(Vanilla: title screen only); the classic Windows menu (on Windows 11 under "Show more options"); an ON/OFF switch on
the Advanced page; the Dev tools that used the old Quick Launch scripts move onto this command line; the Training
entry keeps BalanceLeadTools/DevGameMode.txt (developers only).

The same file in both repositories (the Dev Environment and BROS-Patch). Python 3.8+. Nothing here imports tkinter;
nothing here starts the game: the launcher's own launch() does, exactly as from its window.

COMMAND LINE (parse_args)
    <launcher>.py                                             the window, as always
    <launcher>.py --quick "<version>" --boot title|roommatch|training [--no-pull]
        the window's own launch() with the window never shown: update, install, switches, pool code, start.
        Default rules (game mode DEFAULT). Training honors BROS_GAME_MODE and BalanceLeadTools/DevGameMode.txt
        (dev_game_mode / gate_game_mode below, as "Quick Launch Training Mode.py" did); Room Match honors
        BROS_GAME_MODE (as "Quick Launch Room Match.py" did).
    <launcher>.py --prepare "<version>" [--mode <GameModes folder>] [--no-pull]
        everything a launch does except starting the game (BalanceInit). The Dev launcher only.
    <launcher>.py --quick-menu install|remove|status [--flat] [--match path|folder|name]
        the right-click menu by hand; the launcher keeps it current by itself while its switch is ON.

THE MENU (install / remove / remove_stale)
  Windows -- per user, no administrator rights:
    HKCU\\Software\\Classes\\SystemFileAssociations\\.py\\shell\\BROS.QuickLaunch.<id>  (<id>: this launcher's path)
        MUIVerb "Quick Launch" (+ " (Dev)" from the Dev launcher), SubCommands "" (a cascade from its own shell key),
        AppliesTo 'System.ItemPathDisplay:="<this launcher's path>"' -- the menu shows on that one file only --,
        Icon, and two values of ours: BROSLauncher (the path: stale entries) and BROSMenu (a hash of the layout:
        nothing is rewritten when nothing changed).
        shell\\01  MUIVerb "<version>", SubCommands ""
                   shell\\1  "Title screen"  command: "<python.exe>" "<launcher>" --quick "<version>" --boot title
                   shell\\2  "Room Match"    ... --boot roommatch
                   shell\\3  "Training"      ... --boot training
        shell\\NN  "Vanilla (the Steam game)": one entry, --boot title (vanilla has no loader to read a shortcut).
    Windows 11 lists it under "Show more options" (Shift+F10); Windows 10 in the first menu.
    --flat (one level: "<version>: Room Match") and --match folder|name (a wider AppliesTo) exist for a PC that does
    not show the nested or the path-matched form: a test sitting can try each without a new delivery.
  Linux -- per user (XDG folders), never root:
    applications/bros-quicklaunch-<id>.desktop   the launcher as an application, one action per item (app menus,
                                                 docks, the Steam Deck's desktop)
    mime/packages/bros-launcher-<id>.xml         the type application/x-bros-launcher for the launcher's file name
    kio/servicemenus/bros-quicklaunch-<id>.desktop       Dolphin (KDE, the Steam Deck): a "Quick Launch" submenu
    nemo/actions/bros-quicklaunch-<id>-NN-N.nemo_action  Nemo (Cinnamon)
    Thunar/uca.xml (config folder)                       Thunar (XFCE): our actions merged, unique-id bros-ql-<id>-
    nautilus-python/extensions/bros_quicklaunch_<id>.py  Nautilus (GNOME Files), when nautilus-python is installed
    A file manager that is not installed gets nothing.

A path holding '%' is refused (Windows and the Linux menus would read it as a placeholder).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

VANILLA = "Bleach Rebirth of Souls"
VANILLA_LABEL = "Vanilla (the Steam game)"
BOOTS = (("title", "Title screen"), ("roommatch", "Room Match"), ("training", "Training"))
BOOT_ENV = {"title": None, "roommatch": "roommatch", "training": "training"}
MATCHES = ("path", "folder", "name")
KEY_PREFIX = "BROS.QuickLaunch."
WIN_SHELL = r"Software\Classes\SystemFileAssociations\.py\shell"
MIME_TYPE = "application/x-bros-launcher"
CHOICE = ("Json", "quick_menu.json")         # the Advanced page's switch: {"on": true|false}; absent = ON. Not in
                                              # config.json: a new key there resets every player's settings (its
                                              # template check); kept out of git like Json/netcode.json
LOG_NAME = "Quick Launch"                      # update_window.log_to_file(LOG_NAME): logs\Quick Launch.log


class QuickError(Exception):
    """A malformed command line or a menu that cannot be made; the text is for the player."""


# ---------------------------------------------------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------------------------------------------------

def parse_args(argv):
    """None for a plain start (no arguments); otherwise a dict:
         {"cmd": "quick" | "prepare" | "menu", "version", "boot", "mode", "pull", "action", "flat", "match"}
    Raises QuickError on anything malformed (the launcher shows it and starts nothing)."""
    a = list(argv)
    if not a:
        return None
    out = {"cmd": None, "version": None, "boot": None, "mode": None, "pull": True, "action": None, "flat": False,
           "match": "path"}
    seen = set()

    def value(i, flag):
        if i + 1 >= len(a) or a[i + 1].startswith("--"):
            raise QuickError("%s needs a value" % flag)
        return a[i + 1]

    def command(c):
        if out["cmd"] not in (None, c):
            raise QuickError("--quick, --prepare and --quick-menu cannot be combined")
        out["cmd"] = c

    i = 0
    while i < len(a):
        x = a[i]
        if x in seen:
            raise QuickError("%s is given twice" % x)
        seen.add(x)
        if x == "--quick":
            command("quick")
            out["version"] = value(i, x)
            i += 2
        elif x == "--prepare":
            command("prepare")
            out["version"] = value(i, x)
            i += 2
        elif x == "--quick-menu":
            command("menu")
            out["action"] = value(i, x)
            i += 2
        elif x == "--boot":
            out["boot"] = value(i, x)
            i += 2
        elif x == "--mode":
            out["mode"] = value(i, x)
            i += 2
        elif x == "--match":
            out["match"] = value(i, x)
            i += 2
        elif x == "--no-pull":
            out["pull"] = False
            i += 1
        elif x == "--flat":
            out["flat"] = True
            i += 1
        else:
            raise QuickError("unknown argument: %s" % x)
    c = out["cmd"]
    if c is None:
        raise QuickError("--boot, --mode, --no-pull, --flat and --match need --quick, --prepare or --quick-menu")
    if c == "quick":
        out["boot"] = out["boot"] or "title"
        if out["boot"] not in BOOT_ENV:
            raise QuickError("--boot must be one of: %s" % ", ".join(b for b, _ in BOOTS))
        if out["mode"] is not None:
            raise QuickError("--mode belongs to --prepare (a Quick Launch plays default rules)")
    if c == "prepare" and out["boot"] is not None:
        raise QuickError("--boot belongs to --quick (--prepare starts nothing)")
    if c in ("quick", "prepare") and ("--flat" in seen or "--match" in seen):
        raise QuickError("--flat and --match belong to --quick-menu")
    if c == "menu":
        if out["action"] not in ("install", "remove", "status"):
            raise QuickError("--quick-menu must be install, remove or status")
        if out["boot"] is not None or out["mode"] is not None or not out["pull"]:
            raise QuickError("--boot, --mode and --no-pull belong to --quick / --prepare")
        if out["match"] not in MATCHES:
            raise QuickError("--match must be one of: %s" % ", ".join(MATCHES))
    if c in ("quick", "prepare") and not out["version"].strip():
        raise QuickError("the version is empty")
    return out


def describe(args):
    """One line for the log: what this start was asked to do."""
    if not args:
        return "window"
    if args["cmd"] == "quick":
        return "Quick Launch %s, %s%s" % (args["version"], dict(BOOTS)[args["boot"]],
                                          "" if args["pull"] else ", no update")
    if args["cmd"] == "prepare":
        return "prepare %s%s%s" % (args["version"], (", mode " + args["mode"]) if args["mode"] else "",
                                   "" if args["pull"] else ", no update")
    return "right-click menu: %s" % args["action"]


# ---------------------------------------------------------------------------------------------------------------------
# Training for developers: BROS_GAME_MODE / BalanceLeadTools/DevGameMode.txt, gated by the loader's build flags
# (ported unchanged in behaviour from "Quick Launch Training Mode.py", a5eeab26: _dev_game_mode, MODE_REQUIRES_FLAG,
# _active_dll_recipe, _gate_game_mode -- except that "no mode" is now None, default rules on the normal loader, where
# the script fell back to the TrainingBoot folder's own frozen loader).
# ---------------------------------------------------------------------------------------------------------------------

MODE_REQUIRES_FLAG = {
    # the gauge is a resource driven by add_unique_val index 1 in the mode's pl022.tadjpkg; without the flag nothing
    # reads the accumulator
    "ByakuyaBuilderSpender": "ENABLE_BYAKUYA_BUILDER_SPENDER",
    # pure loader mode, no Script/ of its own -- listed so naming it on the wrong DLL is refused rather than silently
    # doing nothing
    "ByakuyaPetalsTimerLockout": "ENABLE_BYAKUYA_PETAL_TIMER",
    # "ships a loader *and* data": the 10-Konpaku CharaStatus.fsv is only half the mode, the starting form is an engine
    # argument only the dll can set
    "ReawakeningBattle": "ENABLE_REAWAKEN_BATTLE",
}


def dev_game_mode(base_dir, log=print):
    """The game mode a developer asked Training to inject, or None. BROS_GAME_MODE first, then the one-line file
    BalanceLeadTools/DevGameMode.txt (an env var only exists for whoever exports it; the file survives a double-click,
    which is why it exists: 2026-09-05). Players have neither: None."""
    env = os.environ.get("BROS_GAME_MODE")
    if env and env.strip():
        log("[mode] %s, from BROS_GAME_MODE" % env.strip())
        return env.strip()
    token = os.path.join(base_dir, "BalanceLeadTools", "DevGameMode.txt")
    try:
        if os.path.exists(token):
            with open(token, encoding="utf-8") as f:
                for line in f:
                    line = line.split("#", 1)[0].strip()
                    if line:
                        log("[mode] %s, from BalanceLeadTools/DevGameMode.txt" % line)
                        return line
    except Exception as e:
        log("[mode] could not read DevGameMode.txt (%s) -- default rules" % e)
    return None


def active_dll_recipe(base_dir):
    """(variant name, build flags) of the loader dll_switch has active, or None when that cannot be told (no dll_switch,
    or a DLL that matches no saved recipe: its flags are unknown, which is not "no flags")."""
    try:
        d = os.path.join(base_dir, "BalanceLeadTools", "dll_switch")
        if not os.path.isdir(d):
            return None
        if d not in sys.path:
            sys.path.insert(0, d)
        import dll_switch
        name = dll_switch.active(dll_switch.variants())
        if name is None or name not in dll_switch.RECIPES:
            return None
        return name, dll_switch.RECIPES[name]
    except Exception:
        return None


def gate_game_mode(base_dir, mode, log=print):
    """Drop a mode whose loader is not the one installed (a mode's data with no code to read it reads in game as a
    broken mechanic: 2026-09-06). Returns the mode, or None (default rules)."""
    if not mode:
        return None
    need = MODE_REQUIRES_FLAG.get(mode)
    if not need:
        return mode
    got = active_dll_recipe(base_dir)
    flag = "/D%s=1" % need
    if got is not None and flag in got[1]:
        return mode
    if got is None:
        why = "the active dinput8.dll matches no saved dll_switch recipe, so its build flags are unknown"
    else:
        why = "the active DLL is '%s', which is built without %s" % (got[0], need)
    if os.environ.get("BROS_GAME_MODE_FORCE"):
        log("[mode] '%s' applied anyway (BROS_GAME_MODE_FORCE): %s" % (mode, why))
        return mode
    log("[mode] '%s' NOT applied -- %s." % (mode, why))
    log("[mode] Its Script/ would go in with no code to read it, which reads in game as a broken mechanic, not as a "
        "missing mode.")
    try:
        import dll_switch
        cands = sorted(n for n, f in dll_switch.RECIPES.items() if flag in f)
    except Exception:
        cands = []
    if cands:
        log('[mode] To use it:  python BalanceLeadTools/dll_switch/dll_switch.py "%s"' % cands[0])
    log("[mode] To keep this DLL and drop the mode: delete BalanceLeadTools/DevGameMode.txt")
    log("[mode] Default rules for this launch.")
    return None


def quick_game_mode(base_dir, boot, log=print):
    """The game mode a --quick start plays: None (DEFAULT) unless a developer asked. Training: BROS_GAME_MODE or
    DevGameMode.txt, gated; Room Match: BROS_GAME_MODE (as the old Room Match script); title: never."""
    if boot == "training":
        return gate_game_mode(base_dir, dev_game_mode(base_dir, log), log)
    if boot == "roommatch":
        env = (os.environ.get("BROS_GAME_MODE") or "").strip()
        if env:
            log("[mode] %s, from BROS_GAME_MODE" % env)
            return env
    return None


def focus_game_window(pid, timeout=90.0, log=print):
    """Bring the game's window to the front once it exists (Windows; opt-in through BROS_FOCUS, as the old Training
    script: a launcher that steals focus is a nuisance for anyone who starts a game and goes to do something else).
    Best effort: never raises."""
    if os.name != "nt":
        return
    try:
        import ctypes
        import time
        from ctypes import wintypes
        u32, k32 = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32")
        found = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum(hwnd, _):
            owner = wintypes.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and u32.IsWindowVisible(hwnd) and u32.GetWindowTextLengthW(hwnd):
                found.append(hwnd)
                return False
            return True

        deadline = time.time() + timeout
        while time.time() < deadline and not found:
            u32.EnumWindows(WNDENUMPROC(_enum), 0)
            if not found:
                time.sleep(0.5)
        if not found:
            log("[focus] the game window never appeared -- left as it is")
            return
        hwnd = found[0]
        u32.ShowWindow(hwnd, 9)
        if not u32.SetForegroundWindow(hwnd):
            fg = u32.GetForegroundWindow()
            ours = k32.GetCurrentThreadId()
            theirs = u32.GetWindowThreadProcessId(fg, None)
            u32.AttachThreadInput(theirs, ours, True)
            u32.SetForegroundWindow(hwnd)
            u32.AttachThreadInput(theirs, ours, False)
        u32.SwitchToThisWindow(hwnd, True)
        u32.SetActiveWindow(hwnd)
    except Exception as e:
        log("[focus] could not raise the game window: %s" % e)


# ---------------------------------------------------------------------------------------------------------------------
# What the menu lists
# ---------------------------------------------------------------------------------------------------------------------

def menu_items(versions, first=None):
    """[(version, label, ((boot, boot label), ...))]: `first` -- the version, or the versions in order, that the
    window lists first (the version everyone plays; the public launcher's beta) -- then the others by name, Vanilla
    last with the title screen only."""
    firsts = [first] if isinstance(first, str) else list(first or ())
    vs = [v for v in dict.fromkeys(versions) if v != VANILLA]
    head = [f for f in dict.fromkeys(firsts) if f in vs]
    order = head + sorted(v for v in vs if v not in head)
    items = [(v, v, BOOTS) for v in order]
    if VANILLA in versions:
        items.append((VANILLA, VANILLA_LABEL, BOOTS[:1]))
    return items


def launcher_id(launcher):
    p = os.path.normcase(os.path.abspath(launcher))
    return hashlib.sha256(p.encode("utf-8")).hexdigest()[:10]


def menu_python(exe=None):
    """The interpreter a menu entry runs: this one, with python.exe for pythonw.exe (a console the launcher hides at
    once, and the one an error is shown in -- pythonw has no console to show it)."""
    exe = exe or sys.executable                      # absolute: the interpreter running the launcher
    d, n = os.path.split(exe)
    if n.lower() == "pythonw.exe" and os.path.exists(os.path.join(d, "python.exe")):
        return os.path.join(d, "python.exe")
    return exe


def _check_paths(*paths):
    for p in paths:
        if "%" in p:
            raise QuickError("the path %s holds '%%', which the menus would read as a placeholder: no menu" % p)
        if '"' in p or "\n" in p or "\r" in p:
            raise QuickError("the path %s holds a quote or a line break: no menu" % p)


def quick_argv(launcher, version, boot, python=None):
    return [menu_python(python), os.path.abspath(launcher), "--quick", version, "--boot", boot]


# ---------------------------------------------------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------------------------------------------------

def win_command(argv):
    """A command line CreateProcess / CommandLineToArgvW reads back as argv (no argument here ends in a backslash or
    holds a quote: _check_paths)."""
    return " ".join('"%s"' % x if (not x or re.search(r'[\s"]', x)) else x for x in argv)


def applies_to(launcher, match="path"):
    launcher = os.path.abspath(launcher)
    if match == "path":
        return 'System.ItemPathDisplay:="%s"' % launcher
    if match == "folder":
        return 'System.ItemFolderNameDisplay:="%s" AND System.FileName:="%s"' % (
            os.path.basename(os.path.dirname(launcher)), os.path.basename(launcher))
    if match == "name":
        return 'System.FileName:="%s"' % os.path.basename(launcher)
    raise QuickError("unknown --match %r" % match)


def win_layout(launcher, items, label="Quick Launch", icon=None, python=None, flat=False, match="path"):
    """[(key path under WIN_SHELL, {value name: text})], parents before children; the first is the cascade. Every
    value is a REG_SZ ("" is the key's default value)."""
    launcher = os.path.abspath(launcher)
    py = menu_python(python)
    _check_paths(launcher, py, *(v for v, _, _ in items))
    root = KEY_PREFIX + launcher_id(launcher)
    top = {"MUIVerb": label, "SubCommands": "", "AppliesTo": applies_to(launcher, match), "BROSLauncher": launcher}
    if icon:
        top["Icon"] = os.path.abspath(icon)
    keys = [(root, top)]
    for n, (v, vlabel, boots) in enumerate(items, 1):
        k = "%s\\shell\\%02d" % (root, n)
        if len(boots) == 1:
            keys.append((k, {"MUIVerb": vlabel}))
            keys.append((k + "\\command", {"": win_command(quick_argv(launcher, v, boots[0][0], py))}))
        elif flat:
            for m, (b, blabel) in enumerate(boots, 1):
                kk = "%s%d" % (k, m)
                keys.append((kk, {"MUIVerb": "%s: %s" % (vlabel, blabel)}))
                keys.append((kk + "\\command", {"": win_command(quick_argv(launcher, v, b, py))}))
        else:
            keys.append((k, {"MUIVerb": vlabel, "SubCommands": ""}))
            for m, (b, blabel) in enumerate(boots, 1):
                kk = "%s\\shell\\%d" % (k, m)
                keys.append((kk, {"MUIVerb": blabel}))
                keys.append((kk + "\\command", {"": win_command(quick_argv(launcher, v, b, py))}))
    top["BROSMenu"] = hashlib.sha256(json.dumps(keys, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return keys


def _winreg(reg=None):
    if reg is not None:
        return reg
    import winreg
    return winreg


def _win_delete_tree(reg, parent, name):
    """Delete parent\\name and everything under it (Python 3.8 has no DeleteTree)."""
    try:
        k = reg.OpenKey(parent, name, 0, reg.KEY_ALL_ACCESS)
    except OSError:
        return False
    try:
        while True:
            try:
                sub = reg.EnumKey(k, 0)
            except OSError:
                break
            _win_delete_tree(reg, k, sub)
    finally:
        reg.CloseKey(k)
    reg.DeleteKey(parent, name)
    return True


def _win_value(reg, path, name):
    try:
        k = reg.OpenKey(reg.HKEY_CURRENT_USER, path, 0, reg.KEY_READ)
    except OSError:
        return None
    try:
        return reg.QueryValueEx(k, name)[0]
    except OSError:
        return None
    finally:
        reg.CloseKey(k)


def _win_ours(reg):
    """{key name: launcher path or None} of every BROS Quick Launch menu registered for this user."""
    out = {}
    try:
        shell = reg.OpenKey(reg.HKEY_CURRENT_USER, WIN_SHELL, 0, reg.KEY_READ)
    except OSError:
        return out
    try:
        i = 0
        while True:
            try:
                n = reg.EnumKey(shell, i)
            except OSError:
                break
            i += 1
            if n.startswith(KEY_PREFIX):
                out[n] = _win_value(reg, WIN_SHELL + "\\" + n, "BROSLauncher")
    finally:
        reg.CloseKey(shell)
    return out


def _win_notify():
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)     # SHCNE_ASSOCCHANGED, SHCNF_IDLIST
    except Exception:
        pass


def win_install(layout, reg=None):
    """Write the layout unless the same one is there. Returns "unchanged" or "written"."""
    reg = _winreg(reg)
    root, top = layout[0]
    if _win_value(reg, WIN_SHELL + "\\" + root, "BROSMenu") == top["BROSMenu"]:
        return "unchanged"
    shell = reg.CreateKeyEx(reg.HKEY_CURRENT_USER, WIN_SHELL, 0, reg.KEY_ALL_ACCESS)
    try:
        _win_delete_tree(reg, shell, root)
    finally:
        reg.CloseKey(shell)
    # the cascade's values last: a menu cut short has no BROSMenu, so the next start writes it again
    for path, values in layout[1:] + layout[:1]:
        k = reg.CreateKeyEx(reg.HKEY_CURRENT_USER, WIN_SHELL + "\\" + path, 0, reg.KEY_WRITE)
        try:
            for name, val in values.items():
                reg.SetValueEx(k, name, 0, reg.REG_SZ, val)
        finally:
            reg.CloseKey(k)
    _win_notify()
    return "written"


def win_remove(launcher=None, stale_only=False, reg=None, exists=os.path.exists):
    """Remove this launcher's menu (launcher given), or every menu whose launcher file is gone (stale_only). Returns
    the key names removed."""
    reg = _winreg(reg)
    gone = []
    mine = KEY_PREFIX + launcher_id(launcher) if launcher else None
    for name, path in _win_ours(reg).items():
        if name == mine or (stale_only and not (path and exists(path))):
            shell = reg.OpenKey(reg.HKEY_CURRENT_USER, WIN_SHELL, 0, reg.KEY_ALL_ACCESS)
            try:
                if _win_delete_tree(reg, shell, name):
                    gone.append(name)
            finally:
                reg.CloseKey(shell)
    if gone:
        _win_notify()
    return gone


# ---------------------------------------------------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------------------------------------------------

def _data_home(env=None):
    env = os.environ if env is None else env
    return env.get("XDG_DATA_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".local", "share")


def _config_home(env=None):
    env = os.environ if env is None else env
    return env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".config")


def desktop_exec(argv):
    """argv as a Desktop Entry Exec value: reserved characters quoted, '"', '`', '$', '\\' escaped inside quotes, then
    the string type's own escaping (a backslash doubled) and '%' doubled (no field codes here)."""
    out = []
    for a in argv:
        if a and not re.search(r"""[\s"'\\><~|&;$*?#()`=]""", a):
            q = a
        else:
            q = '"' + re.sub(r'(["`$\\])', r"\\\1", a) + '"'
        out.append(q)
    return " ".join(out).replace("\\", "\\\\").replace("%", "%%")


def _desktop_text(s):
    return s.replace("\\", "\\\\").replace("\n", " ").replace("\r", " ")


def _actions(items, flat_label=True):
    """[(action id, label, version, boot)] -- one per menu entry (Linux menus are one level)."""
    acts = []
    for n, (v, vlabel, boots) in enumerate(items, 1):
        for m, (b, blabel) in enumerate(boots, 1):
            label = vlabel if len(boots) == 1 else "%s: %s" % (vlabel, blabel)
            acts.append(("q%02d-%d" % (n, m), label, v, b))
    return acts


def linux_files(launcher, items, label="Quick Launch", app_name=None, icon=None, python=None, env=None,
                have=None):
    """{absolute path: text} of every file this launcher's menus are made of, and which file managers they serve.
    have: {"dolphin", "nemo", "thunar", "nautilus"} present (default: looked up). Thunar is not here (merged into
    uca.xml by linux_install)."""
    launcher = os.path.abspath(launcher)
    py = menu_python(python)
    _check_paths(launcher, py, *(v for v, _, _ in items))
    have = linux_have(env) if have is None else have
    lid = launcher_id(launcher)
    data = _data_home(env)
    acts = _actions(items)
    files = {}
    stamp = "X-BROS-Launcher=%s\n" % _desktop_text(launcher)
    app = ["[Desktop Entry]", "Type=Application", "Version=1.0",
           "Name=%s" % _desktop_text(app_name or "Bleach Rebirth of Souls launcher (%s)"
                                     % os.path.basename(os.path.dirname(launcher))),
           "Comment=Right-click: %s" % _desktop_text(label),
           "Exec=%s" % desktop_exec([py, launcher]),
           "Path=%s" % _desktop_text(os.path.dirname(launcher)),
           "Terminal=false", "Categories=Game;"]
    if icon:
        app.append("Icon=%s" % _desktop_text(os.path.abspath(icon)))
    app.append("Actions=%s;" % ";".join(a[0] for a in acts))
    body = "\n".join(app) + "\n" + stamp
    for aid, alabel, v, b in acts:
        body += "\n[Desktop Action %s]\nName=%s: %s\nExec=%s\n" % (aid, _desktop_text(label), _desktop_text(alabel),
                                                                    desktop_exec(quick_argv(launcher, v, b, py)))
    files[os.path.join(data, "applications", "bros-quicklaunch-%s.desktop" % lid)] = body
    files[os.path.join(data, "mime", "packages", "bros-launcher-%s.xml" % lid)] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!-- Written by the BROS launcher (launcher/quick_menu.py), menu %s -->\n'
        '<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">\n'
        '  <mime-type type="%s">\n'
        '    <comment>Bleach Rebirth of Souls launcher</comment>\n'
        '    <sub-class-of type="text/x-python"/>\n'
        '    <glob pattern="%s" weight="100" case-sensitive="true"/>\n'
        '  </mime-type>\n'
        '</mime-info>\n' % (lid, MIME_TYPE, _xml(os.path.basename(launcher))))
    if "dolphin" in have:
        km = ["[Desktop Entry]", "Type=Service", "MimeType=%s;" % MIME_TYPE,
              "X-KDE-Submenu=%s" % _desktop_text(label), "X-KDE-Priority=TopLevel",
              "Actions=%s;" % ";".join(a[0] for a in acts)]
        body = "\n".join(km) + "\n" + stamp
        for aid, alabel, v, b in acts:
            body += "\n[Desktop Action %s]\nName=%s\nExec=%s\n" % (aid, _desktop_text(alabel),
                                                                 desktop_exec(quick_argv(launcher, v, b, py)))
            if icon:
                body += "Icon=%s\n" % _desktop_text(os.path.abspath(icon))
        files[os.path.join(data, "kio", "servicemenus", "bros-quicklaunch-%s.desktop" % lid)] = body
    if "nemo" in have:
        for aid, alabel, v, b in acts:
            files[os.path.join(data, "nemo", "actions", "bros-quicklaunch-%s-%s.nemo_action" % (lid, aid))] = (
                "[Nemo Action]\nActive=true\nName=%s: %s\nComment=Bleach Rebirth of Souls: start the game\n"
                "Exec=%s\nSelection=s\nMimetypes=%s;\n%s" % (
                    _desktop_text(label), _desktop_text(alabel),
                    " ".join(shlex.quote(x) for x in quick_argv(launcher, v, b, py)), MIME_TYPE, stamp))
    if "nautilus" in have:
        files[os.path.join(data, "nautilus-python", "extensions", "bros_quicklaunch_%s.py" % lid)] = \
            _nautilus_ext(lid, launcher, py, items, label)
    return files


def _xml(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _nautilus_ext(lid, launcher, py, items, label):
    data = json.dumps({"launcher": launcher, "python": py, "label": label,
                       "items": [[v, vl, [list(b) for b in boots]] for v, vl, boots in items]}, sort_keys=True)
    return '''# Written by the BROS launcher (launcher/quick_menu.py); removed when its Quick Launch menu is switched off.
# X-BROS-Launcher=%(launcher_comment)s
import json
import os
import subprocess

from gi.repository import GObject, Nautilus

_MENU = json.loads(%(data)r)


class BrosQuickLaunch_%(lid)s(GObject.GObject, Nautilus.MenuProvider):
    def get_file_items(self, *args):
        files = args[-1]
        if len(files) != 1:
            return []
        try:
            path = files[0].get_location().get_path()
        except Exception:
            return []
        if not path or os.path.normcase(os.path.abspath(path)) != os.path.normcase(_MENU["launcher"]):
            return []
        top = Nautilus.MenuItem(name="BrosQuickLaunch_%(lid)s", label=_MENU["label"])
        menu = Nautilus.Menu()
        top.set_submenu(menu)
        for n, (version, vlabel, boots) in enumerate(_MENU["items"], 1):
            if len(boots) == 1:
                item = Nautilus.MenuItem(name="BrosQL_%(lid)s_%%02d" %% n, label=vlabel)
                item.connect("activate", self._start, version, boots[0][0])
                menu.append_item(item)
                continue
            sub_item = Nautilus.MenuItem(name="BrosQL_%(lid)s_%%02d" %% n, label=vlabel)
            sub = Nautilus.Menu()
            sub_item.set_submenu(sub)
            for m, (boot, blabel) in enumerate(boots, 1):
                item = Nautilus.MenuItem(name="BrosQL_%(lid)s_%%02d_%%d" %% (n, m), label=blabel)
                item.connect("activate", self._start, version, boot)
                sub.append_item(item)
            menu.append_item(sub_item)
        return [top]

    def _start(self, _item, version, boot):
        subprocess.Popen([_MENU["python"], _MENU["launcher"], "--quick", version, "--boot", boot],
                         cwd=os.path.dirname(_MENU["launcher"]), start_new_session=True)
''' % {"launcher_comment": launcher.replace("\n", " "), "data": data, "lid": lid}


def linux_have(env=None):
    """The file managers present: their programs on PATH, or (Nautilus) the nautilus-python library."""
    have = set()
    for prog in ("dolphin", "nemo", "thunar"):
        if shutil.which(prog):
            have.add(prog)
    import glob
    if shutil.which("nautilus") and (glob.glob("/usr/lib*/nautilus/extensions-*/libnautilus-python.so")
                                     or glob.glob("/usr/lib*/*/nautilus/extensions-*/libnautilus-python.so")):
        have.add("nautilus")
    return have


def _write_atomic(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".bros_tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def _our_linux_files(env=None):
    """{path: menu id} of every Quick Launch file of ours under the user's XDG folders (Thunar's actions aside)."""
    data = _data_home(env)
    out = {}
    pats = [(os.path.join(data, "applications"), re.compile(r"^bros-quicklaunch-[0-9a-f]{10}\.desktop$")),
            (os.path.join(data, "mime", "packages"), re.compile(r"^bros-launcher-[0-9a-f]{10}\.xml$")),
            (os.path.join(data, "kio", "servicemenus"), re.compile(r"^bros-quicklaunch-[0-9a-f]{10}\.desktop$")),
            (os.path.join(data, "nemo", "actions"), re.compile(r"^bros-quicklaunch-[0-9a-f]{10}-q\d\d-\d\.nemo_action$")),
            (os.path.join(data, "nautilus-python", "extensions"), re.compile(r"^bros_quicklaunch_[0-9a-f]{10}\.py$"))]
    for d, rx in pats:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if rx.match(n):
                out[os.path.join(d, n)] = re.search(r"[0-9a-f]{10}", n).group(0)
    return out


def _linux_launchers(env=None):
    """{menu id: the launcher path its files name, or None} -- read from X-BROS-Launcher lines."""
    out = {}
    for p, lid in _our_linux_files(env).items():
        out.setdefault(lid, None)
        if out[lid] is not None:
            continue
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    m = re.match(r"^#? ?X-BROS-Launcher=(.*)$", line.rstrip("\n"))
                    if m:
                        v = m.group(1)
                        out[lid] = v if p.endswith(".py") else v.replace("\\\\", "\\")
                        break
        except OSError:
            pass
    return out


UCA = ("Thunar", "uca.xml")


def _uca_path(env=None):
    return os.path.join(_config_home(env), *UCA)


def _uca_merge(launcher, items, label, py, icon, env=None, remove_ids=None):
    """Thunar's custom actions: ours (unique-id bros-ql-<id>-...) replaced, every other action kept. remove_ids: a set
    of launcher ids whose actions are only removed. Returns "written", "unchanged" or a reason it was left alone."""
    import xml.etree.ElementTree as ET
    p = _uca_path(env)
    if os.path.exists(p):
        try:
            tree = ET.parse(p)
            root = tree.getroot()
        except ET.ParseError as e:
            return "Thunar's uca.xml could not be read (%s): left as it is" % e
        if root.tag != "actions":
            return "Thunar's uca.xml is not an actions list: left as it is"
        before = _canon(root)
    else:
        if launcher is None:
            return "unchanged"
        root = ET.Element("actions")
        before = None
    ids = set(remove_ids or ())
    lid = launcher_id(launcher) if launcher else None
    if lid:
        ids.add(lid)
    for a in list(root.findall("action")):
        u = (a.findtext("unique-id") or "")
        m = re.match(r"^bros-ql-([0-9a-f]{10})-", u)
        if m and m.group(1) in ids:
            root.remove(a)
    if launcher is not None:
        for aid, alabel, v, b in _actions(items):
            a = ET.SubElement(root, "action")
            ET.SubElement(a, "icon").text = os.path.abspath(icon) if icon else ""
            ET.SubElement(a, "name").text = "%s: %s" % (label, alabel)
            ET.SubElement(a, "unique-id").text = "bros-ql-%s-%s" % (lid, aid)
            ET.SubElement(a, "command").text = " ".join(shlex.quote(x) for x in quick_argv(launcher, v, b, py))
            ET.SubElement(a, "description").text = "Bleach Rebirth of Souls: start the game (%s)" % launcher
            ET.SubElement(a, "patterns").text = os.path.basename(launcher)
            ET.SubElement(a, "other-files")
            ET.SubElement(a, "text-files")
    if _canon(root) == before:
        return "unchanged"
    ET.indent(root) if hasattr(ET, "indent") else None
    _write_atomic(p, '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n")
    return "written"


def _canon(e):
    """An element's content without layout whitespace: (tag, attributes, stripped text, children)."""
    return (e.tag, tuple(sorted(e.attrib.items())), (e.text or "").strip(), tuple(_canon(c) for c in e))


def _update_mime(env=None):
    tool = shutil.which("update-mime-database")
    if not tool:
        return "update-mime-database is not installed: the file managers do not know the launcher's type yet"
    try:
        r = subprocess.run([tool, os.path.join(_data_home(env), "mime")], capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, **(env or {})))
        return None if r.returncode == 0 else "update-mime-database failed: %s" % (r.stderr or r.stdout).strip()[-300:]
    except Exception as e:
        return "update-mime-database failed: %s" % e


def linux_install(launcher, items, label="Quick Launch", app_name=None, icon=None, python=None, env=None, have=None):
    """Write this launcher's Linux menus; files no longer wanted (a file manager gone, fewer items) are removed.
    Returns "unchanged" or "written" (+ notes)."""
    launcher = os.path.abspath(launcher)
    have = linux_have(env) if have is None else have
    want = linux_files(launcher, items, label, app_name, icon, python, env, have)
    lid = launcher_id(launcher)
    changed = False
    for p, plid in _our_linux_files(env).items():
        if plid == lid and p not in want:
            os.remove(p)
            changed = True
    for p, text in want.items():
        try:
            with open(p, encoding="utf-8") as f:
                same = f.read() == text
        except OSError:
            same = False
        exe = 0o755 if os.sep + os.path.join("kio", "servicemenus") + os.sep in p else None
        if not same:
            _write_atomic(p, text, exe)
            changed = True
        elif exe and (os.stat(p).st_mode & 0o777) != exe:
            os.chmod(p, exe)
            changed = True
    notes = []
    if "thunar" in have or os.path.exists(_uca_path(env)):
        r = _uca_merge(launcher, items, label, menu_python(python), icon, env)
        changed = changed or r == "written"
        if r not in ("written", "unchanged"):
            notes.append(r)
    if changed:
        n = _update_mime(env)
        if n:
            notes.append(n)
    return ("written" if changed else "unchanged") + ("; " + "; ".join(notes) if notes else "")


def linux_remove(launcher=None, stale_only=False, env=None, exists=os.path.exists):
    """Remove this launcher's Linux menus, or (stale_only) every menu whose launcher file is gone (or that names none).
    Returns the files removed (and uca.xml when our actions left it)."""
    mine = launcher_id(launcher) if launcher else None
    launchers = _linux_launchers(env)
    ids = {lid for lid, path in launchers.items() if lid == mine or (stale_only and not (path and exists(path)))}
    if mine:
        ids.add(mine)
    gone = []
    for p, lid in _our_linux_files(env).items():
        if lid in ids:
            os.remove(p)
            gone.append(p)
    if stale_only and os.path.exists(_uca_path(env)):
        ids |= _uca_stale_ids(env, launchers, exists)
    if ids and os.path.exists(_uca_path(env)):
        if _uca_merge(None, (), "", "", None, env, remove_ids=ids) == "written":
            gone.append(_uca_path(env))
    if gone:
        _update_mime(env)
    return gone


def _uca_stale_ids(env, launchers, exists):
    """Ids of our Thunar actions whose launcher is gone: named in no other file of ours, or named and missing."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(_uca_path(env)).getroot()
    except Exception:
        return set()
    out = set()
    for a in root.findall("action"):
        m = re.match(r"^bros-ql-([0-9a-f]{10})-", a.findtext("unique-id") or "")
        if not m:
            continue
        lid = m.group(1)
        path = launchers.get(lid)
        if path is None:
            d = re.search(r"\(([^()]*)\)$", a.findtext("description") or "")
            path = d.group(1) if d else None
        if not (path and exists(path)):
            out.add(lid)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# One entry point for the launchers
# ---------------------------------------------------------------------------------------------------------------------

def install(launcher, versions, first=None, label="Quick Launch", app_name=None, icon=None, python=None, flat=False,
            match="path", reg=None, env=None, have=None, platform_name=None):
    """The menu for this launcher, current; menus of launchers that no longer exist removed. Returns a line for the
    log. Never raises: a menu that cannot be made never stops a launcher."""
    plat = platform_name or ("windows" if os.name == "nt" else sys.platform)
    try:
        items = menu_items(versions, first)
        if plat == "windows":
            stale = win_remove(stale_only=True, reg=reg)
            r = win_install(win_layout(launcher, items, label, icon, python, flat, match), reg)
        elif plat.startswith("linux"):
            stale = linux_remove(stale_only=True, env=env)
            r = linux_install(launcher, items, label, app_name, icon, python, env, have)
        else:
            return "[quick menu] not made on %s" % plat
        return "[quick menu] %s (%d entries)%s" % (r, sum(len(b) for _, _, b in items),
                                                    ("; %d stale removed" % len(stale)) if stale else "")
    except Exception as e:
        return "[quick menu] not made: %s" % e


def remove(launcher, reg=None, env=None, platform_name=None):
    plat = platform_name or ("windows" if os.name == "nt" else sys.platform)
    try:
        if plat == "windows":
            gone = win_remove(launcher, reg=reg)
        elif plat.startswith("linux"):
            gone = linux_remove(launcher, env=env)
        else:
            return "[quick menu] nothing to remove on %s" % plat
        return "[quick menu] removed (%d)" % len(gone) if gone else "[quick menu] none to remove"
    except Exception as e:
        return "[quick menu] not removed: %s" % e


def status(launcher, reg=None, env=None, platform_name=None):
    plat = platform_name or ("windows" if os.name == "nt" else sys.platform)
    try:
        if plat == "windows":
            reg = _winreg(reg)
            h = _win_value(reg, WIN_SHELL + "\\" + KEY_PREFIX + launcher_id(launcher), "BROSMenu")
            others = [n for n in _win_ours(reg) if n != KEY_PREFIX + launcher_id(launcher)]
            return "[quick menu] %s%s" % ("installed (%s)" % h if h else "not installed",
                                          ("; %d other launcher(s) have one" % len(others)) if others else "")
        if plat.startswith("linux"):
            lid = launcher_id(launcher)
            mine = [p for p, plid in _our_linux_files(env).items() if plid == lid]
            return "[quick menu] %s" % ("installed (%d files)" % len(mine) if mine else "not installed")
        return "[quick menu] not available on %s" % plat
    except Exception as e:
        return "[quick menu] status unknown: %s" % e


def load_choice(base_dir):
    """The Advanced page's switch: True (ON) unless Json/quick_menu.json says {"on": false}. A damaged file reads ON."""
    try:
        with open(os.path.join(base_dir, *CHOICE), "r", encoding="utf-8") as f:
            return json.load(f).get("on", True) is not False
    except Exception:
        return True


def save_choice(base_dir, on):
    """Save the switch (Json/quick_menu.json through Json/quick_menu.json.tmp). Raises QuickError."""
    path = os.path.join(base_dir, *CHOICE)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"on": bool(on)}, f)
        os.replace(path + ".tmp", path)
    except OSError as e:
        raise QuickError("could not save %s (%s)" % (path, e))
    if load_choice(base_dir) != bool(on):
        raise QuickError("%s did not read back as written" % path)
