"""An update's files from a GitHub release -- GitHub's download network -- instead of git's own download (2026-11-28).

WHY
---
git downloads an update from GitHub's git servers, and many players reach those at about 0.5 MB/s (V2.0, 2026-11-27).
A release's files come from GitHub's download network instead: any byte range of a file, several requests at once,
and a request that drops is asked for again from where it stopped. update_window's batched git download (THE FILES,
IN BATCHES) stays as the way for everything a release does not have.

WHAT STAYS
----------
The player's patch folder stays a git checkout: its commit is still what the launcher, the room codes and everything
else read. Only the step that brings the files changes. git fetches the history (about 1 MB), so the clone has the new
commit but lacks its files (a blobless clone); this module brings as many of them as the newest release has, and git's
batches bring the rest. git then checks the files out as if it had downloaded them itself.

THE RELEASE
-----------
tools/build_release_files.py, run for a commit (by .github/workflows/release-files.yml, or by hand), writes:
    files-1.zip, files-2.zip, ...   the commit's files, each zip under 2 GiB; one entry per distinct file
    files-manifest.json            for every file: its git object id, its size, and the zip and byte range that
                                   hold it ("schema": 2)
The manifest is uploaded last and the release published only then, so a release is never seen with a manifest naming a
zip that is not there yet. A file is found by its git object id, which is its content: a file unchanged since the
release has the same id, so a release made for an older commit still serves every file the newer commit did not change.

WHICH RELEASE
-------------
The manifest of the repository's latest release, through GitHub's own link (github.com/<repo>/releases/latest/download/
files-manifest.json: no API request, so no API rate limit); when the latest release has none, the newest release that
has one, from GitHub's API. No release at all (or no network to either): Unavailable, and git downloads everything as
before.

THE DOWNLOAD
------------
Neighbouring files are fetched in one request of up to SPAN_BYTES; a file bigger than that comes in SPAN_BYTES pieces,
appended to .git/bros-download/<id>-<size>-<method>.part as they arrive, so a later start resumes it. WORKERS requests
run at once; each worker hands its requests' files to git as a pack once they reach PACK_BYTES (so the scattered
small files of an update do not make a pack each, and no more than about two requests are held in memory). A request that drops keeps the files that arrived whole; the rest is asked for again after a pause (a
request of several files in two halves); MAX_FAILS failures in a row with nothing arriving end this step, and git
brings what is left. A request slower than LOW_SPEED bytes a second for LOW_SPEED_TIME seconds counts as dropped.
A server that ignores byte ranges, an asset that is gone, a full disk: the step ends at once.

Every file is checked against its object id -- the hash git itself computes -- and only then handed to git as a
pack (`git index-pack --stdin --promisor`, which checks them again), marked as the promisor remote's
(pack-<id>.promisor) exactly as git marks the packs it fetches from origin itself -- so gc, repack and fsck treat them
as git's own download. (Unmarked, they would not survive a gc: in a partial clone gc keeps only what origin's packs
lead to -- measured with git 2.43.) A deflated file goes into its pack as it came (the zip's deflate stream in zlib framing): no
second compression. The caller writes the multi-pack-index afterwards (update_window._tidy_packs).
A file that does not match its id is left to git (and the step ends when three do: the release is not what its
manifest says).

Python 3.8 (the players' Windows Python) is the floor; nothing outside the standard library.
"""

from __future__ import annotations

import collections
import errno
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

MANIFEST_ASSET = "files-manifest.json"
SCHEMA = 2
LATEST = "https://github.com/%s/%s/releases/latest/download/%s"
DOWNLOAD = "https://github.com/%s/%s/releases/download/%s/%s"
API_LIST = "https://api.github.com/repos/%s/%s/releases?per_page=%d"
USER_AGENT = "BROS-launcher-release-files/1"

SPAN_BYTES = 32 * 1024 * 1024    # one request (and one pack): neighbouring files up to this many bytes, or one
                                 # piece of a bigger file
