"""Content delivery: work out what changed, download only that.

The patch used to arrive as a git clone -- 5.5 GB of content plus 2.4 GB of
history, for a player who wants to run one game version. Releases replace
that, but a release full of 1.4 GB zips is only an improvement for a first
install; re-downloading one because six files changed would be worse than
the git pull it replaced.

So a release also publishes a content manifest: every file it contains,
with its hash and the exact byte range it occupies inside its asset zip.
The launcher hashes what is on disk, diffs against the manifest, and
range-fetches just the entries that differ. A balance tweak touching four
.fsv files is a few hundred kilobytes, not 1.4 GB.

Two properties fall out of doing it this way rather than shipping
release-to-release patch files:

  * Repair and update are the same operation. A player whose files were
    corrupted, or who deleted something, or who skipped nine releases, all
    converge on "make local match the manifest" with no special casing and
    no chain of intermediate patches to walk.
  * Nothing has to be built per release-pair. The manifest describes a
    state, not a transition.

Falls back to whole-asset download when the diff is large enough that
per-file requests stop paying for themselves -- see plan_update().
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field
from pathlib import Path

USER_AGENT = "BrosCommunityPatchLauncher/2"

# Past this share of an asset's bytes, one request for the whole zip beats
# thousands of range requests -- fewer round trips, and the CDN streams a
# single large response far faster than it serves many small ones. Tuned to
# the shape of the content here: a typical balance release touches a
# handful of files, while a new game version touches all of them.
WHOLE_ASSET_BYTE_RATIO = 0.40
# Independently of size, a diff spread across this many files is a
# whole-asset download regardless -- per-request overhead dominates long
# before the byte ratio would trip.
WHOLE_ASSET_FILE_COUNT = 400

CHUNK = 1 << 20


# ---------------------------------------------------------------------
#  manifest
# ---------------------------------------------------------------------
@dataclass
class FileEntry:
    """One file in a release, and where its bytes live in the asset zip."""

    path: str          # repo-relative, forward slashes
    size: int
    sha256: str
    asset: str         # which release asset holds it
    offset: int        # byte offset of the entry DATA (past the local header)
    csize: int         # compressed size on the wire
    method: int        # 0 = stored, 8 = deflate

    @classmethod
    def from_json(cls, path, d):
        return cls(path, d["size"], d["sha256"], d["asset"],
                   d["offset"], d["csize"], d["method"])


@dataclass
class Manifest:
    release: str = ""
    files: dict = field(default_factory=dict)    # path -> FileEntry
    assets: dict = field(default_factory=dict)   # name -> {size, sha256, url}

    @classmethod
    def loads(cls, raw) -> "Manifest":
        d = json.loads(raw)
        if d.get("schema") != 1:
            raise ValueError(f"unsupported manifest schema {d.get('schema')!r}")
        m = cls(release=d.get("release", ""), assets=d.get("assets", {}))
        m.files = {p: FileEntry.from_json(p, e) for p, e in d["files"].items()}
        return m

    def bytes_in_asset(self, asset: str) -> int:
        """Uncompressed total -- what this asset's files occupy on disk."""
        return sum(f.size for f in self.files.values() if f.asset == asset)

    def file_count(self, asset: str) -> int:
        return sum(1 for f in self.files.values() if f.asset == asset)

    def download_size(self, asset: str) -> int:
        """What fetching this whole asset costs on the wire.

        The zip's own size when the manifest carries it, otherwise the sum
        of the compressed entry sizes. Must never be mixed with
        bytes_in_asset(): comparing a compressed delta against an
        uncompressed total makes a well-compressing asset look like a
        cheap delta no matter how much of it changed.
        """
        declared = self.assets.get(asset, {}).get("size")
        if declared:
            return int(declared)
        return sum(f.csize for f in self.files.values() if f.asset == asset)


