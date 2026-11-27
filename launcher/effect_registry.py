"""Every effect bank a version installs is registered in the Fnames/file_exist.htable that version installs.

WHY (INSTALL_SYNC, 2026-10-11; D:\\Development Log\\history.md entries i14-)
------------------------------------------------------------------------
The game decides whether a file exists from two baked tables, not from the disk. Fnames/file_exist.htable is the
one for effects (Fnames/filename.bin has no Effect/spfx rows): u32 count, then count pairs (crc(path), crc(folder)),
each the engine's CRC-32 seeded with the string's length, of the game-relative path with backslashes. "Unregistered
files are invisible" is the project's rule (PROJECT_MASTER_INDEX; ZANGETSU_MASTER_GUIDE section 7: V1.3 found
P039_zw1_00/zw2_00 on disk but not registered, and V1.2's whole white-effect pass had never loaded).

On 2026-10-11 eleven of Zangetsu's own banks (P005_Shot00, the SP2 evo effects, P005_tm_AtkEn_zan, ...) were in
no version's registry, nor were pl022's COM_sp_Atk_BY and P022_tm_PtlAura00 or V1.3's eleven Yumichika banks. Each
was added by hand, or by a tool that registered it in somebody's own game folder only, and the registry in the repo
was never told. A registry is a whole-roster file that nothing merges, so a missing row stays missing for everyone.

WHAT IT DOES
------------
A version's chain is itself and the versions its base.txt names, parent first. A launch installs the chain's
00HIGH/ and 01MIDDLE/ (and their Overlay/ copies) and, last, the Overlay/Fnames/file_exist.htable of the last chain
member that ships one. So the effect banks that htable must register are every <name>.vfxb / <name>.desktop.vfxt
under <tier>/Effect/ of every chain that ends with it. The missing ones are inserted after the last entry of their
own folder (appended when the folder has none) -- the grouping the tables already use; nothing else moves.

A path is hashed as the game spells it: 00HIGH / 01MIDDLE, Effect, spfx, then the folders and file as committed.

It only ever ADDS a registration. A registered file that is no longer shipped is left alone: that row is harmless,
while deciding that a row is stale needs the stock list, which a commit must not depend on. A chain that installs
banks but ships no table at all cannot be fixed here; --check names it.

USE
---
    python launcher/effect_registry.py --check     what is missing, from the working tree; exit 3 if anything is
    python launcher/effect_registry.py --fix       write the missing rows into the working tree's htables
    python launcher/effect_registry.py --commit    the pre-commit hook. Judges on the commit: the INDEX's files,
                                                   its base.txt and its tables. Each table it writes is printed, one
                                                   per line, right after it is written and read back (the hook stages
                                                   exactly those). A table that needs rows is not written when the
                                                   working tree's copy is not the index's (somebody's own edit) or
                                                   when this is a partial commit (git commit -- <paths> / --only):
                                                   then the last line printed is REFUSED. Exit 0 when all went well,
                                                   3 with REFUSED, 1 when something could not be done (said on stderr).
"""

from __future__ import annotations

import os
import re
import struct
import subprocess
import sys
import zlib

GV = "GameVersions"
TIERS = ("00HIGH", "01MIDDLE")
HTABLE = "Overlay/Fnames/file_exist.htable"
BANK = re.compile(r"[^.]+\.(?:vfxb|desktop\.vfxt)\Z", re.I)
REFUSED = 3
MARKER = "REFUSED"
_TOP = {"00high": "00HIGH", "01middle": "01MIDDLE"}


def game_hash(s):
    """The engine's file-name hash: reflected CRC-32 seeded with the length, no final xor."""
    b = s.encode("utf-8")
    return zlib.crc32(b, len(b) ^ 0xFFFFFFFF) ^ 0xFFFFFFFF


def canon(game_rel):
    """The game's spelling of a path under a tier: 00HIGH / 01MIDDLE, Effect, spfx (the exe builds
    '00HIGH/Effect/spfx/' + folder); the folders below and the file name as written."""
    p = game_rel.replace("\\", "/").split("/")
    if p and p[0].lower() in _TOP:
        p[0] = _TOP[p[0].lower()]
        if len(p) > 1 and p[1].lower() == "effect":
            p[1] = "Effect"
            if len(p) > 2 and p[2].lower() == "spfx":
                p[2] = "spfx"
    return "/".join(p)


def key(game_rel):
    p = canon(game_rel).replace("/", "\\")
    return game_hash(p), game_hash(p.rsplit("\\", 1)[0] if "\\" in p else "")


def parse(raw):
    n = struct.unpack_from("<I", raw, 0)[0] if len(raw) >= 4 else -1
    if n < 0 or 4 + 8 * n != len(raw):
        raise ValueError("not a file_exist.htable (%d bytes)" % len(raw))
    return list(struct.iter_unpack("<II", raw[4:]))


