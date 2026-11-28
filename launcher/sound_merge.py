"""sound_merge.py -- a player's music (or sound) mod is kept and merged with the version's sound files at every
patched launch, instead of being overwritten (2026-11-28).

WHY
---
Berg, 2026-11-28 10:00 CET: "Some people would already have a music mod already installed. One thing I want to do, is
not overwrite their already installed music mod, but incorporate it dynamically into our changes."

The game's music is Sound/bgm.bnk, a Wwise bank (version 150): tracks, segments, playlists and one switch (751 objects),
and for each of its 345 songs only the song's first few KB -- the songs stream from Sound/Media/<id>.wem, starting
where the bank's bytes stop (a bank's bytes for a streamed song ARE the first bytes of its .wem: checked on every song
of Steam's and V2.0's bgm.bnk). A music mod either puts whole songs into bgm.bnk (a player's mod, bgm_bleach_anime.bnk:
130 songs, 235 MB, not one object changed) or replaces Media/<id>.wem files together with the first bytes in bgm.bnk.
The patch ships its own bgm.bnk (V2.0: 6 new songs; 4 segments with new songs and lengths), system.bnk, character
banks and Media .wem files, and install_overlay copied them over the mod: the mod's whole songs were gone, and a mod's
.wem files left in place were started with the first bytes of the songs they replaced -- the game froze or crashed
(Zangetsu's SP2, awakenings: leftovers.py, CHANGED SOUNDS).

AT A PATCHED LAUNCH (prepare(), called by install_overlay before it copies anything)
---------------------------------------------------------------------------------
1. The player's own file, for every Sound/ path the version writes:
   - the file in the game folder, when it is neither the version's, nor what this launcher last wrote there, nor any
     version's file in the repo, nor Steam's -- the player put it there since; it is copied into the launcher's
     backup (_launcher_vanilla_backup, where install_overlay keeps what was there before the patch; the backup it
     replaces moves to _launcher_quarantine\\sound\\<time>\\, nothing is deleted), so it survives the copy below and a
     vanilla start puts it back;
   - else the backup, when it is not Steam's file (a mod that was there before the patch's first launch);
   - else none: the player has no mod at that path.
2. A bank the repo has Steam's copy of (the vanilla version's Root: Sound/bgm.bnk, Sound/system.bnk) and the player
   has his own of: a three-way merge -- Steam's bank the base, the version's "ours", the player's "theirs". A music
   segment goes whole with its tracks and their songs (a song never mixes with the other side's segment), a sound with
   its song, any other object and song alone. What only the player changed comes from the player's bank, what only
   the version changed or added from the version's. What both changed is the player's when MOD_WINS (True: it is his
   music; Berg's words above), else the version's.
3. The Media .wem files the version ships: a song that is the player's after 2. keeps the player's .wem (his own, or
   Steam's when he did not change it) -- the version's is not copied over it. With no bank of his (a mod of .wem files
   only), a song he changed is his too when MOD_WINS.
4. Every bank the version writes gets, for each song it streams, the first bytes of the .wem that will be in the game
   folder: a mod's song whose bank is gone (overwritten by an older launcher) starts with its own bytes.
5. The merged banks are written to %LOCALAPPDATA%\\BROS Launcher\\sound_merge\\<game folder's key>\\ and installed
   instead of the version's files (install_overlay copies them as usual: its backup, its record, its revert). A merge
   is redone only when one of its inputs changed (state.json there, with what the launcher last wrote at each path).
   Not in the repo: an update's `git clean` empties Runtime\\, and without that record the launcher's own merged bank
   would look like a new mod of the player's. With no mod and every streamed song Steam's or the version's, nothing
   changes: the version's own files are installed, as before.

Never raises out of prepare(): a merge that fails is printed and the version's own file is installed for that path.
The written bank: Wwise's own layout -- the media in id order, each on a 16-byte offset, the header padded so the data
starts on 16 bytes, the objects in the version's order (an object only the player has goes before the object that
follows it in his bank: children before their parents, as Wwise writes them).

    python launcher/sound_merge.py <Steam's bank> <the version's bank> <the player's bank> <out.bnk>   a merge by hand

Python 3.8 (the players' Windows Python) is the floor; nothing outside the standard library.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import shutil
import struct
import sys
import time

MOD_WINS = True                      # what both changed: the player's music (Berg, 2026-11-28)
CODE = "sound_merge 1"               # part of every cache key: a new merge rule rebuilds every merged bank
SOUND = "Sound"
MEDIA = "Sound/Media/"
WORK_ENV = "BROS_SOUND_MERGE_DIR"      # where the merged banks and the record go (default: under %LOCALAPPDATA%)
QUARANTINE = ("_launcher_quarantine", "sound")
VANILLA = "Bleach Rebirth of Souls"  # the vanilla version: its Root holds Steam's copies of the banks patches change
FIELDS = 40                          # BKHD (bank version 150): version, bank id, language, alt values, project,
                                     # bank type, 16-byte hash -- the rest is zero padding
T_SOUND, T_SEGMENT, T_TRACK = 2, 10, 11


class BankError(Exception):
    pass


# ------------------------------------------------------------------------------------------------ a bank
class Bank(object):
    """A Wwise bank: its sections, media (id -> bytes) and objects ((type, id) -> body)."""

    def __init__(self, raw, name=""):
        self.name = name
        self.raw = raw
        self.sections = collections.OrderedDict()
        off = 0
        while off + 8 <= len(raw):
            tag = bytes(raw[off:off + 4]).decode("latin1")
            size = struct.unpack_from("<I", raw, off + 4)[0]
            if off + 8 + size > len(raw):
                raise BankError("%s: section %s runs past the end" % (name, tag))
            self.sections[tag] = (off + 8, size)
            off += 8 + size
        if "BKHD" not in self.sections:
            raise BankError("%s: not a Wwise bank" % name)
        bo, bs = self.sections["BKHD"]
        self.version = struct.unpack_from("<I", raw, bo)[0]
        if self.version != 150 or bs < FIELDS:
            raise BankError("%s: bank version %d, this merge reads 150" % (name, self.version))
        self.media = collections.OrderedDict()
        if "DIDX" in self.sections:
            do, ds = self.sections["DIDX"]
            data = self.sections.get("DATA")
            if data is None:
                raise BankError("%s: media listed but no DATA" % name)
            for i in range(ds // 12):
                mid, mo, ms = struct.unpack_from("<III", raw, do + 12 * i)
                if mo + ms > data[1]:
                    raise BankError("%s: media %d runs past DATA" % (name, mid))
                self.media[mid] = memoryview(raw)[data[0] + mo:data[0] + mo + ms]
        self.objects = collections.OrderedDict()
        if "HIRC" in self.sections:
            ho, hs = self.sections["HIRC"]
            n = struct.unpack_from("<I", raw, ho)[0]
            p = ho + 4
            for _ in range(n):
                t = raw[p]
                sz = struct.unpack_from("<I", raw, p + 1)[0]
                oid = struct.unpack_from("<I", raw, p + 5)[0]
                if p + 5 + sz > ho + hs:
                    raise BankError("%s: object %d runs past HIRC" % (name, oid))
                self.objects[(t, oid)] = memoryview(raw)[p + 5:p + 5 + sz]
                p += 5 + sz

    @classmethod
    def read(cls, path):
        with open(path, "rb") as f:
            return cls(f.read(), os.path.basename(path))

    @property
    def header(self):
        bo, bs = self.sections["BKHD"]
        return bytes(self.raw[bo:bo + bs])


def write_bank(path, header, media, objects, extra=()):
    """Write a bank in Wwise's layout. header: the BKHD payload (its first FIELDS bytes are kept, the padding made
    anew); media: {id: bytes}; objects: [((type, id), body)]; extra: [(tag, payload)] other sections, after HIRC."""
    fields = bytes(header[:FIELDS])
    ids = sorted(media)
    didx = bytearray()
    off = 0
    for mid in ids:
        didx += struct.pack("<III", mid, off, len(media[mid]))
        off += len(media[mid])
        off += (-off) % 16 if mid != ids[-1] else 0
    pad = (-(8 + FIELDS + 8 + len(didx) + 8)) % 16
    bkhd = fields + b"\0" * pad
    hirc_size = 4 + sum(5 + len(body) for _k, body in objects)
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(tmp, "wb") as f:
        f.write(b"BKHD" + struct.pack("<I", len(bkhd)) + bkhd)
        if ids:
            f.write(b"DIDX" + struct.pack("<I", len(didx)) + didx)
            f.write(b"DATA" + struct.pack("<I", off))
            pos = 0
            for mid in ids:
                f.write(media[mid])
                pos += len(media[mid])
                if mid != ids[-1]:
                    f.write(b"\0" * ((-pos) % 16))
                    pos += (-pos) % 16
        f.write(b"HIRC" + struct.pack("<II", hirc_size, len(objects)))
        for (t, _oid), body in objects:
            f.write(struct.pack("<BI", t, len(body)))
            f.write(body)
        for tag, payload in extra:
            f.write(tag.encode("latin1") + struct.pack("<I", len(payload)) + bytes(payload))
    os.replace(tmp, path)


# ------------------------------------------------------------------------------------------------ objects and songs
def track_info(body):
    """A music track's body -> (its songs' ids, its segment's id). Checked against wwiser on all 365 tracks of V2.0's
    and 359 of Steam's bgm.bnk."""
    p = 4 + 1
    n = struct.unpack_from("<I", body, p)[0]
    p += 4
    songs = []
    for _ in range(n):
        plugin, _stream, sid = struct.unpack_from("<IBI", body, p)
        p += 14
        if plugin & 0x0F == 2:                    # a source plugin's parameters follow it
            p += 4 + struct.unpack_from("<I", body, p)[0]
        songs.append(sid)
    m = struct.unpack_from("<I", body, p)[0]
    p += 4 + 44 * m
    if m:
        p += 4                                    # numSubTrack
    k = struct.unpack_from("<I", body, p)[0]
    p += 4
    for _ in range(k):
        p += 12 + 12 * struct.unpack_from("<I", body, p + 8)[0]
    nfx = body[p + 1]
    p += 2 + (1 + 6 * nfx if nfx else 0)
    nmeta = body[p + 1]
    p += 2 + 6 * nmeta
    return songs, struct.unpack_from("<I", body, p + 4)[0]


