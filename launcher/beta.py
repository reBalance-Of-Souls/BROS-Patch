"""The invite-only beta: activation, download and install of an encrypted Dev build (launcher side).

HOW A TESTER GETS IN
  The key sequence on the launcher's main screen opens a hidden Beta page. It shows a REQUEST CODE made from a key
  pair this install creates once (Json/beta/install.bin, encrypted with Windows DPAPI: only this Windows user on this
  PC can read it, and a copied launcher folder cannot). The tester sends the request code to the beta's owner, whose
  keygen answers with an ACTIVATION CODE sealed to that key pair. Pasted here it yields the tester's slot key
  (Json/beta/license.bin, DPAPI again). From then on the beta version is in the version list.
  A reinstall makes a new key pair, so an old activation code no longer opens: a new one is needed. Another PC or
  another Windows user cannot use the code or the copied files either.

WHAT IS DOWNLOADED (release assets of the public repo, outside its git tree, so normal players never fetch them)
  index.json   the latest build, and the keygen's public key            (public)
  k-<id>.bin   the build key, wrapped once per tester slot              (a revoked slot is simply left out)
  m-<id>.bin   the manifest: every file, its hash, its key, its place   (encrypted with the build key)
  p-*.bin      the files, each encrypted with its own key               (only the missing ones are fetched, by range)
  Downloaded files stay encrypted in Json/beta/cache/. They are decrypted only into the game folder, at launch.

WHAT A LAUNCH INSTALLS (the Dev launcher's install of the version, captured by the build; see beta_build.py)
  mirror   Script/ and Motion/ become exactly the build's (robocopy /MIR semantics)
  overlay  every other file, with the stock copy backed up the first time it is overwritten, and every path recorded
           in <game>/launcher_patch_state.json -- the contract the public launcher's revert_foreign_overlay() and the
           Dev launcher already share, so choosing any other version afterwards puts the game back. Files the beta
           creates (no stock copy existed) are listed under "beta_created", and the revert deletes exactly those.
  loader   <game>/dinput8.dll;  plugins  <game>/ReBalanceOfSouls/*.dll (mirrored: any other DLL there is removed)
  then the Dev launcher's sweep of stray effect banks, and the match code: the Dev Environment's Community Patch
  pool (SHARED_POOL_CODE), so beta players and that version's Dev players meet.
"""

import hashlib
import http.client
import json
import os
import platform
import re
import shutil
import ssl
import threading
import time
import urllib.error
import urllib.request

try:
    from launcher import beta_crypto as bc
except ImportError:                                   # run from the folder itself (tests)
    import beta_crypto as bc

BETA_NAME = "Zangetsu Beta (dev build)"
RELEASE_BASE = "https://github.com/reBalance-Of-Souls/BROS-Patch/releases/download/lb-data/"
SOURCE_ENV = "BROS_BETA_SOURCE"                         # tests: a local folder or another URL instead of the release
# The beta's online pool (Berg, 2026-10-16). The beta IS the Dev Environment's "Bleach Rebirth of Souls Community
# Patch" version (a build is the Dev launcher's install of it), so it plays in that version's shared pool, which the
# Dev launcher writes for it too (SHARED_POOLS in its main launcher): the two numbers must stay equal. 603966 is the
# code the first build (3f19ecf4, 2026-10-14) carries in its manifest. A build's own code is no longer used, so a later
# build cannot leave the pool by carrying another one. One pool means a build made before a change to that version
# meets the changed version too: their matches can desync where they differ, so a new build follows each change.
SHARED_POOL_CODE = 603966
# The key sequence that opens the Beta page, kept only as the sha256 of its Tk key names joined by spaces.
SEQUENCE_LEN = 7
SEQUENCE_SHA256 = "f735a52b8c73fb48da687778de81a3d14d51217dd908fd7117e600214e249daa"

_DPAPI_ENTROPY = b"BROSBETA1-launcher"
STATE_FORMAT = 1
MIRROR_ROOTS = ("Script", "Motion")
PLUGINS_DIR = "ReBalanceOfSouls"
STAGING = "_beta_staging"                              # decryption happens here, never inside the game's own folders
QUARANTINE = "_launcher_quarantine"
# Dev launcher's _OVERLAY_ALWAYS_REMOVE: files whose mere presence changes the game, deleted rather than left behind
ALWAYS_REMOVE = ("bros_roster_v12.txt", "bros_roster_v13.txt",
                 "00HIGH/Model/chara/pl005_wep00_00_01.lds", "00HIGH/Model/chara/pl005_wep00_00_01.tmd2",
                 "00HIGH/Model/chara/pl005_wep02_00_00.lds", "00HIGH/Model/chara/pl005_wep02_00_00.tmd2",
                 "01MIDDLE/Model/chara/pl005_wep00_00_01.lds", "01MIDDLE/Model/chara/pl005_wep00_00_01.tmd2",
                 "01MIDDLE/Model/chara/pl005_wep02_00_00.lds", "01MIDDLE/Model/chara/pl005_wep02_00_00.tmd2",
                 "Physics/chara/pl005_wep00_01.cphy")