GAP_BYTES = 64 * 1024            # files this close in a zip share a request (the bytes between them are skipped)
PACK_BYTES = 8 * 1024 * 1024     # a worker's checked files go to git as one pack once they reach this much
WORKERS = 4                      # requests at once
MAX_FAILS = 12                   # failed requests in a row, with nothing arriving, before this step gives up
MAX_BAD = 3                      # files that do not match their id before this step gives up
CHUNK = 64 * 1024                # bytes per read from a response (the bar and Cancel follow at this pace)
TIMEOUT = 60                     # seconds without a byte before a request counts as dropped
LOW_SPEED = 1000                 # bytes a second ...
LOW_SPEED_TIME = 60              # ... for this many seconds: a crawling request counts as dropped
DISK_MARGIN = 256 * 1024 * 1024  # free space kept beyond the download itself

_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}
_ZLIB_HEAD = b"\x78\x01"         # zlib framing around a raw deflate stream (32 KiB window; the level is a label)


class Unavailable(Exception):
    """No release to download from (none published, none with a manifest, no network to GitHub): git downloads
    everything, as before."""


class Cancelled(Exception):
    pass


class DiskFull(Exception):
    """The disk holding the checkout has no room for the download."""


class _Fatal(Exception):
    """This release cannot serve this step at all: the step ends at once."""


class _Partial(Exception):
    """A request that dropped: rest is the span still to fetch, progress whether anything of it arrived."""

    def __init__(self, err, rest, progress):
        Exception.__init__(self, str(err))
        self.err = err
        self.rest = rest
        self.progress = progress


# ------------------------------------------------------------------------------------------------ git
def _git(base, args, data=None, timeout=None):
    try:
        r = subprocess.run(["git", "-C", base] + list(args), input=data, capture_output=True, timeout=timeout,
                           **_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, b"", str(e).encode()
    return r.returncode, r.stdout, r.stderr


def git_path(base, name):
    rc, out, _ = _git(base, ["rev-parse", "--git-path", name])
    p = out.decode("utf-8", "replace").strip()
    if rc or not p:
        raise Unavailable("not a git checkout")
    return p if os.path.isabs(p) else os.path.join(base, p)


def origin_slug(base):
    """(owner, name) of origin on GitHub, or None."""
    rc, out, _ = _git(base, ["remote", "get-url", "origin"])
    m = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?/?$", out.decode("utf-8", "replace").strip())
    return (m.group(1), m.group(2)) if m and rc == 0 else None


def _disk_full(ex):
    if getattr(ex, "errno", None) == errno.ENOSPC or getattr(ex, "winerror", None) in (39, 112):
        return True
    s = str(ex).lower()
    return "no space left" in s or "not enough space" in s or "disk is full" in s


# ------------------------------------------------------------------------------------------------ HTTP
class _Follow(urllib.request.HTTPRedirectHandler):
    """Redirects followed as usual, each one noted (the latest release's link names its tag on the way)."""

    def __init__(self):
        self.seen = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.seen.append(newurl)
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


def _open(url, headers=None, timeout=TIMEOUT, follow=None):
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    opener = urllib.request.build_opener(follow or _Follow())
    return opener.open(urllib.request.Request(url, headers=h), timeout=timeout)


def _read_all(url, timeout=30, tries=3, follow=None, headers=None):
    """A small file (the manifest, an API answer), whole; a dropped connection is tried again."""
    err = None
    for i in range(tries):
        try:
            with _open(url, headers, timeout, follow) as r:
                return r.read()
        except urllib.error.HTTPError:
            raise
        except Exception as e:
            err = e
            time.sleep(min(5, 1 + 2 * i))
    raise err


def fetch_range(url, start, end, sink, cancel=None, timeout=TIMEOUT):
    """GET bytes [start, end) of url into sink(bytes) as they arrive. Returns how many arrived. Raises _Fatal when the
    server cannot serve the range at all (it ignores ranges, the asset is gone), IOError when the connection drops or
    crawls (sink keeps what arrived), Cancelled on cancel."""
    want = end - start
    try:
        r = _open(url, {"Range": "bytes=%d-%d" % (start, end - 1), "Accept": "application/octet-stream"}, timeout)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410, 416):
            raise _Fatal("the release's file is not there (HTTP %d)" % e.code)
        raise IOError("HTTP %d" % e.code)
    got = 0
    with r:
        status = getattr(r, "status", None) or r.getcode()
        if status != 206:
            raise _Fatal("the download server ignored the byte range (HTTP %s)" % status)
        cr = r.headers.get("Content-Range", "")
        if cr and not cr.startswith("bytes %d-" % start):
            raise _Fatal("the download server sent another range (%s)" % cr)
        t0, window = time.monotonic(), 0
        while got < want:
            if cancel is not None and cancel.is_set():
                raise Cancelled("cancelled")
            b = r.read(min(CHUNK, want - got))
            if not b:
                break
            sink(b)
            got += len(b)
            window += len(b)
            now = time.monotonic()
            if now - t0 >= LOW_SPEED_TIME:
                if window < LOW_SPEED * (now - t0):
                    raise IOError("the download crawled (%d bytes in %d s)" % (window, now - t0))
                t0, window = now, 0
    if got != want:
        raise IOError("the connection dropped after %d of %d bytes" % (got, want))
    return got