def sound_song(body):
    """A sound's body -> its song's id."""
    return struct.unpack_from("<I", body, 9)[0]


def streamed(data):
    """True when data is the start of a longer .wem (the rest streams from Sound/Media), False for a whole one."""
    if len(data) < 8 or bytes(data[:4]) != b"RIFF":
        return False
    return struct.unpack_from("<I", data, 4)[0] + 8 > len(data)


def units(*banks):
    """The pieces that go together: {key: (object keys, song ids)} -- a music segment with its tracks and their songs,
    a sound with its song -- over every bank given (a segment's tracks can differ between them)."""
    out = collections.defaultdict(lambda: (set(), set()))
    for bank in banks:
        if bank is None:
            continue
        for (t, oid), body in bank.objects.items():
            try:
                if t == T_TRACK:
                    songs, parent = track_info(body)
                    key = ("seg", parent) if any((T_SEGMENT, parent) in b.objects for b in banks if b) else \
                        ("trk", oid)
                    out[key][0].add((t, oid))
                    if key[0] == "seg":
                        out[key][0].add((T_SEGMENT, parent))
                    out[key][1].update(songs)
                elif t == T_SOUND:
                    out[("snd", oid)][0].add((t, oid))
                    out[("snd", oid)][1].add(sound_song(body))
            except (struct.error, IndexError):
                continue                          # an object this reader does not know: merged on its own
    return dict(out)