EXE_NAME = "BLEACH_Rebirth_of_Souls.exe"
# launcher/install_guard.py's rule for an effect bank: <name>.vfxb or <name>.desktop.vfxt, nothing else
_BANK_CANONICAL = re.compile(r"[^.]+\.(?:vfxb|desktop\.vfxt)\Z", re.I)
_TIERS = ("00high", "01middle", "02low")

_busy = threading.Lock()                               # one sync / install / cache deletion at a time


class BetaError(Exception):
    """Something the tester can read and act on."""


class Cancelled(BetaError):
    pass


def is_sequence(keys):
    """keys: the last SEQUENCE_LEN Tk keysyms pressed, oldest first."""
    return hashlib.sha256(" ".join(keys).encode()).hexdigest() == SEQUENCE_SHA256


# ---------------------------------------------------------------------------------------------------------------------
# The machine
# ---------------------------------------------------------------------------------------------------------------------

def available():
    return platform.system() == "Windows"


def _dpapi(data, protect):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    ebuf = ctypes.create_string_buffer(_DPAPI_ENTROPY, len(_DPAPI_ENTROPY))
    bin_, bent, bout = BLOB(len(data), buf), BLOB(len(_DPAPI_ENTROPY), ebuf), BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(bin_), None, ctypes.byref(bent), None, None, 1, ctypes.byref(bout)):
        raise BetaError("Windows could not %s the beta key on this PC." % ("protect" if protect else "read"))
    try:
        return ctypes.string_at(bout.pbData, bout.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(bout.pbData)


def machine_id():
    import winreg
    k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                       winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    try:
        return str(winreg.QueryValueEx(k, "MachineGuid")[0])
    finally:
        winreg.CloseKey(k)


def _atomic_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    bc.replace_retry(tmp, path)


def _atomic_copy(src, dst):
    """A copy that is either complete or absent: a cut-off copy never sits under the final name."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".tmp"
    shutil.copy2(src, tmp)
    with open(tmp, "rb+") as f:
        os.fsync(f.fileno())
    bc.replace_retry(tmp, dst)


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _put_aside(path):
    """A state file this PC cannot read is kept, renamed, never deleted."""
    if os.path.exists(path):
        os.replace(path, "%s.unreadable-%d" % (path, int(time.time())))


# ---------------------------------------------------------------------------------------------------------------------
# Install key and license
# ---------------------------------------------------------------------------------------------------------------------

def state_dir(base_dir):
    return os.path.join(base_dir, "Json", "beta")


def _load_sealed(path):
    if not os.path.exists(path):
        return None
    try:
        d = json.loads(_dpapi(open(path, "rb").read(), False))
    except Exception:
        _put_aside(path)
        return None
    if d.get("v") != STATE_FORMAT or d.get("machine") != machine_id():
        _put_aside(path)
        return None
    return d


def _save_sealed(path, d):
    d = dict(d, v=STATE_FORMAT, machine=machine_id())
    _atomic_write(path, _dpapi(json.dumps(d).encode(), True))


def install_key(base_dir):
    """This install's private key, created on first use."""
    p = os.path.join(state_dir(base_dir), "install.bin")
    d = _load_sealed(p)
    if d is None:
        d = {"priv": os.urandom(32).hex(), "created": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}
        _save_sealed(p, d)
        _put_aside(os.path.join(state_dir(base_dir), "license.bin"))   # a license belongs to the old key
    return bytes.fromhex(d["priv"])


def request_code(base_dir):
    return bc.request_code(bc.public_key(install_key(base_dir)))


def license_info(base_dir):
    """{"slot", "seed", "auth_pub"} when this install is activated, else None."""
    d = _load_sealed(os.path.join(state_dir(base_dir), "license.bin"))
    if d is None:
        return None
    if d.get("install_pub") != bc.public_key(install_key(base_dir)).hex():
        return None
    return d


def is_active(base_dir):
    try:
        return available() and license_info(base_dir) is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------------------------------------------------

def _source():
    return os.environ.get(SOURCE_ENV) or RELEASE_BASE


_NET_ERRORS = (OSError, urllib.error.URLError, ValueError, http.client.HTTPException)


# Python checks HTTPS certificates against the root certificates Windows already holds, and Windows only fetches a
# root the first time something of its own asks for it: on a PC where nothing has, Python refuses GitHub's
# certificate ("unable to get local issuer certificate", seen on this project's VM on 2026-10-14) although every
# browser connects. Windows' own curl.exe verifies through the system (Schannel, with its automatic root updates), so
# a certificate refusal switches the downloads to it.
_CURL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "curl.exe")
_use_curl = False
TMP_DIR = None                                          # set by sync(): curl downloads land beside the cache


