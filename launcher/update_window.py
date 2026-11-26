"""The update before every launch, in a small window -- and no console (V1.5 delivery B.3; pass rn, 2026-11-02).

WHY
---
Every launcher script updates its checkout before it installs anything (its pulling_from_git()). Until now that ran
with git's output captured: the main launcher printed "Checking for updates, please wait" into a console and showed
nothing else until git was done -- for a large update, minutes of a console window with one line in it -- and the
five Quick Launch scripts did the same in their own consoles. Berg (V1.5 answer 8, 2026-11-01): an update window with
the MB, like the public beta's. The plan he approved (V15_PLAN.md §1 item 8, §4 B): the phase, "x of y MB" and a bar;
no console; nothing at all when there is nothing new; developers keep today's pull rules.

WHAT pull() DOES -- a drop-in for pulling_from_git(): the same git steps in the same order, the same result, the same
exceptions
--------------------------------------------------------------------------------------------------------------------
  Without a DevToken (BalanceLeadTools/DevToken.txt) -- a player's checkout, which must equal origin/main:
      git config core.longpaths true
      git ls-remote origin refs/heads/main            NEW: asks the remote first
      git fetch                                       only when the remote has a commit origin/main lacks
      git lfs fetch origin <origin/main>              NEW: only when that commit needs LFS objects this clone lacks
      git reset --hard origin/main
      git clean -fd -e Json
      git pull                                        returned; any failure raises subprocess.CalledProcessError, as
                                                      before (a stale checkout is a desync, so the caller stops)
  With a DevToken -- a developer's checkout, which IS the work:
      git config core.longpaths true
      git ls-remote <upstream remote> <branch>        NEW, as above (no upstream, or no answer: straight to the pull)
      git fetch <upstream remote>                     only when the remote has something new
      git lfs fetch <remote> <upstream>               only when needed
      git pull                                        returned; a refusal is printed and returned, never raised: the
                                                      caller's install report names it, and the launch goes on
  A fetch here passes --progress and -c fetch.unpackLimit=1: git reports no progress at all for a fetch of fewer
  than 100 objects (it unpacks them loose, quietly; measured with git 2.43), and an indexed pack is what a large
  fetch keeps anyway.

THE WINDOW
----------
It opens only when the remote has something the checkout lacks: a new commit, missing LFS objects, or a commit
fetched earlier that the checkout has not taken yet. Otherwise the steps run exactly as before, with nothing shown.
    "The server is preparing the update"   git's "remote:" lines (a bar that moves)
    "Downloading the update"               "12.3 MB received", the bar by git's own count of objects received
    "Unpacking the update"                 git's "Resolving deltas" count
    "Downloading large files"              git-LFS: "x of y MB", exact -- y is the sum of the pointer sizes of the LFS
                                           objects the new commit needs and this clone lacks; x is read from
                                           GIT_LFS_PROGRESS ("download <i>/<n> <done>/<size> <name>" per object)
    "Updating files"                       the checkout (reset --hard and clean, or the developer's merge)
Cancel stops a download. For a player that is a failed update (no launch, the same as before when the network
failed); for a developer the launch goes on with the local tree, like a refused pull.
A modal window: the main launcher's own window cannot start a second launch underneath it.
Nothing in the window or in the question below names a file or says what the update holds.

THE SIZE, AND THE QUESTION (2026-11-26)
---------------------------------------
Before a download the player is told its size and asked: OK downloads, Cancel closes the launcher (a stale checkout
is a desync, so nothing starts without the update; a developer's launch goes on with the local tree). git cannot say
what a fetch will transfer before it transfers it, so the size comes from the release step: a table at the remote's
refs/bros/update-size (one small commit, at a ref no clone fetches by default) -- what the update to commit X
downloads for a checkout on commit Y, for the last SIZE_HISTORY commits the branch was on, and for any other checkout
(the whole download, said as "up to"). It is written in the repository that pushes the update, before the push:
    python launcher/update_window.py size [<commit to publish> [<commit the players are on> ...]]
    git push <remote> +refs/bros/update-size            (with the update itself)
No table at the remote, or a table for another commit (a push made without that step): nothing is asked and the
update downloads at once, in its window, as before. LFS objects a checkout still lacks when there is no commit to
fetch (a download stopped halfway) are asked about with their exact size.

NO CONSOLE
----------
hide_console() at a script's first line hides its console window. The main launcher always did that, once its window
was built; it now happens before the update. Started with arguments (a right-click Quick Launch, a tool's --prepare)
it hides the console only when that console was made for it -- a right-click start's was -- and leaves a terminal it
was started from alone (hide_console(force=False)), as the Quick Launch scripts did until 2026-11-06.
log_to_file() keeps a script's output in %LOCALAPPDATA%\\BROS Launcher\\logs\\<script>.log (the run before as .1),
so a hidden console loses nothing; show_error() / install_check_dialog() say on screen what used to wait for Enter.

Python 3.8 (the players' Windows Python) is the floor. tkinter is imported only when a window is needed; without a
display or without tkinter, pull() still runs every step, with no window, as before.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
import time

DEVTOKEN = os.path.join("BalanceLeadTools", "DevToken.txt")

# The main launcher's palette (Bleach Rebirth of Souls Community Patch.py, "Palette").
BG = "#1c0e23"
PANEL = "#2a1734"
BORDER = "#43284f"
TEXT = "#efe1f4"
MUTED = "#b79bc4"
GOLD = "#e3b34f"
BTN_BG = "#3a2144"
BTN_HOVER = "#4c2c59"

_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}

LS_REMOTE_TIMEOUT = 60      # seconds: the remote's answer; longer means offline for a player (a failed update)
POLL_MS = 100


def is_dev(base_dir):
    return os.path.exists(os.path.join(base_dir, DEVTOKEN))


# ------------------------------------------------------------------------------------------------ git, plainly
def _decode(b):
    if b is None:
        return ""
    if isinstance(b, str):
        return b
    return b.decode("utf-8", "replace")


def _git(base, args, timeout=None):
    """git -C base <args>, captured: a CompletedProcess with str stdout / stderr (UTF-8, never a decode error).
    A timeout is returned as exit code 124 with the reason on stderr."""
    cmd = ["git", "-C", base] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, **_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "fatal: no answer from git within %d s" % timeout)
    except OSError as e:
        return subprocess.CompletedProcess(cmd, 127, "", "fatal: could not run git: %s" % e)
    return subprocess.CompletedProcess(cmd, r.returncode, _decode(r.stdout), _decode(r.stderr))


def _check(r):
    if r.returncode:
        raise subprocess.CalledProcessError(r.returncode, r.args, r.stdout, r.stderr)
    return r


def _rev(base, ref):
    r = _git(base, ["rev-parse", "--verify", "--quiet", ref + "^{commit}"])
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _ls_remote(base, remote, branch):
    """The remote's commit for refs/heads/<branch>: (sha or None, CompletedProcess)."""
    r = _git(base, ["ls-remote", remote, "refs/heads/" + branch], timeout=LS_REMOTE_TIMEOUT)
    if r.returncode:
        return None, r
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == "refs/heads/" + branch:
            return parts[0], r
    return None, subprocess.CompletedProcess(r.args, 2, r.stdout,
                                             "fatal: the remote has no branch %s" % branch)