def emit(entries):
    return struct.pack("<I", len(entries)) + b"".join(struct.pack("<II", a, b) for a, b in entries)


def insert(entries, game_rels):
    """(new entries, [game rels added]): each missing row after the last row of its own folder, else at the end."""
    have = set(entries)
    pending, added = {}, []
    for g in sorted(game_rels):
        k = key(g)
        if k in have:
            continue
        have.add(k)
        pending.setdefault(k[1], []).append(k)
        added.append(g)
    last = {}
    for i, e in enumerate(entries):
        last[e[1]] = i
    out = []
    for i, e in enumerate(entries):
        out.append(e)
        if last.get(e[1]) == i and e[1] in pending:
            out.extend(pending.pop(e[1]))
    for g in added:                                   # folders the table had no row of, in path order
        rows = pending.pop(key(g)[1], None)
        if rows:
            out.extend(rows)
    return out, added


# ------------------------------------------------------------------ what each version installs
def _split(path):
    """GameVersions/<v>/[Overlay/]<tier>/Effect/.../<bank file> -> (v, game rel as the game spells it) or None."""
    p = path.replace("\\", "/").split("/")
    if len(p) < 6 or p[0] != GV:
        return None
    v, rest = p[1], p[2:]
    if rest[0].lower() == "overlay":
        rest = rest[1:]
    if len(rest) < 4 or rest[0].lower() not in _TOP or rest[1].lower() != "effect" or not BANK.match(rest[-1]):
        return None
    return v, canon("/".join(rest))


def _scan(files):
    own, versions, tables = {}, {}, set()
    for f in files:
        p = f.replace("\\", "/").split("/")
        if len(p) > 2 and p[0] == GV:
            versions.setdefault(p[1].lower(), p[1])
            if "/".join(p[2:]).lower() == HTABLE.lower():
                tables.add(p[1])
        s = _split(f)
        if s:
            own.setdefault(s[0], set()).add(s[1])
    return own, versions, tables


def _chain(v, base_of, versions):
    """[root, ..., v]: base.txt names a parent folder (matched without regard to case or a trailing separator, as
    Windows does); a name that is no folder, or a loop, ends the chain."""
    chain, seen, c = [], set(), v
    while c and c.lower() not in seen:
        seen.add(c.lower())
        chain.insert(0, c)
        b = base_of(c)
        b = b.strip().rstrip("/\\").strip() if b else None
        c = versions.get(b.lower()) if b else None
    return chain


def plan(files, base_of):
    """files: repo-relative paths (forward slashes). base_of(v) -> the text of v's base.txt, or None.
    -> {htable repo path: sorted game rels that must be registered in it}."""
    own, versions, tables = _scan(files)
    need = {}
    for v in sorted(versions.values()):
        chain = _chain(v, base_of, versions)
        owner = next((c for c in reversed(chain) if c in tables), None)
        if owner is None:
            continue
        req = need.setdefault("%s/%s/%s" % (GV, owner, HTABLE), set())
        for c in chain:
            req |= own.get(c, set())
    return {t: sorted(r) for t, r in need.items()}


