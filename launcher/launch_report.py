"""Launch report: what happened when the game was started (session mv, 2026-11-17; the same file in the Dev launcher
and the public one).

Berg, 2026-11-17 11:53 CET: "another tester seems to be unable to launch the game sometimes. It fails silently and I
can't know the error that he is having. I need someway to know what happens here so I can fix his launcher".

Why a start can fail with nothing on screen:
- the launcher hides its console, and several errors are only printed there;
- once the game's exe is started the launcher closes, and nobody looks at whether the game survives its first
  seconds (a blocked or missing DLL, an antivirus, Steam not running, a game process left over from before ...).

What this module does (all of it best effort: no function here raises, and none delays the start):
1. begin(base_dir, flavor): everything the launcher prints is also kept, in memory and in a file per run
   (<reports>\\console\\console_<time>_<pid>.log), tracebacks of uncaught errors included (Python prints them).
2. hook_tk(window, messagebox): an error inside a click or a timer of the window (Tk prints it to the hidden console
   and carries on: "the click did nothing") is printed with its traceback, kept as a report, and shown once.
3. note_version(version) at the top of launch(), then game_started(game_path, proc, ...): a small WATCHER
   process (this file, --watch) follows the game after the launcher has closed: whether its process stays, its exit code, when its window appears, whether the patch's own
   log is written (the loader ran), what Windows recorded at that moment (crash records, files blocked by Smart App
   Control or the antivirus), Steam, a game left running from before. It writes one report per start. When the game
   did not come up, it tells the player in a message box and offers to open the folder with the report.
4. not_started(game_path, reason, ...): the same report and message when the exe could not be started at all.
5. python launcher\\launch_report.py --collect (or "BROS Launch Report.bat"): one zip on the Desktop with a fresh
   snapshot of the PC and the game folder, Windows' records of the last 30 minutes, the last reports and the
   launcher's console logs, for the player to send by hand.

Nothing is sent anywhere. The reports stay in %LOCALAPPDATA%\\BROS Launcher\\launch_reports (BROS_LAUNCH_REPORT_DIR
overrides it). They are scrubbed of the Windows user name, the PC's name, Steam IDs and IP addresses.

Test knobs (environment): BROS_LAUNCH_REPORT_DIR; BROS_LAUNCH_REPORT_NOBOX=1 (no message box: its text goes to
lastbox.txt); BROS_LAUNCH_REPORT_TIMES="ok_after,stable,gone,max,appear" in seconds; BROS_LAUNCH_REPORT_OFF=1 (the
launcher starts no watcher).
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback

VERSION = "launch-report 1 (2026-11-17)"
EXE_NAME = "BLEACH_Rebirth_of_Souls.exe"
LOADER_LOG = "patch_ranked.log"
PLUGIN_DIR = "ReBalanceOfSouls"
KEEP_REPORTS = 40
KEEP_CONSOLES = 12
RING_LINES = 400

# seconds: OK once a window has stayed STABLE and OK_AFTER has passed; FAILED once no game process has existed for
# GONE; a start with no window by MAX is reported as stuck; an elevated start whose process never shows by APPEAR
OK_AFTER, STABLE, GONE, MAX, APPEAR = 40.0, 10.0, 8.0, 150.0, 45.0
POLL = 0.5

_NO_WINDOW = 0x08000000
_NEW_GROUP = 0x00000200
_BREAKAWAY = 0x01000000

_state = {"begun": False, "base": None, "flavor": None, "ring": None, "console": None, "boxes": 0, "version": None}


# ------------------------------------------------------------------------------------------------ places and text
def report_dir():
    d = os.environ.get("BROS_LAUNCH_REPORT_DIR")
    if not d:
        root = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        d = os.path.join(root, "BROS Launcher", "launch_reports")
    return d


def _stamp(t=None):
    return time.strftime("%Y%m%d_%H%M%S", time.localtime(t))


def _clock(t=None):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) + time.strftime(" (UTC%z)", time.localtime(t))


_RX_STEAMID = re.compile(r"\b7656119\d{10}\b")
_RX_IP = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")


_COMMON_NAMES = ("user", "admin", "administrator", "owner", "home", "game", "games", "gamer", "steam", "public",
                 "windows", "default", "player", "test", "bleach", "local", "desktop")


def _scrub_table():
    out = []
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    user = os.environ.get("USERNAME") or os.path.basename(home.rstrip("\\/"))
    pc = os.environ.get("COMPUTERNAME") or ""
    if home and len(home) > 3:
        out.append((re.compile(re.escape(home), re.I), "%USERPROFILE%"))
        out.append((re.compile(re.escape(home.replace("\\", "/")), re.I), "%USERPROFILE%"))
    if user and len(user) >= 4 and user.lower() not in _COMMON_NAMES:
        out.append((re.compile(r"(?<![A-Za-z0-9_])" + re.escape(user) + r"(?![A-Za-z0-9_])", re.I), "<user>"))
    if pc and len(pc) >= 3:
        out.append((re.compile(r"(?<![A-Za-z0-9_])" + re.escape(pc) + r"(?![A-Za-z0-9_])", re.I), "<pc>"))
    return out


_scrub_cache = []


def scrub(text):
    """The Windows user name, the PC's name, Steam IDs and IP addresses out of a text."""
    try:
        if not _scrub_cache:
            _scrub_cache.append(_scrub_table())
        text = str(text)
        for rx, to in _scrub_cache[0]:
            text = rx.sub(to, text)
        text = _RX_STEAMID.sub("<steamid>", text)

        def ip(m):
            # file and driver versions look like addresses (10.0.19041.1): keep those that sit beside "version"
            before = text[max(0, m.start() - 24):m.start()].lower()
            if "ver" in before or "build" in before or "file" in before:
                return m.group(0)
            return "<ip>"
        return _RX_IP.sub(ip, text)
    except Exception:
        return "(text withheld: it could not be scrubbed)"


def _read_text(path, limit=400000):
    try:
        with open(path, "rb") as f:
            b = f.read(limit)
    except OSError as e:
        return None, str(e)
    for enc in ("utf-8-sig", "utf-16"):
        try:
            if enc == "utf-16" and not (b[:2] in (b"\xff\xfe", b"\xfe\xff") or b[1:2] == b"\0"):
                continue
            return b.decode(enc), None
        except UnicodeDecodeError:
            pass
    return b.decode("latin-1", "replace"), None


def _prune(folder, prefix, keep):
    try:
        names = sorted(n for n in os.listdir(folder) if n.startswith(prefix))
        for n in names[:-keep] if keep else names:
            try:
                os.remove(os.path.join(folder, n))
            except OSError:
                pass
    except OSError:
        pass


# ------------------------------------------------------------------------------------------------ the launcher's side
class _Tee:
    """stdout / stderr kept as well: the last lines in memory, the whole run in a file."""

    def __init__(self, stream, ring, f):
        self.stream, self.ring, self.f, self.part = stream, ring, f, ""

    def write(self, s):
        try:
            if self.stream is not None:
                self.stream.write(s)
        except Exception:
            pass
        try:
            s = str(s)
            self.part += s
            if "\n" in self.part:
                lines = self.part.split("\n")
                self.part = lines.pop()
                now = time.strftime("%H:%M:%S")
                for line in lines:
                    self.ring.append("%s %s" % (now, line))
                    if self.f is not None:
                        self.f.write("%s %s\n" % (now, line))
                if self.f is not None:
                    self.f.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            if self.stream is not None:
                self.stream.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return bool(self.stream is not None and self.stream.isatty())
        except Exception:
            return False

    @property
    def encoding(self):
        return getattr(self.stream, "encoding", None) or "utf-8"

    def __getattr__(self, name):
        if self.stream is None:
            raise AttributeError(name)
        return getattr(self.stream, name)