def _upstream(base):
    """(remote, branch) the current branch pulls from, or None."""
    r = _git(base, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    up = r.stdout.strip()
    if r.returncode or "/" not in up:
        return None
    b = _git(base, ["symbolic-ref", "--quiet", "--short", "HEAD"]).stdout.strip()
    remote = _git(base, ["config", "--get", "branch.%s.remote" % b]).stdout.strip() if b else ""
    merge = _git(base, ["config", "--get", "branch.%s.merge" % b]).stdout.strip() if b else ""
    if remote and merge.startswith("refs/heads/"):
        return remote, merge[len("refs/heads/"):]
    return up.split("/", 1)[0], up.split("/", 1)[1]


# ------------------------------------------------------------------------------------------------ git-LFS
_POINTER = re.compile(rb"^version https://git-lfs\.github\.com/spec/v1\n(?:.*\n)*?oid sha256:([0-9a-f]{64})\n"
                      rb"(?:.*\n)*?size (\d+)\n", re.M)


def lfs_available(base):
    return _git(base, ["lfs", "version"], timeout=30).returncode == 0


def _lfs_store(base):
    st = _git(base, ["config", "--get", "lfs.storage"]).stdout.strip()
    common = _git(base, ["rev-parse", "--git-common-dir"]).stdout.strip()
    if common and not os.path.isabs(common):
        common = os.path.join(base, common)
    if st:
        return os.path.join(st if os.path.isabs(st) else os.path.join(common, st), "objects")
    return os.path.join(common, "lfs", "objects")


def lfs_pointers(base, commit):
    """{oid: (size, path)} of every git-LFS pointer in commit's tree, read with git itself (ls-tree, cat-file):
    a pointer is a small blob in the spec's format, whatever .gitattributes says (git-lfs decides the same way)."""
    r = subprocess.run(["git", "-C", base, "ls-tree", "-r", "-l", "-z", commit], capture_output=True, **_NO_WINDOW)
    if r.returncode:
        return {}
    small = {}
    for ent in r.stdout.split(b"\0"):
        if not ent:
            continue
        meta, _, path = ent.partition(b"\t")
        f = meta.split()
        if len(f) == 4 and f[1] == b"blob" and f[3] != b"-" and int(f[3]) < 1024:
            small.setdefault(f[2], []).append(path)
    if not small:
        return {}
    r = subprocess.run(["git", "-C", base, "cat-file", "--batch"], input=b"".join(o + b"\n" for o in small),
                       capture_output=True, **_NO_WINDOW)
    out, i, ptrs = r.stdout, 0, {}
    while i < len(out):
        nl = out.find(b"\n", i)
        if nl < 0:
            break
        hdr = out[i:nl].split()
        if len(hdr) < 3 or hdr[1] == b"missing":
            i = nl + 1
            continue
        n = int(hdr[2])
        body = out[nl + 1:nl + 1 + n]
        i = nl + 1 + n + 1
        m = _POINTER.match(body)
        if m:
            oid = m.group(1).decode()
            ptrs.setdefault(oid, (int(m.group(2)), _decode(small[hdr[0]][0])))
    return ptrs


def lfs_missing(base, commit):
    """[(oid, size, path)] of the LFS objects commit needs that this clone's store lacks."""
    store = _lfs_store(base)
    miss = []
    for oid, (size, path) in sorted(lfs_pointers(base, commit).items()):
        if not os.path.exists(os.path.join(store, oid[0:2], oid[2:4], oid)):
            miss.append((oid, size, path))
    return miss


# ------------------------------------------------------------------------------------------------ progress
_UNITS = {"bytes": 1, "byte": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3}
_RX_RECV = re.compile(r"^(Receiving|Unpacking) objects:\s+\d+% \((\d+)/(\d+)\)(?:, ([\d.]+) (bytes|byte|KiB|MiB|GiB))?")
_RX_DELTA = re.compile(r"^Resolving deltas:\s+\d+% \((\d+)/(\d+)\)")
_RX_REMOTE = re.compile(r"^remote: (Enumerating|Counting|Compressing|Total)")
_RX_FILES = re.compile(r"^(?:Updating|Checking out) files:\s+\d+% \((\d+)/(\d+)\)")
_RX_LFS = re.compile(r"^download (\d+)/(\d+) (\d+)/(\d+) (.*)$")


def parse_git_progress(line):
    """One piece of git's progress output (split at CR and LF) -> a dict, or None for anything else."""
    s = line.strip()
    m = _RX_RECV.match(s)
    if m:
        d = {"kind": "receive", "done": int(m.group(2)), "total": int(m.group(3)), "bytes": None}
        if m.group(4):
            d["bytes"] = int(float(m.group(4)) * _UNITS[m.group(5)])
        return d
    m = _RX_DELTA.match(s)
    if m:
        return {"kind": "deltas", "done": int(m.group(1)), "total": int(m.group(2))}
    if _RX_REMOTE.match(s):
        return {"kind": "remote"}
    m = _RX_FILES.match(s)
    if m:
        return {"kind": "files", "done": int(m.group(1)), "total": int(m.group(2))}
    return None


def parse_lfs_progress(line):
    """One GIT_LFS_PROGRESS line -> (object index, objects, bytes done, object size, name), or None."""
    m = _RX_LFS.match(line.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)


def mb(n):
    return "%.1f" % (n / 1e6) if n < 1e8 else "{:,.0f}".format(n / 1e6)


# ------------------------------------------------------------------------------------------------ the size
SIZE_REF = "refs/bros/update-size"      # the release step's table (the module's docstring)
SIZE_HISTORY = 100                       # commits back from the players' one that get a number of their own


def gb(n):
    """Bytes as the question says them."""
    if n >= 1e9:
        return "%.1f GB" % (n / 1e9)
    return "%d MB" % round(n / 1e6) if n >= 1e6 else "under 1 MB"


def size_parse(text, to_sha, have_sha):
    """The table -> (bytes, exact) for a checkout on have_sha updating to to_sha; None when it is another commit's.
    exact False: have_sha has no line of its own, the number is the whole download."""
    rows = {}
    for line in text.splitlines():
        f = line.split()
        if len(f) == 2:
            rows[f[0]] = f[1]
    if rows.get("to") != to_sha:
        return None
    try:
        return (int(rows[have_sha]), True) if have_sha in rows else (int(rows["*"]), False)
    except (KeyError, ValueError):
        return None


def size_read(base, remote, to_sha, have_sha):
    """Ask the remote for its table: (bytes, exact), or None when it has none for to_sha."""
    r = _git(base, ["fetch", "--quiet", "--no-tags", remote, "+%s:%s" % (SIZE_REF, SIZE_REF)],
             timeout=LS_REMOTE_TIMEOUT)
    if r.returncode:
        return None
    r = _git(base, ["cat-file", "blob", SIZE_REF + ":sizes"])
    return size_parse(r.stdout, to_sha, have_sha) if r.returncode == 0 else None


def _must(base, args, data=None):
    """git -C base <args> for the release step: its stdout (bytes); a failure ends the step with git's own words."""
    r = subprocess.run(["git", "-C", base] + list(args), input=data, capture_output=True, **_NO_WINDOW)
    if r.returncode:
        raise SystemExit("git %s: %s" % (" ".join(args[:2]), _decode(r.stderr).strip()))
    return r.stdout


def size_table(base, to_rev, from_revs, history=SIZE_HISTORY):
    """The release step's numbers: (commit, {a commit the players may be on, or "*" for any other checkout: bytes}).
    Bytes = the blobs of to_rev's tree that the other tree lacks, at their size in this repository's store (what a
    fetch transfers, within a few percent), a git-LFS pointer counting as its object."""
    def blobs(rev):
        d = {}
        for ent in _must(base, ["ls-tree", "-r", "-z", rev]).split(b"\0"):
            meta, _, path = ent.partition(b"\t")
            f = meta.split()
            if len(f) == 3 and f[1] == b"blob":
                d[path] = f[2]
        return d

    to_sha = _decode(_must(base, ["rev-parse", "--verify", to_rev + "^{commit}"])).strip()
    new = blobs(to_sha)
    size = {}
    for line in _must(base, ["cat-file", "--batch-check=%(objectname) %(objectsize:disk)"],
                      b"".join(i + b"\n" for i in sorted(set(new.values())))).splitlines():
        f = line.split()
        if len(f) != 2 or not f[1].isdigit():
            raise SystemExit("an object of %s is not in this repository (%s): run this in a full clone"
                             % (to_rev, _decode(line)))
        size[f[0]] = int(f[1])
    for _oid, (n, path) in lfs_pointers(base, to_sha).items():
        size[new[path.encode("utf-8")]] += n
    table = {"*": sum(size.values())}
    for rev in from_revs:
        for sha in _decode(_must(base, ["rev-list", "--first-parent", "-n", str(history), rev])).split():
            if sha != to_sha and sha not in table:
                have = set(blobs(sha).values())
                table[sha] = sum(n for i, n in size.items() if i not in have)
    return to_sha, table


def size_write(base, to_rev, from_revs):
    """size_table() as a commit at SIZE_REF of this repository, to push with the update. Returns what it holds."""
    to_sha, table = size_table(base, to_rev, from_revs)
    text = "to %s\n" % to_sha + "".join("%s %d\n" % kv for kv in table.items())
    blob = _decode(_must(base, ["hash-object", "-w", "--stdin"], text.encode())).strip()
    tree = _decode(_must(base, ["mktree"], ("100644 blob %s\tsizes\n" % blob).encode())).strip()
    commit = _decode(_must(base, ["commit-tree", tree, "-m", "what the update to %s downloads" % to_sha])).strip()
    _must(base, ["update-ref", SIZE_REF, commit])
    return to_sha, table


class Cancelled(Exception):
    pass


class Progress:
    """Written by the worker, read by the window, under one lock."""

    def __init__(self):
        self.lock = threading.Lock()
        self.phase = "Checking for updates"
        self.detail = ""
        self.done = 0.0
        self.total = 0.0               # 0: a bar that moves without a measure
        self.cancel = threading.Event()
        self.cancellable = False
        self.proc = None

    def set(self, phase=None, detail=None, done=None, total=None, cancellable=None):
        with self.lock:
            if phase is not None:
                self.phase = phase
            if detail is not None:
                self.detail = detail
            if done is not None:
                self.done = float(done)
            if total is not None:
                self.total = float(total)
            if cancellable is not None:
                self.cancellable = cancellable

    def snapshot(self):
        with self.lock:
            return self.phase, self.detail, self.done, self.total, self.cancellable

    def request_cancel(self):
        self.cancel.set()
        p = self.proc
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass


def _stream(base, args, prog, on_piece=None, env=None):
    """Run git -C base <args>; feed every piece of its stderr (split at CR and LF) to on_piece while it runs.
    Returns a CompletedProcess with str stdout / stderr. Raises Cancelled when the window's Cancel stopped it."""
    cmd = ["git", "-C", base] + list(args)
    e = dict(os.environ)
    if env:
        e.update(env)
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=e, **_NO_WINDOW)
    except OSError as ex:
        return subprocess.CompletedProcess(cmd, 127, "", "fatal: could not run git: %s" % ex)
    prog.proc = p
    out_chunks, err_chunks = [], []

    def drain_out():
        for chunk in iter(lambda: p.stdout.read(65536), b""):
            out_chunks.append(chunk)

    t = threading.Thread(target=drain_out, daemon=True)
    t.start()
    buf = b""
    while True:
        c = p.stderr.read1(4096) if hasattr(p.stderr, "read1") else p.stderr.read(1)
        if not c:
            break
        err_chunks.append(c)
        buf += c
        parts = re.split(rb"[\r\n]", buf)
        buf = parts.pop()
        if on_piece:
            for piece in parts:
                if piece.strip():
                    on_piece(_decode(piece))
    if buf.strip() and on_piece:
        on_piece(_decode(buf))
    rc = p.wait()
    t.join(5)
    prog.proc = None
    if prog.cancel.is_set():
        raise Cancelled("The update was cancelled.")
    err = _decode(b"".join(err_chunks))
    # What a captured run would have kept: the last state of every progress line, not each repaint.
    err = "\n".join(seg.split("\r")[-1] for seg in err.split("\n"))
    return subprocess.CompletedProcess(cmd, rc, _decode(b"".join(out_chunks)), err)