class _CurlStream:
    """curl.exe's output, read like a response as it arrives; closing it ends curl and removes the header file."""

    def __init__(self, proc, hdr):
        self.proc, self.hdr = proc, hdr

    def read(self, n=-1):
        return self.proc.stdout.read(n)

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.stdout.close()
            self.proc.wait(timeout=10)
        except Exception:
            pass
        try:
            os.remove(self.hdr)
        except OSError:
            pass


def _final_headers(path):
    """(status, {name: value}) of the last complete response in a curl -D file (redirects come first), or None."""
    try:
        text = open(path, "r", encoding="latin-1").read().replace("\r", "")
    except OSError:
        return None
    blocks = [b for b in text.split("\n\n")]
    done = [b for b in blocks[:-1] if b.strip()]          # a block is complete once a blank line follows it
    if not done:
        return None
    lines = done[-1].strip().split("\n")
    try:
        status = int(lines[0].split()[1])
    except (IndexError, ValueError):
        return None
    if 300 <= status < 400:
        return None                                        # a redirect: the real answer is still to come
    hdrs = {}
    for l in lines[1:]:
        if ":" in l:
            k, v = l.split(":", 1)
            hdrs[k.strip().lower()] = v.strip()
    return status, hdrs


def _open_curl(url, name, start, end):
    import subprocess
    import tempfile
    if not os.path.exists(_CURL):
        raise BetaError("This PC cannot check the beta server's certificate, and Windows' curl.exe is missing.")
    tmp_dir = TMP_DIR or tempfile.gettempdir()
    os.makedirs(tmp_dir, exist_ok=True)
    fd, hdr = tempfile.mkstemp(prefix="dl_", suffix=".hdr", dir=tmp_dir)
    os.close(fd)
    cmd = [_CURL, "-sS", "-L", "--connect-timeout", "30", "-A", "BROS-Launcher-beta", "-D", hdr, "-o", "-"]
    if start is not None:
        cmd += ["-r", "%d-%d" % (start, end)]
    proc = subprocess.Popen(cmd + [url], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    stream = _CurlStream(proc, hdr)
    deadline = time.time() + 60
    got = None
    while got is None:
        got = _final_headers(hdr)
        if got is None:
            if proc.poll() is not None:
                got = _final_headers(hdr)
                if got is None:
                    stream.close()
                    raise BetaError("Could not reach the beta server (curl ended with code %d)." % proc.returncode)
            elif time.time() > deadline:
                stream.close()
                raise BetaError("The beta server did not answer.")
            else:
                time.sleep(0.05)
    status, hdrs = got
    if status not in (200, 206):
        stream.close()
        if status == 404:
            raise BetaError("The beta is not published yet (%s is missing)." % name)
        raise BetaError("The beta server answered %d for %s." % (status, name))
    ranged = True
    if start is not None:
        if status != 206:
            ranged = False
        elif not hdrs.get("content-range", "").startswith("bytes %d-" % start):
            stream.close()
            raise BetaError("The beta server sent the wrong part of %s." % name)
    return stream, int(hdrs.get("content-length") or 0), ranged


def _open_url(name, start=None, end=None):
    """(stream, length, ranged). ranged is False when a range was asked for and the whole file came back."""
    global _use_curl
    src = _source()
    if not src.lower().startswith(("http://", "https://")):
        f = open(os.path.join(src, name), "rb")
        if start is not None:
            f.seek(start)
        return f, (end - start + 1) if start is not None else os.path.getsize(os.path.join(src, name)), True
    if _use_curl:
        return _open_curl(src + name, name, start, end)
    req = urllib.request.Request(src + name, headers={"User-Agent": "BROS-Launcher-beta"})
    if start is not None:
        req.add_header("Range", "bytes=%d-%d" % (start, end))
    try:
        r = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise BetaError("The beta is not published yet (%s is missing)." % name)
        raise BetaError("The beta server answered %d for %s." % (e.code, name))
    except _NET_ERRORS as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, ssl.SSLError) and platform.system() == "Windows":
            _use_curl = True
            return _open_curl(src + name, name, start, end)
        raise BetaError("Could not reach the beta server: %s" % reason)
    ranged = True
    if start is not None:
        cr = r.headers.get("Content-Range", "")
        if r.status != 206:
            ranged = False
        elif not cr.startswith("bytes %d-" % start):
            r.close()
            raise BetaError("The beta server sent the wrong part of %s." % name)
    length = int(r.headers.get("Content-Length") or 0)
    return r, length, ranged


def _fetch_small(name, limit=64 * 1024 * 1024):
    f, _n, _r = _open_url(name)
    try:
        data = f.read(limit + 1)
    except _NET_ERRORS as e:
        raise BetaError("The download of %s was cut off: %s" % (name, e))
    finally:
        f.close()
    if len(data) > limit:
        raise BetaError("%s is unexpectedly large." % name)
    return data


