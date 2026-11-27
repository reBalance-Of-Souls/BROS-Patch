"""Thin layers on ReBalance of Souls V2.0: every layer keeps its parent's rows in its own copies of the shared tables.

THE MODEL (Berg, 2026-11-01: inheritance from V1.5 -- "all a dev has to do is push changes onto [it] to get said
changes for everyone, but they would be able to add changes to a specific version ... if they want it to be exclusive
to it"; V1.6 (was V1.2) carries Orihime, V1.7 (was V1.3) inherits from V1.6 and adds Yumichika)
-------------------------------------------------------------------------------------------------------------------
    ReBalance of Souls V2.0            the root: the balance, every feature, Zangetsu, the Reborn
    ReBalance of Souls V1.6            a layer over V1.5 (base.txt + inherit.json): Orihime, and V1.6's own changes
    ReBalance of Souls V1.7            a layer over V1.6 (base.txt + inherit.json): Yumichika, and V1.7's own changes

A launch installs the chain from its root (the launcher's version_chain): every root folder of the chain first, then
every Overlay, parents first. A file a layer does not have is its parent's, so a change pushed to V1.5 reaches V1.6
and V1.7 by itself. A file a layer has is that layer's own -- its character's files, or a file changed for that
version alone.

The exception is a SHARED TABLE: a file that lists every character (CharaSelect, CharaStatus and the other Script
tables, CommonText, the registries, the icon atlases, the select voice banks ...). A layer must ship its own copy to
add its character's rows, and that copy would hide every later change to the parent's. So such a copy is kept as the
parent's rows plus the layer's own, A ROW AT A TIME:

    the layer's row equals what the parent last gave it    -> it becomes the parent's row of today
    the layer's row differs from what the parent last gave -> the layer's own change: kept, never overwritten
    a row only the layer has                               -> kept, where the layer has it
    a new row of the parent's                              -> added, after the row it follows in the parent
    a row the parent dropped, unchanged in the layer       -> dropped too
    a row the layer dropped                                -> stays dropped

"What the parent last gave" is remembered per layer and per file in GameVersions/<layer>/inherit_state/ (one .txt per
shared file: the parent's md5, then one sorted line per row -- a hash of its key and a hash of its bytes). That memory
is what tells a row the parent changed from a row somebody changed in the layer, with no list of exceptions to keep by
hand. Without a memory (a new layer, a deleted state file) the parent's rows of today stand in for it: nothing that
differs is changed, and no row is added -- so a new layer is built from its parent's current files and synced once,
and its state files are committed with it.

A file both have that no row codec reads is compared whole, the same way: the layer's copy follows the parent's only
while it is an unchanged copy of what the parent last had.

Layers are processed parents first (V1.6 before V1.7), so one run carries a V1.5 change through V1.6 into V1.7.

FILES
-----
    GameVersions/<layer>/inherit.json    {"parent": "<version folder>"}: makes the folder a layer; must name the same
                                         folder as its base.txt
    GameVersions/<layer>/base.txt        the install chain (the launcher reads it)
    GameVersions/<layer>/inherit_state/  the memory, written here and committed with the layer; never installed (a
                                         launch copies a version's Script, Motion, 00HIGH, 01MIDDLE and Overlay only)

ROW CODECS (each reads and rebuilds the shipped files byte for byte: launcher/tests/test_version_inherit.py)
    cso      encoded tables (.fsv, .tbl): rows keyed by their first column; rebuilt with the layer's own key
    chsel    Script/CharaSelect.bin: three count-prefixed blocks of named records (the order of block 0 is the grid's)
    icons    Script/icon_list.bin: 96-byte records by name
    strings  PZZE string tables under Text/: version-3 records by key; rebuilt at the file's own zlib level
    atlas    ui/swap region atlases: a changed region is appended (256-aligned) and re-pointed, every other byte kept;
             a changed list of regions only in a file of the canonical layout (rebuilt), else left and said
    htable   Fnames/file_exist.htable: the set of (crc(path), crc(folder)) rows
    fnames   Fnames/filename.bin: the set of (group, folder, basename, extension, logical name) entries
    wwise    Wwise banks: HIRC objects and media by id (media laid out sorted, 16-aligned)
    whole    anything else both have

WHAT IT NEVER DOES
------------------
  - It never writes into a parent, never touches a file the layer does not have, never deletes a file.
  - It never writes over a layer file with unstaged changes of its own (unless force=True): held back and said.
  - It never writes bytes that already agree, and never merges a git-LFS placeholder.
  - It never guesses: a table that does not parse, or a merge that does not read back as merged, is left as it is
    and said, and its memory is not advanced (so the next run says it again).

WHERE IT RUNS
-------------
  - .githooks/pre-commit (--hook): a commit that changes a parent carries its layers in the same commit, decided from
    the index. A layer file or memory that an earlier run (a launch) already merged is staged as it is; one with
    unstaged edits of somebody's own is held back and said; a parent copy with unstaged changes that a layer would
    take refuses the commit (exit 3, "REFUSED"), checked before anything is written.
  - every launcher, after the pull and before the injection (sync_quietly). A player's tree is reset at every
    update, so what a launch writes there lasts until the next one.
  - by hand:  python launcher/version_inherit.py [--dry-run] [--child <layer>]
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import subprocess
import zlib

MANIFEST_NAME = "inherit.json"
BASE_NAME = "base.txt"
STATE_DIR = "inherit_state"
STATE_FORMAT = "1"
_SLOTS = ("script", "motion", "00high", "01middle")     # what launch() copies from a version's root (injectFolder)
_LFS_MAGIC = b"version https://git-lfs.github.com/spec/"

# The launcher's own rule for what is never installed (launcher/install_guard.excluded): dev leftovers and effect-bank
# strays. Loaded the way install_guard loads layers.py; the fallback is install_guard's own list.
try:
    from launcher.install_guard import excluded as _guard_excluded
except Exception:                                   # run as a script from inside launcher/, or an older checkout
    try:
        from install_guard import excluded as _guard_excluded
    except Exception:
        _guard_excluded = None
_FALLBACK_EXACT = {"thumbs.db", "desktop.ini", ".gitkeep", ".gitignore", ".ds_store"}
_FALLBACK_PATTERNS = (re.compile(r"\.bak$", re.I), re.compile(r"_bak$", re.I), re.compile(r"\s\(\d+\)\.", re.I),
                      re.compile(r"\.(bat|py)(\s|$)", re.I))


def _excluded(game_rel):
    if _guard_excluded is not None:
        try:
            return bool(_guard_excluded(game_rel))
        except Exception:
            pass
    name = game_rel.rsplit("/", 1)[-1]
    return name.lower() in _FALLBACK_EXACT or any(p.search(name) for p in _FALLBACK_PATTERNS)


# ======================================================================================================================
# small helpers
# ======================================================================================================================

def _md5(b):
    return hashlib.md5(b).hexdigest()


def _kh(key):
    """a row key's hash in the memory"""
    return hashlib.md5(key.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _vh(value):
    """a row's hash in the memory ("" for the rows of a set, which are only keys)"""
    return "" if value is None else hashlib.md5(value).hexdigest()[:16]


def _norm(rel):
    return rel.replace("\\", "/").strip("/")


def _is_lfs(b):
    return len(b) <= 1024 and b.startswith(_LFS_MAGIC)


def _occ(keys):
    """Unique keys for a list that may repeat one: the second "k" becomes "k\\x1e2", and so on."""
    seen, out = {}, []
    for k in keys:
        n = seen.get(k, 0) + 1
        seen[k] = n
        out.append(k if n == 1 else "%s\x1e%d" % (k, n))
    return out


def _bare(key):
    return key.split("\x1e", 1)[0]


def _show(key):
    s = key.replace("\x1f", "/").replace("\x1e", " #")
    s = "".join(c if " " <= c < "\x7f" else "\\x%02x" % ord(c) for c in s)
    return s if len(s) <= 72 else s[:69] + "..."


class Unmergeable(Exception):
    """A file that should be a table and does not read as one: it is compared whole instead, and said."""


# ======================================================================================================================
# codecs: parse(raw) -> (meta, [(key, value)]); build(meta, rows) -> raw. key: str; value: bytes (None for sets)
# ======================================================================================================================

# ---- cso: encoded CSV tables (.fsv, .tbl) ---------------------------------------------------------------------------
#
# "_cso_<ver>_<key>\n" + encode(text) + 16 raw NUL bytes (stock, V1.5). V1.2 / V1.3 re-encoded six of theirs as
# encode(text + 16 garbage bytes) -- the decode of the stock NULs under an older key, period 8 -- with no raw NULs.
# Both are read; a rebuild writes the stock form with the file's own key. The cipher is FileInjector/fsv2csv.py's.

_CSO_HDR = re.compile(rb"_cso_(\d+)_(-?\d+)\n")


def _cso_delta(key):
    k32 = (key + 2 ** 31) % 2 ** 32 - 2 ** 31                     # ctypes.c_int32
    k = [(i + (k32 >> (4 * i))) & 0xFF for i in range(8)]
    return [x if x & 1 else (-x) & 0xFF for x in k]                 # what encoding adds at i % 8


def _cso_code(data, key, sign):
    d = _cso_delta(key)
    if sign < 0:
        d = [(-x) & 0xFF for x in d]
    out = bytearray(data)
    for j in range(8):
        tbl = bytes((b + d[j]) & 0xFF for b in range(256))
        out[j::8] = bytes(out[j::8]).translate(tbl)
    return bytes(out)


def cso_parse(raw):
    mo = _CSO_HDR.match(raw)
    if not mo:
        raise Unmergeable("no _cso_ header")
    ver, key = int(mo.group(1)), int(mo.group(2))
    body = raw[mo.end():]
    if len(body) >= 16 and body.endswith(b"\0" * 16):
        text = _cso_code(body[:-16], key, -1)
    else:
        full = _cso_code(body, key, -1)
        g = full[-16:]
        if len(full) < 16 or g[:8] != g[8:]:
            raise Unmergeable("neither 16 raw NULs nor a 16-byte period-8 tail")
        text = full[:-16]
    if b"\0" in text:
        raise Unmergeable("a NUL inside the text")
    crlf, lf = text.count(b"\r\n"), text.count(b"\n")
    if crlf and crlf != lf:
        raise Unmergeable("rows end in both CRLF and LF")
    sep = b"\r\n" if crlf else b"\n"
    lines = text.split(sep)
    trailing = lines[-1] == b""
    if trailing:
        lines.pop()
    if not lines:
        raise Unmergeable("no rows")
    keys = [ln.split(b",", 1)[0].decode("latin1") for ln in lines]
    if len(set(keys)) != len(keys):
        raise Unmergeable("first-column keys are not unique")
    return dict(ver=ver, key=key, sep=sep, trailing=trailing), list(zip(keys, lines))


def cso_build(meta, rows):
    text = meta["sep"].join(v for _k, v in rows) + (meta["sep"] if meta["trailing"] else b"")
    return b"_cso_%d_%d\n" % (meta["ver"], meta["key"]) + _cso_code(text, meta["key"], 1) + b"\0" * 16


def cso_check(rows):
    """Rows whose number of fields differs from the header's (the first row) -- what a parent's new column leaves in
    the layer's own rows. Only asked when every row of the parent's table has the header's count."""
    n = rows[0][1].count(b",")
    return [k for k, v in rows if v.count(b",") != n]


# ---- chsel: Script/CharaSelect.bin ----------------------------------------------------------------------------------
#
# Three count-prefixed blocks, no offset table: per-character select records (173 B), the stage roster (68 B),
# per-character asset hashes (64 B). Each record opens with its id, NUL-terminated and space-padded to 32 bytes (the
# name compared lower-case, as launcher/zangetsu_sync.py did). The order of block 0 is the order of the select grid.

_CS_STRIDES = (173, 68, 64)


def _cs_name(rec):
    return rec[:32].split(b"\0")[0].strip().decode("latin1").lower()


def chsel_parse(raw):
    rows, off = [], 0
    for blk, stride in enumerate(_CS_STRIDES):
        if off + 4 > len(raw):
            raise Unmergeable("CharaSelect.bin ends inside block %d's count" % blk)
        n = struct.unpack_from("<I", raw, off)[0]
        off += 4
        if off + n * stride > len(raw):
            raise Unmergeable("CharaSelect.bin block %d runs past the end" % blk)
        for i in range(n):
            rec = raw[off + i * stride:off + (i + 1) * stride]
            rows.append(("%d:%s" % (blk, _cs_name(rec)), rec))
        off += n * stride
    if off != len(raw):
        raise Unmergeable("CharaSelect.bin does not parse to its own end")
    if len({k for k, _v in rows}) != len(rows):
        raise Unmergeable("a CharaSelect.bin block names a record twice")
    return {}, rows


def chsel_build(_meta, rows):
    out = []
    for blk, stride in enumerate(_CS_STRIDES):
        recs = [v for k, v in rows if k.split(":", 1)[0] == str(blk)]
        if any(len(r) != stride for r in recs):
            raise Unmergeable("a block %d record is not %d bytes" % (blk, stride))
        out.append(struct.pack("<I", len(recs)) + b"".join(recs))
    return b"".join(out)


# ---- icons: Script/icon_list.bin ------------------------------------------------------------------------------------
#
# u32 count, then 96-byte records of three 32-byte fields: key / .cat / sprite. Looked up by key.

def icons_parse(raw):
    n = struct.unpack_from("<I", raw, 0)[0] if len(raw) >= 4 else -1
    if n < 0 or 4 + 96 * n != len(raw):
        raise Unmergeable("icon_list.bin: the records do not fill the file")
    rows = [(_cs_name(raw[4 + 96 * i:4 + 96 * (i + 1)]), raw[4 + 96 * i:4 + 96 * (i + 1)]) for i in range(n)]
    if len({k for k, _v in rows}) != n:
        raise Unmergeable("icon_list.bin names a key twice")
    return {}, rows


def icons_build(_meta, rows):
    if any(len(v) != 96 for _k, v in rows):
        raise Unmergeable("an icon_list.bin record is not 96 bytes")
    return struct.pack("<I", len(rows)) + b"".join(v for _k, v in rows)


# ---- strings: PZZE string tables ------------------------------------------------------------------------------------
#
# An 8-byte magic, u64 inflated size, u64 offset (24), then zlib of a version-3 table: u32 3, u32 count, u32 0, four
# u32 columns (offset, size, key hash, flags), then the records, contiguous. A record is a 0x24-byte header, then
# key\0 ... The row is (hash, flags, record). The zlib level is the file's own (mk_v16_strings's map), so a rebuild
# of the same rows gives the same bytes.

_ZLEVEL = {b"\x78\x01": 1, b"\x78\x5e": 2, b"\x78\x9c": 6, b"\x78\xda": 9}


def strings_parse(raw):
    if raw[:4] != b"PZZE" or len(raw) < 26:
        raise Unmergeable("not a PZZE container")
    size, off = struct.unpack_from("<QQ", raw, 8)
    zh = raw[off:off + 2]
    if off != 24 or zh not in _ZLEVEL:
        raise Unmergeable("a PZZE header or zlib level this module does not rebuild")
    try:
        u = zlib.decompress(raw[off:])
    except zlib.error as e:
        raise Unmergeable("zlib: %s" % e)
    if len(u) != size or len(u) < 12:
        raise Unmergeable("the inflated size does not match the header")
    ver, n, zero = struct.unpack_from("<3I", u, 0)
    if ver != 3 or zero != 0 or 12 + 16 * n > len(u):
        raise Unmergeable("not a version-3 string table")
    offs, sizes, hashes, flags = (struct.unpack_from("<%dI" % n, u, 12 + c * 4 * n) for c in range(4))
    if n and (offs[0] != 12 + 16 * n or offs[-1] + sizes[-1] != len(u)
              or any(offs[i] + sizes[i] != offs[i + 1] for i in range(n - 1))):
        raise Unmergeable("an index that does not list contiguous records (written by another tool)")
    if not n and len(u) != 12:
        raise Unmergeable("bytes after an empty table")
    rows = []
    for i in range(n):
        rec = u[offs[i]:offs[i] + sizes[i]]
        end = rec.find(b"\0", 0x24)
        if len(rec) < 0x25 or end < 0:
            raise Unmergeable("record %d has no key" % i)
        rows.append((rec[0x24:end].decode("latin1"), struct.pack("<II", hashes[i], flags[i]) + rec))
    if len({k for k, _v in rows}) != n:
        raise Unmergeable("a key is there twice")
    return dict(magic=raw[:8], zh=zh), rows


def strings_build(meta, rows):
    n = len(rows)
    recs = [v[8:] for _k, v in rows]
    offs, cur = [], 12 + 16 * n
    for r in recs:
        offs.append(cur)
        cur += len(r)
    u = b"".join([struct.pack("<3I", 3, n, 0), struct.pack("<%dI" % n, *offs),
                  struct.pack("<%dI" % n, *[len(r) for r in recs]),
                  b"".join(v[:4] for _k, v in rows), b"".join(v[4:8] for _k, v in rows)] + recs)
    z = zlib.compress(u, _ZLEVEL[meta["zh"]])
    if z[:2] != meta["zh"]:
        raise Unmergeable("zlib did not reproduce the file's level")
    return meta["magic"] + struct.pack("<QQ", len(u), 24) + z


# ---- atlas: ui/swap region atlases (chara_icon.cat, chara_type.cat ...) ---------------------------------------------
#
# Header u32 1, 1, 0, base, data size, 6, nsz, 0; at base a region table (u32 t0, nsz, t6, base, nsz+1 offsets,
# nsz sizes); region 1 is the names ("<name>,\r\n" each), regions 2..nsz one image each behind a 16-byte sub-header
# (16, 1, used, 0). Vanilla's are in the canonical layout (launcher/zangetsu_sync.py's _at_join, from DataChakka's
# bros_charatype.py); V1.5's are not. So a changed region is appended 256-aligned and its table entry re-pointed,
# every other byte kept (how the new V1.6's atlases were built, pass rn, rn094); only a canonical file is rebuilt when
# the merge changes the list of regions.

_AT_PAD = 256


def _at_layout(raw):
    if len(raw) < 32:
        raise Unmergeable("too short for an atlas")
    one, one2, zero, base, size, six, nsz, z2 = struct.unpack_from("<8I", raw, 0)
    if (one, one2, zero, six, z2) != (1, 1, 0, 6, 0) or base + size != len(raw) or nsz < 1:
        raise Unmergeable("not a region atlas")
    if base + 16 + 4 * (2 * nsz + 1) > len(raw):
        raise Unmergeable("the region table runs past the end")
    t0, tn, t6, tb = struct.unpack_from("<4I", raw, base)
    if (tn, tb) != (nsz, base):
        raise Unmergeable("the region table disagrees with the header")
    offs = list(struct.unpack_from("<%dI" % (nsz + 1), raw, base + 16))
    sizes = list(struct.unpack_from("<%dI" % nsz, raw, base + 16 + 4 * (nsz + 1)))
    s = base + offs[1]
    blob = raw[s:s + sizes[0]].split(b"\0")[0].replace(b"\r\n", b"\n")
    names = [x.rstrip(b",").decode("latin1") for x in blob.split(b"\n") if x.strip()]
    if len(names) != nsz - 1:
        raise Unmergeable("%d names for %d images" % (len(names), nsz - 1))
    return base, nsz, offs, sizes, names, t0, t6


def atlas_parse(raw):
    base, nsz, offs, sizes, names, t0, t6 = _at_layout(raw)
    rows = []
    for i, nm in enumerate(names):
        a, ln = base + offs[i + 2], sizes[i + 1]
        reg = raw[a:a + ln]
        if len(reg) != ln or ln < 16 or struct.unpack_from("<I", reg, 0)[0] != 16:
            raise Unmergeable("region %s has no 16-byte sub-header" % nm)
        rows.append((nm, reg))
    if len({k for k, _v in rows}) != len(rows):
        raise Unmergeable("a region name is there twice")
    return dict(raw=raw), rows


def _at_pad(n):
    return (n + _AT_PAD - 1) // _AT_PAD * _AT_PAD


def _at_join(base, t0, t6, rows):
    """the canonical layout of these regions (zangetsu_sync._at_join's)"""
    nsz = len(rows) + 1
    names = b"".join(n.encode("latin1") + b",\r\n" for n, _r in rows)
    tbl_len = 16 + 4 * (nsz + 1) + 4 * nsz
    offs, sizes, cur = [0], [], _at_pad(tbl_len)
    offs.append(cur)
    sizes.append(len(names))
    cur += _at_pad(len(names))
    for _n, reg in rows:
        offs.append(cur)
        sizes.append(len(reg))
        cur += _at_pad(len(reg))
    out = bytearray(struct.pack("<8I", 1, 1, 0, base, cur, 6, nsz, 0))
    out += b"\0" * (base - len(out))
    tbl = struct.pack("<4I", t0, nsz, t6, base) + struct.pack("<%dI" % (nsz + 1), *offs) \
        + struct.pack("<%dI" % nsz, *sizes)
    out += tbl + b"\0" * (_at_pad(tbl_len) - len(tbl))
    out += names + b"\0" * (_at_pad(len(names)) - len(names))
    for _n, reg in rows:
        used = len(reg)
        out += struct.pack("<4I", 16, 1, used, 0) + reg[16:] + b"\0" * (_at_pad(used) - used)
    return bytes(out)


def atlas_build(meta, rows):
    raw = meta["raw"]
    base, nsz, offs, sizes, names, t0, t6 = _at_layout(raw)
    if [k for k, _v in rows] == names:
        if len(raw) % _AT_PAD:
            raise Unmergeable("the atlas is not 256-aligned")
        out = bytearray(raw)
        for i, (_nm, reg) in enumerate(rows):
            a = base + offs[i + 2]
            if sizes[i + 1] == len(reg) and raw[a:a + len(reg)] == reg:
                continue
            pos = len(out)
            out += reg + b"\0" * (_at_pad(len(reg)) - len(reg))
            offs[i + 2] = pos - base
            sizes[i + 1] = len(reg)
        struct.pack_into("<%dI" % (nsz + 1), out, base + 16, *offs)
        struct.pack_into("<%dI" % nsz, out, base + 16 + 4 * (nsz + 1), *sizes)
        struct.pack_into("<I", out, 16, len(out) - base)
        return bytes(out)
    _m, mine = atlas_parse(raw)
    if base < 32 or _at_join(base, t0, t6, mine) != raw:
        raise Unmergeable("the merge changes the list of regions, and this atlas is not in the canonical layout, "
                          "which is the only one rebuilt")
    if any(struct.unpack_from("<4I", reg, 0) != (16, 1, len(reg), 0) for _n, reg in rows):
        raise Unmergeable("a region's sub-header is not (16, 1, size, 0)")
    return _at_join(base, t0, t6, rows)


# ---- htable: Fnames/file_exist.htable -------------------------------------------------------------------------------
#
# u32 count, then (crc(path), crc(folder)) pairs, in no order: the loader builds its own map. A set.

def htable_parse(raw):
    n = struct.unpack_from("<I", raw, 0)[0] if len(raw) >= 4 else -1
    if n < 0 or 4 + 8 * n != len(raw):
        raise Unmergeable("file_exist.htable: the rows do not fill the file")
    keys = _occ(["%08x%08x" % struct.unpack_from("<II", raw, 4 + 8 * i) for i in range(n)])
    return {}, [(k, None) for k in keys]


def htable_build(_meta, rows):
    return struct.pack("<I", len(rows)) + b"".join(
        struct.pack("<II", int(_bare(k)[:8], 16), int(_bare(k)[8:16], 16)) for k, _v in rows)


# ---- fnames: Fnames/filename.bin ------------------------------------------------------------------------------------
#
# u32 group count; group := str name, u32 folder count, folders; folder := str name, u32 file count, (str basename,
# str extension, str logical name) each; str := u32 length, bytes, NUL (DataChakka's FnamesVfs.h). The engine maps the
# entries, so they are a set (every shipped copy repeats 148 of vanilla's: a repeat is keyed by its occurrence). A
# rebuild keeps the layer's own groups and folders in their order, empty ones too; a new entry goes at the end of its
# folder (made at the end when missing).

def _fn_read(d):
    pos = [0]

    def u32():
        if pos[0] + 4 > len(d):
            raise Unmergeable("filename.bin ends inside a count")
        v = struct.unpack_from("<I", d, pos[0])[0]
        pos[0] += 4
        return v

    def s():
        n = u32()
        if pos[0] + n >= len(d) or d[pos[0] + n] != 0:
            raise Unmergeable("filename.bin: a string without its NUL")
        v = d[pos[0]:pos[0] + n]
        pos[0] += n + 1
        return v

    groups = []
    for _ in range(u32()):
        g = s()
        folders = []
        for _ in range(u32()):
            fo = s()
            folders.append((fo, [(s(), s(), s()) for _ in range(u32())]))
        groups.append((g, folders))
    if pos[0] != len(d):
        raise Unmergeable("filename.bin does not parse to its own end")
    return groups


def _fn_write(groups):
    out = [struct.pack("<I", len(groups))]

    def s(b):
        out.append(struct.pack("<I", len(b)) + b + b"\0")

    for g, folders in groups:
        s(g)
        out.append(struct.pack("<I", len(folders)))
        for fo, files in folders:
            s(fo)
            out.append(struct.pack("<I", len(files)))
            for t in files:
                for x in t:
                    s(x)
    return b"".join(out)


def _fn_key(g, fo, t):
    return "\x1f".join(x.decode("latin1") for x in (g, fo) + tuple(t))


def fnames_parse(raw):
    groups = _fn_read(raw)
    if len({g for g, _f in groups}) != len(groups) or any(len({fo for fo, _x in f}) != len(f) for _g, f in groups):
        raise Unmergeable("filename.bin names a group, or a folder in a group, twice")
    keys = _occ([_fn_key(g, fo, t) for g, folders in groups for fo, files in folders for t in files])
    return dict(groups=groups), [(k, None) for k in keys]


def fnames_build(meta, rows):
    skel = [(g, [(fo, []) for fo, _x in folders]) for g, folders in meta["groups"]]
    gi = {g: i for i, (g, _f) in enumerate(skel)}
    fi = {(g, fo): files for g, folders in skel for fo, files in folders}
    for k, _v in rows:
        parts = [x.encode("latin1") for x in _bare(k).split("\x1f")]
        if len(parts) != 5:
            raise Unmergeable("a filename.bin entry key with %d parts" % len(parts))
        g, fo, t = parts[0], parts[1], tuple(parts[2:])
        if g not in gi:
            gi[g] = len(skel)
            skel.append((g, []))
        if (g, fo) not in fi:
            files = []
            skel[gi[g]][1].append((fo, files))
            fi[(g, fo)] = files
        fi[(g, fo)].append(t)
    return _fn_write(skel)


# ---- wwise: Wwise sound banks (bank version 150: BKHD DIDX DATA HIRC) -----------------------------------------------
#
# HIRC objects (u8 type, u32 size, body starting with the u32 id) in their order, keyed "o:<id>"; media keyed
# "m:<id>". A rebuild keeps BKHD's 40 fixed bytes, lays the media out sorted by id on 16 bytes with zero gaps, and pads
# BKHD so DATA's payload starts on 16 bytes (the rules of the stock banks; pass rn, rn098).

def _ww_chunks(raw):
    ch, p = [], 0
    while p < len(raw):
        if p + 8 > len(raw):
            raise Unmergeable("a bank chunk header runs past the end")
        tag, size = raw[p:p + 4], struct.unpack_from("<I", raw, p + 4)[0]
        if p + 8 + size > len(raw):
            raise Unmergeable("a bank chunk runs past the end")
        ch.append((tag, raw[p + 8:p + 8 + size]))
        p += 8 + size
    return ch


def wwise_parse(raw):
    ch = _ww_chunks(raw)
    if [t for t, _c in ch] != [b"BKHD", b"DIDX", b"DATA", b"HIRC"]:
        raise Unmergeable("not the chunks BKHD DIDX DATA HIRC")
    bk, didx, data, hirc = (c for _t, c in ch)
    if len(bk) < 40 or any(bk[40:]) or len(didx) % 12 or len(hirc) < 4:
        raise Unmergeable("a BKHD, DIDX or HIRC this module does not rebuild")
    rows, q = [], 4
    for _ in range(struct.unpack_from("<I", hirc, 0)[0]):
        if q + 9 > len(hirc):
            raise Unmergeable("a HIRC object header runs past the end")
        s, oid = struct.unpack_from("<II", hirc, q + 1)
        if s < 4 or q + 5 + s > len(hirc):
            raise Unmergeable("a HIRC object runs past the end")
        rows.append(("o:%d" % oid, hirc[q:q + 5 + s]))
        q += 5 + s
    if q != len(hirc):
        raise Unmergeable("the HIRC objects do not fill the chunk")
    for i in range(0, len(didx), 12):
        mid, off, sz = struct.unpack_from("<III", didx, i)
        if off + sz > len(data):
            raise Unmergeable("a medium runs past DATA")
        rows.append(("m:%d" % mid, data[off:off + sz]))
    if len({k for k, _v in rows}) != len(rows):
        raise Unmergeable("an object or medium id is there twice")
    return dict(bkhd=bk[:40]), rows


def wwise_build(meta, rows):
    objs = [v for k, v in rows if k.startswith("o:")]
    media = sorted(((int(k[2:]), v) for k, v in rows if k.startswith("m:")), key=lambda x: x[0])
    hirc = struct.pack("<I", len(objs)) + b"".join(objs)
    didx, data = [], bytearray()
    for mid, blob in media:
        if len(data) % 16:
            data += bytes(16 - len(data) % 16)
        didx.append(struct.pack("<III", mid, len(data), len(blob)))
        data += blob
    didx = b"".join(didx)
    pad = 0
    while (8 + 40 + pad + 8 + len(didx) + 8) % 16:
        pad += 4
    return b"".join(t + struct.pack("<I", len(c)) + c for t, c in
                    ((b"BKHD", meta["bkhd"] + bytes(pad)), (b"DIDX", didx), (b"DATA", bytes(data)), (b"HIRC", hirc)))


# ---- the dispatcher -------------------------------------------------------------------------------------------------
CODECS = {
    "cso": (cso_parse, cso_build),
    "chsel": (chsel_parse, chsel_build),
    "icons": (icons_parse, icons_build),
    "strings": (strings_parse, strings_build),
    "atlas": (atlas_parse, atlas_build),
    "htable": (htable_parse, htable_build),
    "fnames": (fnames_parse, fnames_build),
    "wwise": (wwise_parse, wwise_build),
}
SETS = ("htable", "fnames")               # rows that are only keys, in no meaningful order


def codec_for(game_path, raw):
    """The codec for a file both a layer and its parent have, by its game path and its first bytes."""
    g = _norm(game_path).lower()
    name = g.rsplit("/", 1)[-1]
    if raw[:5] == b"_cso_":
        return "cso"
    if g == "script/charaselect.bin":
        return "chsel"
    if g == "script/icon_list.bin":
        return "icons"
    if g == "fnames/file_exist.htable":
        return "htable"
    if g == "fnames/filename.bin":
        return "fnames"
    if raw[:4] == b"PZZE" and g.startswith("text/") and name.endswith(".cat"):
        return "strings"
    if name.endswith(".bnk") and raw[:4] == b"BKHD":
        return "wwise"
    if ("/" + g).find("/ui/swap/") >= 0 and name.endswith(".cat") and len(raw) >= 32 \
            and struct.unpack_from("<3I", raw, 0) == (1, 1, 0) and struct.unpack_from("<I", raw, 20)[0] == 6:
        return "atlas"
    return "whole"


# ======================================================================================================================
# the merge
# ======================================================================================================================

def _chain(inserts, key):
    """the rows inserted after `key`, each followed by the rows inserted after it (iterative: a parent may add
    thousands of rows in a row)"""
    out, stack = [], list(reversed(inserts.get(key, ())))
    while stack:
        kv = stack.pop()
        out.append(kv)
        stack.extend(reversed(inserts.get(kv[0], ())))
    return out


def merge_rows(parent, child, memory, is_set=False):
    """The layer's rows after taking its parent's.

    parent, child: [(key, value)] in file order. memory: {key hash: row hash} of the rows the parent last gave, or
    None -- then the parent's rows of today stand in for it (nothing that differs is changed, nothing is added).
    -> (rows, events): rows in the layer's order, each new parent row after the row it follows in the parent;
    events [(kind, key)] with kind in took / added / dropped / conflict / kept_dropped / both_added."""
    vh = (lambda v: "") if is_set else _vh
    P = dict(parent)
    M = memory if memory is not None else {_kh(k): vh(v) for k, v in parent}
    events, out = [], []
    for k, v in child:
        kh = _kh(k)
        if k in P:
            if kh not in M:                                   # new in the parent, and the layer has the key too
                out.append((k, v))
                if vh(P[k]) != vh(v):
                    events.append(("both_added", k))
            elif vh(v) == M[kh]:                              # as the parent gave it -> the parent's row of today
                out.append((k, P[k]))
                if vh(P[k]) != vh(v):
                    events.append(("took", k))
            else:                                             # the layer's own change
                out.append((k, v))
                if vh(P[k]) != M[kh] and vh(P[k]) != vh(v):
                    events.append(("conflict", k))
        elif kh in M:                                         # the parent dropped it
            if vh(v) == M[kh]:
                events.append(("dropped", k))
                continue
            out.append((k, v))
            events.append(("kept_dropped", k))
        else:                                                 # only the layer has it
            out.append((k, v))
    have = {k for k, _v in out}
    inserts, prev = {}, None
    for k, v in parent:
        if k in have:
            prev = k
        elif _kh(k) not in M:                                 # new since the memory
            inserts.setdefault(prev, []).append((k, v))
            events.append(("added", k))
            prev = k
        # else: given before and no longer in the layer -- the layer dropped it, and it stays dropped
    if not inserts:
        return out, events
    res = _chain(inserts, None)
    for kv in out:
        res.append(kv)
        res.extend(_chain(inserts, kv[0]))
    return res, events


def _summary(events):
    """events -> lines for a person"""
    n = {}
    for kind, _k in events:
        n[kind] = n.get(kind, 0) + 1
    lines = []
    bits = ["%d %s" % (n[k], w) for k, w in (("took", "row(s) changed by the parent taken"),
                                             ("added", "new row(s) added"), ("dropped", "row(s) dropped"))
            if n.get(k)]
    if bits:
        lines.append(", ".join(bits))
    for kind, k in events:
        if kind == "conflict":
            lines.append("kept this layer's own row %s; the parent changed it too" % _show(k))
        elif kind == "kept_dropped":
            lines.append("kept this layer's own row %s; the parent dropped it" % _show(k))
        elif kind == "both_added":
            lines.append("kept this layer's row %s; the parent added a different one of the same key" % _show(k))
    return lines


def _make_mem(codec, pmd5, prows):
    if codec == "whole":
        return {"codec": "whole", "parent_md5": pmd5, "rows": None}
    is_set = codec in SETS
    return {"codec": codec, "parent_md5": pmd5,
            "rows": {_kh(k): ("" if is_set else _vh(v)) for k, v in prows}}


def canon(codec, rows):
    """rows in the order the codec writes them: a set's sorted, CharaSelect's by block, a bank's media by id"""
    if codec in SETS:
        return sorted(rows, key=lambda kv: kv[0])
    if codec == "chsel":
        return sorted(rows, key=lambda kv: int(kv[0].split(":", 1)[0]))      # stable: each block keeps its order
    if codec == "wwise":
        return [kv for kv in rows if kv[0].startswith("o:")] + \
            sorted((kv for kv in rows if kv[0].startswith("m:")), key=lambda kv: int(kv[0][2:]))
    return list(rows)


def same_rows(codec, a, b):
    return canon(codec, a) == canon(codec, b)


def merge_file(codec, parent_raw, child_raw, mem):
    """-> (the layer's new bytes or None when they stay, the new memory or None to leave it, [lines to report])."""
    pmd5 = _md5(parent_raw)
    if mem is not None and mem.get("parent_md5") == pmd5:
        return None, mem, []                                  # the parent has not changed since the memory
    notes = []
    if codec != "whole":
        parse, build = CODECS[codec]
        try:
            _pm, prows = parse(parent_raw)
            cmeta, crows = parse(child_raw)
        except Unmergeable as e:
            notes.append("not read as a %s table (%s): compared whole" % (codec, e))
            codec = "whole"
        else:
            memory = mem["rows"] if (mem is not None and mem.get("codec") == codec and mem.get("rows") is not None) \
                else None
            rows, events = merge_rows(prows, crows, memory, codec in SETS)
            notes += _summary(events)
            new_mem = _make_mem(codec, pmd5, prows)
            if same_rows(codec, rows, crows):
                return None, new_mem, notes
            if codec == "cso" and not cso_check(prows):
                bad = cso_check(rows)
                if bad:
                    return None, mem, notes + [
                        "NOT merged: these rows would not have the header's number of fields (the parent changed "
                        "the columns?): %s -- fix them in this layer; its copy is left as it is"
                        % ", ".join(_show(k) for k in bad[:8])]
            try:
                out = build(cmeta, rows)
                _m2, back = parse(out)
            except Unmergeable as e:
                return None, mem, notes + ["NOT merged (%s): this layer's copy is left as it is" % e]
            if not same_rows(codec, back, rows):
                return None, mem, notes + ["NOT merged: the rebuilt file does not read back as merged; this layer's "
                                           "copy is left as it is"]
            return out, new_mem, notes
    new_mem = _make_mem("whole", pmd5, None)
    cmd5 = _md5(child_raw)
    last = mem.get("parent_md5") if mem is not None else pmd5
    if cmd5 == pmd5:
        return None, new_mem, notes
    if cmd5 == last:
        return parent_raw, new_mem, notes + ["took the parent's new file"]
    if pmd5 != last:
        notes.append("kept this layer's own file; the parent changed its copy too")
    return None, new_mem, notes


# ======================================================================================================================
# the memory files
# ======================================================================================================================

def _gv(base_dir, *p):
    return os.path.join(base_dir, "GameVersions", *p)


def state_path(base_dir, layer, rel):
    rel = _norm(rel)
    flat = re.sub(r"[^A-Za-z0-9._-]+", "_", rel).strip("_")
    return _gv(base_dir, layer, STATE_DIR, "%s.%s.txt" % (flat, _md5(rel.encode("utf-8"))[:6]))


def state_text(layer, parent, rel, mem):
    lines = ["# version_inherit memory: the rows '%s' last gave this layer's copy of the file below." % parent,
             "# One line per row: a hash of its key, then a hash of its bytes. Written by launcher/version_inherit.py;",
             "# do not edit. Deleted, the next sync takes the parent's rows of that moment as the memory.",
             "format: " + STATE_FORMAT, "layer: " + layer, "parent: " + parent, "path: " + _norm(rel),
             "codec: " + mem["codec"], "parent_md5: " + mem["parent_md5"]]
    if mem["rows"] is None:
        lines.append("rows: none")
    else:
        lines.append("rows: %d" % len(mem["rows"]))
        lines += sorted(("%s %s" % (k, v)).rstrip() for k, v in mem["rows"].items())
    return "\n".join(lines) + "\n"


def parse_state(text, layer, rel):
    """a memory file's text -> the memory, or None (another file's, or cut short)"""
    lines = text.replace("\r\n", "\n").split("\n")
    hdr, i = {}, 0
    while i < len(lines):
        ln = lines[i]
        i += 1
        if not ln or ln.startswith("#"):
            continue
        name, sep, val = ln.partition(": ")
        if not sep:
            return None
        hdr[name] = val
        if name == "rows":
            break
    if hdr.get("format") != STATE_FORMAT or hdr.get("path") != _norm(rel) or hdr.get("layer") != layer \
            or not re.fullmatch(r"[0-9a-f]{32}", hdr.get("parent_md5", "")) or "codec" not in hdr:
        return None
    if hdr.get("rows") == "none":
        rows = None
    else:
        try:
            n = int(hdr.get("rows", ""))
        except ValueError:
            return None
        body = [ln for ln in lines[i:] if ln]
        if len(body) != n:
            return None
        rows = {}
        for ln in body:
            k, _sp, v = ln.partition(" ")
            rows[k] = v
        if len(rows) != n:
            return None
    return {"codec": hdr["codec"], "parent_md5": hdr["parent_md5"], "rows": rows, "parent": hdr.get("parent")}


def read_state(base_dir, layer, rel):
    """the memory of this layer file, or None (none, unreadable, another file's, or cut short)"""
    try:
        with open(state_path(base_dir, layer, rel), "r", encoding="ascii", newline="") as f:
            return parse_state(f.read(), layer, rel)
    except (OSError, ValueError):
        return None


# ======================================================================================================================
# versions, layers, what a version installs
# ======================================================================================================================

def _base_of(base_dir, v):
    """base.txt's parent, the launcher's way: None when it names no existing folder"""
    try:
        with open(_gv(base_dir, v, BASE_NAME), "r", encoding="utf-8") as f:
            b = f.read().strip()
    except (OSError, ValueError):
        return None
    return b if b and os.path.isdir(_gv(base_dir, b)) else None


def version_chain(base_dir, v):
    """[root, ..., v] following base.txt (the launcher's version_chain)"""
    chain, seen = [], set()
    while v and v not in seen:
        seen.add(v)
        chain.append(v)
        v = _base_of(base_dir, v)
    return list(reversed(chain))


def version_files(base_dir, v):
    """What version v itself installs: (roots, overlays), each {game path lower: (version-relative path, abs path)}.
    roots: its Script, Motion, 00HIGH, 01MIDDLE; overlays: its Overlay. Dev leftovers excluded, as the launcher does."""
    root = _gv(base_dir, v)
    roots, overlays = {}, {}
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return roots, overlays
    for name in names:
        top = os.path.join(root, name)
        low = name.lower()
        if not os.path.isdir(top) or (low not in _SLOTS and low != "overlay"):
            continue
        target = overlays if low == "overlay" else roots
        for dp, _dn, fn in os.walk(top):
            for f in fn:
                a = os.path.join(dp, f)
                rel = _norm(os.path.relpath(a, root))
                g = rel.split("/", 1)[1] if low == "overlay" else rel
                if (low == "overlay" and f == "_overlay_manifest.json") or _excluded(g):
                    continue
                target[g.lower()] = (rel, a)
    return roots, overlays


def effective(base_dir, version, cache=None):
    """{game path lower: absolute path} of what installing `version` puts down: every root of its chain in order, then
    every Overlay in order (launch(): injectFolder, then install_overlay)."""
    cache = cache if cache is not None else {}
    chain = version_chain(base_dir, version)
    for v in chain:
        if v not in cache:
            cache[v] = version_files(base_dir, v)
    res = {}
    for part in (0, 1):
        for v in chain:
            for g, (_rel, a) in cache[v][part].items():
                res[g] = a
    return res


class Layer(object):
    def __init__(self, name, parent):
        self.name = name
        self.parent = parent


def load_layers(base_dir):
    """Every folder with an inherit.json, parents first. A manifest that is malformed, or whose parent is not the
    folder its base.txt names, raises: guessing what a layer is, is how a sync writes over it."""
    root = _gv(base_dir)
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    layers = []
    for name in names:
        p = _gv(base_dir, name, MANIFEST_NAME)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            parent = data.get("parent") if isinstance(data, dict) else None
        except Exception as e:
            raise ValueError("%s/%s: %s" % (name, MANIFEST_NAME, e))
        if not isinstance(parent, str) or not parent.strip():
            raise ValueError("%s/%s: no \"parent\"" % (name, MANIFEST_NAME))
        parent = parent.strip()
        base = _base_of(base_dir, name)
        if base != parent:
            raise ValueError("%s: %s names '%s' but %s names %s -- the rows would come from another version than the "
                             "install" % (name, MANIFEST_NAME, parent, BASE_NAME,
                                          "'%s'" % base if base else "no existing folder"))
        layers.append(Layer(name, parent))
    layers.sort(key=lambda x: (len(version_chain(base_dir, x.name)), x.name))
    return layers


# ======================================================================================================================
# the sync
# ======================================================================================================================

def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _write(path, data):
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    tmp = path + ".vi_tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    if _read(path) != data:
        raise OSError("read-back differs: " + path)


def _git(base_dir, args, data=None, timeout=300):
    """git's stdout, or None when git is missing or fails"""
    try:
        r = subprocess.run(["git"] + list(args), cwd=base_dir, input=data, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout)
    except Exception:
        return None
    return r.stdout if r.returncode == 0 else None


def _unstaged(base_dir, under="GameVersions"):
    """Repo paths (lower case) under `under` whose working copy differs from the index, and untracked ones. None when
    git cannot say."""
    a = _git(base_dir, ["diff", "--name-only", "--no-renames", "-z", "--", under])
    b = _git(base_dir, ["ls-files", "--others", "--exclude-standard", "-z", "--", under])
    if a is None or b is None:
        return None
    return {_norm(x.decode("utf-8", "surrogateescape")).lower() for x in (a + b"\0" + b).split(b"\0") if x}


def _index_bytes(base_dir, rel):
    """the index's copy of a repo path (a git-LFS file's real bytes), or None"""
    b = _git(base_dir, ["cat-file", "blob", ":" + rel])
    if b is not None and _is_lfs(b):
        b = _git(base_dir, ["lfs", "smudge", "--", rel], data=b, timeout=1800)
        if b is not None and _is_lfs(b):
            b = None
    return b


def _partial_commit():
    """git commit -- <paths> / --only builds the commit in a temporary index (.git/next-index-*.lock): a file staged
    there reaches the commit but not the real index (launcher/effect_registry.py's test, the same rule)"""
    return os.path.basename(os.environ.get("GIT_INDEX_FILE", "")).startswith("next-index-")


def _wanted(only_rels):
    """repo-relative paths a commit stages -> (game paths lower they touch, versions to sync whole)"""
    want, whole = set(), set()
    for r in only_rels:
        p = _norm(r).split("/")
        if len(p) < 3 or p[0] != "GameVersions":
            continue
        v, rest = p[1], p[2:]
        if rest[0] in (MANIFEST_NAME, BASE_NAME, STATE_DIR):
            whole.add(v)
        elif rest[0].lower() == "overlay" and len(rest) > 1:
            want.add("/".join(rest[1:]).lower())
        elif rest[0].lower() in _SLOTS:
            want.add("/".join(rest).lower())
    return want, whole


def _rel(base_dir, path):
    return _norm(os.path.relpath(path, base_dir))


def sync(base_dir, only=None, only_rels=None, dry_run=False, force=False, log=print, hook=False, refused=None):
    """Bring every layer up to its parent. Returns the repo paths written (layer files and memory files) -- in hook
    mode, every repo path the commit must stage, written now or by an earlier run.

    only       one layer's folder name.
    only_rels  repo paths a commit stages: only the game paths they touch are looked at (a staged inherit.json,
               base.txt or memory file syncs that layer whole).
    force      write even over a layer file with unstaged changes.
    hook       the pre-commit hook: what a layer file and its memory ARE is the index's copy. A layer file or memory
               with unstaged changes is staged when the working copy is exactly what the sync makes from the index
               (an earlier launch merged it), else held back and said. A parent copy with unstaged changes that a
               layer would take is a refusal (appended to `refused`): the layer would get what the commit does not.
    refused    a list the refusals are appended to (hook mode)."""
    layers = load_layers(base_dir)
    if only:
        layers = [x for x in layers if x.name == only]
        if not layers:
            log("  inherit: '%s' is not a layer (no %s)" % (only, MANIFEST_NAME))
            return []
    want, whole_layers = (None, set()) if only_rels is None else _wanted(only_rels)
    unstaged = None
    if hook:
        unstaged = _unstaged(base_dir)
        if unstaged is None:
            raise ValueError("git cannot list the unstaged files, so the layers cannot be checked against the index")
    refused = refused if refused is not None else []
    cache, pcache, out, touched = {}, {}, [], set()
    for lay in layers:
        if not os.path.isdir(_gv(base_dir, lay.parent)):
            log("  inherit: %s -> its parent '%s' is missing; left as it is" % (lay.name, lay.parent))
            continue
        lwant = None if (want is None or lay.name in whole_layers) else want
        parent_eff = effective(base_dir, lay.parent, cache)
        p_overlays = set()
        for v in version_chain(base_dir, lay.parent):
            p_overlays |= set(cache[v][1])
        if lay.name not in cache:
            cache[lay.name] = version_files(base_dir, lay.name)
        roots, overlays = cache[lay.name]
        mine = dict(overlays)
        dead = []
        for g, (rel, a) in roots.items():
            if g in overlays or g in p_overlays:
                if g in parent_eff:
                    dead.append(rel)
                continue
            mine[g] = (rel, a)
        dirty = None
        taken, staged_as_is, held, said = [], [], [], []
        for g in sorted(mine):
            rel, apath = mine[g]
            if lwant is not None and g not in lwant:
                continue
            ppath = parent_eff.get(g)
            sp = state_path(base_dir, lay.name, rel)
            layer_rel, state_rel = "GameVersions/%s/%s" % (lay.name, rel), _rel(base_dir, sp)
            if ppath is None:
                if read_state(base_dir, lay.name, rel) is not None:
                    said.append((rel, "the parent no longer has this file: this layer's copy now installs on its own "
                                      "(remove it here too if it should go)"))
                continue
            parent_rel = _rel(base_dir, ppath)
            if hook and parent_rel.lower() in unstaged and parent_rel.lower() not in touched:
                refused.append("%s: its parent's copy %s has changes that are not staged -- the layer would take what "
                               "this commit does not carry. Stage them (git add) or set them aside (git stash), then "
                               "commit again." % (layer_rel, parent_rel))
                continue
            if ppath not in pcache:
                b = _read(ppath)
                pcache[ppath] = (b, _md5(b))
            praw, pmd5 = pcache[ppath]
            if _is_lfs(praw):
                said.append((rel, "the parent's copy is a git-LFS placeholder (git lfs pull): not merged"))
                continue
            if hook and (layer_rel.lower() in unstaged or state_rel.lower() in unstaged):
                # The working copy differs from the index here: decide from the index.
                idx_layer = _index_bytes(base_dir, layer_rel)
                idx_state = _git(base_dir, ["cat-file", "blob", ":" + state_rel])
                idx_mem = parse_state(idx_state.decode("ascii", "replace"), lay.name, rel) if idx_state else None
                ok = False
                if idx_layer is not None:
                    new, new_mem, _n = merge_file(codec_for(g, praw), praw, idx_layer, idx_mem)
                    want_layer = new if new is not None else idx_layer
                    want_state = state_text(lay.name, lay.parent, rel, new_mem).encode("ascii") \
                        if new_mem is not None else idx_state
                    try:
                        wt_state = _read(sp).replace(b"\r\n", b"\n")
                    except OSError:
                        wt_state = None
                    ok = _read(apath) == want_layer and wt_state == want_state
                if ok:
                    for p in (layer_rel, state_rel):
                        if p.lower() in unstaged and p.lower() not in touched:
                            out.append(p)
                            touched.add(p.lower())
                    staged_as_is.append(rel)
                else:
                    held.append(rel)
                continue
            mem = read_state(base_dir, lay.name, rel)
            if mem is not None and mem.get("parent_md5") == pmd5:
                continue                                      # the fast path: nothing changed above
            craw = _read(apath)
            if _is_lfs(craw):
                said.append((rel, "this layer's copy is a git-LFS placeholder (git lfs pull): not merged"))
                continue
            new, new_mem, notes = merge_file(codec_for(g, praw), praw, craw, mem)
            said += [(rel, n) for n in notes]
            stext = state_text(lay.name, lay.parent, rel, new_mem).encode("ascii") if new_mem is not None else None
            try:
                old_stext = _read(sp).replace(b"\r\n", b"\n") if stext is not None else None
            except OSError:
                old_stext = None
            if new is None and (stext is None or stext == old_stext):
                continue
            if not hook and new is not None:
                if dirty is None:
                    dirty = set() if force else (_unstaged(base_dir, "GameVersions/" + lay.name) or set())
                if layer_rel.lower() in dirty:
                    held.append(rel)
                    continue
            if not dry_run:
                if new is not None:
                    _write(apath, new)
                if stext is not None and stext != old_stext:
                    _write(sp, stext)
            if new is not None:
                taken.append(rel)
                out.append(layer_rel)
                touched.add(layer_rel.lower())
            if stext is not None and stext != old_stext:
                out.append(state_rel)
                touched.add(state_rel.lower())
        if taken:
            log("  inherit: %s %s %d file(s) from %s:" % (lay.name, "would take" if dry_run else "took", len(taken),
                                                          lay.parent))
            for rel in taken:
                log("      " + rel)
        if staged_as_is:
            log("  inherit: %s: %d file(s) already merged by an earlier run, staged with this commit:"
                % (lay.name, len(staged_as_is)))
            for rel in staged_as_is:
                log("      " + rel)
        if held:
            log("  inherit: %s: %d file(s) held back -- they have changes of their own that are not staged; this "
                "layer takes its parent's rows there once they are committed:" % (lay.name, len(held)))
            for rel in held:
                log("      " + rel)
        for rel, n in said:
            log("  inherit: %s: %s: %s" % (lay.name, rel, n))
        for rel in dead:
            log("  inherit: %s: %s is never installed (an Overlay copy of the same game file wins); not merged"
                % (lay.name, rel))
        if lwant is None:
            sd = _gv(base_dir, lay.name, STATE_DIR)
            have = {state_path(base_dir, lay.name, rel).lower() for rel, _a in mine.values()}
            for f in sorted(os.listdir(sd)) if os.path.isdir(sd) else ():
                if f.endswith(".txt") and os.path.join(sd, f).lower() not in have:
                    log("  inherit: %s: %s/%s remembers a file this layer no longer installs; delete it"
                        % (lay.name, STATE_DIR, f))
    for r in refused:
        log("  inherit: REFUSED " + r)
    return out


def sync_quietly(base_dir, log=print):
    """sync(), every failure swallowed: what the launchers call. A layer that could not be brought up to date is
    exactly as it was before this ran."""
    try:
        return sync(base_dir, log=log)
    except Exception as e:
        log("  inherit: skipped (%s)" % e)
        return []


def _main(argv):
    import sys
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dry = "--dry-run" in argv or "-n" in argv
    force = "--force" in argv
    porcelain = "--porcelain" in argv
    hook = "--hook" in argv
    nul = "-z" in argv
    only = argv[argv.index("--child") + 1] if "--child" in argv else None
    rels = None
    if "--only-stdin" in argv:
        rels = [p for p in sys.stdin.buffer.read().decode("utf-8", "surrogateescape").split("\0") if p]
    elif "--only" in argv:
        rels = argv[argv.index("--only") + 1:]

    def log(line):
        print(line, file=sys.stderr if porcelain else sys.stdout)

    try:
        if hook:
            # first without writing: a refusal must leave the tree exactly as it was
            refused = []
            would = sync(base, only=only, only_rels=rels, dry_run=True, log=lambda _l: None, hook=True,
                         refused=refused)
            if would and not refused and _partial_commit():
                refused.append("this is a partial commit (git commit -- <paths> / --only): the layer files it needs "
                               "(%s) would reach the commit but not the index. Commit without naming paths."
                               % ", ".join(would[:4]) + (" ..." if len(would) > 4 else ""))
            if refused:
                for r in refused:
                    print("  inherit: REFUSED " + r, file=sys.stderr)
                sys.stdout.write("REFUSED\n")
                return 3
        written = sync(base, only=only, only_rels=rels, dry_run=dry, force=force, log=log, hook=hook)
    except ValueError as e:
        print("version_inherit: " + str(e), file=sys.stderr)
        return 2
    if porcelain:
        out = sys.stdout.buffer
        for p in written:
            out.write(p.encode("utf-8", "surrogateescape") + (b"\0" if nul else b"\n"))
        out.flush()
        return 0
    if not written:
        print("Every layer already has its parent's rows.")
    elif dry:
        print("%d file(s) WOULD be written. Nothing was." % len(written))
    else:
        print("%d file(s) written." % len(written))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