# ------------------------------------------------------------------------------------------------ the release
class Entry(object):
    __slots__ = ("path", "oid", "size", "asset", "offset", "csize", "method")

    def __init__(self, path, d):
        self.path = path
        self.oid = str(d["oid"])
        self.size = int(d["size"])
        self.asset = str(d["asset"])
        self.offset = int(d["offset"])
        self.csize = int(d["csize"])
        self.method = int(d["method"])


class Release(object):
    def __init__(self, tag, commit, assets, by_oid):
        self.tag = tag
        self.commit = commit
        self.assets = assets          # name -> download URL
        self.by_oid = by_oid          # git object id -> Entry


def parse_manifest(raw, assets=None, tag="", slug=None):
    """files-manifest.json -> Release. assets: {asset name: download URL}; without it the URLs are the release's own
    links (slug and tag needed)."""
    d = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    if d.get("schema") != SCHEMA:
        raise Unavailable("the release's manifest has schema %r, this launcher reads %d" % (d.get("schema"), SCHEMA))
    tag = tag or d.get("release", "")
    if assets is None:
        if not slug or not tag:
            raise Unavailable("the manifest does not say which release it belongs to")
        assets = {n: DOWNLOAD % (slug[0], slug[1], urllib.parse.quote(tag), urllib.parse.quote(n))
                  for n in d.get("assets", {})}
    by_oid = {}
    for path, e in d.get("files", {}).items():
        ent = Entry(path, e)
        if ent.asset in assets and ent.method in (0, 8) and re.match(r"^[0-9a-f]{40}$", ent.oid):
            by_oid.setdefault(ent.oid, ent)
    return Release(tag, d.get("commit", ""), assets, by_oid)


def find_release(base=None, slug=None, timeout=30):
    """The latest release of origin's repository with a files manifest -- see WHICH RELEASE."""
    slug = slug or (origin_slug(base) if base else None)
    if not slug:
        raise Unavailable("origin is not a GitHub repository")
    why = []
    follow = _Follow()
    try:
        raw = _read_all(LATEST % (slug[0], slug[1], MANIFEST_ASSET), timeout, follow=follow)
        tag = ""
        for u in follow.seen:
            m = re.search(r"/releases/download/([^/]+)/", u)
            if m:
                tag = urllib.parse.unquote(m.group(1))
                break
        return parse_manifest(raw, tag=tag, slug=slug)
    except Unavailable as e:
        why.append(str(e))
    except urllib.error.HTTPError as e:
        why.append("the latest release has no %s (HTTP %d)" % (MANIFEST_ASSET, e.code))
    except Exception as e:
        why.append("github.com did not answer (%s)" % e)
    try:
        rels = json.loads(_read_all(API_LIST % (slug[0], slug[1], 20), timeout,
                                    headers={"Accept": "application/vnd.github+json"}).decode("utf-8"))
    except Exception as e:
        raise Unavailable("; ".join(why + ["GitHub's API did not answer (%s)" % e]))
    for r in rels:
        if r.get("draft"):
            continue
        assets = {a["name"]: a["browser_download_url"] for a in r.get("assets", [])
                  if a.get("state", "uploaded") == "uploaded"}
        if MANIFEST_ASSET not in assets:
            continue
        try:
            raw = _read_all(assets[MANIFEST_ASSET], timeout)
        except Exception as e:
            raise Unavailable("the manifest of release %s could not be read (%s)" % (r.get("tag_name"), e))
        return parse_manifest(raw, assets, r.get("tag_name", ""))
    raise Unavailable("; ".join(why + ["no release has %s yet" % MANIFEST_ASSET]))