def fetch_index():
    try:
        idx = json.loads(_fetch_small("index.json"))
    except ValueError:
        raise BetaError("The beta index could not be read.")
    if idx.get("format") != 1 or "latest" not in idx:
        raise BetaError("This launcher is too old for the published beta. Update the launcher.")
    return idx


# ---------------------------------------------------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------------------------------------------------

def activate(base_dir, code):
    """Check an activation code against this install and the published beta; store the license. Returns the slot."""
    if not available():
        raise BetaError("The beta is for Windows only.")
    idx = fetch_index()
    auth_pub = bytes.fromhex(idx["auth_pub"])
    try:
        slot, seed = bc.open_activation(code, install_key(base_dir), auth_pub)
    except bc.CodeError as e:
        raise BetaError("That code is not complete or has a typo (%s)." % e)
    except bc.OpenError:
        raise BetaError("That code was not made for this install. Codes only work on the PC and install whose "
                        "request code they were made from; after a reinstall a new code is needed.")
    b = idx["builds"][idx["latest"]]
    kr = _fetch_small(b["keyring"])
    if hashlib.sha256(kr).hexdigest() != b["keyring_sha256"]:
        raise BetaError("The beta download is damaged (keyring hash). Try again later.")
    try:
        bc.open_keyring(kr, slot, seed)
    except bc.OpenError:
        raise BetaError("This tester slot has no access to the current beta build (it may have been revoked).")
    _save_sealed(os.path.join(state_dir(base_dir), "license.bin"), {
        "slot": slot, "seed": seed.hex(), "auth_pub": idx["auth_pub"],
        "install_pub": bc.public_key(install_key(base_dir)).hex(),
        "activated": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())})
    return slot


# ---------------------------------------------------------------------------------------------------------------------
# The manifest: authenticated by the build key, and still checked before anything touches the disk
# ---------------------------------------------------------------------------------------------------------------------

_SAFE_PART = re.compile(r"^[^<>:\"\\|?*\x00-\x1f]+$")


def _safe_rel(rel):
    """A game-relative path: forward slashes, no drive, no root, no '.' or '..', no Windows-reserved character."""
    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\\" in rel:
        return False
    parts = rel.split("/")
    return all(p not in ("", ".", "..") and _SAFE_PART.match(p) and not p.endswith((" ", ".")) for p in parts)


def check_manifest(m):
    """Refuse a manifest that would write or delete anywhere but where a launch may."""
    if m.get("format") != 1:
        raise BetaError("This launcher is too old for the published beta. Update the launcher.")
    if list(m.get("mirror_roots", [])) != list(MIRROR_ROOTS) or m.get("plugins_dir") != PLUGINS_DIR:
        raise BetaError("The beta build does not look right (folders). Nothing was installed.")
    kinds = {"mirror", "overlay", "loader", "plugin"}
    seen = set()
    for f in m["files"]:
        p, k = f.get("path"), f.get("kind")
        if k not in kinds or not _safe_rel(p):
            raise BetaError("The beta build does not look right (%r). Nothing was installed." % (p,))
        top = p.split("/", 1)[0]
        if (k == "mirror") != (top in MIRROR_ROOTS) or (k == "loader") != (p == "dinput8.dll") \
                or (k == "plugin") != (top == PLUGINS_DIR and p.count("/") == 1 and p.lower().endswith(".dll")):
            raise BetaError("The beta build does not look right (%s). Nothing was installed." % p)
        if p.lower() in seen or top.lower() in (STAGING.lower(), QUARANTINE.lower(), "_launcher_vanilla_backup"):
            raise BetaError("The beta build does not look right (%s). Nothing was installed." % p)
        seen.add(p.lower())
    return m


# ---------------------------------------------------------------------------------------------------------------------
# Sync: the latest build's manifest and every file it needs, encrypted, in the cache
# ---------------------------------------------------------------------------------------------------------------------

def _cache(base_dir, *p):
    return os.path.join(state_dir(base_dir), "cache", *p)


def _blob_ok(path, blob, length):
    return os.path.exists(path) and os.path.getsize(path) == length and _sha256_file(path) == blob


class Progress:
    def __init__(self):
        self.lock = threading.Lock()
        self.done = 0
        self.total = 0
        self.phase = ""
        self.cancel = threading.Event()

    def set(self, phase=None, done=None, total=None):
        with self.lock:
            if phase is not None:
                self.phase = phase
            if done is not None:
                self.done = done
            if total is not None:
                self.total = total

    def add(self, n):
        with self.lock:
            self.done += n

    def snapshot(self):
        with self.lock:
            return self.phase, self.done, self.total

    def check(self):
        if self.cancel.is_set():
            raise Cancelled("Cancelled.")