def begin(base_dir, flavor=None):
    """Keep what the launcher prints. Safe to call twice; never raises. Returns the console file's path or None."""
    try:
        if _state["begun"]:
            return _state["console"]
        _state.update(begun=True, base=base_dir, flavor=flavor, ring=collections.deque(maxlen=RING_LINES))
        f = None
        try:
            d = os.path.join(report_dir(), "console")
            os.makedirs(d, exist_ok=True)
            _prune(d, "console_", KEEP_CONSOLES - 1)
            p = os.path.join(d, "console_%s_%d.log" % (_stamp(), os.getpid()))
            f = open(p, "w", encoding="utf-8", errors="replace")
            f.write("%s  %s  %s\n%s\n" % (_clock(), VERSION, flavor or "", scrub(" ".join(sys.argv[1:]))))
            f.flush()
            _state["console"] = p
        except Exception:
            f = None
        sys.stdout = _Tee(sys.stdout, _state["ring"], f)
        sys.stderr = _Tee(sys.stderr, _state["ring"], f)

        # uncaught errors of the launcher, of its threads and of Tk callbacks are printed to sys.stderr by Python's
        # own hooks: with the tee in place they are kept too
        return _state["console"]
    except Exception:
        return None


def note_version(version, boot_mode=None):
    """The version the player chose (launch() tells it before it prepares anything). Never raises."""
    try:
        _state["version"] = "%s%s" % (version, " (Quick Launch: %s)" % boot_mode if boot_mode else "")
        print("[launch-report] launch asked: %s" % _state["version"])
    except Exception:
        pass


def console_tail(lines=80):
    try:
        ring = _state["ring"]
        return list(ring)[-lines:] if ring else []
    except Exception:
        return []


def hook_tk(window, messagebox=None):
    """An error inside a click or a timer: printed with its traceback, kept as a report, shown (twice at most)."""
    try:
        def report(exc, val, tb):
            text = "".join(traceback.format_exception(exc, val, tb))
            try:
                sys.stderr.write("[launch-report] error in a click or a timer of the launcher:\n" + text + "\n")
            except Exception:
                pass
            try:
                if exc is not None and exc.__name__ == "TclError":
                    return                      # a widget that is already gone: nothing the player did wrong
                path = write_simple_report(
                    "LAUNCHER", "THE LAUNCHER HIT AN ERROR in a click or a timer; it may not have done what was asked",
                    ["The error:"] + text.rstrip().splitlines())
                if messagebox is not None and _state["boxes"] < 2:
                    _state["boxes"] += 1
                    last = text.strip().splitlines()[-1][:300] if text.strip() else "?"
                    messagebox.showerror(
                        "Launcher error",
                        "The launcher hit an error and may not have\ndone what you asked:\n\n%s\n\n"
                        "A report was saved. Please send it to the\npatch team:\n%s" % (last, path or "(not saved)"))
            except Exception:
                pass
        window.report_callback_exception = report
        return True
    except Exception:
        return False


def _commit(base):
    try:
        g = os.path.join(base, ".git")
        head, _ = _read_text(os.path.join(g, "HEAD"), 400)
        head = (head or "").strip()
        if head.startswith("ref:"):
            ref = head[4:].strip()
            t, _ = _read_text(os.path.join(g, *ref.split("/")), 200)
            if t:
                return "%s (%s)" % (t.strip()[:12], ref.split("/")[-1])
            packed, _ = _read_text(os.path.join(g, "packed-refs"))
            for line in (packed or "").splitlines():
                if line.endswith(" " + ref):
                    return "%s (%s)" % (line[:12], ref.split("/")[-1])
            return "? (%s)" % ref
        return head[:12] or "?"
    except Exception:
        return "?"


def _context(game_path, how, version, note):
    log = os.path.join(game_path or "", LOADER_LOG)
    try:
        st = os.stat(log)
        log0 = [st.st_size, st.st_mtime]
    except OSError:
        log0 = None
    return {
        "report": VERSION, "t0": time.time(), "flavor": _state["flavor"], "base": _state["base"],
        "commit": _commit(_state["base"]) if _state["base"] else "?", "game": game_path, "how": how,
        "version": version or _state["version"], "note": note, "launcher_pid": os.getpid(), "log0": log0,
        "console": console_tail(120), "console_file": _state["console"],
        "env": {k: os.environ.get(k) for k in ("BROS_BOOT_MODE", "BROS_GAME_MODE", "BROS_VFS_MANIFEST")
                if os.environ.get(k)},
        "python": sys.version.split()[0] + (" 64-bit" if sys.maxsize > 2 ** 32 else " 32-bit"),
        "argv": [scrub(a) for a in sys.argv[1:]],
    }


def _spawn(ctx, handle=None):
    d = report_dir()
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "pending_%s_%d.json" % (_stamp(), os.getpid()))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(ctx, f)
    exe = sys.executable or "python"
    argv = [exe, "-B", os.path.abspath(__file__), "--watch", p]
    if handle:
        argv += ["--handle", str(int(handle))]
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=d,
              close_fds=not handle)
    if os.name == "nt":
        for flags in (_NO_WINDOW | _NEW_GROUP | _BREAKAWAY, _NO_WINDOW | _NEW_GROUP):
            try:
                subprocess.Popen(argv, creationflags=flags, **kw)
                return True
            except OSError:
                continue
        return False
    subprocess.Popen(argv, start_new_session=True, **kw)
    return True


def game_started(game_path, proc=None, how="direct", version=None, note=None):
    """Called right after the game's exe was started (proc: the Popen object, or None for an elevated start).
    Starts the watcher and returns at once. True when the watcher was started."""
    try:
        if os.environ.get("BROS_LAUNCH_REPORT_OFF"):
            return False
        ctx = _context(game_path, how, version, note)
        ctx["pid"] = getattr(proc, "pid", None)
        handle = None
        try:
            if proc is not None and os.name == "nt":
                import _winapi
                cur = _winapi.GetCurrentProcess()
                handle = _winapi.DuplicateHandle(cur, int(proc._handle), cur, 0, True, _winapi.DUPLICATE_SAME_ACCESS)
        except Exception:
            handle = None
        ok = _spawn(ctx, handle)
        print("[launch-report] watching the start (%s)%s" % (how, "" if ok else ": the watcher could not be started"))
        return ok
    except Exception as e:
        try:
            print("[launch-report] no watcher: %s" % e)
        except Exception:
            pass
        return False


def not_started(game_path, reason, version=None, how="direct"):
    """The exe could not be started at all (reason: the error's text). A report and a message, from the watcher."""
    try:
        print("[launch-report] the game was NOT started: %s" % reason)
        if os.environ.get("BROS_LAUNCH_REPORT_OFF"):
            return False
        ctx = _context(game_path, how, version, None)
        ctx["pid"] = None
        ctx["failed"] = str(reason)
        return _spawn(ctx)
    except Exception:
        return False