# ------------------------------------------------------------------------------------------------ planning
class Span(object):
    __slots__ = ("asset", "start", "end", "entries", "big")

    def __init__(self, asset, entries, big=False):
        self.asset = asset
        self.entries = entries
        self.start = min(e.offset for e in entries)
        self.end = max(e.offset + e.csize for e in entries)
        self.big = big


def plan(entries, span_bytes=SPAN_BYTES, gap_bytes=GAP_BYTES):
    """Entries (none empty) -> spans: neighbours in one request (up to span_bytes), a bigger file alone, in pieces."""
    spans = []
    by_asset = collections.defaultdict(list)
    for e in entries:
        by_asset[e.asset].append(e)
    for asset in sorted(by_asset):
        cur, cur_end = [], 0
        for e in sorted(by_asset[asset], key=lambda x: x.offset):
            if e.csize > span_bytes:
                if cur:
                    spans.append(Span(asset, cur))
                    cur = []
                spans.append(Span(asset, [e], big=True))
                continue
            if cur and e.offset - cur_end <= gap_bytes and e.offset + e.csize - cur[0].offset <= span_bytes:
                cur.append(e)
                cur_end = max(cur_end, e.offset + e.csize)
                continue
            if cur:
                spans.append(Span(asset, cur))
            cur, cur_end = [e], e.offset + e.csize
        if cur:
            spans.append(Span(asset, cur))
    return spans


def split(span):
    """A failed span of several files, in two."""
    h = len(span.entries) // 2
    return [Span(span.asset, span.entries[:h]), Span(span.asset, span.entries[h:])]


# ------------------------------------------------------------------------------------------------ checking, packing
def _inflate(pieces, method, out_max=1 << 20):
    """A zip entry's content from its compressed pieces (method 0 = stored, 8 = deflate), in pieces of at most
    out_max bytes. Raises ValueError when the deflate stream is cut short or carries bytes past its end."""
    if method == 0:
        for c in pieces:
            if c:
                yield c
        return
    d = zlib.decompressobj(-15)
    for c in pieces:
        buf = c
        while buf:
            out = d.decompress(buf, out_max)
            if out:
                yield out
            buf = d.unconsumed_tail
            if d.eof:
                break
        if d.eof and (buf or d.unused_data):
            raise ValueError("bytes past the end of a deflate stream")
    out = d.flush()
    if out:
        yield out
    if not d.eof:
        raise ValueError("a deflate stream cut short")


def check(e, pieces):
    """The adler-32 of e's content when its compressed pieces hold exactly the file e names (size and git object id);
    None when they do not."""
    h = hashlib.sha1(b"blob %d\0" % e.size)
    a, n = 1, 0
    try:
        for out in _inflate(pieces, e.method):
            h.update(out)
            a = zlib.adler32(out, a)
            n += len(out)
    except (ValueError, zlib.error):
        return None
    if n != e.size or h.hexdigest() != e.oid:
        return None
    return a & 0xFFFFFFFF


def _obj_head(size, kind=3):
    """A pack entry's header: its type (3 = blob) and its size."""
    c = (kind << 4) | (size & 0x0F)
    size >>= 4
    out = bytearray()
    while size:
        out.append(c | 0x80)
        c = size & 0x7F
        size >>= 7
    out.append(c)
    return bytes(out)


def _write_blob(w, e, pieces, adler):
    """One blob into a pack being written with w(bytes): its header and its zlib stream -- a deflated file's own
    deflate stream in zlib framing, a stored file in stored blocks (it did not compress)."""
    w(_obj_head(e.size))
    if e.method == 8:
        w(_ZLIB_HEAD)
        for c in pieces:
            w(c)
        w(struct.pack(">I", adler))
    else:
        z = zlib.compressobj(0)
        for c in pieces:
            w(z.compress(c))
        w(z.flush())


_PROMISOR_OPTION = [True]               # git index-pack --promisor (git 2.17+); False once a git refused it