def untabled(files, base_of):
    """{version: number of effect bank files its chain installs} for every chain that ships no table at all: the
    game then keeps whatever registry an earlier launch left, and nothing here can register those banks."""
    own, versions, tables = _scan(files)
    out = {}
    for v in sorted(versions.values()):
        chain = _chain(v, base_of, versions)
        if any(c in tables for c in chain):
            continue
        n = sum(len(own.get(c, ())) for c in chain)
        if n:
            out[v] = n
    return out


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _write(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def missing(base_dir, files, base_of, read=None):
    """{htable repo path: [game rels not registered]} (only the tables that miss something). read(t) -> the table's
    bytes; the working tree's copy by default. Raises on a table it cannot read."""
    read = read or (lambda t: _read(os.path.join(base_dir, *t.split("/"))))
    out = {}
    for t, req in plan(files, base_of).items():
        rows = set(parse(read(t)))
        gone = [g for g in req if key(g) not in rows]
        if gone:
            out[t] = gone
    return out


def fix(base_dir, files, base_of, writable=lambda t: True, read=None, on_written=None):
    """Register what is missing, table by table: judged on read(t) (see missing()), written into the working tree's
    copy when writable(t), read back, then reported through on_written(t, added) before the next table is touched.
    One table that cannot be read or written does not stop the others.
    -> ({table: [added]}, [tables that need rows but were held back], [(table, error)])."""
    read = read or (lambda t: _read(os.path.join(base_dir, *t.split("/"))))
    done, held, errors = {}, [], []
    for t, req in sorted(plan(files, base_of).items()):
        try:
            rows = set(parse(read(t)))
            gone = [g for g in req if key(g) not in rows]
            if not gone:
                continue
            if not writable(t):
                held.append(t)
                continue
            path = os.path.join(base_dir, *t.split("/"))
            entries, added = insert(parse(_read(path)), gone)
            _write(path, emit(entries))
            if parse(_read(path)) != entries:
                raise IOError("did not read back as written")
        except Exception as e:
            errors.append((t, "%s: %s" % (type(e).__name__, e)))
            continue
        done[t] = added
        if on_written:
            on_written(t, added)
    return done, held, errors


# ------------------------------------------------------------------ the two views of the repo
def worktree_files(base_dir):
    out = []
    root = os.path.join(base_dir, GV)
    for d, _dirs, names in os.walk(root):
        rel = os.path.relpath(d, base_dir).replace(os.sep, "/")
        out.extend("%s/%s" % (rel, n) for n in names)
    return out


def base_reader(base_dir):
    def base_of(v):
        try:
            with open(os.path.join(base_dir, GV, v, "base.txt"), "r", encoding="utf-8") as f:
                return f.read().strip() or None
        except OSError:
            return None
    return base_of


def _git(base_dir, *args):
    return subprocess.run(["git", "--literal-pathspecs"] + list(args), cwd=base_dir, capture_output=True)


def index_files(base_dir):
    r = _git(base_dir, "ls-files", "-z", "--", GV)
    if r.returncode:
        raise RuntimeError("git ls-files failed: %s" % r.stderr.decode("utf-8", "replace").strip())
    return [p for p in r.stdout.decode("utf-8", "replace").split("\0") if p]


def index_reader(base_dir):
    """read(t) for missing()/fix(): the table as the commit will carry it."""
    def read(t):
        r = _git(base_dir, "show", ":" + t)
        if r.returncode:
            raise RuntimeError("git show :%s failed: %s" % (t, r.stderr.decode("utf-8", "replace").strip()))
        return r.stdout
    return read


def index_base_reader(base_dir):
    """base_of(v) for the commit: the base.txt the index holds, not an unstaged or untracked one."""
    cache = {}

    def base_of(v):
        if v not in cache:
            r = _git(base_dir, "show", ":%s/%s/base.txt" % (GV, v))
            cache[v] = r.stdout.decode("utf-8", "replace").strip() or None if r.returncode == 0 else None
        return cache[v]
    return base_of


def same_as_index(base_dir, t):
    """True when the working tree's copy of t holds exactly the index's bytes (a mode-only difference is not an
    edit: compared by content, not by `git diff`)."""
    a = _git(base_dir, "hash-object", "--", t)
    b = _git(base_dir, "rev-parse", ":" + t)
    return a.returncode == 0 and b.returncode == 0 and a.stdout.strip() == b.stdout.strip()


def _partial_commit():
    """git commit -- <paths> / --only builds the commit in a temporary index (.git/next-index-*.lock): a table staged
    there reaches the commit but not the real index, which then holds a staged reversal of the rows."""
    return os.path.basename(os.environ.get("GIT_INDEX_FILE", "")).startswith("next-index-")


def _main(argv):
    mode = argv[1] if len(argv) > 1 else ""
    if mode not in ("--check", "--fix", "--commit"):
        print(__doc__)
        return 2
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if mode == "--commit":
        files = index_files(base)
        partial = _partial_commit()

        def wrote(t, added):
            print(t, flush=True)
            print("   registry: %d effect file(s) registered in %s (first: %s)" % (len(added), t, added[0]),
                  file=sys.stderr)
        done, held, errors = fix(base, files, index_base_reader(base),
                                 writable=lambda t: not partial and same_as_index(base, t),
                                 read=index_reader(base), on_written=wrote)
        for t in held:
            print("   registry: %s needs rows for effect banks this commit ships, and %s" % (t, (
                "this is a partial commit (git commit -- <paths> / --only), which cannot carry it: commit "
                "without naming paths" if partial else
                "it holds edits of its own that are not staged: stage or discard them")), file=sys.stderr)
        for t, e in errors:
            print("   registry: %s could not be checked or written (%s)" % (t, e), file=sys.stderr)
        if held:
            print(MARKER, flush=True)
            return REFUSED
        return 1 if errors else 0
    files = worktree_files(base)
    base_of = base_reader(base)
    if mode == "--check":
        gone = missing(base, files, base_of)
        for t, g in sorted(gone.items()):
            print("%s: %d not registered" % (t, len(g)))
            for x in g:
                print("   " + x)
        for v, n in sorted(untabled(files, base_of).items()):
            print("not checked: %s installs %d effect bank file(s) and ships no %s anywhere in its chain (the game "
                  "keeps whatever registry an earlier launch left)" % (v, n, HTABLE))
        if not gone:
            print("every effect bank a version with a registry installs is registered")
        return REFUSED if gone else 0
    done, _held, errors = fix(base, files, base_of)
    for t, added in sorted(done.items()):
        print("%s: +%d" % (t, len(added)))
    for t, e in errors:
        print("%s: NOT FIXED (%s)" % (t, e))
    if not done and not errors:
        print("nothing to register")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