# ------------------------------------------------------------------------------------------------ Windows, read only
class _Win:
    """The few Windows calls the watcher needs. Every method returns a plain value and never raises."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.c, self.w = ctypes, wintypes
        k = self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        u = self.u = ctypes.WinDLL("user32", use_last_error=True)

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", wintypes.WCHAR * 260)]
        self.PE = PROCESSENTRY32W
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
        k.Process32FirstW.argtypes = k.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        k.WaitForSingleObject.restype = wintypes.DWORD
        k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        self.ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.EnumWindows.argtypes = (self.ENUM, wintypes.LPARAM)
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        u.IsWindowVisible.argtypes = (wintypes.HWND,)
        u.GetWindowTextW.argtypes = u.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        u.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        u.MessageBoxW.restype = ctypes.c_int
        u.MessageBoxW.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT)

    def processes(self):
        """[(pid, parent pid, exe name)] of every process, or [] when it cannot be told."""
        out = []
        try:
            snap = self.k.CreateToolhelp32Snapshot(2, 0)
            if not snap or snap == self.w.HANDLE(-1).value:
                return out
            try:
                pe = self.PE()
                pe.dwSize = self.c.sizeof(pe)
                ok = self.k.Process32FirstW(snap, self.c.byref(pe))
                while ok:
                    out.append((int(pe.th32ProcessID), int(pe.th32ParentProcessID), pe.szExeFile))
                    ok = self.k.Process32NextW(snap, self.c.byref(pe))
            finally:
                self.k.CloseHandle(snap)
        except Exception:
            pass
        return out

    def open(self, pid):
        try:
            return self.k.OpenProcess(0x00100000 | 0x1000, False, int(pid)) or None
        except Exception:
            return None

    def close(self, h):
        try:
            if h:
                self.k.CloseHandle(h)
        except Exception:
            pass

    def exit_code(self, h):
        """None while the process runs (or when it cannot be told); its exit code once it has ended."""
        try:
            r = self.k.WaitForSingleObject(h, 0)
            if r != 0:
                return None
            code = self.w.DWORD()
            if self.k.GetExitCodeProcess(h, self.c.byref(code)):
                return int(code.value)
        except Exception:
            pass
        return None

    def valid(self, h):
        try:
            return self.k.WaitForSingleObject(h, 0) in (0, 0x102)
        except Exception:
            return False

    def started_at(self, h):
        """The process's creation time (epoch seconds), or None."""
        try:
            ft = [self.w.FILETIME() for _ in range(4)]
            if not self.k.GetProcessTimes(h, *[self.c.byref(x) for x in ft]):
                return None
            v = (ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime
            return v / 1e7 - 11644473600.0
        except Exception:
            return None

    def windows(self, pids):
        """Visible titled windows of these processes: [(pid, title, class, width, height)]."""
        out = []
        pids = set(pids)
        try:
            def cb(hwnd, _):
                try:
                    owner = self.w.DWORD()
                    self.u.GetWindowThreadProcessId(hwnd, self.c.byref(owner))
                    if owner.value in pids and self.u.IsWindowVisible(hwnd):
                        t = self.c.create_unicode_buffer(256)
                        self.u.GetWindowTextW(hwnd, t, 256)
                        cl = self.c.create_unicode_buffer(128)
                        self.u.GetClassNameW(hwnd, cl, 128)
                        r = self.w.RECT()
                        self.u.GetWindowRect(hwnd, self.c.byref(r))
                        out.append((int(owner.value), t.value, cl.value, r.right - r.left, r.bottom - r.top))
                except Exception:
                    pass
                return True
            self.u.EnumWindows(self.ENUM(cb), 0)
        except Exception:
            pass
        return out

    def box(self, title, text, ask=True):
        """A message box on top of everything. True when Yes was chosen."""
        try:
            flags = 0x30 | 0x40000 | 0x10000 | (0x4 if ask else 0)      # warning, topmost, set foreground, yes/no
            return self.u.MessageBoxW(None, text, title, flags) == 6
        except Exception:
            return False


def _reg(root, key, value):
    try:
        import winreg
        with winreg.OpenKey(getattr(winreg, root), key) as k:
            return winreg.QueryValueEx(k, value)[0]
    except Exception:
        return None


def _run(argv, timeout=20, need_ok=False):
    """The output of a command (text), or None (it could not be run; with need_ok: or it reported a failure).
    No window."""
    try:
        r = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=timeout, creationflags=_NO_WINDOW if os.name == "nt" else 0)
        b = r.stdout or b""
        if need_ok and r.returncode != 0:
            return None
    except Exception:
        return None
    for enc in ("utf-8", "oem", "mbcs", "latin-1"):
        try:
            return b.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


EXIT_CODES = {
    0x00000000: "0: it closed by itself and reported no error",
    0x00000001: "1: it ended reporting a general error",
    0xFFFFFFFF: "-1: it was ended by another program (Task Manager, a launcher, a tool) or ended itself with -1",
    0xC0000005: "an access violation: the game crashed",
    0xC0000017: "not enough memory",
    0xC000001D: "an illegal instruction: the processor lacks something a DLL was built for, or a damaged file",
    0xC0000022: "access denied: Windows or a security program refused a file the game needs",
    0xC000007B: "a bad image: a DLL of the wrong kind (32-bit beside 64-bit) or a damaged one",
    0xC00000FD: "a stack overflow: the game crashed",
    0xC0000135: "a DLL the game needs was not found",
    0xC0000139: "a DLL is present but lacks a function the game needs (an old or foreign DLL)",
    0xC0000142: "a DLL failed to start (often a security program or an overlay)",
    0xC0000374: "heap corruption: the game crashed",
    0xC0000409: "a stack buffer check or a fast-fail: the game stopped itself",
    0xC000041D: "an error inside a window callback: the game crashed",
    0xC0000428: "Windows refused a file's signature",
    0xC0000602: "a fail-fast: the game stopped itself",
    0xC0E90002: "Smart App Control (or an application control policy) blocked one of the patch's DLLs",
    0xE06D7363: "an unhandled C++ error: the game crashed",
    0x40010004: "it was ended as a debugged process",
    0x000004C7: "the start was cancelled (the administrator prompt was declined)",
}


def exit_text(code):
    if code is None:
        return "unknown (the process was gone before it could be read)"
    code &= 0xFFFFFFFF
    known = EXIT_CODES.get(code)
    return "0x%08X (%s)" % (code, known) if known else "0x%08X (%d)" % (code, code)


# ------------------------------------------------------------------------------------------------ facts for the report
def _md5(path, limit=None):
    try:
        h = hashlib.md5()
        n = 0
        with open(path, "rb") as f:
            while True:
                b = f.read(1 << 20)
                if not b:
                    break
                h.update(b)
                n += len(b)
                if limit and n >= limit:
                    return h.hexdigest() + " (first %d MB)" % (limit >> 20)
        return h.hexdigest()
    except OSError as e:
        return "UNREADABLE: %s" % e


def _file_line(path, md5=True):
    try:
        st = os.stat(path)
    except OSError as e:
        return "%s: MISSING or unreadable (%s)" % (os.path.basename(path), e.strerror or e)
    return "%s: %d bytes, changed %s%s" % (os.path.basename(path), st.st_size,
                                         time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                                         ", md5 " + _md5(path) if md5 else "")