def index_pack(base, objects, pack_dir=None):
    """objects: [(entry, pieces factory, adler)], each already checked. Streams them as one pack into
    `git index-pack --stdin --promisor`, which checks them again, writes pack + index into objects/pack and marks the
    pack as the promisor remote's before the pack is in place -- git's own fetch does the same. Unmarked, a gc would
    drop these files again: a partial clone's gc keeps only what origin's packs lead to. Returns the pack's id.
    Raises DiskFull, or IOError with git's message."""
    pack_dir = pack_dir or os.path.join(git_path(base, "objects"), "pack")
    flag = _PROMISOR_OPTION[0]
    rc, out, err = _index_pack_once(base, objects, flag)
    if rc and flag and re.search(r"usage: git index-pack|unknown option", err):
        _PROMISOR_OPTION[0] = flag = False      # an old git: the marker is written below instead
        rc, out, err = _index_pack_once(base, objects, flag)
    if rc:
        if _disk_full(IOError(err)):
            raise DiskFull("the disk is full (git: %s)" % err)
        raise IOError("git index-pack: %s" % (err or "exit %d" % rc))
    m = re.search(rb"([0-9a-f]{40,64})", out)
    if not m:
        raise IOError("git index-pack named no pack")
    name = m.group(1).decode()
    marker = os.path.join(pack_dir, "pack-%s.promisor" % name)
    if not flag or not os.path.exists(marker):
        with open(marker, "wb"):
            pass
    return name


def _index_pack_once(base, objects, promisor):
    env = dict(os.environ)
    env["GIT_NO_LAZY_FETCH"] = "1"          # never a download from here (git 2.44+; older git ignores it)
    cmd = ["git", "-C", base, "index-pack", "--stdin"] + (["--promisor"] if promisor else [])
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                             **_NO_WINDOW)
    except OSError as e:
        raise IOError("could not run git index-pack: %s" % e)
    outs = {}

    def drain(k, f):
        outs[k] = f.read()
    ts = [threading.Thread(target=drain, args=(k, f), daemon=True) for k, f in (("out", p.stdout), ("err", p.stderr))]
    for t in ts:
        t.start()
    h = hashlib.sha1()

    def w(b):
        h.update(b)
        p.stdin.write(b)
    try:
        w(b"PACK" + struct.pack(">II", 2, len(objects)))
        for e, pieces, adler in objects:
            _write_blob(w, e, pieces(), adler)
        p.stdin.write(h.digest())
    except OSError:
        pass                                   # index-pack stopped reading: its own message says why
    finally:
        try:
            p.stdin.close()
        except OSError:
            pass
    rc = p.wait()
    for t in ts:
        t.join(30)
    return rc, outs.get("out", b""), outs.get("err", b"").decode("utf-8", "replace").strip()