# ---------------------------------------------------------------------
#  local state
# ---------------------------------------------------------------------
class HashCache:
    """Remembers file hashes so a launch does not re-read 5.5 GB.

    Keyed on (size, mtime_ns): if either moved, the cached hash is stale
    and the file is read again. That is the same assumption every build
    system makes, and the failure mode -- a file edited within the same
    nanosecond stamp and identical length -- cannot be produced by the
    things that actually write here (our own downloader, git, an
    extractor), all of which move mtime.
    """

    def __init__(self, path):
        self.path = Path(path)
        self._d = {}
        self._dirty = False
        try:
            with open(self.path, encoding="utf-8") as f:
                self._d = json.load(f)
        except Exception:
            self._d = {}

    def get(self, rel: str, size: int, mtime_ns: int):
        e = self._d.get(rel)
        if e and e[0] == size and e[1] == mtime_ns:
            return e[2]
        return None

    def put(self, rel: str, size: int, mtime_ns: int, digest: str):
        self._d[rel] = [size, mtime_ns, digest]
        self._dirty = True

    def drop(self, rel: str):
        if self._d.pop(rel, None) is not None:
            self._dirty = True

    def save(self):
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._d, f)
        os.replace(tmp, self.path)
        self._dirty = False


def sha256_file(path, chunk=CHUNK) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def diff_local(base_dir, manifest: Manifest, cache: HashCache,
               only_assets=None, progress=None) -> list:
    """Which manifest files are missing or wrong on disk?

    Size is checked before hashing, which settles the overwhelming majority
    of files for the cost of a stat. Only same-size candidates are read,
    and the cache means even those are usually read once ever.
    """
    base_dir = Path(base_dir)
    out = []
    total = len(manifest.files)
    for i, (rel, entry) in enumerate(manifest.files.items()):
        if only_assets and entry.asset not in only_assets:
            continue
        if progress and (i % 500 == 0):
            progress(i, total, rel)

        p = base_dir / rel
        try:
            st = p.stat()
        except OSError:
            out.append(entry)
            cache.drop(rel)
            continue
        if st.st_size != entry.size:
            out.append(entry)
            cache.drop(rel)
            continue

        digest = cache.get(rel, st.st_size, st.st_mtime_ns)
        if digest is None:
            try:
                digest = sha256_file(p)
            except OSError:
                out.append(entry)
                continue
            cache.put(rel, st.st_size, st.st_mtime_ns, digest)
        if digest != entry.sha256:
            out.append(entry)
    if progress:
        progress(total, total, "")
    return out


# ---------------------------------------------------------------------
#  planning
# ---------------------------------------------------------------------
@dataclass
class AssetPlan:
    asset: str
    whole: bool                       # download the entire asset and extract
    files: list = field(default_factory=list)   # FileEntry, when not whole
    wire_bytes: int = 0

    def describe(self) -> str:
        how = "full asset" if self.whole else f"{len(self.files)} file(s)"
        return f"{self.asset}: {how}, {self.wire_bytes / 1e6:.1f} MB"


@dataclass
class UpdatePlan:
    assets: list = field(default_factory=list)

    @property
    def wire_bytes(self) -> int:
        return sum(a.wire_bytes for a in self.assets)

    @property
    def file_count(self) -> int:
        return sum(len(a.files) for a in self.assets)

    def __bool__(self):
        return bool(self.assets)

    def describe(self) -> str:
        if not self.assets:
            return "already up to date"
        return (f"{self.wire_bytes / 1e6:.1f} MB to download\n  "
                + "\n  ".join(a.describe() for a in self.assets))