def foreign_files(game):
    """Graphics add-ons beside the exe (launcher/injector_check.py, the file next to this one): a list, or None."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import injector_check
        return injector_check.scan(game)
    except Exception:
        return None


def game_folder_facts(game, t0=None):
    out = []
    if not game:
        return ["(no game folder was given)"]
    out.append("Folder: %s" % game)
    flags = []
    low = game.lower()
    if "onedrive" in low:
        flags.append("inside OneDrive (its sync can lock or revert files)")
    if "\\program files" in low and "steamapps" not in low:
        flags.append("under Program Files outside Steam (Windows protects writes there)")
    if any(ord(ch) > 127 for ch in game):
        flags.append("its path has non-English characters")
    if flags:
        out.append("NOTE: the folder is " + "; ".join(flags))
    if not os.path.isdir(game):
        out.append("THE FOLDER DOES NOT EXIST or cannot be opened")
        return out
    try:
        import shutil
        du = shutil.disk_usage(game)
        out.append("Free space on its drive: %.1f GB%s" % (du.free / 2 ** 30, "  <-- LOW" if du.free < 2 * 2 ** 30
                                                         else ""))
    except Exception:
        pass
    out.append(_file_line(os.path.join(game, EXE_NAME)))
    out.append(_file_line(os.path.join(game, "dinput8.dll")) + "   (the patch's loader)")
    try:
        root_dlls = sorted(n for n in os.listdir(game) if n.lower().endswith((".dll", ".asi")))
        out.append("DLLs beside the exe (%d): %s" % (len(root_dlls), ", ".join(
            "%s %d" % (n, os.path.getsize(os.path.join(game, n))) for n in root_dlls)))
    except OSError as e:
        out.append("The folder could not be listed: %s" % e)
    foreign = foreign_files(game)
    if foreign:
        out.append("GRAPHICS ADD-ONS beside the exe (not the game's, not the patch's): " + ", ".join(
            "%s (%s, %d bytes)" % (f["name"], f["what"], f["bytes"]) for f in foreign))
    elif foreign is not None:
        out.append("Graphics add-ons beside the exe (ReShade and the like): none")
    pd = os.path.join(game, PLUGIN_DIR)
    try:
        plugs = sorted(n for n in os.listdir(pd) if n.lower().endswith(".dll"))
        out.append("Plugins in %s (%d): %s" % (PLUGIN_DIR, len(plugs), ", ".join(
            "%s %d" % (n[:-4], os.path.getsize(os.path.join(pd, n))) for n in plugs)))
        bad = []
        for n in plugs:
            try:
                with open(os.path.join(pd, n), "rb") as f:
                    if f.read(2) != b"MZ":
                        bad.append(n + " (not a DLL: damaged)")
            except OSError as e:
                bad.append("%s (cannot be read: %s)" % (n, e.strerror or e))
        if bad:
            out.append("PLUGINS THAT CANNOT BE LOADED: " + ", ".join(bad))
    except OSError:
        out.append("No %s folder (no plugins)" % PLUGIN_DIR)
    for n in ("patch_ranked.txt", "steam_appid.txt"):
        t, err = _read_text(os.path.join(game, n), 200)
        out.append("%s: %s" % (n, t.strip()[:80] if t is not None else "absent"))
    try:
        sw = sorted(n for n in os.listdir(game) if n.lower().startswith("bros_") and n.lower().endswith(".txt"))
        out.append("Switch files: %s" % (", ".join(sw) or "none"))
    except OSError:
        pass
    st, _ = _read_text(os.path.join(game, "launcher_patch_state.json"), 200000)
    if st:
        m = re.search(r'"(?:version|gameVersion|game_version)"\s*:\s*"([^"]+)"', st)
        out.append("launcher_patch_state.json: version %s" % (m.group(1) if m else "(not named)"))
    cl = os.path.join(game, "crashlogs")
    if os.path.isdir(cl):
        try:
            names = sorted(os.listdir(cl))
            if "session.active" in names:
                out.append("crashlogs\\session.active is present: the last session did not end cleanly, or a game "
                           "is running")
            new = [n for n in names if t0 and os.path.getmtime(os.path.join(cl, n)) >= t0 - 2 and n != "session.active"]
            out.append("Crash reports written by the patch during this start: %s" % (", ".join(new) or "none"))
            for n in new[-2:]:
                t, _ = _read_text(os.path.join(cl, n), 20000)
                if t:
                    out.append("--- %s (first lines)" % n)
                    out += ["    " + line for line in t.splitlines()[:60]]
        except OSError:
            pass
    if t0:
        try:
            new = []
            for n in sorted(os.listdir(game)):
                p = os.path.join(game, n)
                if os.path.isfile(p) and os.path.getmtime(p) >= t0 - 1:
                    new.append("%s %d" % (n, os.path.getsize(p)))
            out.append("Files beside the exe written since the start: %s" % (", ".join(new) or "none"))
        except OSError:
            pass
    return out


def loader_log_facts(game, log0, t0):
    """What the patch's own log gained since the start: the proof that the loader ran."""
    p = os.path.join(game or "", LOADER_LOG)
    try:
        st = os.stat(p)
    except OSError:
        return False, ["%s does not exist: the patch's loader has never written here" % LOADER_LOG]
    if st.st_mtime < t0 - 1:
        return False, ["%s was NOT written during this start (last written %s): the patch's loader did not run "
                       "-- it was blocked, is missing, or the game ended before loading it"
                       % (LOADER_LOG, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)))]
    start = log0[0] if (log0 and st.st_size >= log0[0]) else 0          # smaller than before: a fresh file
    try:
        with open(p, "rb") as f:
            f.seek(start)
            b = f.read(600000)
    except OSError as e:
        return True, ["%s was written during this start but cannot be read: %s" % (LOADER_LOG, e)]
    lines = b.decode("utf-8", "replace").splitlines()
    if start and not lines:
        try:
            with open(p, "rb") as f:
                lines = f.read(600000).decode("utf-8", "replace").splitlines()
        except OSError:
            pass
    out = ["%s gained %d line(s) during this start: the patch's loader ran" % (LOADER_LOG, len(lines))]
    show = lines if len(lines) <= 110 else lines[:70] + ["    ... (%d lines left out) ..." % (len(lines) - 110)] + \
        lines[-40:]
    out += ["    " + line[:300] for line in show]
    return True, out


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


EVENT_SOURCES = (
    ("Application", "Provider[@Name='Application Error' or @Name='Windows Error Reporting' or "
                    "@Name='Application Hang' or @Name='SideBySide' or @Name='.NET Runtime']",
     "Windows' crash and error records (Application log)"),
    ("Microsoft-Windows-CodeIntegrity/Operational", None,
     "Files Windows refused to load (Code Integrity: Smart App Control, application control)"),
    ("Microsoft-Windows-Windows Defender/Operational",
     "(EventID=1006 or EventID=1007 or EventID=1008 or EventID=1015 or EventID=1116 or EventID=1117 or "
     "EventID=1118 or EventID=1119 or EventID=1121 or EventID=1122 or EventID=1123 or EventID=1124)",
     "Microsoft Defender: detections and blocks"),
    ("Microsoft-Windows-AppLocker/EXE and DLL", "(EventID=8004 or EventID=8003)", "AppLocker blocks"),
)


