#!/usr/bin/env python3
"""Build -- and optionally publish -- the release the launcher downloads an update's files from (2026-11-28).

    python tools/build_release_files.py --out dist [--repo .] [--commit HEAD] [--tag files-2026-11-28]
    python tools/build_release_files.py --out dist --upload files-2026-11-28 --one-at-a-time    # needs gh, logged in

For one commit it writes, into --out:
    files-1.zip, files-2.zip, ...  the commit's files, read from git (not from the working tree), each zip under
                                   --max-asset bytes (GitHub refuses a release file of 2 GiB or more); a file whose
                                   content appears at several paths is stored once
    files-manifest.json            for every path: its git object id, size, zip, and the byte range of its data in
                                   that zip ("schema": 2), plus the commit -- see launcher/release_files.py

Entries are deflated (level 1) unless that saves under 5 % (already-compressed game files are stored as they are),
and every entry is compressed on its own, which is what lets the launcher fetch any one file by its byte range.
With --upload the release is made as a draft, the zips go up one at a time (--one-at-a-time deletes each after its
upload, so the disk holds the repository plus one zip), the manifest last, and only then is the release published,
as the repository's latest -- a launcher never sees a manifest naming a zip that is not there yet. Without --upload,
--tag names the release the files will be uploaded to by hand (the launcher reads it from the manifest).
The release workflow (.github/workflows/release-files.yml) runs this on GitHub's own machines.

Python 3.8+, standard library; git on the PATH; gh for --upload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
import time
import zipfile
import zlib

SCHEMA = 2
MANIFEST = "files-manifest.json"
MAX_ASSET = 1_900_000_000          # under GitHub's 2 GiB per release file, with room for the zip's own framing
STORE_IF_SAVES_UNDER = 0.05        # deflate only when it saves at least 5 %
SAMPLE = 1 << 20


def git(repo, *args, data=None):
    r = subprocess.run(["git", "-C", repo] + list(args), input=data, capture_output=True)
    if r.returncode:
        sys.exit("git %s: %s" % (" ".join(args[:2]), r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout


def tree(repo, commit):
    """[(path, oid, size)] of every file in commit, sorted by path (neighbours in a folder share a request)."""
    out = []
    for ent in git(repo, "ls-tree", "-r", "-l", "-z", "--full-tree", commit).split(b"\0"):
        if not ent:
            continue
        meta, _, path = ent.partition(b"\t")
        f = meta.split()
        if len(f) == 4 and f[1] == b"blob":
            out.append((path.decode("utf-8"), f[2].decode(), int(f[3])))
    return sorted(out)


class Blobs(object):
    """git cat-file --batch: one process for every object, each read in pieces."""

    def __init__(self, repo):
        self.p = subprocess.Popen(["git", "-C", repo, "cat-file", "--batch"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE)

    def read(self, oid):
        self.p.stdin.write(oid.encode() + b"\n")
        self.p.stdin.flush()
        hdr = self.p.stdout.readline().split()
        if len(hdr) != 3 or hdr[1] != b"blob":
            raise SystemExit("%s is not a blob in this repository: %r" % (oid, hdr))
        n = int(hdr[2])
        left = n
        while left:
            b = self.p.stdout.read(min(left, 1 << 20))
            if not b:
                raise SystemExit("git stopped in the middle of %s" % oid)
            left -= len(b)
            yield b
        self.p.stdout.read(1)               # the newline after each object

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(30)
        except Exception:
            pass


def method_for(first_piece):
    if not first_piece:
        return zipfile.ZIP_STORED
    c = zlib.compressobj(1, zlib.DEFLATED, -15)
    n = len(c.compress(first_piece[:SAMPLE]) + c.flush())
    return zipfile.ZIP_DEFLATED if n <= len(first_piece[:SAMPLE]) * (1 - STORE_IF_SAVES_UNDER) else zipfile.ZIP_STORED


def write_entry(zf, name, size, pieces):
    pieces = iter(pieces)
    first = next(pieces, b"")
    zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    zi.compress_type = method_for(first)
    zi.external_attr = 0o644 << 16
    zi.file_size = size                       # zipfile decides on zip64 from it
    if zi.compress_type == zipfile.ZIP_DEFLATED:
        zi._compresslevel = 1                 # zipfile reads it from here for ZipFile.open(..., "w")
    with zf.open(zi, "w") as w:
        if first:
            w.write(first)
        for b in pieces:
            w.write(b)


def data_offsets(path):
    """{entry name: (data offset, compressed size, method)} read back from the finished zip's local headers."""
    out = {}
    with zipfile.ZipFile(path) as zf, open(path, "rb") as f:
        for zi in zf.infolist():
            f.seek(zi.header_offset)
            hdr = f.read(30)
            if hdr[:4] != b"PK\x03\x04":
                raise SystemExit("bad local header for %s in %s" % (zi.filename, path))
            name_len, extra_len = struct.unpack("<HH", hdr[26:30])
            out[zi.filename] = (zi.header_offset + 30 + name_len + extra_len, zi.compress_size, zi.compress_type)
    return out


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def gh(*args):
    r = subprocess.run(["gh"] + list(args), capture_output=True)
    if r.returncode:
        raise SystemExit("gh %s: %s" % (" ".join(args[:2]), r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout.decode("utf-8", "replace")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="the repository (a checkout or a bare clone); default: here")
    ap.add_argument("--commit", default="HEAD", help="the commit to package (default HEAD)")
    ap.add_argument("--out", default="dist", help="output folder (default dist)")
    ap.add_argument("--max-asset", type=int, default=MAX_ASSET, help="bytes per zip at most")
    ap.add_argument("--tag", help="the release these files are for (default: --upload's tag)")
    ap.add_argument("--upload", metavar="TAG", help="publish as the GitHub release TAG of origin (needs gh)")
    ap.add_argument("--gh-repo", help="owner/name for gh (default: gh's own choice, origin)")
    ap.add_argument("--one-at-a-time", action="store_true", help="with --upload: delete each zip once uploaded")
    a = ap.parse_args(argv)

    commit = git(a.repo, "rev-parse", "--verify", a.commit + "^{commit}").decode().strip()
    files = tree(a.repo, commit)
    os.makedirs(a.out, exist_ok=True)
    ghr = ["--repo", a.gh_repo] if a.gh_repo else []
    if a.upload:
        title = "Patch files for %s" % commit[:10]
        notes = ("The files of commit %s for the launcher's download (launcher/release_files.py). Not an installer: "
                 "players update with the launcher." % commit)
        exists = subprocess.run(["gh", "release", "view", a.upload] + ghr, capture_output=True).returncode == 0
        if exists:
            gh("release", "edit", a.upload, "--draft", *ghr)
        else:
            gh("release", "create", a.upload, "--draft", "--title", title, "--notes", notes, "--target", commit, *ghr)

    manifest = {"schema": SCHEMA, "commit": commit, "release": a.upload or a.tag or "",
                "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "assets": {}, "files": {}}
    blobs = Blobs(a.repo)
    placed = {}                     # oid -> (asset, data offset, compressed size, method)
    n_asset, zf, zpath, names = 0, None, None, []

    def close_asset():
        nonlocal zf
        if zf is None:
            return
        zf.close()
        zf = None
        offs = data_offsets(zpath)
        aname = os.path.basename(zpath)
        for name in names:
            o, c, m = offs[name]
            placed[name_oid[name]] = (aname, o, c, m)
        manifest["assets"][aname] = {"size": os.path.getsize(zpath), "sha256": sha256_file(zpath)}
        print("  %s: %d files, %.1f MB" % (aname, len(names), os.path.getsize(zpath) / 1e6), flush=True)
        if a.upload:
            gh("release", "upload", a.upload, zpath, "--clobber", *ghr)
            if a.one_at_a_time:
                os.remove(zpath)

    name_oid = {}
    seen = set()
    print("%s: %d files, %.1f MB" % (commit[:10], len(files), sum(s for _p, _o, s in files) / 1e6), flush=True)
    for path, oid, size in files:
        if oid in seen:
            continue
        seen.add(oid)
        if size >= a.max_asset:
            sys.exit("%s is %d bytes: no release file may be that big" % (path, size))
        if zf is not None and os.path.getsize(zpath) + size + 1024 > a.max_asset:
            close_asset()
        if zf is None:
            n_asset += 1
            zpath = os.path.join(a.out, "files-%d.zip" % n_asset)
            zf = zipfile.ZipFile(zpath, "w", allowZip64=True)
            names = []
        name = path                         # the entry carries the first path with this content
        write_entry(zf, name, size, blobs.read(oid))
        zf.fp.flush()
        names.append(name)
        name_oid[name] = oid
    close_asset()
    blobs.close()

    for path, oid, size in files:
        aname, o, c, m = placed[oid]
        manifest["files"][path] = {"oid": oid, "size": size, "asset": aname, "offset": o, "csize": c, "method": m}
    mpath = os.path.join(a.out, MANIFEST)
    with open(mpath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, separators=(",", ":"), sort_keys=True)
    total = sum(x["size"] for x in manifest["assets"].values())
    print("%d paths, %d distinct files, %d zip(s), %.2f GB; manifest %.1f MB"
          % (len(files), len(seen), len(manifest["assets"]), total / 1e9, os.path.getsize(mpath) / 1e6))
    if a.upload:
        gh("release", "upload", a.upload, mpath, "--clobber", *ghr)
        gh("release", "edit", a.upload, "--draft=false", "--latest", *ghr)
        print("published %s" % a.upload)


if __name__ == "__main__":
    main()