# ------------------------------------------------------------------------------------------------ the download
def fetch(base, oids, prog=None, release=None, workers=WORKERS, span_bytes=SPAN_BYTES, max_fails=MAX_FAILS,
          pause=None, log=print, get_range=None, phase="Downloading the update"):
    """Bring the objects oids (files a blobless clone lacks) from the newest release into git's object store.
    Returns the set of object ids it brought. Raises Unavailable (no release), Cancelled (prog.cancel) or DiskFull;
    any other trouble ends the step early and returns what arrived -- git's own download brings the rest.
    prog: update_window.Progress (or None), phase: what its window says; get_range / pause: replaceable for the
    tests."""
    rc, out, _e = _git(base, ["rev-parse", "--show-object-format"])
    if rc == 0 and out.strip() not in (b"", b"sha1"):
        raise Unavailable("this clone's object format is %s" % out.strip().decode())
    release = release or find_release(base)
    get_range = get_range or fetch_range
    cancel = prog.cancel if prog is not None else threading.Event()
    pause = pause or (lambda s: cancel.wait(s))
    objects_dir = git_path(base, "objects")
    pack_dir = os.path.join(objects_dir, "pack")
    part_dir = git_path(base, "bros-download")
    want = [release.by_oid[o] for o in dict.fromkeys(oids) if o in release.by_oid]
    if not want:
        log("[release files] %s has none of the %d missing files" % (release.tag, len(oids)))
        return set()
    written = set()
    lock = threading.Lock()

    # Empty files need no request.
    empty = [e for e in want if e.csize == 0]
    want = [e for e in want if e.csize > 0]
    if empty:
        objs = [(e, (lambda: iter(())), 1) for e in empty if check(e, []) is not None]
        if objs:
            index_pack(base, objs, pack_dir)
            written.update(e.oid for e, _p, _a in objs)
    total = sum(e.csize for e in want)
    try:
        free = shutil.disk_usage(objects_dir).free
    except OSError:
        free = None
    if free is not None and free < total + DISK_MARGIN:
        raise DiskFull("the update needs %.1f GB on this disk and %.1f GB are free" % ((total + DISK_MARGIN) / 1e9,
                                                                                         free / 1e9))
    spans = collections.deque(plan(want, span_bytes))
    st = {"bytes": 0, "total": total, "fails": 0, "stop": False, "err": "", "bad": 0, "disk": ""}
    log("[release files] %s: %d of %d missing files, %s MB, in %d request(s)"
        % (release.tag, len(want) + len(empty), len(oids), _mb(total), len(spans)))

    # Pieces of big files from an earlier start: kept when this download still wants them, else removed.
    parts = {"%s-%d-%d.part" % (e.oid, e.csize, e.method) for e in want if e.csize > span_bytes}
    try:
        for n in os.listdir(part_dir):
            if n.endswith(".part") and n not in parts:
                os.remove(os.path.join(part_dir, n))
    except OSError:
        pass

    def report():
        if prog is not None:
            prog.set(phase=phase, done=st["bytes"], total=st["total"],
                     detail="%s of %s MB" % (_mb(st["bytes"]), _mb(st["total"])))

    def add_bytes(n):
        with lock:
            st["bytes"] += n
            report()

    def drop(e, why):
        """e is left to git: it does not count in this step any more."""
        with lock:
            st["bad"] += 1
            st["total"] -= e.csize
            if st["bad"] >= MAX_BAD:
                st["stop"] = True
                st["err"] = "%d files did not match their ids" % st["bad"]
            report()
        log("[release files] %s %s: git brings it" % (e.path, why))

    def small(span, pending):
        """One request of neighbouring files; the ones that check out go to pending (a pack, soon)."""
        buf = bytearray()

        def sink(b):
            buf.extend(b)
            add_bytes(len(b))
        failure = None
        try:
            get_range(release.assets[span.asset], span.start, span.end, sink, cancel)
        except (Cancelled, _Fatal):
            add_bytes(-len(buf))
            raise
        except Exception as ex:
            failure = ex
        got_to = span.start + len(buf)
        view = memoryview(buf)
        kept = 0
        rest = []
        for e in span.entries:
            if e.offset + e.csize > got_to:
                rest.append(e)
                continue
            raw = view[e.offset - span.start:e.offset - span.start + e.csize]
            adler = check(e, [raw])
            if adler is None:
                drop(e, "does not match its id in the release")
                continue
            pending.append((e, (lambda raw=raw: iter([raw])), adler))
            kept += e.csize
        add_bytes(kept - len(buf))           # what is kept counts; cut-off files and the gaps between files do not
        if failure is not None and rest:
            raise _Partial(failure, Span(span.asset, rest), progress=kept > 0)

    def flush(pending):
        """pending -> one pack. On failure its files come again (re-queued) and the error is raised."""
        if not pending:
            return
        objs = list(pending)
        del pending[:]
        try:
            index_pack(base, objs, pack_dir)
        except Exception:
            with lock:
                st["bytes"] -= sum(e.csize for e, _p, _a in objs)
                spans.extend(plan([e for e, _p, _a in objs], span_bytes))
                report()
            raise
        with lock:
            written.update(e.oid for e, _p, _a in objs)

    counted = {}                      # big file -> its bytes already in st["bytes"] (a retry must not add them again)
    fresh = set()                     # big files whose pieces did not add up once: downloaded again from zero

    def big(span):
        """A file bigger than one request: in pieces, appended to its .part file, then checked and packed."""
        e = span.entries[0]
        os.makedirs(part_dir, exist_ok=True)
        part = os.path.join(part_dir, "%s-%d-%d.part" % (e.oid, e.csize, e.method))
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if have > e.csize:             # not this file's: start over
            os.remove(part)
            have = 0
        with lock:
            st["bytes"] += have - counted.get(e.oid, 0)
            counted[e.oid] = have
            report()
        with open(part, "ab") as f:
            while have < e.csize:
                end = min(e.csize, have + span_bytes)
                before = have

                def sink(b):
                    f.write(b)
                    with lock:
                        counted[e.oid] = counted.get(e.oid, 0) + len(b)
                    add_bytes(len(b))
                try:
                    get_range(release.assets[span.asset], e.offset + have, e.offset + end, sink, cancel)
                except (Cancelled, _Fatal):
                    raise
                except Exception as ex:
                    f.flush()
                    raise _Partial(ex, span, progress=f.tell() > before)
                finally:
                    f.flush()              # what arrived stays on disk: the next attempt (or start) resumes there
                    have = f.tell()
                with lock:
                    st["fails"] = 0        # a piece arrived: the connection works
        adler = check(e, _file_pieces(part))
        if adler is None:
            os.remove(part)
            with lock:
                st["bytes"] -= counted.pop(e.oid, 0)
                report()
            if e.oid in fresh:
                drop(e, "does not match its id in the release")
                return
            fresh.add(e.oid)
            raise IOError("%s did not add up; it is downloaded again" % e.path)
        index_pack(base, [(e, (lambda: _file_pieces(part)), adler)], pack_dir)
        with lock:
            written.add(e.oid)
        try:
            os.remove(part)
        except OSError:
            pass

    def failed(span, ex):
        """A request failed (span None: a pack, whose files flush() put back itself): stop, or put it back (in halves
        when it holds several files) and pause. False when this worker stops."""
        err = getattr(ex, "err", ex)
        if isinstance(err, DiskFull) or _disk_full(err):
            with lock:
                st["stop"] = True
                st["disk"] = str(err)
            return False
        if cancel.is_set():
            return False
        again = ex.rest if isinstance(ex, _Partial) else span
        with lock:
            if isinstance(ex, _Partial) and ex.progress:
                st["fails"] = 0            # some of it arrived: the connection works
            st["fails"] += 1
            st["err"] = str(err)
            fails = st["fails"]
            if fails >= max_fails:
                st["stop"] = True
                return False
            if again is not None:
                for s in reversed(split(again) if not again.big and len(again.entries) > 1 else [again]):
                    spans.appendleft(s)
        log("[release files] a request failed (%d in a row): %s" % (fails, err))
        if prog is not None:
            prog.set(detail="The connection dropped; trying again (%d of %d)..." % (fails, max_fails))
        pause(min(60, 5 * fails))
        return True

    def worker():
        pending = []
        try:
            while True:
                with lock:
                    if st["stop"] or cancel.is_set() or not spans:
                        return
                    span = spans.popleft()
                try:
                    if span.big:
                        big(span)
                    else:
                        small(span, pending)
                    with lock:
                        st["fails"] = 0
                except Cancelled:
                    return
                except _Fatal as ex:
                    with lock:
                        st["stop"] = True
                        st["err"] = str(ex)
                    return
                except Exception as ex:
                    if not failed(span, ex):
                        return
                    continue
                if sum(e.csize for e, _p, _a in pending) >= PACK_BYTES:
                    try:
                        flush(pending)
                    except Exception as ex:
                        if not failed(None, ex):
                            return
        finally:
            n = len(pending)
            try:
                flush(pending)             # what checked out is kept, also on Cancel or a stop
            except Exception as ex:
                if isinstance(ex, DiskFull) or _disk_full(ex):
                    with lock:
                        st["disk"] = str(ex)
                log("[release files] %d checked files could not be stored (%s); git brings them" % (n, ex))

    if prog is not None:
        prog.set(phase=phase, cancellable=True)
        report()
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, min(workers, len(spans))))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if cancel.is_set():
        raise Cancelled("The update was cancelled.")
    if st["disk"]:
        raise DiskFull(st["disk"])
    if st["stop"]:
        log("[release files] stopped (%s); git brings the rest" % st["err"])
    log("[release files] %d of %d files arrived" % (len(written), len(want) + len(empty)))
    return written


def _file_pieces(path, n=1 << 20):
    with open(path, "rb") as f:
        while True:
            b = f.read(n)
            if not b:
                return
            yield b


def _mb(n):
    return "%.1f" % (n / 1e6) if n < 1e8 else "{:,.0f}".format(n / 1e6)