def windows_events(since, only_game=True):
    """What Windows logged since `since` (epoch seconds), read with wevtutil; the text as Windows gives it.
    Returns (lines for the report, {channel: number of events kept, or None when the log could not be read})."""
    out, counts = [], {}
    for channel, cond, title in EVENT_SOURCES:
        q = "*[System[%sTimeCreated[@SystemTime>='%s']]]" % ((cond + " and ") if cond else "", _iso(since))
        text = _run(["wevtutil", "qe", channel, "/q:" + q, "/f:text", "/rd:true", "/c:40"], timeout=25, need_ok=True)
        out.append("== %s" % title)
        if text is None:
            counts[channel] = None
            out.append("   (could not be read)")
            continue
        events = [e.strip() for e in re.split(r"(?m)^Event\[\d+\]:?\s*$", text) if e.strip()]
        events = [e for e in events if re.search(r"(?m)^\s*(Event ID|Log Name|Source)\s*:", e)]
        if channel == "Application" and only_game:
            stem = EXE_NAME.lower()[:20]
            events = [e for e in events if stem in e.lower() or "dinput8" in e.lower() or "python" in e.lower()
                      or PLUGIN_DIR.lower() in e.lower()]
        counts[channel] = len(events)
        if not events:
            out.append("   none")
            continue
        for e in events[:25]:
            lines = [ln.rstrip() for ln in e.splitlines() if ln.strip()
                     and not re.match(r"^\s*(User|User Name|Computer)\s*:", ln)]      # who and which PC: left out
            out += ["   " + ln[:400] for ln in lines[:40]]
            out.append("   --")
        counts[channel + "#text"] = "\n".join(events)
    return out, counts


def wer_facts(since):
    """Windows Error Reporting's own report of a crash of the game: the faulting module and the DLLs loaded."""
    out = []
    roots = []
    for base in (os.environ.get("ProgramData"), os.environ.get("LOCALAPPDATA")):
        if base:
            for sub in ("ReportArchive", "ReportQueue"):
                roots.append(os.path.join(base, "Microsoft", "Windows", "WER", sub))
    found = []
    for r in roots:
        try:
            for n in os.listdir(r):
                if EXE_NAME[:12].lower() in n.lower():
                    p = os.path.join(r, n)
                    if os.path.getmtime(p) >= since - 5:
                        found.append(p)
        except OSError:
            continue
    for p in sorted(found, key=os.path.getmtime)[-3:]:
        out.append("== %s" % os.path.basename(p))
        t, err = _read_text(os.path.join(p, "Report.wer"), 2000000)
        if t is None:
            out.append("   Report.wer cannot be read (%s)" % err)
            continue
        names, mods = {}, []
        for line in t.splitlines():
            m = re.match(r"^(Sig|DynamicSig)\[(\d+)\]\.(Name|Value)=(.*)$", line)
            if m:
                names.setdefault((m.group(1), m.group(2)), {})[m.group(3)] = m.group(4)
                continue
            m = re.match(r"^LoadedModule\[\d+\]=(.*)$", line)
            if m:
                mods.append(m.group(1))
            elif line.startswith(("EventType=", "FriendlyEventName=", "AppName=")):
                out.append("   " + line[:200])
        for key in sorted(names, key=lambda k: (k[0], int(k[1]))):
            if key[0] == "Sig":
                out.append("   %s = %s" % (names[key].get("Name", "?"), names[key].get("Value", "?")))
        windir = (os.environ.get("WINDIR") or "C:\\Windows").lower()
        other = [m for m in mods if not m.lower().startswith(windir)]
        if other:
            out.append("   DLLs loaded from outside Windows (%d): %s" % (len(other), "; ".join(other[:80])))
    dumps = os.path.join(os.environ.get("LOCALAPPDATA") or "", "CrashDumps")
    try:
        new = [n for n in os.listdir(dumps) if n.lower().startswith(EXE_NAME[:12].lower())
               and os.path.getmtime(os.path.join(dumps, n)) >= since - 5]
        if new:
            out.append("Crash dumps written: " + ", ".join("%s (%d bytes) in %s" % (
                n, os.path.getsize(os.path.join(dumps, n)), dumps) for n in new))
    except OSError:
        pass
    return out or ["none"]


WATCHED_PROCESSES = (
    "steam.exe", "steamwebhelper.exe", "easyanticheat.exe", "easyanticheat_eos.exe", "start_protected_game.exe",
    "werfault.exe", "msmpeng.exe", "avp.exe", "avgsvc.exe", "avastsvc.exe", "bdservicehost.exe", "mbam.exe",
    "mbamservice.exe", "ekrn.exe", "mcshield.exe", "nortonsecurity.exe", "sophosfilescanner.exe", "rtss.exe",
    "msiafterburner.exe", "discord.exe", "obs64.exe", "nvcontainer.exe", "radeonsoftware.exe", "reshade.exe",
    "sandboxie.exe", "sbiesvc.exe", "gamebar.exe", "xboxgamebarwidgets.exe")


def pc_facts(win, slow=False):
    out = []
    try:
        v = sys.getwindowsversion() if hasattr(sys, "getwindowsversion") else None
        cv = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        ubr = _reg("HKEY_LOCAL_MACHINE", cv, "UBR")
        out.append("Windows: %s %s, build %s%s (%s)" % (
            _reg("HKEY_LOCAL_MACHINE", cv, "ProductName") or "?",
            _reg("HKEY_LOCAL_MACHINE", cv, "DisplayVersion") or "",
            v.build if v else _reg("HKEY_LOCAL_MACHINE", cv, "CurrentBuild"), "" if ubr is None else ".%s" % ubr,
            "Windows 11" if v and v.build >= 22000 else "Windows 10 or older"))
    except Exception:
        pass
    try:
        import locale
        out.append("Language: %s" % (locale.getlocale()[0] or locale.getdefaultlocale()[0]))
    except Exception:
        pass
    cpu = _reg("HKEY_LOCAL_MACHINE", r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString")
    if cpu:
        out.append("CPU: %s" % cpu.strip())
    try:
        c = win.c

        class MS(c.Structure):
            _fields_ = [("dwLength", c.c_ulong), ("dwMemoryLoad", c.c_ulong)] + [
                (n, c.c_ulonglong) for n in ("ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile",
                                             "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")]
        ms = MS()
        ms.dwLength = c.sizeof(ms)
        if win.k.GlobalMemoryStatusEx(c.byref(ms)):
            out.append("Memory: %.1f GB, %.1f GB free; page file %.1f GB free of %.1f GB" % (
                ms.ullTotalPhys / 2 ** 30, ms.ullAvailPhys / 2 ** 30, ms.ullAvailPageFile / 2 ** 30,
                ms.ullTotalPageFile / 2 ** 30))
    except Exception:
        pass
    for i in range(4):
        key = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\%04d" % i
        d = _reg("HKEY_LOCAL_MACHINE", key, "DriverDesc")
        if d:
            out.append("Graphics: %s, driver %s (%s)" % (d, _reg("HKEY_LOCAL_MACHINE", key, "DriverVersion"),
                                                       _reg("HKEY_LOCAL_MACHINE", key, "DriverDate")))
    sac = _reg("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\CI\Policy", "VerifiedAndReputablePolicyState")
    out.append("Smart App Control: %s" % {0: "off", 1: "ON  <-- it blocks the patch's DLLs", 2: "evaluation",
                                          None: "not present"}.get(sac, sac))
    cfa = _reg("HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\Windows Defender\Windows Defender Exploit Guard"
               r"\Controlled Folder Access", "EnableControlledFolderAccess")
    out.append("Defender controlled folder access: %s" % {0: "off", 1: "ON  <-- it can block the launcher's writes",
                                                          2: "audit", None: "off or not readable"}.get(cfa, cfa))
    sysdir = os.path.join(os.environ.get("WINDIR") or "C:\\Windows", "System32")
    missing = [n for n in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "d3d11.dll", "xinput1_4.dll",
                           "dinput8.dll") if not os.path.exists(os.path.join(sysdir, n))]
    out.append("System DLLs the game needs: %s" % ("MISSING " + ", ".join(missing) if missing else "all present"))
    user = _reg("HKEY_CURRENT_USER", r"Software\Valve\Steam\ActiveProcess", "ActiveUser")
    procs = win.processes() if win else []
    names = [n.lower() for _, _, n in procs]
    steam = "steam.exe" in names
    out.append("Steam: %s; signed in: %s" % ("running" if steam else "NOT RUNNING  <-- the game needs Steam open",
                                              "yes" if user else "no  <-- or it cannot be told" if steam else "no"))
    seen = sorted(set(n for n in names if n in WATCHED_PROCESSES and n not in ("steam.exe", "steamwebhelper.exe")))
    out.append("Security, overlay and capture programs running (from a fixed list): %s" % (", ".join(seen) or "none"))
    if slow:
        av = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                   "Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | "
                   "ForEach-Object { $_.displayName + ' (state ' + $_.productState + ')' }"], timeout=20)
        out.append("Antivirus products registered with Windows: %s" % (
            "; ".join(x.strip() for x in av.splitlines() if x.strip()) if av and av.strip() else "(not readable)"))
    return out