def _git_progress_feeder(prog):
    """on_piece for a fetch: git's progress -> the window."""
    state = {"bytes": 0}

    def feed(piece):
        d = parse_git_progress(piece)
        if not d:
            return
        if d["kind"] == "remote":
            prog.set(phase="The server is preparing the update", detail="", done=0, total=0)
        elif d["kind"] == "receive":
            if d["bytes"] is not None:
                state["bytes"] = d["bytes"]
            prog.set(phase="Downloading the update", done=d["done"], total=d["total"],
                     detail="%s MB received" % mb(state["bytes"]) if state["bytes"] else "")
        elif d["kind"] == "deltas":
            prog.set(phase="Unpacking the update", done=d["done"], total=d["total"],
                     detail="%s MB received" % mb(state["bytes"]) if state["bytes"] else "")
        elif d["kind"] == "files":
            prog.set(phase="Updating files", done=d["done"], total=d["total"], detail="")
    return feed


def _lfs_fetch(base, remote, commit, missing, prog):
    """git lfs fetch <remote> <commit>, its bytes read from GIT_LFS_PROGRESS into the window as "x of y MB"."""
    total = sum(s for _o, s, _p in missing)
    prog.set(phase="Downloading large files", done=0, total=total,
             detail="0.0 of %s MB" % mb(total), cancellable=True)
    fd, pfile = tempfile.mkstemp(prefix="bros_lfs_", suffix=".txt")
    os.close(fd)
    stop = threading.Event()
    per = {}

    def follow():
        pos, part = 0, ""
        while True:
            try:
                with open(pfile, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    data = f.read()
                    pos = f.tell()
            except OSError:
                data = ""
            if data:
                lines = (part + data).split("\n")
                part = lines.pop()
                for ln in lines:
                    p = parse_lfs_progress(ln)
                    if p:
                        per[(p[0], p[4])] = p[2]
                got = sum(per.values())
                prog.set(done=min(got, total), detail="%s of %s MB" % (mb(min(got, total)), mb(total)))
            if stop.is_set():
                break
            time.sleep(0.1)

    t = threading.Thread(target=follow, daemon=True)
    t.start()
    try:
        return _stream(base, ["lfs", "fetch", remote, commit], prog, env={"GIT_LFS_PROGRESS": pfile})
    finally:
        stop.set()
        t.join(2)
        try:
            os.remove(pfile)
        except OSError:
            pass


# ------------------------------------------------------------------------------------------------ the steps
class _Plan:
    """What the remote has and the checkout lacks, decided before any window."""

    def __init__(self):
        self.remote = "origin"
        self.branch = "main"
        self.remote_sha = None
        self.local = None              # the remote's commit as this clone last saw it (what the checkout has)
        self.need_fetch = False
        self.target = None             # the commit the checkout should end on (the upstream, after a fetch)
        self.lfs = []                  # missing LFS objects of target (known before the fetch only if no fetch)
        self.checkout_changes = False

    def anything_new(self):
        return self.need_fetch or bool(self.lfs) or self.checkout_changes


def _plan(base, dev):
    """Ask the remote. Returns (plan, failed CompletedProcess or None)."""
    p = _Plan()
    if dev:
        up = _upstream(base)
        if up is None:
            return None, None              # no upstream: today's pull says so itself
        p.remote, p.branch = up
    p.remote_sha, r = _ls_remote(base, p.remote, p.branch)
    if p.remote_sha is None:
        return None, r
    local = p.local = _rev(base, "refs/remotes/%s/%s" % (p.remote, p.branch))
    p.need_fetch = p.remote_sha != local
    if not p.need_fetch:
        p.target = local
        if dev:
            anc = _git(base, ["merge-base", "--is-ancestor", local, "HEAD"])
            p.checkout_changes = anc.returncode == 1
        else:
            p.checkout_changes = _rev(base, "HEAD") != local
        # The LFS objects are looked for only when the checkout is about to change: reading every pointer costs a
        # moment on each launch, and a launch with nothing new does what it always did (a missing object is then
        # fetched by git-lfs's own checkout filter, silently, as before).
        if p.checkout_changes and lfs_available(base):
            p.lfs = lfs_missing(base, local)
    return p, None


def _steps_player(base, plan, prog, show):
    """Without a DevToken: today's fetch / reset --hard / clean / pull, every failure raised."""
    if plan is not None and plan.need_fetch:
        show()
        prog.set(phase="Downloading the update", detail="", done=0, total=0, cancellable=True)
        _check(_stream(base, ["-c", "fetch.unpackLimit=1", "fetch", "--progress"], prog,
                       _git_progress_feeder(prog)))
        plan.target = _rev(base, "refs/remotes/origin/main")
        if plan.target and lfs_available(base):
            plan.lfs = lfs_missing(base, plan.target)
    if plan is not None and plan.lfs:
        show()
        _check(_lfs_fetch(base, "origin", plan.target, plan.lfs, prog))
    if plan is not None and plan.anything_new():
        show()
        prog.set(phase="Updating files", detail="", done=0, total=0, cancellable=False)
    _check(_git(base, ["reset", "--hard", "origin/main"]))
    _check(_git(base, ["clean", "-fd", "-e", "Json"]))
    r = _git(base, ["pull"])
    if r.returncode:
        raise subprocess.CalledProcessError(r.returncode, r.args, r.stdout, r.stderr)
    return r


def _steps_dev(base, plan, prog, show):
    """With a DevToken: today's pull; a fetch and the LFS objects ahead of it only to show their progress. Nothing
    here raises: a failed step is left for the pull, whose refusal is returned."""
    if plan is not None and plan.need_fetch:
        show()
        prog.set(phase="Downloading the update", detail="", done=0, total=0, cancellable=True)
        f = _stream(base, ["-c", "fetch.unpackLimit=1", "fetch", "--progress", plan.remote], prog,
                    _git_progress_feeder(prog))
        if f.returncode == 0:
            plan.target = _rev(base, "refs/remotes/%s/%s" % (plan.remote, plan.branch))
            if plan.target and lfs_available(base):
                plan.lfs = lfs_missing(base, plan.target)
            anc = _git(base, ["merge-base", "--is-ancestor", plan.target, "HEAD"]) if plan.target else None
            plan.checkout_changes = bool(anc is not None and anc.returncode == 1)
    if plan is not None and plan.lfs and plan.target:
        show()
        _lfs_fetch(base, plan.remote, plan.target, plan.lfs, prog)
    if plan is not None and plan.anything_new():
        show()
        prog.set(phase="Updating files", detail="", done=0, total=0, cancellable=False)
    r = _git(base, ["pull"])
    if r.returncode:
        print("[git] pull refused, continuing on the local tree (dev mode): " + (r.stderr or r.stdout).strip())
    return r


def _cancelled_result(dev, base):
    cmd = ["git", "-C", base, "pull"]
    text = "error: the update was cancelled before it finished"
    if dev:
        print("[git] pull refused, continuing on the local tree (dev mode): " + text)
        return subprocess.CompletedProcess(cmd, 1, "", text + "; the launch goes on with the local tree")
    raise subprocess.CalledProcessError(1, cmd, "", text + "; the game is not started without it")


def _download_size(base, plan):
    """(bytes, exact) of what is about to be downloaded, or None when it cannot be told (nothing is asked then)."""
    if plan.need_fetch:
        return size_read(base, plan.remote, plan.remote_sha, plan.local)
    if plan.lfs:
        return sum(s for _o, s, _p in plan.lfs), True
    return None


def _confirm(size, dev, parent, title):
    """The question before a download: True = download it."""
    n, exact = size
    return _box("ask", title, "An update is available.\n\nDownload size: %s%s\n\nOK downloads it now. Cancel %s"
                % ("" if n < 1e6 else "about " if exact else "up to ", gb(n),
                   "skips it: the launch goes on with the local tree." if dev else
                   "closes the launcher: the game does not start without the update."), parent)


def pull(base_dir, parent=None, title=None):
    """The update before a launch -- see the module's docstring. parent: the caller's Tk window, if it has one (the
    update window is then modal over it); without one the window is the process's own, made only if needed."""
    dev = is_dev(base_dir)
    _git(base_dir, ["config", "core.longpaths", "true"])
    plan, failed = _plan(base_dir, dev)
    if plan is None and not dev and failed is not None:
        # The remote did not answer: for a player that is today's failed fetch.
        raise subprocess.CalledProcessError(failed.returncode, failed.args, failed.stdout, failed.stderr)
    steps = _steps_dev if dev else _steps_player
    prog = Progress()
    if plan is None or not plan.anything_new():
        # Nothing the checkout lacks: the steps run as before, and nothing is shown.
        return steps(base_dir, plan, prog, lambda: None)
    title = title or "Bleach Rebirth of Souls: update"
    try:
        size = _download_size(base_dir, plan)
    except Exception:                   # the question is an extra: whatever goes wrong with it, the update goes on
        size = None
    if size is not None and not _confirm(size, dev, parent, title):
        if dev:
            return _cancelled_result(dev, base_dir)
        raise SystemExit(0)             # a player said no: the launcher closes, as the question told
    win = _Window(parent, title, prog)
    if not win.ok:
        return steps(base_dir, plan, prog, lambda: None)
    # On screen, and modal over the caller's window, before any event is handled: a click queued while the remote
    # was asked must not reach the caller's own buttons (a second launch inside this one).
    prog.set(phase="Preparing the update")
    win.show_now()
    box = {}

    def work():
        try:
            box["r"] = steps(base_dir, plan, prog, win.request_show)
        except Cancelled:
            box["cancelled"] = True
        except BaseException as e:      # handed to the caller on the main thread, unchanged
            box["e"] = e

    win.run(work)
    if box.get("cancelled"):
        return _cancelled_result(dev, base_dir)
    if "e" in box:
        raise box["e"]
    return box["r"]


# ------------------------------------------------------------------------------------------------ the window
def _dpi_aware():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class _Window:
    """The update window: the phase, a bar, the MB; Cancel while a download runs. The worker never touches it."""

    def __init__(self, parent, title, prog):
        self.prog = prog
        self.ok = False
        self.parent = parent
        self.shown = False
        self.want_show = threading.Event()
        self.anim = 0
        try:
            import tkinter as tk
            self.tk = tk
            if parent is None:
                _dpi_aware()
                self.top = tk.Tk()
            else:
                self.top = tk.Toplevel(parent)
            self.top.withdraw()
            self._build(title)
            self.ok = True
        except Exception:
            self.ok = False

    def _build(self, title):
        tk = self.tk
        t = self.top
        t.title(title)
        t.configure(bg=BG)
        t.resizable(False, False)
        try:
            ico = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ressources",
                               "pimplin.ico")
            if sys.platform == "win32" and os.path.exists(ico):
                t.iconbitmap(ico)
        except Exception:
            pass
        frame = tk.Frame(t, bg=BG, padx=22, pady=18)
        frame.pack(fill="both", expand=True)
        self.lab_phase = tk.Label(frame, text="", font=("Segoe UI", 11, "bold"), bg=BG, fg=TEXT, anchor="w")
        self.lab_phase.pack(fill="x")
        self.W, self.H = 420, 12
        self.bar = tk.Canvas(frame, width=self.W, height=self.H, bg=PANEL, highlightthickness=1,
                             highlightbackground=BORDER, bd=0)
        self.bar.pack(pady=(10, 6))
        self.fill = self.bar.create_rectangle(0, 0, 0, self.H, fill=GOLD, width=0)
        row = tk.Frame(frame, bg=BG)
        row.pack(fill="x")
        self.lab_detail = tk.Label(row, text="", font=("Segoe UI", 9), bg=BG, fg=MUTED, anchor="w")
        self.lab_detail.pack(side="left")
        self.lab_pct = tk.Label(row, text="", font=("Segoe UI", 9), bg=BG, fg=MUTED, anchor="e")
        self.lab_pct.pack(side="right")
        self.btn = tk.Button(frame, text="Cancel", command=self._cancel, font=("Segoe UI", 9), bg=BTN_BG, fg=TEXT,
                             activebackground=BTN_HOVER, activeforeground=TEXT, relief="flat", bd=0, padx=14,
                             pady=4, cursor="hand2", state="disabled")
        self.btn.pack(anchor="e", pady=(12, 0))
        t.protocol("WM_DELETE_WINDOW", self._cancel)

    def request_show(self):
        """From the worker: the window should be on screen (it already is: pull() shows it first)."""
        self.want_show.set()

    def show_now(self):
        if not self.shown:
            self._show()
            self._paint()
            self.top.update_idletasks()

    def _show(self):
        t = self.top
        t.update_idletasks()
        w, h = t.winfo_reqwidth(), t.winfo_reqheight()
        try:
            if self.parent is not None and self.parent.winfo_viewable():
                x = self.parent.winfo_rootx() + (self.parent.winfo_width() - w) // 2
                y = self.parent.winfo_rooty() + (self.parent.winfo_height() - h) // 3
            else:
                x = (t.winfo_screenwidth() - w) // 2
                y = (t.winfo_screenheight() - h) // 3
            t.geometry("+%d+%d" % (max(0, x), max(0, y)))
        except Exception:
            pass
        # Over a visible parent only: a transient window takes its master's state, so over a hidden one (a Quick
        # Launch never shows the launcher's window, MATCHFIND 2026-11-06) it would never appear.
        over = self._parent_visible()
        if over:
            t.transient(self.parent)
        t.deiconify()
        t.lift()
        try:
            t.attributes("-topmost", True)
            t.after(400, lambda: t.attributes("-topmost", False))
        except Exception:
            pass
        if over:
            try:
                t.grab_set()
            except Exception:
                pass
        self.shown = True

    def _parent_visible(self):
        try:
            return self.parent is not None and bool(self.parent.winfo_viewable())
        except Exception:
            return False

    def _cancel(self):
        if self.prog.snapshot()[4]:
            self.prog.request_cancel()
            self.prog.set(phase="Cancelling...", cancellable=False)

    def _paint(self):
        phase, detail, done, total, cancellable = self.prog.snapshot()
        self.lab_phase.config(text=phase)
        self.lab_detail.config(text=detail)
        if total > 0:
            f = max(0.0, min(1.0, done / total))
            self.bar.coords(self.fill, 0, 0, int(self.W * f), self.H)
            self.lab_pct.config(text="%d %%" % int(f * 100))
        else:
            seg = self.W // 4
            self.anim = (self.anim + 12) % (self.W + seg)
            self.bar.coords(self.fill, self.anim - seg, 0, self.anim, self.H)
            self.lab_pct.config(text="")
        self.btn.config(state="normal" if cancellable else "disabled")

    def run(self, work):
        """Run work() on a thread while the window repaints; return when it is done (the window is gone then)."""
        th = threading.Thread(target=work, daemon=True)
        done = threading.Event()

        def poll():
            if self.want_show.is_set() and not self.shown:
                self._show()
            if self.shown:
                self._paint()
            if th.is_alive():
                self.top.after(POLL_MS, poll)
            else:
                done.set()
                if self.parent is None:
                    self.top.quit()
                else:
                    try:
                        self.top.grab_release()
                    except Exception:
                        pass
                    self.top.destroy()

        th.start()
        self.top.after(POLL_MS, poll)
        if self.parent is None:
            self.top.mainloop()
            try:
                self.top.destroy()
            except Exception:
                pass
        else:
            self.parent.wait_window(self.top)
        th.join()