def _same(a, b):
    return a is None and b is None or a is not None and b is not None and len(a) == len(b) and a == b


def merge(base, ours, theirs, mod_wins=MOD_WINS):
    """Three-way merge of banks (module docstring, 2.). Returns (objects [((type, id), body)], media {id: bytes},
    the ids of the songs whose bytes are the player's and not the version's, a report {what: count})."""
    side_obj, side_song, rep = {}, {}, collections.Counter()

    def changed(bank, keys, songs):
        return (any(not _same(bank.objects.get(k), base.objects.get(k)) for k in keys) or
                any(not _same(bank.media.get(s), base.media.get(s)) for s in songs))

    for key, (keys, songs) in units(base, ours, theirs).items():
        mod, ver = changed(theirs, keys, songs), changed(ours, keys, songs)
        if not mod:
            continue
        side = "theirs" if (not ver or mod_wins) else "ours"
        rep["both changed: the player's" if ver and side == "theirs" else "both changed: the version's" if ver else
            "the player's only"] += 1
        for k in keys:
            if side == "theirs" or k not in side_obj:
                side_obj[k] = side
        for s in songs:
            if side == "theirs" or s not in side_song:
                side_song[s] = side
    # Objects and songs in no unit: on their own.
    for k in theirs.objects:
        if k not in side_obj and not _same(theirs.objects.get(k), base.objects.get(k)):
            if _same(ours.objects.get(k), base.objects.get(k)) or k not in ours.objects:
                side_obj[k] = "theirs"
                rep["objects: the player's only"] += 1
            else:
                rep["objects both changed: the version's"] += 1
    for s in theirs.media:
        if s not in side_song and not _same(theirs.media.get(s), base.media.get(s)):
            if _same(ours.media.get(s), base.media.get(s)) or s not in ours.media:
                side_song[s] = "theirs"
                rep["songs: the player's only"] += 1
            else:
                side_song[s] = "theirs" if mod_wins else "ours"
                rep["songs both changed: the player's" if mod_wins else "songs both changed: the version's"] += 1

    # The objects: the version's order; an object only the player has goes before the next one his bank lists.
    objects = []
    for k, body in ours.objects.items():
        if side_obj.get(k) == "theirs" and k in theirs.objects:
            body = theirs.objects[k]
        objects.append((k, body))
    pos = {k: i for i, (k, _b) in enumerate(objects)}
    extra = [k for k in theirs.objects if k not in ours.objects and side_obj.get(k) == "theirs"]
    if extra:
        torder = list(theirs.objects)
        tpos = {k: i for i, k in enumerate(torder)}
        inserts = collections.defaultdict(list)
        for k in extra:
            anchor = next((a for a in torder[tpos[k] + 1:] if a in pos), None)
            inserts[anchor].append(k)
        out = []
        for k, body in objects:
            for e in inserts.get(k, ()):
                out.append((e, theirs.objects[e]))
            out.append((k, body))
        for e in inserts.get(None, ()):
            out.append((e, theirs.objects[e]))
        objects = out
    media = collections.OrderedDict()
    for s in set(ours.media) | set(theirs.media):
        if side_song.get(s) == "theirs" and s in theirs.media or s not in ours.media:
            media[s] = theirs.media[s]
        else:
            media[s] = ours.media[s]
    rep["objects"] = len(objects)
    rep["songs"] = len(media)
    # The player's songs: those whose bytes now are his and not the version's (their files must be his too).
    mine = {x for x, v in side_song.items() if v == "theirs" and x in media and
            (x not in ours.media or not _same(media[x], ours.media[x]))}
    return objects, media, mine, dict(rep)


