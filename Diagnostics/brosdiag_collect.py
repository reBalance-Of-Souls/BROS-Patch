#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brosdiag_collect.py -- one run gathers what is needed to tell why one PC's BLEACH Rebirth of Souls plays
differently from another PC's with the same patch.

Pass sf (SACRED_FILES_2026-10-31), 2026-10-31. Python 3.6 or newer, standard library only. Windows; Linux and
Steam Deck (Proton); macOS (CrossOver).

HOW TO RUN
  Best: start the game with the patch the way you always do, go into a match or Training, and run this while the
  game is still open -- it also records what is actually loaded in the running game.

      python brosdiag_collect.py                      finds the game (the launcher's Json/config.json, then Steam)
      python brosdiag_collect.py "<game folder>"      or name the folder that holds BLEACH_Rebirth_of_Souls.exe

  Options: --repo <launcher checkout>   --full (md5 of every game file, slower)   --out <folder>   --no-pause

  It writes ONE zip next to itself (brosdiag_<UTC time>.zip) and prints a short summary. It changes nothing and sends
  nothing: it only reads, then writes that zip.

WHAT IS IN THE ZIP
  report.json     the machine (Windows build, or Linux / Steam Deck / macOS, Wine / Proton / CrossOver and their DLL
                  overrides), CPU, RAM, GPU and display refresh rates, the decimal separator; BROS_* environment
                  variables (process and registry); Windows compatibility flags on the game exe; controllers seen
                  (XInput slots, HID game controllers by name and vendor/product id); Steam's build and branch of the
                  game, every Steam library that holds it, its launch options, Steam Input and Proton settings;
                  the launcher checkout (commit, upstream, local changes, untracked files, Json/*.json switches with
                  secrets removed); the newest patch_ranked.log session in short (plugins found / armed / declined,
                  refused claims, mode lines, warnings); the running game's loaded DLLs with md5; known programs that
                  remap input, draw overlays, limit or generate frames, edit memory or inject DLLs, when running.
  inventory.tsv   every file of the game folder with size and date, and the md5 of everything a patch or a mod can
                  change (all files beside the exe, Script/, Motion/, Fnames/, ReBalanceOfSouls/, the launcher's
                  overlay list, anything written after Steam's last update of the game; --full: all files).
  files/          scrubbed copies: the text and config files beside the exe and in ReBalanceOfSouls/,
                  patch_ranked.log and .log.1, launcher_install_report.txt, launcher_patch_state.json, the five
                  newest crash logs, the two newest network diagnostics.

PRIVACY
  Replaced everywhere before anything is written: user-folder names in paths, this PC's Windows user and computer
  name, the Steam account and persona names found on this PC, Steam IDs and every other run of 15+ digits, IP
  addresses, lobby data, URL credentials and access tokens, tournament salt and upload address. Never read:
  DevToken.txt, TokenOpen.txt, the launcher's UPDATE_TOKEN value, adminConfig.json's values (only its VERSION),
  the contents of save files (only their md5). Programs are named only when they match the fixed TOOLS list below.
"""
import argparse
import datetime
import glob
import hashlib
import json
import locale
import os
import platform
import re
import socket
import struct
import subprocess
import sys
import time
import zipfile

COLLECTOR = "brosdiag_collect.py 2026-10-31 (pass sf; pass fd: recordings listed, not hashed)"
APPID = "1689620"
GAME_EXE = "BLEACH_Rebirth_of_Souls.exe"
LOG_MARK = "==== dinput8 proxy loaded INTO GAME"
LFS_MAGIC = b"version https://git-lfs.github.com/spec/"
HASH_TOPS = ("script/", "motion/", "fnames/", "rebalanceofsouls/")
NO_HASH_TOPS = ("_launcher_vanilla_backup/", "_launcher_quarantine/", "_to_delete/", "brosdiag_",
                "bros_fulldiag/", "bros_diagnostics/")   # fd: the recordings -- up to GBs, never patch content
TEXT_EXT = (".txt", ".ini", ".json", ".cfg", ".log", ".csv", ".toml", ".xml")
SMALL = 2 * 1024 * 1024
NEWER_CAP_FILE = 64 * 1024 * 1024
NEWER_CAP_TOTAL = 2 * 1024 * 1024 * 1024

TOOLS = [
    ("input remapping", r"ds4windows|rewasd\w*|x360ce\w*|joytokey|antimicrox?|autohotkey\w*|betterjoy\w*|inputmapper"
                        r"|hidhide\w*|vjoy\w*|dsx|dualsensex|scptoolkit\w*|xoutput|gopher\w*|joyshockmapper\w*"
                        r"|steaminput\w*|padstick|keysticks"),
    ("overlay or capture", r"rtss|rtsshooksloader64|msiafterburner|discord|obs|obs32|obs64|medal|overwolf"
                           r"|nvidia share|nvsphelper64|radeonsoftware|amdrsserv|gamebar\w*|fraps|bandicam"
                           r"|action_x64|xsplit\w*"),
    ("frame limiting or generation", r"lossless ?scaling|losslessscaling|skif|specialk\w*|mangohud|gamescope\w*"
                                     r"|vkbasalt|fpslimiter\w*|battle ?\(?encoder\)? ?shirase|bes"),
    ("memory editor or trainer", r"cheat ?engine\w*|cheatengine-x86_64\w*|wemod|artmoney\w*|\w*trainer\w*|plitch"
                                 r"|cosmos|ce"),
    ("injector", r"reshade\w*|injector\w*|extreme ?injector\w*|3dmigoto\w*"),
    ("game or anticheat", r"bleach_rebirth_of_souls|start_protected_game|easyanticheat\w*|steam|steamwebhelper"),
    ("wine", r"wineserver|wine64-preloader|wine-preloader|wine64|wine|crossover|cxmanip|proton|winedevice"),
]
_TOOL_RE = [(cat, re.compile(r"^(?:%s)$" % pat, re.I)) for cat, pat in TOOLS]

# ---------------------------------------------------------------------------------------------------- scrubbing

_USERPATH = re.compile(r"(?i)([a-z]:[\\/]+(?:users|documents and settings)[\\/]+)(?!<user>)[^\\/\r\n\"'<>|]+")
_HOMEPATH = re.compile(r"(?i)([\\/](?:home|users|var[\\/]home)[\\/]+)(?!<user>)[^\\/\r\n\"'<>|]+")
_URLCRED = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/@\s\"']+@")
_TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_\-]{20,})")
_LOBBY = re.compile(r'(SetLobby\w*Data\s*\(?\s*"[^"\r\n]*"\s*[=,]\s*")[^"\r\n]*')
_SALT = re.compile(r"(?im)^(\s*(?:salt|upload)\s+)\S.*$")
_LONGNUM = re.compile(r"\d{15,}")
_B64 = re.compile(r"[A-Za-z0-9+]{32,}={0,2}")
_IPV4 = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])")
_IPV6 = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{1,4}:){4,7}[0-9A-Fa-f]{1,4}(?![0-9A-Fa-f:])")
_KEEP_IP = ("0.0.0.0", "127.0.0.1", "255.255.255.255")
_STOPWORDS = {"user", "users", "admin", "administrator", "owner", "guest", "default", "public", "steam", "game",
              "games", "home", "root", "steamuser", "crossover", "deck", "windows", "desktop", "player", "bleach"}


def _b64_repl(m):
    s = m.group(0)
    if re.search(r"\d", s) and re.search(r"[A-Z]", s) and re.search(r"[a-z]", s):
        return "<b64>"
    return s


def _ip_repl(m):
    if all(int(g) <= 255 for g in m.groups()) and m.group(0) not in _KEEP_IP:
        return "<ip>"
    return m.group(0)


class Scrubber(object):
    def __init__(self):
        self.words = []
        self._wre = None

    def add(self, word):
        w = (word or "").strip()
        if len(w) >= 4 and w.lower() not in _STOPWORDS and w not in self.words:
            self.words.append(w)
            self.words.sort(key=len, reverse=True)
            self._wre = re.compile("|".join(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(x) for x in self.words),
                                   re.I)

    def __call__(self, s):
        if not s:
            return s
        s = _URLCRED.sub(r"\1<cred>@", s)
        s = _TOKEN.sub("<token>", s)
        s = _LOBBY.sub(r"\1<lobbydata>", s)
        s = _SALT.sub(r"\1<removed>", s)
        s = _USERPATH.sub(r"\1<user>", s)
        s = _HOMEPATH.sub(r"\1<user>", s)
        if self._wre is not None:
            s = self._wre.sub("<name>", s)
        s = _LONGNUM.sub("<id>", s)
        s = _B64.sub(_b64_repl, s)
        s = _IPV4.sub(_ip_repl, s)
        return _IPV6.sub("<ip6>", s)

    def obj(self, o):
        if isinstance(o, str):
            return self(o)
        if isinstance(o, dict):
            return dict((self(str(k)), self.obj(v)) for k, v in o.items())
        if isinstance(o, (list, tuple)):
            return [self.obj(v) for v in o]
        return o


SCRUB = Scrubber()

# ---------------------------------------------------------------------------------------------------- helpers


def utc(ts=None):
    d = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc) if ts is not None else \
        datetime.datetime.now(datetime.timezone.utc)
    return d.strftime("%Y-%m-%d %H:%M:%S")


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def read_text(path, limit=None):
    with open(path, "rb") as f:
        data = f.read() if limit is None else f.read(limit)
    return data.decode("utf-8", "replace")


def run(cmd, timeout=60, env=None):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env)
    return r.returncode, r.stdout.decode("utf-8", "replace").strip(), r.stderr.decode("utf-8", "replace").strip()


def is_windows():
    return os.name == "nt"


def section(report, name, fn, *args):
    t0 = time.time()
    try:
        out = fn(*args)
    except Exception as e:                                  # a probe that fails must never stop the collection
        report.setdefault("errors", {})[name] = "%s: %s" % (type(e).__name__, e)
        out = None
    report.setdefault("timing_s", {})[name] = round(time.time() - t0, 2)
    return out


def norm(p):
    """A path in one comparable form: resolved, case-folded on Windows, without a \\\\?\\ prefix."""
    p = os.path.normcase(os.path.realpath(p))
    return p[4:] if p.startswith("\\\\?\\") else p


def find_exe(folder):
    if not folder or not os.path.isdir(folder):
        return None
    p = os.path.join(folder, GAME_EXE)
    if os.path.isfile(p):
        return p
    try:
        for f in os.listdir(folder):
            if f.lower() == GAME_EXE.lower():
                return os.path.join(folder, f)
    except OSError:
        pass
    return None


# ---------------------------------------------------------------------------------------------------- VDF (Steam)

_VDF_TOK = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|(//[^\n]*)')


def vdf_load(path):
    root, stack, key = {}, [], None
    stack.append(root)
    for q, br, cm in _VDF_TOK.findall(read_text(path)):
        if cm:
            continue
        if br == "{":
            d = {}
            if key is not None:
                stack[-1][key] = d
            stack.append(d)
            key = None
        elif br == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        else:
            s = q.replace("\\\\", "\\").replace('\\"', '"')
            if key is None:
                key = s
            else:
                stack[-1][key] = s
                key = None
    return root


def vget(d, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        hit = None
        for kk in d:
            if kk.lower() == k.lower():
                hit = d[kk]
                break
        d = hit
    return d


def vdf_app_blocks(d):
    """Every dict under an "apps" key (any depth, any case) that has our app id."""
    if not isinstance(d, dict):
        return
    for k, v in d.items():
        if isinstance(v, dict):
            if k.lower() == "apps" and isinstance(vget(v, APPID), dict):
                yield vget(v, APPID)
            for x in vdf_app_blocks(v):
                yield x


# ---------------------------------------------------------------------------------------------------- Wine paths


def wine_prefix_of(path):
    p = os.path.abspath(path)
    while True:
        if os.path.basename(p).lower() == "drive_c":
            return os.path.dirname(p)
        np = os.path.dirname(p)
        if np == p:
            return None
        p = np


def map_wine_path(prefix, winpath):
    m = re.match(r"^([A-Za-z]):[\\/]*(.*)$", winpath or "")
    if not m:
        return winpath
    dev = os.path.join(prefix, "dosdevices", m.group(1).lower() + ":")
    if os.path.exists(dev):
        base = os.path.realpath(dev)
    elif m.group(1).lower() == "c":
        base = os.path.join(prefix, "drive_c")
    else:
        return None
    rest = [x for x in re.split(r"[\\/]+", m.group(2)) if x]
    return os.path.join(base, *rest) if rest else base


def reg_section(regfile, header):
    """The lines of one [section] of a Wine .reg file (user.reg / system.reg)."""
    out, on = [], False
    want = header.lower()
    for line in read_text(regfile).splitlines():
        if line.startswith("["):
            on = line.lower().startswith("[" + want + "]")
            continue
        if on and line.strip() and not line.startswith("#"):
            out.append(line.strip())
    return out


# ---------------------------------------------------------------------------------------------------- the machine


def machine_info():
    m = {"platform": platform.platform(), "system": platform.system(), "release": platform.release(),
         "machine": platform.machine(), "python": sys.version.split()[0],
         "python_bits": struct.calcsize("P") * 8, "cpu_count": os.cpu_count()}
    if is_windows():
        import winreg
        try:
            m["windows_version"] = list(sys.getwindowsversion())[:4]
        except AttributeError:
            pass
        try:
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
            for n in ("ProductName", "DisplayVersion", "CurrentBuild", "UBR"):
                try:
                    m["windows_" + n] = winreg.QueryValueEx(k, n)[0]
                except OSError:
                    pass
        except OSError:
            pass
        try:
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            m["cpu"] = str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
        try:
            import ctypes
            from ctypes import wintypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = MEMORYSTATUSEX()
            ms.dwLength = ctypes.sizeof(ms)
            if ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(ms)):
                m["ram_gb"] = round(ms.ullTotalPhys / 1024.0 ** 3, 1)
                m["ram_in_use_pct"] = ms.dwMemoryLoad
        except Exception as e:
            m["ram_error"] = type(e).__name__
        for path, name, key in ((r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", "hags"),):
            try:
                m[key] = winreg.QueryValueEx(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path), name)[0]
            except OSError:
                pass
        for path, name, key in ((r"Software\Microsoft\GameBar", "AutoGameModeEnabled", "game_mode"),
                                (r"Software\Microsoft\DirectX\UserGpuPreferences", "DirectXUserGlobalSettings",
                                 "directx_global")):
            try:
                m[key] = winreg.QueryValueEx(winreg.OpenKey(winreg.HKEY_CURRENT_USER, path), name)[0]
            except OSError:
                pass
    elif sys.platform == "darwin":
        m["mac_version"] = platform.mac_ver()[0]
        for key, cmd in (("cpu", ["sysctl", "-n", "machdep.cpu.brand_string"]),
                         ("apple_silicon", ["sysctl", "-n", "hw.optional.arm64"]),
                         ("ram_bytes", ["sysctl", "-n", "hw.memsize"])):
            try:
                m[key] = run(cmd, 20)[1]
            except Exception:
                pass
    else:
        try:
            for line in read_text("/etc/os-release").splitlines():
                if line.startswith(("PRETTY_NAME=", "VARIANT_ID=", "ID=")):
                    k, v = line.split("=", 1)
                    m["os_" + k.lower()] = v.strip('"')
        except OSError:
            pass
        try:
            for line in read_text("/proc/cpuinfo").splitlines():
                if line.lower().startswith("model name"):
                    m["cpu"] = line.split(":", 1)[1].strip()
                    break
            for line in read_text("/proc/meminfo").splitlines():
                if line.startswith("MemTotal:"):
                    m["ram_gb"] = round(int(line.split()[1]) / 1024.0 ** 2, 1)
        except (OSError, ValueError):
            pass
    m["locale"] = locale_info()
    return m


def locale_info():
    out = {}
    if is_windows():
        import ctypes
        k32 = ctypes.WinDLL("kernel32")
        buf = ctypes.create_unicode_buffer(85)
        if k32.GetUserDefaultLocaleName(buf, 85):
            out["user_locale"] = buf.value
            dec = ctypes.create_unicode_buffer(8)
            if k32.GetLocaleInfoEx(buf.value, 0x0E, dec, 8):          # LOCALE_SDECIMAL
                out["decimal_separator"] = dec.value
    else:
        old = locale.setlocale(locale.LC_ALL)
        try:
            locale.setlocale(locale.LC_ALL, "")
            out["user_locale"] = locale.setlocale(locale.LC_NUMERIC)
            out["decimal_separator"] = locale.localeconv().get("decimal_point")
        except locale.Error as e:
            out["error"] = str(e)
        finally:
            try:
                locale.setlocale(locale.LC_ALL, old)
            except locale.Error:
                pass
    return out


def displays():
    if not is_windows():
        return None
    import ctypes
    from ctypes import wintypes

    class DEVMODEW(ctypes.Structure):
        _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                    ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD),
                    ("dmFields", wintypes.DWORD), ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
                    ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
                    ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
                    ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
                    ("dmFormName", wintypes.WCHAR * 32), ("dmLogPixels", wintypes.WORD),
                    ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
                    ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                    ("dmDisplayFrequency", wintypes.DWORD)]

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                    ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                    ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]
    user32 = ctypes.WinDLL("user32")
    out, i = [], 0
    while i < 32:
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(dd)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
            break
        i += 1
        if not dd.StateFlags & 1:                                           # attached to the desktop
            continue
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(dm)
        if user32.EnumDisplaySettingsW(dd.DeviceName, -1, ctypes.byref(dm)):    # ENUM_CURRENT_SETTINGS
            out.append({"adapter": dd.DeviceString, "width": dm.dmPelsWidth, "height": dm.dmPelsHeight,
                        "refresh_hz": dm.dmDisplayFrequency, "primary": bool(dd.StateFlags & 4)})
    return out


def controllers():
    if not is_windows():
        return None
    import ctypes
    from ctypes import wintypes
    out = {"xinput": []}
    x = None
    for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            x = ctypes.WinDLL(name)
            out["xinput_dll"] = name
            break
        except OSError:
            continue
    if x is not None:
        class XINPUT_GAMEPAD(ctypes.Structure):
            _fields_ = [("wButtons", wintypes.WORD), ("bLeftTrigger", wintypes.BYTE),
                        ("bRightTrigger", wintypes.BYTE), ("sThumbLX", wintypes.SHORT),
                        ("sThumbLY", wintypes.SHORT), ("sThumbRX", wintypes.SHORT), ("sThumbRY", wintypes.SHORT)]

        class XINPUT_VIBRATION(ctypes.Structure):
            _fields_ = [("wLeftMotorSpeed", wintypes.WORD), ("wRightMotorSpeed", wintypes.WORD)]

        class XINPUT_CAPABILITIES(ctypes.Structure):
            _fields_ = [("Type", wintypes.BYTE), ("SubType", wintypes.BYTE), ("Flags", wintypes.WORD),
                        ("Gamepad", XINPUT_GAMEPAD), ("Vibration", XINPUT_VIBRATION)]
        sub = {1: "gamepad", 2: "wheel", 3: "arcade stick", 4: "flight stick", 5: "dance pad", 6: "guitar",
               7: "guitar alternate", 8: "drum kit", 0x0B: "guitar bass", 0x13: "arcade pad"}
        for slot in range(4):
            caps = XINPUT_CAPABILITIES()
            if x.XInputGetCapabilities(slot, 0, ctypes.byref(caps)) == 0:
                out["xinput"].append({"slot": slot, "subtype": sub.get(caps.SubType, caps.SubType),
                                      "flags": caps.Flags})
    ps = ("Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -match "
          "'game|controller|gamepad|joystick|xbox|dualsense|dualshock|arcade|fight ?stick|8bitdo|hori|pro controller'"
          " } | ForEach-Object { $_.Class + '|' + $_.FriendlyName + '|' + $_.InstanceId }")
    try:
        rc, so, se = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=60)
        seen = []
        for line in so.splitlines():
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            vp = re.search(r"VID[_&](?:0002)?([0-9A-Fa-f]{4}).{0,4}?PID[_&]([0-9A-Fa-f]{4})", parts[2], re.I)
            row = {"class": parts[0], "name": parts[1],
                   "vid_pid": ("%s:%s" % (vp.group(1), vp.group(2))).lower() if vp else None}
            if row not in seen:
                seen.append(row)
        out["devices"] = seen
        if rc and not seen:
            out["devices_error"] = se[:300]
    except Exception as e:
        out["devices_error"] = "%s: %s" % (type(e).__name__, e)
    return out


def wine_info():
    out = {}
    if is_windows():
        import ctypes
        try:
            f = getattr(ctypes.WinDLL("ntdll"), "wine_get_version", None)
            if f is not None:
                f.restype = ctypes.c_char_p
                out["wine_get_version"] = f().decode("latin1", "replace")
        except Exception as e:
            out["probe_error"] = type(e).__name__
        import winreg
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Wine\DllOverrides")
            ov, i = {}, 0
            while True:
                try:
                    n, v, _t = winreg.EnumValue(k, i)
                except OSError:
                    break
                ov[n] = v
                i += 1
            out["dll_overrides_registry"] = ov
        except OSError:
            pass
    for k in sorted(os.environ):
        if k.upper() in ("WINEUSERNAME", "WINEHOMEDIR"):
            continue
        if re.match(r"(?i)(WINE|DXVK|VKD3D|PROTON|STEAM_COMPAT|__COMPAT_LAYER|SteamAppId|SteamGameId)", k):
            out.setdefault("env", {})[k] = os.environ[k]
    return out


def env_vars():
    out = {"process": dict((k, v) for k, v in os.environ.items() if k.upper().startswith("BROS_"))}
    if is_windows():
        import winreg
        for hive, label, path in ((winreg.HKEY_CURRENT_USER, "user", "Environment"),
                                  (winreg.HKEY_LOCAL_MACHINE, "system",
                                   r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                k = winreg.OpenKey(hive, path)
            except OSError:
                continue
            i = 0
            while True:
                try:
                    n, v, _t = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if re.match(r"(?i)(BROS_|WINE|DXVK|VKD3D|__COMPAT_LAYER)", n):
                    out.setdefault(label, {})[n] = str(v)
    return out


def compat_flags(game_dir):
    if not is_windows():
        return None
    import winreg
    out = {}
    targets = (GAME_EXE.lower(), "start_protected_game.exe")
    for hive, label in ((winreg.HKEY_CURRENT_USER, "user"), (winreg.HKEY_LOCAL_MACHINE, "machine")):
        for path in (r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers",
                     r"Software\Microsoft\DirectX\UserGpuPreferences"):
            try:
                k = winreg.OpenKey(hive, path)
            except OSError:
                continue
            i = 0
            while True:
                try:
                    n, v, _t = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if n.lower().endswith(targets):
                    out.setdefault(label + ":" + path.split("\\")[-1], {})[n] = str(v)
    return out


# ---------------------------------------------------------------------------------------------------- Steam


def steam_roots():
    roots = []
    if is_windows():
        import winreg
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
            roots.append(os.path.normpath(winreg.QueryValueEx(k, "SteamPath")[0]))
        except OSError:
            pass
        roots += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    else:
        home = os.path.expanduser("~")
        roots += [os.path.join(home, ".steam", "steam"), os.path.join(home, ".local", "share", "Steam"),
                  os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam"),
                  os.path.join(home, "Library", "Application Support", "Steam")]
        bottles = glob.glob(os.path.join(home, "Library", "Application Support", "CrossOver", "Bottles", "*"))
        bottles += [os.path.join(home, ".wine")]
        for b in bottles:
            roots += [os.path.join(b, "drive_c", "Program Files (x86)", "Steam"),
                      os.path.join(b, "drive_c", "Program Files", "Steam")]
    out, seen = [], set()
    for r in roots:
        try:
            rp = os.path.realpath(r)
        except OSError:
            continue
        if rp not in seen and os.path.isdir(os.path.join(rp, "steamapps")):
            seen.add(rp)
            out.append(rp)
    return out


def steam_libraries(root):
    libs = [root]
    lf = os.path.join(root, "steamapps", "libraryfolders.vdf")
    if os.path.isfile(lf):
        d = vget(vdf_load(lf), "libraryfolders") or {}
        prefix = wine_prefix_of(root)
        for k, v in d.items():
            p = vget(v, "path") if isinstance(v, dict) else (v if k.isdigit() else None)
            if not p:
                continue
            if prefix:
                p = map_wine_path(prefix, p)
            if p and os.path.isdir(p):
                libs.append(os.path.realpath(p))
    out = []
    for l in libs:
        if l not in out:
            out.append(l)
    return out


def game_from_library(lib):
    acf = os.path.join(lib, "steamapps", "appmanifest_%s.acf" % APPID)
    if not os.path.isfile(acf):
        return None
    inst = vget(vdf_load(acf), "AppState", "installdir") or "BLEACH Rebirth of Souls"
    return os.path.join(lib, "steamapps", "common", inst)


def steam_info(game_dir):
    out = {"roots": [], "installs": []}
    roots = steam_roots()
    for root in roots:
        r = {"root": root, "wine_prefix": bool(wine_prefix_of(root))}
        users = os.path.join(root, "config", "loginusers.vdf")
        if os.path.isfile(users):
            for u in (vget(vdf_load(users), "users") or {}).values():
                if isinstance(u, dict):
                    SCRUB.add(vget(u, "AccountName"))
                    SCRUB.add(vget(u, "PersonaName"))
        cfg = os.path.join(root, "config", "config.vdf")
        if os.path.isfile(cfg):
            tool = vget(vdf_load(cfg), "InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping", APPID)
            if tool is not None:
                r["compat_tool"] = tool
        r["users"] = []
        for lc in glob.glob(os.path.join(root, "userdata", "*", "config", "localconfig.vdf")):
            try:
                blocks = list(vdf_app_blocks(vdf_load(lc)))
            except Exception as e:
                r["users"].append({"error": type(e).__name__})
                continue
            for b in blocks:
                r["users"].append(dict((k, v) for k, v in b.items() if not isinstance(v, dict)))
        for lib in steam_libraries(root):
            g = game_from_library(lib)
            if g:
                acf = vget(vdf_load(os.path.join(lib, "steamapps", "appmanifest_%s.acf" % APPID)), "AppState") or {}
                keep = {}
                for k in ("appid", "StateFlags", "installdir", "LastUpdated", "SizeOnDisk", "buildid",
                          "TargetBuildID", "UpdateResult", "AutoUpdateBehavior", "BytesToDownload",
                          "BytesDownloaded", "ScheduledAutoUpdate"):
                    v = vget(acf, k)
                    if v is not None:
                        keep[k] = v
                for k in ("UserConfig", "MountedConfig"):
                    v = vget(acf, k)
                    if isinstance(v, dict):
                        keep[k] = v
                if keep.get("LastUpdated", "").isdigit():
                    keep["LastUpdated_utc"] = utc(int(keep["LastUpdated"]))
                comp = os.path.join(lib, "steamapps", "compatdata", APPID)
                inst = {"library": lib, "game_folder": g, "exists": bool(find_exe(g)), "manifest": keep,
                        "this_is_the_collected_folder": bool(game_dir) and norm(g) == norm(game_dir)}
                if os.path.isdir(comp):
                    inst["proton_compatdata"] = True
                    for f in ("version", "config_info"):
                        p = os.path.join(comp, f)
                        if os.path.isfile(p):
                            inst["proton_" + f] = read_text(p, 2000).strip()
                    ureg = os.path.join(comp, "pfx", "user.reg")
                    if os.path.isfile(ureg):
                        inst["proton_dll_overrides"] = reg_section(ureg, "Software\\\\Wine\\\\DllOverrides")
                if inst not in out["installs"]:
                    out["installs"].append(inst)
        out["roots"].append(r)
    if game_dir:
        prefix = wine_prefix_of(game_dir)
        if prefix:
            pre = {"prefix": prefix}
            ureg = os.path.join(prefix, "user.reg")
            if os.path.isfile(ureg):
                pre["dll_overrides"] = reg_section(ureg, "Software\\\\Wine\\\\DllOverrides")
            conf = os.path.join(prefix, "cxbottle.conf")
            if os.path.isfile(conf):
                pre["crossover_environment"] = reg_section(conf, "EnvironmentVariables")
            out["game_wine_prefix"] = pre
    return out


# ---------------------------------------------------------------------------------------------------- the launcher checkout


def find_repo(starts):
    for s in starts:
        if not s:
            continue
        d = os.path.abspath(s)
        for _ in range(8):
            if os.path.isfile(os.path.join(d, "Json", "configTemplate.json")) and \
                    os.path.isdir(os.path.join(d, "launcher")):
                return d
            nd = os.path.dirname(d)
            if nd == d:
                break
            d = nd
    return None


_SECRET_KEY = re.compile(r"(?i)token|secret|passw|apikey|api_key|^key$|hash_value|admin_id|salt|upload")


def drop_secrets(o):
    if isinstance(o, dict):
        return dict((k, "<removed>" if _SECRET_KEY.search(str(k)) else drop_secrets(v)) for k, v in o.items())
    if isinstance(o, list):
        return [drop_secrets(v) for v in o]
    return o


def git(repo, *args, **kw):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    rc, so, se = run(["git", "-C", repo] + list(args), timeout=kw.get("timeout", 60), env=env)
    if rc == 1 and not so and not se and "unset" in kw:
        return kw["unset"]
    return so if rc == 0 else "(git %s failed: %s)" % (args[0], se[:300])


def repo_info(repo):
    out = {"path": repo, "devtoken_present": os.path.exists(os.path.join(repo, "BalanceLeadTools", "DevToken.txt"))
           or os.path.exists(os.path.join(repo, "DevToken.txt"))}
    try:
        run(["git", "--version"], 20)
        have_git = True
    except Exception:
        have_git = False
    if have_git:
        out["head"] = git(repo, "log", "-1", "--format=%H | %cI | %s")
        out["branch"] = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        out["upstream"] = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        out["upstream_head"] = git(repo, "log", "-1", "--format=%H | %cI | %s", "@{u}")
        out["ahead_behind"] = git(repo, "rev-list", "--left-right", "--count", "HEAD...@{u}")
        out["origin_url"] = git(repo, "remote", "get-url", "origin")
        out["modified_or_deleted"] = git(repo, "ls-files", "-m", timeout=300).splitlines()[:500]
        untracked = git(repo, "ls-files", "--others", "--exclude-standard", timeout=300).splitlines()
        out["untracked_count"] = len(untracked)
        out["untracked"] = untracked[:400]
        out["stash_count"] = len([l for l in git(repo, "stash", "list").splitlines() if l.strip()])
        out["autocrlf"] = git(repo, "config", "--show-origin", "--get-all", "core.autocrlf", unset="(not set)")
        out["lfs"] = git(repo, "lfs", "version")
    else:
        out["git"] = "not on PATH"
        gd = os.path.join(repo, ".git")
        try:
            head = read_text(os.path.join(gd, "HEAD")).strip()
            out["head_file"] = head
            if head.startswith("ref: "):
                ref = head[5:]
                p = os.path.join(gd, *ref.split("/"))
                if os.path.isfile(p):
                    out["head"] = read_text(p).strip()
                else:
                    for line in read_text(os.path.join(gd, "packed-refs")).splitlines():
                        if line.endswith(" " + ref):
                            out["head"] = line.split()[0]
            fh = os.path.join(gd, "FETCH_HEAD")
            if os.path.isfile(fh):
                out["last_fetch_utc"] = utc(os.path.getmtime(fh))
        except OSError as e:
            out["git_dir_error"] = str(e)
    pv = os.path.join(repo, "patch_version.txt")
    if os.path.isfile(pv):
        out["patch_version_txt"] = read_text(pv, 200).strip()
    adm = os.path.join(repo, "adminConfig.json")
    if os.path.isfile(adm):
        try:
            out["adminConfig_VERSION"] = json.loads(read_text(adm)).get("VERSION")
        except Exception:
            out["adminConfig_VERSION"] = "(unreadable)"
    out["json"] = {}
    for p in sorted(glob.glob(os.path.join(repo, "Json", "*.json"))):
        name = os.path.basename(p)
        try:
            out["json"][name] = drop_secrets(json.loads(read_text(p)))
        except Exception as e:
            out["json"][name] = "(unreadable: %s)" % type(e).__name__
    gm = os.path.join(repo, "GameModes")
    if os.path.isdir(gm):
        out["game_modes_available"] = sorted(os.listdir(gm))
        out["team_battle_token_present"] = os.path.exists(os.path.join(gm, "TeamBattle", "TokenOpen.txt"))
    sd = os.path.join(repo, "ressources", "savedata.bin")
    if os.path.isfile(sd):
        out["ressources_savedata_md5"] = md5_file(sd)
    return out


# ---------------------------------------------------------------------------------------------------- saves


def save_folders(game_dir):
    cands = []
    if is_windows() and os.environ.get("APPDATA"):
        cands.append(os.path.join(os.environ["APPDATA"], "BLEACH Rebirth of Souls", "Savedata"))
    prefixes = []
    if game_dir and wine_prefix_of(game_dir):
        prefixes.append(wine_prefix_of(game_dir))
    if game_dir:
        lib = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(game_dir))))
        prefixes.append(os.path.join(lib, "steamapps", "compatdata", APPID, "pfx"))
    for pf in prefixes:
        for sub in ("AppData/Roaming", "Application Data"):
            cands += glob.glob(os.path.join(pf, "drive_c", "users", "*", sub, "BLEACH Rebirth of Souls", "Savedata"))
    out = []
    for c in cands:
        if os.path.isdir(c) and c not in [o["folder"] for o in out]:
            files = []
            for dp, dn, fn in os.walk(c):
                for f in sorted(fn):
                    p = os.path.join(dp, f)
                    try:
                        files.append({"file": os.path.relpath(p, c).replace(os.sep, "/"),
                                      "size": os.path.getsize(p), "modified_utc": utc(os.path.getmtime(p)),
                                      "md5": md5_file(p)})
                    except OSError:
                        pass
            out.append({"folder": c, "files": files})
    return out


# ---------------------------------------------------------------------------------------------------- the game folder


def overlay_set(game_dir):
    p = os.path.join(game_dir, "launcher_patch_state.json")
    if not os.path.isfile(p):
        return set()
    try:
        ov = json.loads(read_text(p)).get("overlay") or []
        return set(str(x).replace("\\", "/").lower() for x in ov)
    except Exception:
        return set()


def inventory(game_dir, full, last_update_ts):
    ov = overlay_set(game_dir)
    rows, lfs, newer_total, n_hashed, b_hashed = [], [], 0, 0, 0
    t_last = time.time()
    newer_skipped = 0
    for dp, dn, fn in os.walk(game_dir):
        dn.sort()
        rel_dir = os.path.relpath(dp, game_dir).replace(os.sep, "/")
        for f in sorted(fn):
            p = os.path.join(dp, f)
            rel = f if rel_dir == "." else rel_dir + "/" + f
            low = rel.lower()
            try:
                st = os.stat(p)
            except OSError:
                rows.append("%s\t?\t?\tunreadable\t" % rel)
                continue
            why = ""
            if full:
                why = "full"
            elif low.startswith(NO_HASH_TOPS):
                why = ""
            elif "/" not in low:
                why = "root"
            elif low.startswith(HASH_TOPS):
                why = "patch dir"
            elif low in ov:
                why = "overlay"
            elif last_update_ts and st.st_mtime > last_update_ts + 600 and st.st_size <= NEWER_CAP_FILE:
                if newer_total + st.st_size <= NEWER_CAP_TOTAL:
                    why = "newer than Steam update"
                    newer_total += st.st_size
                else:
                    newer_skipped += 1
            md5 = ""
            if f.lower() in ("devtoken.txt", "tokenopen.txt"):
                why, md5 = "", "(secret, not read)"
            if why:
                try:
                    md5 = md5_file(p)
                    n_hashed += 1
                    b_hashed += st.st_size
                except OSError:
                    md5 = "unreadable"
            if st.st_size <= 1024:
                try:
                    with open(p, "rb") as fh:
                        if fh.read(len(LFS_MAGIC)) == LFS_MAGIC:
                            lfs.append(rel)
                except OSError:
                    pass
            rows.append("%s\t%d\t%s\t%s\t%s" % (rel, st.st_size, utc(st.st_mtime), md5, why))
            if time.time() - t_last > 5:
                t_last = time.time()
                print("  ... %d files listed, %d hashed (%.1f GB)" % (len(rows), n_hashed, b_hashed / 1e9))
                sys.stdout.flush()
    return rows, {"files": len(rows), "hashed": n_hashed, "hashed_gb": round(b_hashed / 1e9, 2),
                  "overlay_list_entries": len(ov), "lfs_placeholders": lfs[:200],
                  "newer_than_steam_update_not_hashed": newer_skipped}


def root_files(game_dir):
    out = []
    for f in sorted(os.listdir(game_dir)):
        p = os.path.join(game_dir, f)
        if os.path.isfile(p):
            out.append({"name": f, "size": os.path.getsize(p), "modified_utc": utc(os.path.getmtime(p))})
    return out


# ---------------------------------------------------------------------------------------------------- patch_ranked.log


def log_summary(game_dir):
    out = {"files": []}
    found = None
    for name in ("patch_ranked.log", "patch_ranked.log.1"):
        p = os.path.join(game_dir, name)
        if not os.path.isfile(p):
            continue
        out["files"].append({"name": name, "size": os.path.getsize(p), "modified_utc": utc(os.path.getmtime(p))})
        if found is None:
            lines = read_text(p).splitlines()
            marks = [i for i, l in enumerate(lines) if LOG_MARK in l]
            if marks:
                found = (name, lines[marks[-1]:], len(marks))
    if found is None:
        out["verdict"] = ("NO game session in patch_ranked.log: the patch loader (dinput8.dll) did not load, or the "
                          "game writes its log somewhere else")
        return out
    name, sess, n = found
    out["session_file"] = name
    out["sessions_in_file"] = n
    out["session_lines"] = len(sess)
    out["header"] = sess[:14]
    out["plugins"] = [l for l in sess if "BROS/plugins:" in l and (" found, " in l or "holds" in l)]
    declined = []
    for i, l in enumerate(sess):
        if "declined to arm" in l or "REFUSING" in l:
            declined.append((sess[i - 1] if i else "") + "  >>  " + l)
    out["declined"] = declined[:60]
    out["refused"] = [l for l in sess if re.search(r"REFUSED|\b[1-9]\d* refused", l)][:60]
    out["mode_and_switch_lines"] = [l for l in sess if re.search(
        r"BROS_GAME_MODE|BROS_BOOT_MODE|game mode|\(BROS_[A-Z_]+=|BROS_RR_|bros_zangetsu|bros_tools|bros_net|"
        r"bros_pl015|bros_roster|pacing|pl005_[a-z0-9]+\.txt|patch_ranked\.txt|PATCHSTAMP", l)][:120]
    out["warnings"] = [l for l in sess if re.search(r"⚠|(?i:\berror\b|\bfailed\b|\bfault\b|exception|crash)", l)][:120]
    out["tail"] = sess[-60:]
    s = out["plugins"][-1] if out["plugins"] else ""
    m = re.search(r"(\d+) found, (\d+) armed, (\d+) declined.*?(\d+) refused", s)
    out["verdict"] = ("loader ran; %s found, %s armed, %s declined, %s refused" % m.groups()) if m else \
        "loader ran, but no plugin summary line was found"
    return out


# ---------------------------------------------------------------------------------------------------- the running game


def classify_proc(name):
    base = re.split(r"[\\/]", name.strip())[-1]
    base = re.sub(r"(?i)\.exe$", "", base).lower()
    for cat, rx in _TOOL_RE:
        if rx.match(base):
            return cat, base
    return None, base


def win_snapshot():
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    invalid = wintypes.HANDLE(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    class MODULEENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("GlblcntUsage", wintypes.DWORD),
                    ("ProccntUsage", wintypes.DWORD), ("modBaseAddr", ctypes.c_void_p),
                    ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE),
                    ("szModule", wintypes.WCHAR * 256), ("szExePath", wintypes.WCHAR * 260)]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Module32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
    k32.Module32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]

    procs = []
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    if snap in (None, invalid):
        raise OSError(ctypes.get_last_error(), "process snapshot failed")
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            procs.append((e.th32ProcessID, e.szExeFile))
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)

    def modules(pid):
        snap = None
        for _ in range(6):
            snap = k32.CreateToolhelp32Snapshot(0x8 | 0x10, pid)
            if snap not in (None, invalid):
                break
            err = ctypes.get_last_error()
            if err != 24:                                               # ERROR_BAD_LENGTH: try again
                hint = {5: "access denied -- the game runs as administrator; run this collector as administrator",
                        299: "a 32-bit Python cannot read a 64-bit game"}.get(err, "")
                raise OSError(err, "module snapshot failed %s" % hint)
            time.sleep(0.25)
        out = []
        try:
            m = MODULEENTRY32W()
            m.dwSize = ctypes.sizeof(m)
            ok = k32.Module32FirstW(snap, ctypes.byref(m))
            while ok:
                out.append((m.szModule, m.szExePath, m.modBaseSize))
                ok = k32.Module32NextW(snap, ctypes.byref(m))
        finally:
            k32.CloseHandle(snap)
        return out
    return procs, modules


def posix_processes():
    """(pid, first argument, args) for every process, from /proc on Linux, from ps elsewhere."""
    out = []
    if os.path.isdir("/proc/self"):
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % d, "rb") as f:
                    args = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
            except OSError:
                continue
            if args:
                out.append((int(d), args[0], " ".join(args)))
        return out
    rc, so, _ = run(["ps", "-A", "-o", "pid=,command="], 30)
    for line in so.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            out.append((int(parts[0]), parts[1].split(" ")[0], parts[1]))
    return out


def runtime(game_dir):
    out = {"game_running": False, "tools": {}}
    game_real = norm(game_dir).lower() + os.sep if game_dir else ""
    windir = norm(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows").lower() + os.sep
    found_pids = []
    if is_windows():
        procs, modules = win_snapshot()
        for pid, exe in procs:
            cat, base = classify_proc(exe)
            if cat:
                out["tools"].setdefault(cat, set()).add(base)
            if exe.lower() == GAME_EXE.lower():
                found_pids.append(pid)
        out["game_processes"] = len(found_pids)
        for pid in found_pids[:2]:
            out["game_running"] = True
            mods = []
            try:
                for name, path, size in modules(pid):
                    low = norm(path).lower()
                    row = {"module": name, "path": path, "size": size}
                    in_game = bool(game_real) and low.startswith(game_real)
                    row["where"] = "game folder" if in_game else ("windows" if low.startswith(windir) else "other")
                    if row["where"] != "windows":
                        try:
                            row["md5"] = md5_file(path)
                        except OSError:
                            row["md5"] = "unreadable"
                    mods.append(row)
            except OSError as e:
                out["modules_error"] = str(e)
            out["modules"] = mods
    else:
        for pid, first, args in posix_processes():
            cat, base = classify_proc(first)
            if cat:
                out["tools"].setdefault(cat, set()).add(base)
            if GAME_EXE.lower() in args.lower() and "brosdiag_collect" not in args:
                found_pids.append(pid)
        out["game_processes"] = len(found_pids)
        for pid in found_pids[:4]:
            maps = set()
            mp = "/proc/%d/maps" % pid
            if os.path.isfile(mp):
                try:
                    for line in read_text(mp).splitlines():
                        parts = line.split(None, 5)
                        if len(parts) == 6 and parts[5].lower().endswith((".dll", ".exe", ".asi")):
                            maps.add(parts[5])
                except OSError as e:
                    out["maps_error"] = str(e)
                try:
                    env = read_text("/proc/%d/environ" % pid).split("\0")
                    keep = [x for x in env if re.match(r"(?i)(BROS_|WINE|DXVK|VKD3D|PROTON|STEAM_COMPAT_|SteamAppId"
                                                       r"|SteamGameId|LD_PRELOAD|__COMPAT_LAYER)", x)]
                    if keep:
                        out.setdefault("game_env", []).append(keep)
                except OSError:
                    pass
            else:
                try:
                    rc, so, _ = run(["lsof", "-p", str(pid), "-Fn"], 60)
                    for line in so.splitlines():
                        if line.startswith("n") and line.lower().endswith((".dll", ".exe", ".asi")):
                            maps.add(line[1:])
                except Exception as e:
                    out["lsof_error"] = type(e).__name__
            if maps:
                out["game_running"] = True
                mods = []
                for path in sorted(maps):
                    in_game = bool(game_real) and norm(path).lower().startswith(game_real)
                    row = {"module": os.path.basename(path), "path": path,
                           "where": "game folder" if in_game else "other"}
                    if in_game:
                        try:
                            row["md5"] = md5_file(path)
                        except OSError:
                            row["md5"] = "unreadable"
                    mods.append(row)
                out.setdefault("modules", []).extend(mods)
    out["tools"] = dict((k, sorted(v)) for k, v in out["tools"].items())
    mods = out.get("modules") or []
    names = [m["module"].lower() for m in mods]
    out["dinput8_from_game_folder"] = any(m["module"].lower() == "dinput8.dll" and m["where"] == "game folder"
                                          for m in mods)
    out["rebalance_plugins_loaded"] = sorted(m["module"] for m in mods
                                             if "rebalanceofsouls" in m["path"].replace("\\", "/").lower())
    out["dinput8_copies_loaded"] = names.count("dinput8.dll")
    return out


# ---------------------------------------------------------------------------------------------------- copies


def copy_list(game_dir):
    out = []
    for f in sorted(os.listdir(game_dir)):
        p = os.path.join(game_dir, f)
        low = f.lower()
        if not os.path.isfile(p) or low in ("devtoken.txt", "tokenopen.txt"):
            continue
        if low.startswith("patch_ranked.log") or (low.endswith(TEXT_EXT) and os.path.getsize(p) <= SMALL):
            out.append((f, p))
    rb = os.path.join(game_dir, "ReBalanceOfSouls")
    if os.path.isdir(rb):
        for f in sorted(os.listdir(rb)):
            p = os.path.join(rb, f)
            if os.path.isfile(p) and f.lower().endswith(TEXT_EXT) and os.path.getsize(p) <= SMALL:
                out.append(("ReBalanceOfSouls/" + f, p))
    for sub, pat, keep, cap in (("crashlogs", "*", 5, SMALL), ("BROS_Diagnostics", "*.jsonl", 2, 8 * SMALL)):
        d = os.path.join(game_dir, sub)
        if os.path.isdir(d):
            files = [p for p in glob.glob(os.path.join(d, pat)) if os.path.isfile(p) and os.path.getsize(p) <= cap]
            for p in sorted(files, key=os.path.getmtime)[-keep:]:
                out.append((sub + "/" + os.path.basename(p), p))
    return out


# ---------------------------------------------------------------------------------------------------- main


def pick_game(args, repo, cfg):
    tried = []
    if args.game:
        g = args.game.strip().strip('"')
        if os.path.isfile(g):
            g = os.path.dirname(g)
        tried.append(("argument", g))
    if cfg and cfg.get("GAME_PATH"):
        tried.append(("launcher Json/config.json GAME_PATH", cfg["GAME_PATH"]))
    for root in steam_roots():
        for lib in steam_libraries(root):
            g = game_from_library(lib)
            if g:
                tried.append(("Steam library", g))
    for how, g in tried:
        if find_exe(g):
            return os.path.abspath(g), how
    if sys.stdin and sys.stdin.isatty():
        print("I could not find the game. Paste or drag the folder that holds %s here, then press Enter:" % GAME_EXE)
        g = input("> ").strip().strip('"').strip("'")
        if os.path.isfile(g):
            g = os.path.dirname(g)
        if find_exe(g):
            return os.path.abspath(g), "typed"
    return None, "; ".join("%s: %s" % t for t in tried) or "nothing found"


def main():
    ap = argparse.ArgumentParser(description="Collect what is needed to diagnose a BLEACH Rebirth of Souls install.")
    ap.add_argument("game", nargs="?", help="the folder that holds BLEACH_Rebirth_of_Souls.exe")
    ap.add_argument("--repo", help="the launcher checkout (the folder with Json/ and launcher/)")
    ap.add_argument("--full", action="store_true", help="md5 every file of the game folder (slow)")
    ap.add_argument("--out", help="where to write the zip (default: beside this script)")
    ap.add_argument("--no-pause", action="store_true", help="do not wait for Enter at the end")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass

    for w in (os.environ.get("USERNAME"), os.environ.get("USER"), os.environ.get("LOGNAME"),
              os.environ.get("COMPUTERNAME"), os.environ.get("USERDOMAIN")):
        SCRUB.add(w)
    try:
        SCRUB.add(socket.gethostname().split(".")[0])
    except Exception:
        pass
    try:
        import getpass
        SCRUB.add(getpass.getuser())
    except Exception:
        pass

    here = os.path.dirname(os.path.abspath(__file__))
    print("BROS diagnostics collector -- reading only; nothing is sent anywhere.")
    t0 = time.time()
    report = {"collector": COLLECTOR, "collector_md5": md5_file(os.path.abspath(__file__)), "utc": utc()}
    report["machine"] = section(report, "machine", machine_info)
    report["displays"] = section(report, "displays", displays)
    report["controllers"] = section(report, "controllers", controllers)
    report["wine"] = section(report, "wine", wine_info)
    report["environment"] = section(report, "environment", env_vars)

    repo = find_repo([args.repo, os.getcwd(), here])
    cfg = None
    if repo:
        try:
            cfg = json.loads(read_text(os.path.join(repo, "Json", "config.json")))
        except Exception:
            cfg = None
    game, how = pick_game(args, repo, cfg)
    report["game_folder"] = game
    report["game_folder_found_by"] = how
    if not repo and game:
        rep = os.path.join(game, "launcher_install_report.txt")
        if os.path.isfile(rep):
            m = re.search(r"(?m)^Repo:\s*(.+)$", read_text(rep, 4000))
            if m:
                repo = find_repo([m.group(1).strip()])
    report["steam"] = section(report, "steam", steam_info, game)       # also learns the Steam names to scrub
    if repo:
        print("Launcher checkout: %s" % repo)
        report["repo"] = section(report, "repo", repo_info, repo)
    else:
        report["repo"] = None
        print("No launcher checkout found (pass --repo <folder> if there is one).")
    rows, inv = [], None
    if game:
        print("Game folder: %s (%s)" % (game, how))
        report["exe_md5"] = section(report, "exe_md5", md5_file, find_exe(game))
        report["compat_flags"] = section(report, "compat_flags", compat_flags, game)
        report["root_files"] = section(report, "root_files", root_files, game)
        report["log"] = section(report, "log", log_summary, game)
        report["saves"] = section(report, "saves", save_folders, game)
        ref = (report.get("repo") or {}).get("ressources_savedata_md5")
        for sv in report.get("saves") or []:
            for f in sv.get("files", []):
                f["same_as_launcher_ressources_savedata_bin"] = bool(ref) and f.get("md5") == ref
        last_upd = None
        for inst in (report.get("steam") or {}).get("installs", []):
            if inst.get("this_is_the_collected_folder"):
                lu = (inst.get("manifest") or {}).get("LastUpdated", "")
                last_upd = int(lu) if lu.isdigit() else None
        print("Listing the game folder and hashing what a patch can change ...")
        res = section(report, "inventory", inventory, game, args.full, last_upd)
        if res:
            rows, inv = res
        report["inventory"] = inv
    else:
        print("The game folder was not found: %s" % how)
    report["runtime"] = section(report, "runtime", runtime, game)

    stamp = utc().replace("-", "").replace(":", "").replace(" ", "_")
    outdirs = [args.out] if args.out else []
    if args.out and not os.path.isdir(args.out):
        try:
            os.makedirs(args.out)
        except OSError:
            pass
    outdirs += [here, os.getcwd(), os.path.expanduser("~")]
    copies = (section(report, "copy_list", copy_list, game) or []) if game else []
    report["copied_files"] = [c[0] for c in copies]
    report["total_s"] = round(time.time() - t0, 1)
    text = json.dumps(SCRUB.obj(report), indent=1, ensure_ascii=False, default=str)
    text2 = SCRUB(text)
    try:
        json.loads(text2)
        text = text2
    except ValueError:
        pass
    out = None
    for d in outdirs:
        if not d:
            continue
        cand = os.path.join(d, "brosdiag_%s.zip" % stamp)
        try:
            with zipfile.ZipFile(cand + ".tmp", "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("report.json", text)
                z.writestr("inventory.tsv", SCRUB("path\tsize\tmodified_utc\tmd5\twhy_hashed\n" + "\n".join(rows)
                                                  + "\n"))
                for rel, p in copies:
                    try:
                        with open(p, "rb") as f:
                            data = f.read()
                        z.writestr("files/" + rel, SCRUB(data.decode("utf-8", "replace")).encode("utf-8"))
                    except OSError as e:
                        z.writestr("files/" + rel + ".unreadable.txt", "%s" % e)
            os.replace(cand + ".tmp", cand)
            out = cand
            break
        except OSError:
            try:
                os.remove(cand + ".tmp")
            except OSError:
                pass
            continue

    print("")
    print("==== Summary")
    mach = report.get("machine") or {}
    wine = (report.get("wine") or {}).get("wine_get_version")
    print("Machine: %s, Python %s (%s-bit)%s" % (mach.get("platform"), mach.get("python"), mach.get("python_bits"),
                                                 ", Wine %s" % wine if wine else ""))
    lg = report.get("log") or {}
    print("patch_ranked.log: %s" % lg.get("verdict", "not read"))
    for f in lg.get("files", []):
        print("  %s  %d bytes, last written %s UTC" % (f["name"], f["size"], f["modified_utc"]))
    for l in (lg.get("declined") or [])[:12]:
        print("  declined: %s" % SCRUB(l)[:220])
    env = report.get("environment") or {}
    bros = {}
    for k in ("process", "user", "system"):
        for n, v in (env.get(k) or {}).items():
            if n.upper().startswith("BROS_"):
                bros["%s %s" % (k, n)] = v
    print("BROS_* environment variables: %s" % (", ".join("%s=%s" % kv for kv in sorted(bros.items())) or "none"))
    rt = report.get("runtime") or {}
    if rt.get("game_running"):
        print("Running game: dinput8.dll from the game folder: %s; ReBalanceOfSouls plugins loaded: %d"
              % ("yes" if rt.get("dinput8_from_game_folder") else "NO", len(rt.get("rebalance_plugins_loaded") or [])))
        other = [m["module"] for m in (rt.get("modules") or []) if m.get("where") == "other"]
        if other:
            print("  other non-system DLLs in the game: %s" % ", ".join(sorted(set(other))[:30]))
    elif rt.get("modules_error"):
        print("Running game: %s" % rt.get("modules_error"))
    else:
        print("Running game: not running (start it and run this again to record what it loads)")
    for cat, names in sorted((rt.get("tools") or {}).items()):
        print("Programs running -- %s: %s" % (cat, ", ".join(names)))
    for inst in (report.get("steam") or {}).get("installs", []):
        man = inst.get("manifest") or {}
        print("Steam copy: %s  build %s, updated %s%s" % (SCRUB(inst["game_folder"]), man.get("buildid"),
                                                         man.get("LastUpdated_utc"),
                                                         "  <- collected" if inst.get("this_is_the_collected_folder")
                                                         else ""))
    for r in (report.get("steam") or {}).get("roots", []):
        for u in r.get("users", []):
            if u.get("LaunchOptions"):
                print("Steam launch options: %s" % SCRUB(u["LaunchOptions"]))
        if r.get("compat_tool"):
            tool = r["compat_tool"]
            print("Steam compatibility tool: %s" % (tool.get("name") if isinstance(tool, dict) else tool))
    if report.get("errors"):
        print("Probes that failed (not fatal): %s" % ", ".join(sorted(report["errors"])))
    if out:
        print("")
        print("Wrote %s  (%d files listed, %d copied, %.0f s)." % (out, len(rows), len(copies), time.time() - t0))
        print("Please send that zip to Berg. It was written on this PC only; nothing was uploaded.")
    else:
        print("Could not write the zip anywhere -- pass --out <a folder you can write to>.")
    if is_windows() and not args.no_pause and sys.stdin and sys.stdin.isatty():
        try:
            input("Press Enter to close.")
        except EOFError:
            pass
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