def plan_update(manifest: Manifest, stale: list) -> UpdatePlan:
    """Group the stale files by asset and decide how to fetch each group."""
    by_asset = {}
    for e in stale:
        by_asset.setdefault(e.asset, []).append(e)

    plan = UpdatePlan()
    for asset, files in sorted(by_asset.items()):
        # Both sides of this comparison are wire bytes. Compressed delta
        # against the compressed asset -- see Manifest.download_size().
        whole_cost = manifest.download_size(asset)
        delta_cost = sum(f.csize for f in files)
        in_asset = manifest.file_count(asset)

        whole = (
            # Needing every file in the asset is the from-scratch install.
            # Checked first and on its own: with many small entries the zip's
            # own framing outweighs the compressed data, so delta_cost can
            # land under the ratio even when nothing is being reused.
            len(files) >= in_asset
            or len(files) >= WHOLE_ASSET_FILE_COUNT
            or (whole_cost > 0 and delta_cost >= whole_cost * WHOLE_ASSET_BYTE_RATIO)
        )
        plan.assets.append(AssetPlan(asset, whole, [] if whole else files,
                                     whole_cost if whole else delta_cost))
    return plan


# ---------------------------------------------------------------------
#  transfer
# ---------------------------------------------------------------------
_explicit_token = ""


def set_token(t: str) -> None:
    """Use this token for subsequent requests, or "" to stop sending one.

    Set around a private-channel operation and cleared afterwards, so a dev
    channel's credential is not attached to unrelated requests. Takes
    precedence over the environment, which is what tools and CI use.
    """
    global _explicit_token
    _explicit_token = (t or "").strip()


def token() -> str:
    """The token to authenticate with, if there is one.

    Only needed for a private repository -- a public release needs none, and
    players on the stable channel will never have one. Development and
    staging repos are usually private, though, so without this the whole
    pipeline is untestable before it goes public.
    """
    return (_explicit_token
            or os.environ.get("GH_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or "")


class _StripAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Drop Authorization when a redirect crosses to another host.

    GitHub answers an authenticated asset download with a 302 to its CDN,
    and the CDN URL carries its own signed credentials in the query string.
    Forwarding our Authorization header there makes the request carry two
    competing auth mechanisms, which the CDN rejects outright. urllib
    preserves headers across redirects by default, so it has to be removed
    deliberately.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            if urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
                for k in [h for h in new.headers if h.lower() == "authorization"]:
                    del new.headers[k]
        return new


_opener = urllib.request.build_opener(_StripAuthOnRedirect)

# Accept is set per call rather than globally: the releases API must be
# asked for JSON, while an asset fetched through the API returns its
# metadata as JSON unless octet-stream is requested instead.
ACCEPT_JSON = "application/vnd.github+json"
ACCEPT_BINARY = "application/octet-stream"


def _open(url, headers=None, timeout=60):
    h = {"User-Agent": USER_AGENT, **(headers or {})}
    tok = token()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, headers=h)
    return _opener.open(req, timeout=timeout)


def http_get(url, timeout=60, accept=ACCEPT_BINARY) -> bytes:
    with _open(url, {"Accept": accept}, timeout=timeout) as r:
        return r.read()


def fetch_range(url, offset: int, length: int, timeout=60) -> bytes:
    """Fetch exactly [offset, offset+length). Raises if the server ignores it.

    A server that does not honour Range answers 200 with the whole body
    instead of 206 with a slice. Silently accepting that would mean pulling
    1.4 GB while believing we asked for 8 KB, so it is treated as an error
    and the caller falls back to a whole-asset download deliberately.
    """
    end = offset + length - 1
    with _open(url, {"Range": f"bytes={offset}-{end}", "Accept": ACCEPT_BINARY}, timeout) as r:
        if r.status != 206:
            raise urllib.error.URLError(f"range not honoured (HTTP {r.status})")
        data = r.read()
    if len(data) != length:
        raise urllib.error.URLError(f"short range read: {len(data)} != {length}")
    return data


def _inflate(data: bytes, method: int) -> bytes:
    if method == 0:
        return data
    if method == 8:
        # -15: raw deflate, no zlib wrapper. Zip entries are each compressed
        # independently, which is exactly what makes per-entry fetching work.
        return zlib.decompressobj(-15).decompress(data)
    raise ValueError(f"unsupported zip compression method {method}")


def write_atomic(dest: Path, data: bytes):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)