def _open_build(base_dir, idx):
    lic = license_info(base_dir)
    if lic is None:
        raise BetaError("This install is not activated.")
    bid = idx["latest"]
    b = idx["builds"][bid]
    blobs = {}
    for key in ("keyring", "manifest"):
        cp = _cache(base_dir, b[key])
        data = open(cp, "rb").read() if os.path.exists(cp) else None
        if data is None or hashlib.sha256(data).hexdigest() != b[key + "_sha256"]:
            data = _fetch_small(b[key], limit=256 * 1024 * 1024)
            if hashlib.sha256(data).hexdigest() != b[key + "_sha256"]:
                raise BetaError("The beta download is damaged (%s hash). Try again later." % key)
            _atomic_write(cp, data)
        blobs[key] = data
    try:
        build_id, build_key = bc.open_keyring(blobs["keyring"], lic["slot"], bytes.fromhex(lic["seed"]))
    except bc.OpenError:
        raise BetaError("Your beta access ends with the build you already have: the newest build has no key for "
                        "your tester slot.")
    if build_id.hex() != bid:
        raise BetaError("The beta index and keyring do not match. Try again later.")
    return check_manifest(json.loads(bc.open_manifest(blobs["manifest"], build_id, build_key)))


def sync(base_dir, progress=None, game=None):
    """Bring the cache up to the latest build. Returns the manifest. Safe to call from a worker thread."""
    progress = progress or Progress()
    if not _busy.acquire(blocking=False):
        raise BetaError("The beta is already being downloaded or installed.")
    try:
        return _sync(base_dir, progress, game)
    finally:
        _busy.release()


def _sync(base_dir, progress, game):
    global TMP_DIR
    TMP_DIR = _cache(base_dir, "tmp")
    progress.set(phase="Checking for the latest beta build", done=0, total=0)
    idx = fetch_index()
    m = _open_build(base_dir, idx)
    need = {}
    for f in m["files"]:
        if f["blob"] in need:
            continue
        progress.check()
        if not _blob_ok(_cache(base_dir, "blobs", f["blob"]), f["blob"], f["len"]):
            need[f["blob"]] = f
    total = sum(f["len"] for f in need.values())
    os.makedirs(_cache(base_dir, "blobs"), exist_ok=True)
    free = shutil.disk_usage(state_dir(base_dir)).free
    if total and free < total + 512 * 1024 * 1024:
        raise BetaError("Not enough disk space: the beta needs %.1f GB more on the launcher's drive." % (total / 1e9))
    if game:
        _check_game_space(game, m)
    progress.set(phase="Downloading the beta", done=0, total=total)
    by_pack = {}
    for f in need.values():
        by_pack.setdefault(f["pack"], []).append(f)
    for pack, files in sorted(by_pack.items()):
        files.sort(key=lambda f: f["off"])
        if pack not in idx["packs"]:
            raise BetaError("The beta is incomplete on the server (%s is not listed). Try again later." % pack)
        psize = idx["packs"][pack]["size"]
        if sum(f["len"] for f in files) > psize * 0.6:
            _fetch_whole_pack(base_dir, pack, files, progress)
        else:
            runs = list(_runs(files))
            for i, run in enumerate(runs):
                if not _fetch_range(base_dir, pack, run, progress):
                    # the server ignored the range: take everything still missing from this pack in one pass
                    _fetch_whole_pack(base_dir, pack, [f for r in runs[i:] for f in r], progress)
                    break
    progress.set(phase="Beta is up to date")
    _atomic_write(_cache(base_dir, "current.json"), json.dumps({"build": m["build"]["id"]}).encode())
    prune(base_dir, m, idx)
    return m


def _check_game_space(game, m):
    """Room on the game's drive for every file not yet there, plus the stock copies of the files it replaces."""
    need = 0
    for f in m["files"]:
        dst = _game_path(game, f["path"])
        cur = os.path.getsize(dst) if os.path.exists(dst) else 0
        need += max(0, f["size"] - cur) + (cur if f["kind"] == "overlay" else 0)
    free = shutil.disk_usage(game).free
    if free < need + 256 * 1024 * 1024:
        raise BetaError("Not enough disk space on the game's drive: the beta needs %.1f GB more there." % (need / 1e9))


def _runs(files, gap=256 * 1024):
    """Group blobs that sit close together in a pack into one ranged request."""
    run = [files[0]]
    for f in files[1:]:
        last = run[-1]
        if f["off"] - (last["off"] + last["len"]) <= gap and f["off"] + f["len"] - run[0]["off"] < 64 * 1024 * 1024:
            run.append(f)
        else:
            yield run
            run = [f]
    yield run


def _write_blob(base_dir, f, read, progress):
    dst = _cache(base_dir, "blobs", f["blob"])
    tmp = dst + ".part"
    h = hashlib.sha256()
    left = f["len"]
    ok = False
    try:
        with open(tmp, "wb") as o:
            while left:
                progress.check()
                try:
                    c = read(min(1 << 20, left))
                except _NET_ERRORS as e:
                    raise BetaError("The download was cut off (%s). Try again." % e)
                if not c:
                    raise BetaError("The download was cut off. Try again.")
                o.write(c)
                h.update(c)
                left -= len(c)
        if h.hexdigest() != f["blob"]:
            raise BetaError("A downloaded beta file is damaged. Try again.")
        bc.replace_retry(tmp, dst)
        ok = True
    finally:
        if not ok and os.path.exists(tmp):
            os.remove(tmp)