def compat_facts(game):
    exe = os.path.normpath(os.path.join(game or "", EXE_NAME))
    out = []
    for root in ("HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"):
        v = _reg(root, r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers", exe)
        if v:
            out.append("Compatibility settings on the exe (%s): %s%s" % (
                "this user" if root.endswith("USER") else "all users", v,
                "  <-- run as administrator: a game mode or Quick Launch does not reach it" if "RUNASADMIN" in v
                else ""))
    return out or ["Compatibility settings on the exe: none"]


# ------------------------------------------------------------------------------------------------ the report
def _sections(pairs):
    out = []
    n = 0
    for title, lines in pairs:
        if lines is None:
            continue
        n += 1
        out.append("")
        out.append("%d. %s" % (n, title))
        out.append("-" * (len(title) + 3 + len(str(n))))
        out += [str(x) for x in lines]
    return out


def _write(kind, verdict, body):
    d = report_dir()
    os.makedirs(d, exist_ok=True)
    _prune(d, "launch_", KEEP_REPORTS - 1)
    p = os.path.join(d, "launch_%s_%s.txt" % (_stamp(), kind))
    head = ["BROS launch report -- %s" % VERSION, _clock(), "", "RESULT: " + verdict, ""]
    if kind != "OK":
        head += ["Please send this file to the patch team. It holds no Steam ID, no account or PC name and no IP",
                 "address (they are replaced by <...>); it lists file names, sizes and what Windows recorded.", ""]
    text = scrub("\n".join(head + body) + "\n")
    with open(p + ".tmp", "w", encoding="utf-8", errors="replace", newline="\r\n") as f:
        f.write(text)
    os.replace(p + ".tmp", p)
    return p


def write_simple_report(kind, verdict, lines):
    """A report made inside the launcher (an error in a click): the error, the console's last lines."""
    try:
        body = _sections([("What happened", lines),
                          ("The launcher", ["Launcher: %s, commit %s" % (_state["flavor"] or "?", _commit(
                              _state["base"]) if _state["base"] else "?"), "Python %s" % sys.version.split()[0]]),
                          ("The launcher's console (last lines)", console_tail(80) or ["(empty)"])])
        return _write(kind, verdict, body)
    except Exception:
        return None


def hints(facts):
    """Likely causes, most telling first. Each is a pointer for the patch team, not a verdict."""
    out = []
    code = facts.get("exit_code")
    code = code & 0xFFFFFFFF if code is not None else None
    if facts.get("failed"):
        f = facts["failed"]
        if "WinError 2" in f or "WinError 3" in f:
            out.append("The exe is not where the launcher looks: the game path in the launcher is wrong, or the "
                       "game was moved or uninstalled.")
        if "WinError 5" in f or "WinError 225" in f or "WinError 1260" in f or "WinError 4551" in f:
            out.append("Windows or a security program refused to start the exe (an antivirus block or quarantine, "
                       "an application control policy).")
    if facts.get("sac_on") or code == 0xC0E90002:
        out.append("Smart App Control is on or blocked a DLL: it must be turned off in Windows Security (it cannot "
                   "make an exception for one file).")
    if facts.get("ci_blocks"):
        out.append("Windows refused to load a file during this start (section 'What Windows recorded', Code "
                   "Integrity): the file named there is the one that stopped the game.")
    if facts.get("defender_hits"):
        out.append("Microsoft Defender acted during this start (section 'What Windows recorded'): an exclusion for "
                   "the game folder, or restoring the quarantined file, is the fix.")
    if facts.get("foreign"):
        out.append("A graphics add-on sits in the game folder (%s). ReShade as dxgi.dll made the patched game die "
                   "as it created its window (a tester's crash log, 2026-11-16: a null call inside ReShade, reached "
                   "through online.dll and framedata.dll). Renaming the file is the test." % facts["foreign"])
    if facts.get("preexisting"):
        out.append("A game process from an earlier start was still running (%s). A second copy closes at once, and "
                   "files it holds cannot be replaced: end it in Task Manager (or restart the PC), then start again."
                   % facts["preexisting"])
    if code == 0 and not facts.get("window_seen") and not facts.get("preexisting"):
        out.append("It ended by itself with code 0 before showing a window: an exe does that when it hands over to "
                   "Steam, or when it finds a copy of itself already running.")
    if facts.get("steam_running") is False:
        out.append("Steam was not running. The game needs Steam open and signed in; started without it, it closes "
                   "or hands over to Steam without the patch.")
    if facts.get("relaunched"):
        out.append("The exe that was started ended and another game process took over (a restart through Steam). "
                   "A game restarted by Steam runs under EasyAntiCheat, which refuses the patch's loader.")
    if facts.get("loader_ran") is False and not facts.get("failed"):
        out.append("The patch's loader never wrote its log: dinput8.dll was not loaded (blocked, missing or "
                   "damaged), or the game ended before loading it.")
    if code == 0xC0000135:
        out.append("A DLL was not found: a missing system component (Visual C++ runtime, DirectX) or a file the "
                   "antivirus removed. Windows usually names it in a message box; 'System DLLs' below lists what "
                   "is missing.")
    if code in (0xC0000005, 0xC0000374, 0xC00000FD, 0xE06D7363, 0xC0000409, 0xC000041D) and facts.get("loader_ran"):
        out.append("The game crashed after the loader ran: the last lines of the patch's log and the Windows crash "
                   "record (faulting module) name where.")
    if facts.get("werfault"):
        out.append("Windows' crash reporter (WerFault) ran: the game crashed rather than closed.")
    if facts.get("no_window") and not out:
        out.append("The game's process stayed but never showed a window: it is stuck at start-up (a security "
                   "program scanning it, a hung overlay or driver, a full-screen mode the monitor refuses).")
    if facts.get("runasadmin"):
        out.append("The exe is set to run as administrator: an elevated game does not receive the launcher's "
                   "game mode or Quick Launch settings, and cannot be followed by this report.")
    if not out:
        out.append("Nothing obvious: the sections below hold what was seen.")
    return out


# ------------------------------------------------------------------------------------------------ the watcher
def _times():
    v = [OK_AFTER, STABLE, GONE, MAX, APPEAR]
    try:
        t = os.environ.get("BROS_LAUNCH_REPORT_TIMES")
        if t:
            got = [float(x) for x in t.split(",")]
            v[:len(got)] = got
    except Exception:
        pass
    return v


def watch(ctx_path, handle=None):
    """Follow one start to its verdict, write the report, tell the player when the game did not come up."""
    with open(ctx_path, "r", encoding="utf-8") as f:
        ctx = json.load(f)
    try:
        os.remove(ctx_path)
    except OSError:
        pass
    t0 = float(ctx.get("t0") or time.time())
    game = ctx.get("game") or ""
    ok_after, stable, gone, max_s, appear = _times()
    win = _Win() if os.name == "nt" else None
    facts = {"failed": ctx.get("failed")}
    timeline = []

    def note(text, t=None):
        timeline.append("+%6.1f s  %s" % ((t if t is not None else time.time()) - t0, text))

    pid = ctx.get("pid")
    h = None
    if win and not facts["failed"]:
        if handle and win.valid(handle):
            h = handle
        elif pid:
            h = win.open(pid)
        if pid:
            note("the launcher started the game's exe, process %d%s" % (
                pid, "" if h else " (it could not be opened: it ended at once, or runs elevated)"), t0)
        else:
            note("the launcher asked Windows to start the game's exe elevated (the administrator prompt)", t0)

    ours, before, ended = {}, {}, {}          # pid -> handle (or None) ; pid -> text ; pid -> (time, code)
    if pid:
        ours[pid] = h
    exe_low = EXE_NAME.lower()
    win_first, win_since, win_seen, last_alive = None, None, {}, t0
    log_noted = False
    steam_seen, wer_seen = None, False
    verdict, kind = None, None
    first_scan = True

    while win and not facts["failed"]:
        now = time.time()
        el = now - t0
        procs = win.processes()
        names = {}
        for p_id, parent, name in procs:
            names.setdefault(name.lower(), []).append(p_id)
        if procs:
            steam = "steam.exe" in names
            if steam_seen is None:
                facts["steam_running"] = steam
                note("Steam is %s" % ("running" if steam else "NOT running"))
            elif steam != steam_seen:
                note("Steam %s" % ("started" if steam else "closed"))
            steam_seen = steam
            if "werfault.exe" in names and not wer_seen:
                wer_seen = True
                facts["werfault"] = True
                note("Windows' crash reporter (WerFault.exe) is running")
            for g in names.get(exe_low, []):
                if g in ours or g in before:
                    continue
                gh = win.open(g)
                born = win.started_at(gh) if gh else None
                if first_scan and g != pid and born is not None and born < t0 - 2.0:
                    before[g] = "process %d, started %d s before this start" % (g, t0 - born)
                    note("a game process was ALREADY running before this start: %s" % before[g])
                    win.close(gh)
                elif first_scan and g != pid and born is None and pid:
                    before[g] = "process %d (its start time cannot be read)" % g
                    note("another game process is present: %s" % before[g])
                    win.close(gh)
                else:
                    ours[g] = gh
                    if pid:
                        facts["relaunched"] = True
                    note("a%s game process appeared: %d" % ("nother" if pid else "", g))
        first_scan = False
        alive = []
        for g, gh in list(ours.items()):
            if g in ended:
                continue
            code = win.exit_code(gh) if gh else None
            present = (not procs) or g in names.get(exe_low, [])
            if code is not None or not present:
                ended[g] = (now, code)
                if g == pid or facts.get("exit_code") is None:
                    facts["exit_code"] = code
                note("game process %d ENDED, exit code %s" % (g, exit_text(code)))
            else:
                alive.append(g)
        if alive:
            last_alive = now
            wins = [w for w in win.windows(alive) if w[1] and w[3] >= 200 and w[4] >= 150]
            for w in wins:
                key = (w[0], w[1], w[2])
                if key not in win_seen:
                    win_seen[key] = now
                    note("a window is on screen: \"%s\" (class %s, %d x %d), process %d" % (w[1], w[2], w[3], w[4],
                                                                                         w[0]))
            if wins:
                win_first = win_first or now
                win_since = win_since or now
            else:
                if win_since:
                    note("the game's window is gone")
                win_since = None
        if not log_noted:
            try:
                if os.path.getmtime(os.path.join(game, LOADER_LOG)) >= t0 - 1:
                    log_noted = True
                    note("the patch's loader wrote its log (%s): the loader is running" % LOADER_LOG)
            except OSError:
                pass
        # the verdict
        if alive and win_since and now - win_since >= stable and el >= ok_after:
            kind, verdict = "OK", "the game came up: its window was on screen %.0f s after the start and stayed" % (
                win_first - t0)
            break
        if not alive and (ours or el >= appear) and now - last_alive >= gone:
            if not ours:
                kind, verdict = "FAILED", ("THE GAME DID NOT START: no game process appeared within %.0f s of the "
                                          "elevated start (the administrator prompt was declined or blocked)" % el)
            else:
                lived = max(t for t, _ in ended.values()) - t0 if ended else last_alive - t0
                code = facts.get("exit_code")
                if win_first:
                    kind = "CLOSED" if code in (0, None) else "FAILED"
                    verdict = ("the game showed its window and closed %.1f s after the start, exit code %s"
                               % (lived, exit_text(code)))
                    if kind == "FAILED":
                        verdict = "THE GAME DID NOT STAY UP: " + verdict
                else:
                    kind = "FAILED"
                    verdict = ("THE GAME DID NOT COME UP: it closed %.1f s after it was started, without ever "
                               "showing a window; exit code %s" % (lived, exit_text(code)))
            break
        if el >= max_s:
            if alive and not win_since:
                kind = "FAILED"
                facts["no_window"] = True
                verdict = ("THE GAME DID NOT COME UP: its process is still there %.0f s after the start, but it "
                           "has not shown a window" % el)
            elif alive:
                kind, verdict = "OK", "the game came up: its window is on screen"
            else:
                kind, verdict = "FAILED", "THE GAME DID NOT START: no game process was seen"
            break
        time.sleep(POLL)

    if facts["failed"]:
        kind = "FAILED"
        verdict = "THE GAME WAS NOT STARTED: Windows refused to start the exe -- %s" % facts["failed"]
        note("the launcher could not start the game's exe: %s" % facts["failed"], t0)
        if win:
            names = [n.lower() for _, _, n in win.processes()]
            facts["steam_running"] = ("steam.exe" in names) if names else None
            others = [str(p_id) for p_id, _, n in win.processes() if n.lower() == exe_low]
            if others:
                before = {int(x): "process %s" % x for x in others}
    if kind is None:
        kind, verdict = "UNKNOWN", "this report could not follow the start (not Windows?)"
    if before:
        facts["preexisting"] = "; ".join(before.values())
    facts["window_seen"] = bool(win_first)
    bad = kind == "FAILED"

    if bad:
        time.sleep(3.0)                       # Windows Error Reporting writes its record after the process is gone
    loader_ran, log_lines = loader_log_facts(game, ctx.get("log0"), t0)
    facts["loader_ran"] = loader_ran
    sac = _reg("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\CI\Policy", "VerifiedAndReputablePolicyState")
    facts["sac_on"] = sac == 1
    ff = foreign_files(game)
    facts["foreign"] = ", ".join("%s: %s" % (f["name"], f["what"]) for f in ff) if ff else None
    compat = compat_facts(game)
    facts["runasadmin"] = any("RUNASADMIN" in x for x in compat)
    events = wer = None
    if kind != "OK":
        events, counts = windows_events(t0 - 20)
        ci = counts.get("Microsoft-Windows-CodeIntegrity/Operational#text") or ""
        facts["ci_blocks"] = bool(re.search(r"(?i)dinput8|%s|%s" % (re.escape(PLUGIN_DIR), re.escape(EXE_NAME[:12])),
                                            ci))
        facts["defender_hits"] = bool(counts.get("Microsoft-Windows-Windows Defender/Operational"))
        wer = wer_facts(t0)

    start = ["Started: %s" % _clock(t0),
             "Launcher: %s, commit %s, Python %s" % (ctx.get("flavor") or "?", ctx.get("commit"), ctx.get("python")),
             "Version chosen: %s" % (ctx.get("version") or "(not told)"),
             "How: %s%s" % (ctx.get("how"), "; " + ", ".join("%s=%s" % kv for kv in sorted(
                 (ctx.get("env") or {}).items())) if ctx.get("env") else "")]
    if ctx.get("argv"):
        start.append("Launcher arguments: %s" % " ".join(ctx["argv"]))
    if ctx.get("note"):
        start.append("Note: %s" % ctx["note"])
    body = []
    if kind != "OK":
        body = ["WHAT IT POINTS TO (for the patch team; pointers, not a verdict):"]
        body += ["  - " + x for x in hints(facts)]
    body += _sections([
        ("The start", start),
        ("What happened, second by second", timeline or ["(nothing was seen)"]),
        ("What Windows recorded during this start", events),
        ("Windows Error Reporting's own crash report", wer),
        ("The patch's own log", log_lines),
        ("The game folder", game_folder_facts(game, t0)),
        ("This PC", pc_facts(win, slow=bad) + compat if win else ["(not Windows)"]),
        ("The launcher's console before the start (last lines)", ctx.get("console") or ["(empty)"]),
    ])
    path = _write(kind, verdict, body)
    for gh in ours.values():
        if win and gh and gh != handle:
            win.close(gh)

    if bad:
        short = verdict.split(": ", 1)[-1]
        short = short[0].upper() + short[1:]
        text = ("The game did not come up.\n\n%s.\n\nA report was saved. Please send it to the patch team\n"
                "so the cause can be found:\n\n%s\n\nOpen the folder with the report now?" % (short, path))
        if os.environ.get("BROS_LAUNCH_REPORT_NOBOX") or not win:
            with open(os.path.join(report_dir(), "lastbox.txt"), "w", encoding="utf-8") as f:
                f.write(text)
        elif win.box("BROS launcher: the game did not start", text):
            try:
                subprocess.Popen('explorer /select,"%s"' % path)
            except Exception:
                pass
    return kind, path


# ------------------------------------------------------------------------------------------------ on request
def snapshot(game=None, minutes=30):
    """A report without a start: the PC, the game folder and what Windows recorded in the last `minutes`."""
    win = _Win() if os.name == "nt" else None
    since = time.time() - 60 * minutes
    running = []
    if win:
        running = ["process %d" % p for p, _, n in win.processes() if n.lower() == EXE_NAME.lower()]
    body = _sections([
        ("Now", ["Game processes running now: %s" % (", ".join(running) or "none")]),
        ("What Windows recorded in the last %d minutes" % minutes, windows_events(since)[0]),
        ("Windows Error Reporting's own crash reports of the last %d minutes" % minutes, wer_facts(since)),
        ("The game folder", game_folder_facts(game) if game else ["(the game folder is not known: start this from "
                                                                  "the launcher's folder)"]),
        ("The last lines of the patch's own log", _tail_lines(os.path.join(game or "", LOADER_LOG), 60)),
        ("This PC", (pc_facts(win, slow=True) + compat_facts(game)) if win else ["(not Windows)"]),
    ])
    return _write("SNAPSHOT", "a snapshot on request (no start was followed)", body)


def _tail_lines(path, n):
    t, err = _read_text(path, 8000000)
    if t is None:
        return ["(%s)" % err]
    return ["    " + x[:300] for x in t.splitlines()[-n:]]


def _game_from_config(base):
    try:
        with open(os.path.join(base, "Json", "config.json"), "r", encoding="utf-8") as f:
            g = json.load(f).get("GAME_PATH") or ""
        return g.replace("/", "\\") if os.name == "nt" else g
    except Exception:
        return None


def collect(base=None, out_dir=None):
    """One zip for the player to send: a fresh snapshot, the last reports, the launcher's console logs."""
    import zipfile
    base = base or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    snap = snapshot(_game_from_config(base))
    d = report_dir()
    out_dir = out_dir or os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(out_dir):
        out_dir = d
    z = os.path.join(out_dir, "BROS_Launch_Reports_%s.zip" % _stamp())
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(snap, os.path.basename(snap))
        for n in sorted(x for x in os.listdir(d) if x.startswith("launch_") and x.endswith(".txt"))[-15:]:
            if os.path.join(d, n) != snap:
                zf.write(os.path.join(d, n), n)
        cd = os.path.join(d, "console")
        if os.path.isdir(cd):
            for n in sorted(os.listdir(cd))[-KEEP_CONSOLES:]:
                t, _ = _read_text(os.path.join(cd, n), 4000000)
                zf.writestr("console/" + n, scrub(t or ""))
        for extra in ("Quick Launch.log", "Quick Launch.log.1"):
            p = os.path.join(os.path.dirname(d), "logs", extra)
            t, _ = _read_text(p, 4000000)
            if t is not None:
                zf.writestr("logs/" + extra, scrub(t))
    return z


def main(argv):
    if len(argv) >= 2 and argv[0] == "--watch":
        handle = None
        if "--handle" in argv:
            try:
                handle = int(argv[argv.index("--handle") + 1])
            except Exception:
                handle = None
        try:
            watch(argv[1], handle)
        except Exception:
            try:
                os.makedirs(report_dir(), exist_ok=True)
                with open(os.path.join(report_dir(), "watcher_error.txt"), "a", encoding="utf-8") as f:
                    f.write("%s\n%s\n" % (_clock(), scrub(traceback.format_exc())))
            except Exception:
                pass
            return 1
        return 0
    if argv and argv[0] == "--collect":
        z = collect()
        print("")
        print("  One file was made for the patch team:")
        print("    " + z)
        print("  It holds no Steam ID, no account or PC name and no IP address.")
        print("  Send it as it is.")
        try:
            if os.name == "nt" and not os.environ.get("BROS_LAUNCH_REPORT_NOBOX"):
                subprocess.Popen('explorer /select,"%s"' % z)
        except Exception:
            pass
        return 0
    if argv and argv[0] == "--snapshot":
        print(snapshot(argv[1] if len(argv) > 1 else _game_from_config(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        return 0
    if argv and argv[0] == "--path":
        print(report_dir())
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