def apply_plan(base_dir, manifest: Manifest, plan: UpdatePlan,
               asset_url, progress=None, log=print) -> int:
    """Carry out the plan. Returns the number of files written.

    asset_url(name) -> download URL for that release asset.
    progress(done_bytes, total_bytes, label) is called as work completes.
    """
    base_dir = Path(base_dir)
    done_bytes = 0
    total = plan.wire_bytes or 1
    written = 0

    for ap in plan.assets:
        url = asset_url(ap.asset)
        if url is None:
            raise FileNotFoundError(f"release has no asset named {ap.asset!r}")

        if not ap.whole:
            try:
                for e in ap.files:
                    raw = fetch_range(url, e.offset, e.csize)
                    data = _inflate(raw, e.method)
                    if len(data) != e.size:
                        raise ValueError(f"{e.path}: expected {e.size} bytes, got {len(data)}")
                    if hashlib.sha256(data).hexdigest() != e.sha256:
                        raise ValueError(f"{e.path}: hash mismatch after download")
                    write_atomic(base_dir / e.path, data)
                    written += 1
                    done_bytes += e.csize
                    if progress:
                        progress(done_bytes, total, e.path)
                continue
            except (urllib.error.URLError, OSError) as ex:
                # Most likely the CDN declined the range request. Falling
                # back is the whole reason ranges are attempted optimis-
                # tically rather than probed for first.
                log(f"[update] per-file fetch failed for {ap.asset} ({ex}); "
                    f"falling back to the full asset")
                ap = AssetPlan(ap.asset, True, [], manifest.download_size(ap.asset))

        written += _download_and_extract(
            base_dir, manifest, ap, url,
            lambda n, label: progress(done_bytes + n, total, label) if progress else None,
        )
        done_bytes += ap.wire_bytes

    return written


def _download_and_extract(base_dir, manifest: Manifest, ap: AssetPlan, url, progress) -> int:
    """Stream a whole asset to a temp file, then extract the files it owns.

    Only the paths the manifest attributes to this asset are written, so a
    zip that happens to carry anything else cannot place files outside the
    set we published -- and neither can a crafted path inside it.
    """
    import tempfile
    import zipfile

    owned = {p: e for p, e in manifest.files.items() if e.asset == ap.asset}
    fd, tmp_path = tempfile.mkstemp(prefix="brospatch-", suffix=".zip")
    os.close(fd)
    try:
        with _open(url, {"Accept": ACCEPT_BINARY}, timeout=120) as r, open(tmp_path, "wb") as out:
            got = 0
            while True:
                b = r.read(CHUNK)
                if not b:
                    break
                out.write(b)
                got += len(b)
                if progress:
                    progress(got, ap.asset)

        expect = manifest.assets.get(ap.asset, {}).get("sha256")
        if expect and sha256_file(tmp_path) != expect:
            raise ValueError(f"{ap.asset}: downloaded asset failed its checksum")

        written = 0
        with zipfile.ZipFile(tmp_path) as zf:
            for name in zf.namelist():
                entry = owned.get(name)
                if entry is None:
                    continue          # not ours to place
                with zf.open(name) as src:
                    data = src.read()
                if hashlib.sha256(data).hexdigest() != entry.sha256:
                    raise ValueError(f"{name}: hash mismatch inside {ap.asset}")
                write_atomic(Path(base_dir) / name, data)
                written += 1
        return written
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------
#  GitHub releases
# ---------------------------------------------------------------------
GITHUB_API = "https://api.github.com/repos/{repo}/releases"


@dataclass
class Release:
    tag: str
    name: str
    prerelease: bool
    assets: dict = field(default_factory=dict)   # name -> {url, size}

    @property
    def title(self) -> str:
        """Something to call this release in a message.

        A draft has no tag yet -- the tag is created when it is published --
        so falling back to its name keeps "Dev: " from appearing where a
        version was meant to be.
        """
        return self.tag or self.name or "(untitled draft)"

    def url_for(self, asset_name):
        a = self.assets.get(asset_name)
        return a["url"] if a else None