class _Skipper:
    def __init__(self, r, progress, pos=0):
        self.r, self.pos, self.progress = r, pos, progress

    def read(self, n):
        c = self.r.read(n)
        self.pos += len(c)
        self.progress.add(len(c))
        return c

    def skip_to(self, off):
        while self.pos < off:
            self.progress.check()
            try:
                c = self.r.read(min(1 << 20, off - self.pos))
            except _NET_ERRORS as e:
                raise BetaError("The download was cut off (%s). Try again." % e)
            if not c:
                raise BetaError("The download was cut off. Try again.")
            self.pos += len(c)


def _fetch_whole_pack(base_dir, pack, files, progress):
    r, _n, _ranged = _open_url(pack)
    try:
        s = _Skipper(r, progress)
        for f in sorted(files, key=lambda f: f["off"]):
            s.skip_to(f["off"])
            _write_blob(base_dir, f, s.read, progress)
    finally:
        r.close()


def _fetch_range(base_dir, pack, run, progress):
    """True when done; False when the server ignored the range (nothing written: the caller takes the whole pack)."""
    start = run[0]["off"]
    end = run[-1]["off"] + run[-1]["len"] - 1
    r, _n, ranged = _open_url(pack, start, end)
    try:
        if not ranged:
            return False
        s = _Skipper(r, progress, pos=start)
        for f in run:
            s.skip_to(f["off"])
            _write_blob(base_dir, f, s.read, progress)
        return True
    finally:
        r.close()


def cached_manifest(base_dir):
    """The manifest of the build in the cache, without going online, or None."""
    try:
        cur = json.loads(open(_cache(base_dir, "current.json"), "rb").read())["build"]
        lic = license_info(base_dir)
        kr = open(_cache(base_dir, "k-%s.bin" % cur), "rb").read()
        mb = open(_cache(base_dir, "m-%s.bin" % cur), "rb").read()
        build_id, build_key = bc.open_keyring(kr, lic["slot"], bytes.fromhex(lic["seed"]))
        m = check_manifest(json.loads(bc.open_manifest(mb, build_id, build_key)))
    except Exception:
        return None
    for f in m["files"]:
        if not os.path.exists(_cache(base_dir, "blobs", f["blob"])):
            return None
    return m


def prune(base_dir, m, idx=None):
    """Remove cached files the given build does not use (older builds' files), and old manifests and keyrings."""
    keep = {f["blob"] for f in m["files"]}
    freed = 0
    d = _cache(base_dir, "blobs")
    if os.path.isdir(d):
        for n in os.listdir(d):
            if n not in keep:
                p = os.path.join(d, n)
                freed += os.path.getsize(p)
                os.remove(p)
    bid = m["build"]["id"]
    for n in os.listdir(_cache(base_dir)):
        if n.endswith(".bin") and n[:2] in ("k-", "m-") and bid not in n:
            os.remove(_cache(base_dir, n))
    return freed


# ---------------------------------------------------------------------------------------------------------------------
# Install into the game folder
# ---------------------------------------------------------------------------------------------------------------------

def _game_path(game, rel):
    return os.path.join(game, *rel.split("/"))