# ------------------------------------------------------------------------------------------------ no console
_console_hidden = False


def _console_processes():
    """Names of the processes attached to this console (Windows), lower case; None when it cannot be told."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    arr = (wintypes.DWORD * 64)()
    n = k32.GetConsoleProcessList(arr, 64)
    if n <= 0:
        return None
    names = []
    for pid in list(arr)[:min(n, 64)]:
        if pid == os.getpid():
            continue
        h = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            names.append("?")
            continue
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            ok = k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
            names.append(os.path.basename(buf.value).lower() if ok else "?")
        finally:
            k32.CloseHandle(h)
    return names


# The console belongs to someone else when one of these shares it: the script was started from a terminal or a .bat.
_SHELLS = ("cmd.exe", "powershell.exe", "pwsh.exe", "bash.exe", "sh.exe", "wsl.exe", "windowsterminal.exe",
           "openconsole.exe", "wt.exe", "conemu.exe", "conemu64.exe", "conemuc.exe", "conemuc64.exe", "mintty.exe",
           "code.exe", "?")


def console_is_own(names):
    """True when nothing but this launch (python.exe, the py.exe launcher) shares the console."""
    if names is None:
        return False
    return not any(n in _SHELLS for n in names)


def hide_console(force=False):
    """Hide this process's console window (Windows). force: always (the main launcher's rule since its first version);
    otherwise only a console made for this launch -- a terminal the script was started from stays as it is."""
    global _console_hidden
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        h = ctypes.windll.kernel32.GetConsoleWindow()
        if not h:
            return False
        if not force and not console_is_own(_console_processes()):
            return False
        ctypes.windll.user32.ShowWindow(h, 0)
        _console_hidden = True
        return True
    except Exception:
        return False


def console_hidden():
    return _console_hidden


class _Tee:
    """stdout / stderr into the log file as well; a hidden console is not a terminal anyone reads."""

    def __init__(self, stream, f):
        self.stream, self.f = stream, f

    def write(self, s):
        try:
            if self.stream is not None:
                self.stream.write(s)
        except Exception:
            pass
        try:
            self.f.write(s)
            self.f.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        for x in (self.stream, self.f):
            try:
                if x is not None:
                    x.flush()
            except Exception:
                pass

    def isatty(self):
        if _console_hidden or self.stream is None:
            return False
        try:
            return self.stream.isatty()
        except Exception:
            return False

    def fileno(self):
        if self.stream is None:
            raise OSError("no console")
        return self.stream.fileno()

    @property
    def encoding(self):
        return getattr(self.stream, "encoding", "utf-8") or "utf-8"


_log_path = None


def log_dir():
    root = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(root, "BROS Launcher", "logs")


def log_to_file(name):
    """Keep this run's output in log_dir()/<name>.log (the previous run as .1). Returns the path, or None."""
    global _log_path
    try:
        d = log_dir()
        os.makedirs(d, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9 ._-]", "_", os.path.splitext(os.path.basename(name))[0]) or "launcher"
        p = os.path.join(d, stem + ".log")
        if os.path.exists(p):
            os.replace(p, p + ".1")
        f = open(p, "w", encoding="utf-8", errors="replace")
        f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), name))
        sys.stdout = _Tee(sys.stdout, f)
        sys.stderr = _Tee(sys.stderr, f)
        _log_path = p
        return p
    except Exception:
        return None