def repo_accessible(repo: str, timeout=20) -> bool:
    """Can we read this repository at all, with whatever token is set?

    Needed because /releases/latest answers 404 to BOTH "you cannot see this
    repository" and "it exists but has published nothing" -- and for a
    private channel those must not be confused. Treating no-access as
    no-releases would let a missing or expired token look like a successful
    connection to an empty channel, and the launcher would cheerfully
    install nothing at all.

    /repos/{owner}/{name} has no such ambiguity: 200 means readable.
    """
    try:
        with _open(f"https://api.github.com/repos/{repo}",
                   {"Accept": ACCEPT_JSON}, timeout) as r:
            return r.status == 200
    except urllib.error.HTTPError:
        return False
    except Exception:
        # A network failure is not an access answer; say nothing rather than
        # reporting a denial the caller would show as "bad token".
        raise


class NoReleases(LookupError):
    """The repository exists but has published nothing yet.

    Worth its own type because it is not a network failure and must not be
    reported as one -- it is exactly what every install sees between this
    code landing and the first release being tagged, and "check your
    internet connection" would be actively misleading advice.
    """


def latest_release(repo: str, include_prerelease=False, timeout=20) -> Release:
    """Newest published release for owner/name."""
    try:
        if include_prerelease:
            data = json.loads(http_get(GITHUB_API.format(repo=repo) + "?per_page=10",
                                       timeout, ACCEPT_JSON))
            if not data:
                raise NoReleases(f"{repo} has no published releases yet")
            d = data[0]
        else:
            d = json.loads(http_get(GITHUB_API.format(repo=repo) + "/latest", timeout, ACCEPT_JSON))
    except urllib.error.HTTPError as e:
        # GitHub answers 404 both for "no repo" and "no releases". The repo
        # is ours, so in practice this is always the latter.
        if e.code == 404:
            if not token():
                raise NoReleases(
                    f"{repo} returned 404. If it is private, set GH_TOKEN to a "
                    f"token with 'repo' scope; otherwise it has published "
                    f"nothing yet") from None
            raise NoReleases(f"{repo} has no published releases yet") from None
        raise
    return Release(
        tag=d.get("tag_name", ""),
        name=d.get("name", ""),
        prerelease=bool(d.get("prerelease")),
        assets={a["name"]: {"url": a["url"] if token() else a["browser_download_url"],
                            "browser_url": a["browser_download_url"],
                            "size": a["size"]}
                for a in d.get("assets", [])},
    )


MANIFEST_ASSET = "content-manifest.json"


def fetch_manifest(release: Release, timeout=30) -> Manifest:
    url = release.url_for(MANIFEST_ASSET)
    if not url:
        raise LookupError(f"release {release.tag} has no {MANIFEST_ASSET}")
    m = Manifest.loads(http_get(url, timeout))
    # The manifest names assets; the release knows their URLs. Joining them
    # here means the rest of the code never has to care where a file came
    # from, only which asset owns it.
    for name, meta in m.assets.items():
        a = release.assets.get(name)
        if a:
            meta["url"] = a["url"]
            meta.setdefault("size", a["size"])
    return m


# ---------------------------------------------------------------------
#  installed-version stamp
# ---------------------------------------------------------------------
STAMP_NAME = "installed.json"


def read_stamp(runtime_dir) -> dict:
    try:
        with open(Path(runtime_dir) / STAMP_NAME, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_stamp(runtime_dir, release_tag: str, assets_present) -> None:
    """Record what is installed.

    Advisory only -- diff_local() is the source of truth, and it looks at
    the files themselves. The stamp exists so the common "nothing changed"
    case can skip the scan entirely.
    """
    p = Path(runtime_dir)
    p.mkdir(parents=True, exist_ok=True)
    tmp = p / (STAMP_NAME + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"release": release_tag,
                   "assets": sorted(assets_present),
                   "stamped": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=1)
    os.replace(tmp, p / STAMP_NAME)


def free_space(path) -> int:
    try:
        return shutil.disk_usage(str(path)).free
    except OSError:
        return -1