def fix_starts(media, wem_for, log=None):
    """For every streamed song, its first bytes as in the .wem that will be in the game folder (module docstring, 4.).
    wem_for(id) -> path or None. Returns the ids changed."""
    fixed = []
    for mid in list(media):
        data = media[mid]
        if not streamed(data):
            continue
        path = wem_for(mid)
        if not path:
            continue
        try:
            with open(path, "rb") as f:
                head = f.read(len(data))
        except OSError:
            continue
        if head == bytes(data):
            continue
        media[mid] = head                         # (a file shorter than the start it replaces goes in whole)
        fixed.append(mid)
    if fixed and log:
        log("[sound] %d song start(s) re-read from the song files on disk: %s" % (len(fixed), ", ".join(
            str(m) for m in fixed[:8]) + (" ..." if len(fixed) > 8 else "")))
    return fixed


def index(path):
    """{song id: (offset in the file, size, streamed)} of a bank, read by seeks (a 58 MB bank is not read whole)."""
    out = collections.OrderedDict()
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        secs, off = {}, 0
        while off + 8 <= size:
            f.seek(off)
            h = f.read(8)
            secs[h[:4].decode("latin1")] = (off + 8, struct.unpack("<I", h[4:])[0])
            off += 8 + secs[h[:4].decode("latin1")][1]
        if "DIDX" not in secs or "DATA" not in secs:
            return out
        f.seek(secs["DIDX"][0])
        didx = f.read(secs["DIDX"][1])
        for i in range(len(didx) // 12):
            mid, mo, ms = struct.unpack_from("<III", didx, 12 * i)
            f.seek(secs["DATA"][0] + mo)
            h = f.read(8)
            out[mid] = (secs["DATA"][0] + mo, ms, h[:4] == b"RIFF" and struct.unpack("<I", h[4:])[0] + 8 > ms)
    return out


def _read_at(path, off, n):
    with open(path, "rb") as f:
        f.seek(off)
        return f.read(n)


# ------------------------------------------------------------------------------------------------ files
def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class _Hashes(object):
    """sha1 of files, kept by path, size and time across launches (a 235 MB bank is hashed once, not every launch)."""

    def __init__(self, saved=None):
        self.saved = saved if saved is not None else {}

    def __call__(self, path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        key = os.path.normcase(os.path.abspath(path))
        old = self.saved.get(key)
        if old and old[0] == st.st_size and old[1] == st.st_mtime_ns:
            return old[2]
        h = sha1_file(path)
        self.saved[key] = [st.st_size, st.st_mtime_ns, h]
        return h


def _stat(path):
    try:
        st = os.stat(path)
        return [st.st_size, st.st_mtime_ns]
    except (OSError, TypeError):
        return None


def _steam_row(steam, rel):
    """(size, sha1 or None) of Steam's file at rel, or None. steam: vanilla_revert.SteamList, or a {lower rel:
    (rel, size, sha1)} dict, or None."""
    files = getattr(steam, "files", steam) or {}
    row = files.get(rel.lower())
    if not row:
        return None
    hashed = getattr(steam, "hashed", True)
    sha = row[2] if hashed and row[2] and row[2] != "-" else None
    return int(row[1]), (sha.lower() if sha and len(sha) == 40 else None)


def is_steams(path, row, sha1):
    """path is Steam's file (row = _steam_row): by size, and by sha1 when Steam's list has it."""
    if row is None or not os.path.exists(path):
        return False
    if os.path.getsize(path) != row[0]:
        return False
    return row[1] is None or sha1(path) == row[1]


def _known_versions(base_dir, rel):
    """Every version's file at rel in the repo: GameVersions/*/{Root,Overlay}/rel."""
    out = []
    gv = os.path.join(base_dir, "GameVersions")
    try:
        names = os.listdir(gv)
    except OSError:
        return out
    for v in names:
        for sub in ("Root", "Overlay"):
            p = os.path.join(gv, v, sub, *rel.split("/"))
            if os.path.isfile(p):
                out.append(p)
    return out


def _quarantine(game, rel, path, log):
    dst = os.path.join(game, *QUARANTINE, time.strftime("%Y%m%d-%H%M%S"), *rel.split("/"))
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(path, dst)
        log("[sound] the earlier backup of %s moved to %s" % (rel, os.path.relpath(dst, game)))
        return True
    except OSError as e:
        log("[sound] the earlier backup of %s could not be moved aside (%s): it stays" % (rel, e))
        return False


def players_file(game, base_dir, rel, src, backup_root, steam, recent, sha1, log):
    """The player's own file at rel (module docstring, 1.), or None. A file in the game folder that the launcher did not
    write there (not the version's, not what it last wrote, no other version's) is the player's latest: it replaces the
    backup (the one before goes to the quarantine) -- also when it is Steam's (a verify: the mod is gone, and is no
    longer merged)."""
    row = _steam_row(steam, rel)
    g = os.path.join(game, *rel.split("/"))
    b = os.path.join(backup_root, *rel.split("/"))
    if os.path.isfile(g):
        gs = os.path.getsize(g)
        ours = [src] + [p for p in _known_versions(base_dir, rel) if not _is_vanilla(base_dir, p)]
        mine = any(os.path.getsize(p) == gs and sha1(p) == sha1(g) for p in ours if os.path.isfile(p))
        if not mine and recent and sha1(g) in recent:
            mine = True                           # what this launcher wrote there (one of its last few files)
        if not mine:
            steams = is_steams(g, row, sha1)
            if not (os.path.isfile(b) and sha1(b) == sha1(g)):
                if os.path.isfile(b) and not _quarantine(game, rel, b, log):
                    return None if steams else g
                os.makedirs(os.path.dirname(b), exist_ok=True)
                shutil.copy2(g, b)
                log("[sound] %s: %s" % (rel, "Steam's own file again (a verify?): no mod there any more" if steams else
                                        "the player's own file (a mod?): kept, and merged with the version's"))
            return None if steams else b
    if os.path.isfile(b) and not is_steams(b, row, sha1):
        return b
    return None


def _drop(path):
    """A merged bank the launcher made and no longer installs (only its own cache, in the work folder)."""
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _is_vanilla(base_dir, path):
    v = os.path.join(base_dir, "GameVersions", VANILLA)
    return os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(os.path.abspath(v)) + os.sep)


def _installable(path, game, rel, rt):
    """path, or a copy of it in the work folder's files\\ when it IS the game folder's file at rel (install_overlay
    copies a source over its destination)."""
    g = os.path.join(game, *rel.split("/"))
    if os.path.normcase(os.path.abspath(path)) != os.path.normcase(os.path.abspath(g)):
        return path
    dst = os.path.join(rt, "files", *rel.split("/"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(path, dst)
    return dst


def _steam_copy(game, base_dir, rel, backup_root, steam, sha1):
    """A copy of Steam's file at rel, or None: the backup, the game folder or the vanilla version's Root."""
    row = _steam_row(steam, rel)
    for p in (os.path.join(backup_root, *rel.split("/")), os.path.join(game, *rel.split("/")),
              os.path.join(base_dir, "GameVersions", VANILLA, "Root", *rel.split("/"))):
        if os.path.isfile(p) and is_steams(p, row, sha1):
            return p
    return None


# ------------------------------------------------------------------------------------------------ the launch
def work_dir(game):
    """The merged banks' and the record's folder for this game folder (module docstring, 5.)."""
    root = os.environ.get(WORK_ENV)
    if not root:
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
        root = os.path.join(base, "BROS Launcher", "sound_merge")
    key = hashlib.sha1(os.path.normcase(os.path.abspath(game)).encode("utf-8")).hexdigest()[:12]
    return os.path.join(root, key)


def prepare(game, base_dir, pairs, backup_root, steam=None, log=print, mod_wins=MOD_WINS):
    """{rel: file to install instead of the version's} for the Sound/ paths of pairs (install_overlay's [(source,
    rel)]) -- module docstring. Never raises."""
    try:
        return _prepare(game, base_dir, pairs, backup_root, steam, log, mod_wins)
    except Exception as e:                        # the sound merge is an extra: the version's files go in as before
        log("[sound] not merged (%s: %s): the version's own sound files are installed" % (type(e).__name__, e))
        return {}


def _prepare(game, base_dir, pairs, backup_root, steam, log, mod_wins):
    rt = work_dir(game)
    state_path = os.path.join(rt, "state.json")
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        if state.get("code") != CODE:
            state = {}
    except (OSError, ValueError):
        state = {}
    state["code"] = CODE
    written = state.setdefault("written", {})
    cache = state.setdefault("cache", {})
    sha1 = _Hashes(state.setdefault("hashes", {}))
    sound = [(src, rel) for src, rel in pairs if rel.lower().startswith("sound/")]
    if not sound:
        return {}
    src_of = {rel: src for src, rel in sound}
    banks = [rel for rel in src_of if rel.lower().endswith(".bnk")]
    wems = {int(os.path.basename(rel)[:-4]): rel for rel in src_of
            if rel.lower().startswith(MEDIA.lower()) and rel.lower().endswith(".wem") and
            os.path.basename(rel)[:-4].isdigit()}
    theirs_of = {}
    for rel in src_of:
        p = players_file(game, base_dir, rel, src_of[rel], backup_root, steam, written.get(rel) or [], sha1, log)
        if p:
            theirs_of[rel] = p
    overrides = {}
    players_songs = set()

    # 2. banks the repo has Steam's copy of, with a bank of the player's: merged (or the last merge, if nothing changed)
    plans = {}
    for rel in banks:
        theirs = theirs_of.get(rel)
        if not theirs:
            continue
        base_p = os.path.join(base_dir, "GameVersions", VANILLA, "Root", *rel.split("/"))
        row = _steam_row(steam, rel)
        if not os.path.isfile(base_p) or (row is not None and not is_steams(base_p, row, sha1)):
            log("[sound] %s: the player's own bank, but the repo has no copy of Steam's to merge against: the "
                "version's is installed" % rel)
            continue
        plans[rel] = (base_p, theirs)
    merged = {}
    for rel, (base_p, theirs) in plans.items():
        c = cache.get(rel) or {}
        if c.get("inputs") == json.loads(json.dumps([CODE, mod_wins, _stat(src_of[rel]), _stat(theirs),
                                                     _stat(base_p)])) and "songs" in c:
            players_songs |= set(c["songs"])      # the same three banks as last time: the same songs are his
            merged[rel] = None
            continue
        try:
            b, o, t = Bank.read(base_p), Bank.read(src_of[rel]), Bank.read(theirs)
            objects, media, songs, rep = merge(b, o, t, mod_wins)
        except (BankError, OSError, struct.error) as e:
            log("[sound] %s: not merged (%s): the version's is installed" % (rel, e))
            continue
        players_songs |= songs
        merged[rel] = (o, objects, media, rep)
        c.update(inputs=[CODE, mod_wins, _stat(src_of[rel]), _stat(theirs), _stat(base_p)], songs=sorted(songs),
                 key=None)
        cache[rel] = c

    # 3. the version's .wem files: the player's, for his songs
    wem_final = {}
    for mid, rel in wems.items():
        mine = theirs_of.get(rel)
        if mid in players_songs:
            p = mine or _steam_copy(game, base_dir, rel, backup_root, steam, sha1)
            if p:
                overrides[rel] = wem_final[mid] = _installable(p, game, rel, rt)
                continue
            log("[sound] %s: the player's song, but no copy of his file or Steam's: the version's is installed" % rel)
        elif mine and mod_wins:
            overrides[rel] = wem_final[mid] = _installable(mine, game, rel, rt)
            players_songs.add(mid)
            continue
        wem_final[mid] = src_of[rel]

    def wem_for(mid):
        if mid in wem_final:
            return wem_final[mid]
        p = os.path.join(game, "Sound", "Media", "%d.wem" % mid)
        return p if os.path.isfile(p) else None

    # 4. + 5. every bank the version writes: its streamed songs start as the files on disk do
    def out_key(rel, songs):
        # As state.json gives it back (lists, not tuples); a song file by its size and time, wherever it is copied from.
        return json.loads(json.dumps([CODE, mod_wins, _stat(src_of[rel]),
                                      (cache.get(rel) or {}).get("inputs") if rel in merged else None,
                                      [[m, _stat(wem_for(m))] for m in sorted(songs)]]))

    for rel in banks:
        src = src_of[rel]
        out = os.path.join(rt, *rel.split("/"))
        c = cache.setdefault(rel, {})
        try:
            idx = index(src)
        except (OSError, struct.error) as e:
            log("[sound] %s: not read (%s): installed as it is" % (rel, e))
            continue
        ours_streamed = set(m for m, (_o, _n, st) in idx.items() if st)
        # The songs the last result streamed: the version's, and the player's when it was a merge.
        if c.get("key") == out_key(rel, ours_streamed | set(c.get("streamed", []))) and \
                (not c.get("out") or os.path.isfile(out)):
            if c.get("out"):
                overrides[rel] = out
            else:
                _drop(out)
            continue
        if rel in merged and merged[rel] is None:     # the same three banks, a song file changed: merged again
            b, o, t = Bank.read(plans[rel][0]), Bank.read(src), Bank.read(plans[rel][1])
            objects, media, _songs, rep = merge(b, o, t, mod_wins)
            merged[rel] = (o, objects, media, rep)
        if rel in merged:
            o, objects, media, rep = merged[rel]
        else:
            # The version's bank and nobody else's: rewritten only if a streamed song's file starts otherwise.
            differs = any(wem_for(m) and _read_at(wem_for(m), 0, idx[m][1]) != _read_at(src, idx[m][0], idx[m][1])
                          for m in sorted(ours_streamed))
            if not differs:
                c.update(key=out_key(rel, ours_streamed), out=None, streamed=sorted(ours_streamed))
                _drop(out)
                continue
            o = Bank.read(src)
            objects, media, rep = list(o.objects.items()), collections.OrderedDict(o.media), {}
        fixed = fix_starts(media, wem_for)
        extra = [(tag, o.raw[a:a + n]) for tag, (a, n) in o.sections.items()
                 if tag not in ("BKHD", "DIDX", "DATA", "HIRC")]
        write_bank(out, o.header, media, objects, extra)
        final_streamed = set(m for m, d in media.items() if streamed(d))
        c.update(key=out_key(rel, ours_streamed | final_streamed), out=out, streamed=sorted(final_streamed))
        log("[sound] %s: %s%s -> %s" % (
            rel, "merged with the player's own (%s)" % ", ".join("%s %d" % (k, v) for k, v in sorted(rep.items())
                                                                if k not in ("objects", "songs")) if rep else
            "the version's", ", %d song start(s) as the files on disk" % len(fixed) if fixed else "", out))
        overrides[rel] = out
    # What will be in the game folder after the copy: the next launch knows its own files by these.
    for src, rel in sound:
        h = sha1(overrides.get(rel, src))
        if h:
            before = written.get(rel)
            before = before if isinstance(before, list) else []
            written[rel] = [h] + [x for x in before if x != h][:4]
    try:
        os.makedirs(rt, exist_ok=True)
        with open(state_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1, sort_keys=True)
        os.replace(state_path + ".tmp", state_path)
    except OSError as e:
        log("[sound] the merge's record was not written (%s)" % e)
    if players_songs:
        log("[sound] %d of the player's own songs kept" % len(players_songs))
    return overrides


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if len(a) != 4:
        print(__doc__.split("\n\n")[0])
        print("usage: python sound_merge.py <Steam's bank> <the version's bank> <the player's bank> <out.bnk>")
        return 2
    b, o, t = (Bank.read(p) for p in a[:3])
    objects, media, songs, rep = merge(b, o, t)
    extra = [(tag, o.raw[x:x + n]) for tag, (x, n) in o.sections.items() if tag not in ("BKHD", "DIDX", "DATA", "HIRC")]
    write_bank(a[3], o.header, media, objects, extra)
    print("%s: %d objects, %d songs, %d of them the player's; %s" % (a[3], len(objects), len(media), len(songs), rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