def _decrypt_to(base_dir, game, f, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    staging = os.path.join(game, STAGING)
    os.makedirs(staging, exist_ok=True)
    src = _cache(base_dir, "blobs", f["blob"])
    with open(src, "rb") as r:
        bc.open_stream(bytes.fromhex(f["key"]), bc.BLOB_AD, r.read, dst, f["len"], want_sha256=f["sha256"],
                       tmp_path=os.path.join(staging, f["sha256"] + ".tmp"))


def read_patch_state(game):
    try:
        with open(os.path.join(game, "launcher_patch_state.json"), "r") as f:
            s = json.load(f)
        s.setdefault("overlay", [])
        s.setdefault("exe", False)
        return s
    except Exception:
        return {"version": None, "overlay": [], "exe": False}


def write_patch_state(game, s):
    _atomic_write(os.path.join(game, "launcher_patch_state.json"), json.dumps(s, indent=1).encode())


def sweep_effect_strays(game, log=print):
    """launcher/install_guard.sweep_effect_strays(), as every Dev launch runs it: a file the effect loader would take
    for a bank without being one (a backup like X.vfxb.pre_bak, a leftover X.vfxb.tmp) is moved out of the Effect
    trees into _launcher_quarantine/, keeping its game-relative path. Nothing is deleted."""
    moved = []
    roots = []
    for name in os.listdir(game):
        full = os.path.join(game, name)
        if not os.path.isdir(full):
            continue
        if name.lower() in _TIERS:
            for sub in os.listdir(full):
                if sub.lower() == "effect" and os.path.isdir(os.path.join(full, sub)):
                    roots.append((os.path.join(full, sub), name + "/" + sub))
        elif name.lower() == "effect":
            roots.append((full, name))
    for root, rel_root in roots:
        for dirpath, _dirs, files in os.walk(root):
            for n in files:
                low = n.lower()
                if not ((".vfxb" in low or ".vfxt" in low) and not _BANK_CANONICAL.match(n)):
                    continue
                src = os.path.join(dirpath, n)
                rel = rel_root + "/" + os.path.relpath(src, root).replace(os.sep, "/")
                dst = os.path.join(game, QUARANTINE, *rel.split("/"))
                k = 0
                cand = dst
                while os.path.lexists(cand):
                    k += 1
                    cand = "%s.%d" % (dst, k)
                try:
                    os.makedirs(os.path.dirname(cand), exist_ok=True)
                    os.replace(src, cand)
                    moved.append(rel)
                except OSError as e:
                    log("[beta] could not move the stray effect file %s: %s" % (rel, e))
    if moved:
        log("[beta] %d stray effect file(s) moved to %s/" % (len(moved), QUARANTINE))
    return moved


def install(base_dir, game, m, log=print, progress=None):
    """Put the build's end state into the game folder. Every file written is checked against the manifest's hash."""
    if not _busy.acquire(blocking=False):
        raise BetaError("The beta is already being downloaded or installed.")
    try:
        return _install(base_dir, game, check_manifest(m), log, progress or Progress())
    finally:
        _busy.release()


def _install(base_dir, game, m, log, progress):
    files = m["files"]
    total = sum(f["size"] for f in files)
    progress.set(phase="Installing the beta", done=0, total=total)
    staging = os.path.join(game, STAGING)
    if os.path.isdir(staging):                 # what a launch that was cut off left in our own staging folder
        for n in os.listdir(staging):
            os.remove(os.path.join(staging, n))
    _check_game_space(game, m)
    rec_path = os.path.join(state_dir(base_dir), "installed.json")
    try:
        rec = json.load(open(rec_path))
        if rec.get("game") != os.path.abspath(game):
            rec = {}
    except Exception:
        rec = {}
    seen = rec.get("files", {})
    now = {}

    def place(f):
        progress.check()
        dst = _game_path(game, f["path"])
        st = os.stat(dst) if os.path.exists(dst) else None
        r = seen.get(f["path"])
        if st and r and r[0] == f["sha256"] and r[1] == st.st_size and r[2] == st.st_mtime_ns:
            now[f["path"]] = r
            progress.add(f["size"])
            return False
        _decrypt_to(base_dir, game, f, dst)
        st = os.stat(dst)
        now[f["path"]] = [f["sha256"], st.st_size, st.st_mtime_ns]
        progress.add(f["size"])
        return True

    counts = {"mirror": 0, "overlay": 0, "loader": 0, "plugin": 0, "skipped": 0, "removed": 0}

    # 1. mirror roots
    mirror = {f["path"].lower() for f in files if f["kind"] == "mirror"}     # Windows paths: case-insensitive
    for f in files:
        if f["kind"] == "mirror":
            counts["mirror" if place(f) else "skipped"] += 1
    for root in MIRROR_ROOTS:
        top = os.path.join(game, root)
        for dp, dn, fn in os.walk(top, topdown=False):
            for n in fn:
                rel = os.path.relpath(os.path.join(dp, n), game).replace(os.sep, "/")
                if rel.lower() not in mirror:
                    os.remove(os.path.join(dp, n))
                    counts["removed"] += 1
            if dp != top and not os.listdir(dp):
                os.rmdir(dp)

    # 2. overlay, under the shared state-file contract (the Dev launcher's install_overlay)
    state = read_patch_state(game)
    prev = list(state.get("overlay", []))
    backup_root = os.path.join(game, "_launcher_vanilla_backup")
    wanted = [f for f in files if f["kind"] == "overlay"]
    wanted_set = {f["path"] for f in wanted}
    ours_other = {f["path"].lower() for f in files if f["kind"] != "overlay"}
    # "beta_created": the paths the beta wrote where no file existed before. They have no stock copy, so a switch
    # back (revert_foreign_overlay, patched to read this list) deletes them instead of leaving beta content behind.
    created = set(state.get("beta_created", []))
    orphans = []
    for rel in prev:
        if rel in wanted_set:
            continue
        if rel.lower() in ours_other:
            # This launch's mirror, loader or plugin step has just written rel: restoring an older backup now would
            # put it back over the beta's file. Keep it listed, and its backup, for a later switch (Dev's rule).
            orphans.append(rel)
            continue
        dst, bak = _game_path(game, rel), _game_path(backup_root, rel)
        try:
            if os.path.exists(bak):
                _atomic_copy(bak, dst)
                os.remove(bak)
            elif os.path.exists(dst) and (rel in ALWAYS_REMOVE or rel in created):
                os.remove(dst)
            elif os.path.exists(dst):
                orphans.append(rel)
        except OSError as e:
            log("[beta] could not revert %s: %s" % (rel, e))
            orphans.append(rel)
    # Stock copies are taken and every path is recorded BEFORE anything is written: a launch cut off halfway then
    # leaves a state a later revert handles, and never one where a beta file gets captured as "stock".
    for f in wanted:
        progress.check()
        rel = f["path"]
        dst, bak = _game_path(game, rel), _game_path(backup_root, rel)
        if os.path.exists(dst):
            if not os.path.exists(bak) and rel not in prev:
                _atomic_copy(dst, bak)
        elif not os.path.exists(bak):
            created.add(rel)
    # The exe: this build ships no exe patch, so a patched exe left by a Dev launch goes back to stock (setup_exe).
    if state.get("exe"):
        bak = os.path.join(backup_root, EXE_NAME)
        if os.path.exists(bak):
            try:
                _atomic_copy(bak, os.path.join(game, EXE_NAME))
                state["exe"] = False
                log("[beta] restored the stock %s" % EXE_NAME)
            except OSError as e:
                raise BetaError("The game's exe could not be put back to stock (%s). Close the game and launch "
                                "again." % e)
        else:
            state["exe"] = False
    state["overlay"] = sorted(wanted_set | set(orphans))
    state["beta_created"] = sorted(created & set(state["overlay"]))
    state["version"] = BETA_NAME
    write_patch_state(game, state)
    for f in wanted:
        counts["overlay" if place(f) else "skipped"] += 1

    # 3. loader and plugins
    for f in files:
        if f["kind"] == "loader":
            counts["loader" if place(f) else "skipped"] += 1
    plugdir = os.path.join(game, PLUGINS_DIR)
    plugins = [f for f in files if f["kind"] == "plugin"]
    want = {f["path"].rsplit("/", 1)[1].lower() for f in plugins}
    if os.path.isdir(plugdir):
        for n in os.listdir(plugdir):
            if n.lower().endswith(".dll") and n.lower() not in want:
                os.remove(os.path.join(plugdir, n))
                log("[beta] removed plugin %s (not in the beta)" % n)
    for f in plugins:
        counts["plugin" if place(f) else "skipped"] += 1

    # 4. stray effect banks out of the way, as every Dev launch does
    sweep_effect_strays(game, log)

    # 5. every file the build lists is there with its size (each one written now was checked against its sha256
    #    as it was decrypted; one skipped had the recorded hash, size and time of the last checked write)
    bad = [f["path"] for f in files if not os.path.exists(_game_path(game, f["path"]))
           or os.path.getsize(_game_path(game, f["path"])) != f["size"]]
    if bad:
        raise BetaError("%d beta file(s) did not install, first: %s. An antivirus scanning the game folder is the "
                        "usual cause; allow it and launch again." % (len(bad), bad[0]))

    # 6. the match code: the Dev Community Patch's shared pool (SHARED_POOL_CODE), not the build's own
    code = SHARED_POOL_CODE
    if str(m.get("match_code")) != str(code):
        log("[beta] match code %d (the Dev Community Patch's pool); the build's own %s is not used"
            % (code, m.get("match_code")))
    try:
        from launcher import match_pool
        match_pool.write_code(game, code)
    except ImportError:
        _atomic_write(os.path.join(game, "patch_ranked.txt"), b"%d\n" % code)

    _atomic_write(rec_path, json.dumps({"game": os.path.abspath(game), "build": m["build"]["id"],
                                        "files": now}).encode())
    log("[beta] build %s installed: %s" % (m["build"]["id"][:8], ", ".join("%s %d" % kv for kv in counts.items())))
    return counts


def forget_cache(base_dir):
    """The tester's 'free the space' button: the downloaded beta files go; the activation stays. Returns the bytes
    actually freed."""
    if not _busy.acquire(blocking=False):
        raise BetaError("The beta is being downloaded or installed right now. Try again when it is done.")
    try:
        d = _cache(base_dir)
        freed, failed = 0, []
        if os.path.isdir(d):
            for dp, _dn, fn in os.walk(d, topdown=False):
                for n in fn:
                    p = os.path.join(dp, n)
                    try:
                        size = os.path.getsize(p)
                        os.remove(p)
                        freed += size
                    except OSError as e:
                        failed.append("%s (%s)" % (n, e))
                if dp != d:
                    try:
                        os.rmdir(dp)
                    except OSError:
                        pass
        if failed:
            raise BetaError("%.1f GB freed, but %d file(s) could not be deleted, first: %s"
                            % (freed / 1e9, len(failed), failed[0]))
        return freed
    finally:
        _busy.release()