def log_path():
    return _log_path


def log_tail(lines=25):
    if not _log_path:
        return ""
    try:
        with open(_log_path, "r", encoding="utf-8", errors="replace") as f:
            return "\n".join(f.read().splitlines()[-lines:])
    except OSError:
        return ""


# ------------------------------------------------------------------------------------------------ messages
def _box(kind, title, text, parent=None):
    """A message box over parent, or over a hidden window of its own when the script has none."""
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception:
        print("[%s]\n%s" % (title, text))
        return True
    own = None
    try:
        if parent is None:
            _dpi_aware()
            own = tk.Tk()
            own.withdraw()
            try:
                own.attributes("-topmost", True)
            except Exception:
                pass
            parent = own
        if kind == "error":
            messagebox.showerror(title, text, parent=parent)
            return True
        if kind == "info":
            messagebox.showinfo(title, text, parent=parent)
            return True
        return bool(messagebox.askokcancel(title, text, parent=parent))
    except Exception:
        print("[%s]\n%s" % (title, text))
        return True
    finally:
        if own is not None:
            try:
                own.destroy()
            except Exception:
                pass


def show_error(title, text, parent=None):
    return _box("error", title, text, parent)


def show_info(title, text, parent=None):
    return _box("info", title, text, parent)


def install_check_dialog(title, text, problem):
    """launcher/install_guard.finish()'s screen for a script with no console: True starts the game, False does not."""
    if problem:
        return _box("ask", title, text + "\n\nOK starts the game anyway. Cancel does not.")
    _box("info", title, text)
    return True


def failure_text(head):
    """What a Quick Launch shows when the game was not started: head, the end of the log, where the log is."""
    tail = log_tail(18)
    out = head
    if tail:
        out += "\n\n" + tail
    if _log_path:
        out += "\n\nThe whole log: %s" % _log_path
    return out


# ------------------------------------------------------------------------------------------------ the release step
if __name__ == "__main__":
    # run in the repository that pushes the update (see THE SIZE in the docstring)
    if len(sys.argv) < 2 or sys.argv[1] != "size":
        sys.exit("usage: python launcher/update_window.py size [<commit to publish> [<commit the players are on> ...]]")
    _to, _table = size_write(os.getcwd(), sys.argv[2] if len(sys.argv) > 2 else "HEAD", sys.argv[3:] or ["@{u}"])
    print("update to %s: %d checkout(s) with a size of their own" % (_to[:10], len(_table) - 1))
    for _sha, _n in list(_table.items())[:4]:
        print("  %-10s %s" % ("any other" if _sha == "*" else _sha[:10], gb(_n)))
    print("written at %s; push it with the update:  git push <remote> +%s" % (SIZE_REF, SIZE_REF))
