"""save_unlock.py -- unlock a character in the player's OWN save (V1.5 delivery B.2, pass rn, 2026-11-02).

Berg (V15 plan, answer 7): "Unlock Dangai without overwriting the save". Until now "Unlock Dangai Ichigo" copied
ressources\\savedata.bin -- another player's whole save: settings, items, ranked record and that player's online
identity -- over every save of the player. This module sets the ONE flag the character's own row names, in the
player's own save, keeps a backup first, and proves the result byte for byte.

WHAT UNLOCKS A CHARACTER (history rn074; read from the game's files and its exe):
  * Script\\Play_menu_chara.bin: a character's row may carry an "アンロック" (unlock) column. pl002, Dangai Ichigo:
    "nd_04_000_0350_end", a story flag (chapter 4, node 0350 finished). The other unlock columns name DLC ids, which
    are no flags: refused here.
  * Script\\SaveDataScript.cat: the game's list of flags. PZZE (zlib) -> a version-1 container -> member key 0 (the
    exe's lookup, 0x1409db400) -> the first variable class's table at member + int32[member + 0x14] (0x1401c5e78):
    u32 count, then count entries of (u32 name hash, u32 default, u32 group). Flag i is the i-th entry
    (SaveCommonFlag's Init, 0x1401c4440). The game appends: the 1,731 flags of Bros 1.0 are the first 1,731 of
    today's 1,891, so an index never moves.
  * savedata.bin: com_flag (SaveComFlagData { uint32_t sData[1024]; }) is the flags' buffer as the game keeps it:
    sData[0] = the count, flag i = sData[1 + i / 32] bit i % 32 (SaveCommonFlag's Load, 0x1401c4650).
    nd_04_000_0350_end = flag 284 = sData[9] bit 28.

THE SAVE (self-describing; no checksum: every byte belongs to the tree):
    FILE := u32 n ; ELEM[n]
    ELEM := u32 typeHash ; u32 nameHash ; u32 index ; BODY
    BODY := a struct (typeHash = the struct's tag in Script\\define.bin): u32 k ; ELEM[k]
            a primitive: sizeof(type) bytes (char, int8_t, bool 1; int16_t, uint16_t 2; int, int32_t, uint32_t,
            float 4; int64_t 8)
    hash := zlib.crc32(name, len(name) ^ 0xFFFFFFFF) ^ 0xFFFFFFFF   (the game's)
  A save is used only when every byte is accounted for and every type is known. The edit changes one bit of one
  byte; the file is written whole (.su_tmp + os.replace), read back, parsed again, and compared with the original:
  exactly that byte differs, or the original is put back.

    status(base_dir, game_path, chara="pl002")   -> (ok, text, results)   every save of the player, read only
    unlock(base_dir, game_path, chara="pl002")   -> (ok, text, results)   the same, and the flag set where it is not
CLI (a developer's check):  python launcher\\save_unlock.py status|unlock [--game <game folder>] [--chara pl002]

THE ONLINE CHARACTER AT A VANILLA START (2026-11-28)
Berg: "if you also had zangetsu selected from v2.0 and then go online from vanilla, you would be stuck unable to go
online. You have to go through ranked, and then change characters from there to play. I want to make it convenient
and just switch you to pl000 selected online when you switch to vanilla."
  * savedata.bin: onlinematch (SaveOnlineMatch) holds MyChara and MyCostume (int): the character and costume the
    online menus start from (Ranked's character select writes them). MyChara is the character's id, pl<id>
    (the save that "Unlock Dangai Ichigo" used to copy has 2, Dangai Ichigo).
  * The characters only the patch makes playable: the Steam game's IsPlayableCharacter refuses them, the patch's
    roster tables admit them (Files/Matchmaking/bros_roster.c): 5 Zangetsu (V2.0, the CP), 15 Yumichika, 34 Orihime,
    and 9 with Orihime (V1.2 with her, V1.7).
  * A vanilla start (the launcher, after vanilla_revert's proof) sets MyChara to 0 (pl000, Ichigo) and MyCostume to 0
    in every save whose MyChara is one of those -- the same way as the unlock: a backup first, the file written whole,
    read back, parsed again, and exactly those 8 bytes changed, or the original is put back. Any other character is
    left as it is.
    vanilla_online(game_path)                    -> (ok, text, results)   every save; changes only those
CLI:  python launcher\\save_unlock.py online|online-reset [--game <game folder>]   (online: read only)
"""
import datetime
import json
import os
import shutil
import struct
import sys
import zlib

EXE_NAME = "BLEACH_Rebirth_of_Souls.exe"
SAVE_NAME = "savedata.bin"
SAVE_ROOT = ("BLEACH Rebirth of Souls", "Savedata")          # under %APPDATA%
UNLOCK_COLUMN = "アンロック"
ID_COLUMN = "ID"
FLAGS_VARIABLE = "com_flag"                                     # the root field that holds the flags
TMP_SUFFIX = ".su_tmp"
NAMES = {"pl002": "Dangai Ichigo"}

# sizeof() of the save's primitive types (define.bin's spelling)
SIZES = {"char": 1, "int8_t": 1, "uint8_t": 1, "bool": 1, "int16_t": 2, "uint16_t": 2, "int": 4, "int32_t": 4,
         "uint32_t": 4, "float": 4, "int64_t": 8, "uint64_t": 8, "double": 8}


class SaveError(Exception):
    """Refused: nothing was written."""


def ghash(text):
    b = text.encode("utf-8")
    return zlib.crc32(b, len(b) ^ 0xFFFFFFFF) ^ 0xFFFFFFFF


def _u32(d, o):
    if o < 0 or o + 4 > len(d):
        raise SaveError("read past the end (offset %d of %d)" % (o, len(d)))
    return struct.unpack_from("<I", d, o)[0]


def _read(path):
    with open(path, "rb") as f:
        return f.read()


# ------------------------------------------------------------------------------------ the game's own tables
def unpack_pzze(raw):
    """A PZZE file's payload (magic, subtype, u64 size, u64 offset, zlib); a file without the wrapper as it is."""
    if raw[:4] != b"PZZE":
        return raw
    if len(raw) < 0x18:
        raise SaveError("a PZZE header cut short")
    size, off = struct.unpack_from("<QQ", raw, 8)
    try:
        data = zlib.decompress(raw[off:])
    except zlib.error as e:
        raise SaveError("the PZZE payload does not inflate: %s" % e)
    if len(data) != size:
        raise SaveError("the PZZE payload is %d bytes, its header says %d" % (len(data), size))
    return data


def cat_member(u, key=0):
    """(offset, size) of a version-1 container's member, found the way the exe finds it (0x1409db400): u32 version,
    u32 n, u32 0, then n offsets, n sizes, n keys."""
    if len(u) < 0x10 or _u32(u, 0) != 1:
        raise SaveError("not a version-1 container")
    n = _u32(u, 4)
    if not 0 < n < 4096 or 0xC + 12 * n > len(u):
        raise SaveError("a container header with %d members" % n)
    for i in range(n):
        if _u32(u, 0xC + 8 * n + 4 * i) == key:
            off, size = _u32(u, 0xC + 4 * i), _u32(u, 0xC + 4 * n + 4 * i)
            if off < 0xC + 12 * n or off + size > len(u):
                raise SaveError("member %d lies outside the container" % key)
            return off, size
    raise SaveError("the container has no member %d" % key)


def flag_table(cat_bytes):
    """The flags of SaveDataScript.cat, by index: [name hash]."""
    u = unpack_pzze(cat_bytes)
    m, size = cat_member(u, 0)
    rel = struct.unpack_from("<i", u, m + 0x14)[0] if m + 0x18 <= len(u) else 0
    if rel <= 0 or rel >= size:
        raise SaveError("SaveDataScript.cat names no flag table")
    t = m + rel
    n = _u32(u, t)
    if not 0 < n <= 32 * 1023 or t + 4 + 12 * n > m + size:
        raise SaveError("a flag table of %d entries does not fit" % n)
    keys = [_u32(u, t + 4 + 12 * i) for i in range(n)]
    defaults = [_u32(u, t + 8 + 12 * i) for i in range(n)]
    if len(set(keys)) != n:
        raise SaveError("the flag table repeats a flag")
    if any(v not in (0, 1) for v in defaults):
        raise SaveError("the flag table has a default that is not 0 or 1")
    return keys


def _strings_decoded(raws):
    """A row table's strings are all XOR 0xAA, or none are (DataChakka's ScriptTables.h); decide for the whole file:
    a per-string guess reads XOR'd "名前" as the ASCII "O:'O#'"."""
    for xor in (True, False):
        out = []
        try:
            for r in raws:
                t = (bytes(b ^ 0xAA for b in r) if xor else r).decode("utf-8")
                if not all(c.isprintable() or c in "\r\n\t" for c in t):
                    raise ValueError(t)
                out.append(t)
            return out
        except (UnicodeDecodeError, ValueError):
            continue
    raise SaveError("a row table whose text is neither plain nor XOR 0xAA")


def read_rows(data):
    """A Script row table (Play_menu_chara.bin): [[ (column name, [(key, value)]) ]]."""
    o = [0]
    raws = []

    def u32():
        v = _u32(data, o[0])
        o[0] += 4
        return v

    def s():
        n = u32()
        if o[0] + n >= len(data) or data[o[0] + n] != 0:
            raise SaveError("a row-table string without its NUL")
        raws.append(data[o[0]:o[0] + n])
        o[0] += n + 1
        return len(raws) - 1

    shape = []
    for _ in range(u32()):
        cols = []
        for _ in range(u32()):
            name = s()
            cols.append((name, [(s(), s()) for _ in range(u32())]))
        shape.append(cols)
    if o[0] != len(data):
        raise SaveError("a row table with %d bytes left over" % (len(data) - o[0]))
    txt = _strings_decoded(raws)
    return [[(txt[n], [(txt[k], txt[v]) for k, v in kv]) for n, kv in cols] for cols in shape]


def unlock_flag(game_path, chara):
    """The flag in chara's unlock column of the installed Script\\Play_menu_chara.bin."""
    p = os.path.join(game_path, "Script", "Play_menu_chara.bin")
    try:
        rows = read_rows(_read(p))
    except (OSError, SaveError) as e:
        raise SaveError("Script\\Play_menu_chara.bin: %s" % e)
    for cols in rows:
        values = {}
        for _name, kv in cols:
            for k, v in kv:
                values.setdefault(k, v)
        if values.get(ID_COLUMN) == chara:
            if UNLOCK_COLUMN not in values:
                raise SaveError("%s has no unlock in Script\\Play_menu_chara.bin: nothing to unlock" % chara)
            return values[UNLOCK_COLUMN]
    raise SaveError("Script\\Play_menu_chara.bin has no row for %s" % chara)


def flag_index(game_path, name):
    """(index, count): name's place in the installed Script\\SaveDataScript.cat."""
    p = os.path.join(game_path, "Script", "SaveDataScript.cat")
    try:
        keys = flag_table(_read(p))
    except (OSError, SaveError) as e:
        raise SaveError("Script\\SaveDataScript.cat: %s" % e)
    h = ghash(name)
    if h not in keys:
        raise SaveError("%s is not one of the game's %d flags (a DLC id, not a flag?)" % (name, len(keys)))
    return keys.index(h), len(keys)


# ------------------------------------------------------------------------------------ the save's declaration
class Declaration:
    """Script\\define.bin: the save's C declaration. structs {type hash: tag}, root fields {name: (type, count)}."""

    def __init__(self, data):
        o = [0]

        def u32():
            v = _u32(data, o[0])
            o[0] += 4
            return v

        def s():
            n = u32()
            if o[0] + n >= len(data) or data[o[0] + n] != 0:
                raise SaveError("a define.bin string without its NUL")
            r = data[o[0]:o[0] + n]
            o[0] += n + 1
            return r

        def fields():
            out = []
            for _ in range(u32()):
                name, typ = s(), s()
                count, k = u32(), u32()
                o[0] += 4 * k
                out.append((name, typ, count))
            return out

        raw_structs = []
        for _ in range(u32()):
            tag = s()
            tds = [s() for _ in range(u32())]
            raw_structs.append((tag, tds, fields()))
        raw_root = fields()
        if o[0] != len(data):
            raise SaveError("define.bin has %d bytes left over" % (len(data) - o[0]))
        strings = []
        for tag, tds, fl in raw_structs:
            strings += [tag] + tds + [x for f in fl for x in f[:2]]
        strings += [x for f in raw_root for x in f[:2]]
        txt = iter(_strings_decoded(strings))
        self.struct_by_name = {}                     # any of a struct's names -> (tag, [(field, type, count)])
        self.tags = {}                               # type hash -> tag
        for tag, tds, fl in raw_structs:
            tag = next(txt)
            names = [next(txt) for _ in tds]
            flds = []
            for _n, _t, c in fl:
                flds.append((next(txt), next(txt), c))
            for nm in [tag] + names:
                self.struct_by_name[nm] = (tag, flds)
            self.tags[ghash(tag)] = tag
        self.root = []
        for _n, _t, c in raw_root:
            self.root.append((next(txt), next(txt), c))
        self.prims = {ghash(t): (t, SIZES[t]) for t in SIZES}

    def field(self, name):
        for n, t, c in self.root:
            if n == name:
                return t, c
        raise SaveError("define.bin declares no %s" % name)


def parse_save(data, decl):
    """The save's tree, every byte of it: [(type hash, name hash, index, offset, kids | (value offset, size))].
    Refused: an unknown type, a count or a size past the end, bytes left over."""
    def elem(o, depth):
        if depth > 16:
            raise SaveError("a save nested deeper than any declaration")
        th, nh, idx = _u32(data, o), _u32(data, o + 4), _u32(data, o + 8)
        if th in decl.tags:
            k = _u32(data, o + 12)
            if k > len(data):
                raise SaveError("a struct of %d members at offset %d" % (k, o))
            q = o + 16
            kids = []
            for _ in range(k):
                e, q = elem(q, depth + 1)
                kids.append(e)
            return (th, nh, idx, o, kids), q
        if th in decl.prims:
            size = decl.prims[th][1]
            if o + 12 + size > len(data):
                raise SaveError("a value cut short at offset %d" % o)
            return (th, nh, idx, o, (o + 12, size)), o + 12 + size
        raise SaveError("an unknown type (hash %08x) at offset %d" % (th, o))

    n = _u32(data, 0)
    if n > len(data):
        raise SaveError("a save of %d elements" % n)
    q = 4
    root = []
    for _ in range(n):
        e, q = elem(q, 0)
        root.append(e)
    if q != len(data):
        raise SaveError("the save has %d bytes after its last element" % (len(data) - q))
    return root


def flag_slot(data, decl, index):
    """(byte offset, mask, the save's flag count) of flag `index` in a save's com_flag."""
    root = parse_save(data, decl)
    ftype, fcount = decl.field(FLAGS_VARIABLE)
    if ftype not in decl.struct_by_name or fcount != 1:
        raise SaveError("define.bin's %s is not one struct" % FLAGS_VARIABLE)
    tag, flds = decl.struct_by_name[ftype]
    if len(flds) != 1 or flds[0][1] != "uint32_t":
        raise SaveError("define.bin's %s is not one uint32_t array" % tag)
    fname, _ft, words = flds[0]
    found = [e for e in root if e[1] == ghash(FLAGS_VARIABLE)]
    if len(found) != 1:
        raise SaveError("the save holds %d %s" % (len(found), FLAGS_VARIABLE))
    th, _nh, idx, off, kids = found[0]
    if th != ghash(tag) or idx != 0 or not isinstance(kids, list):
        raise SaveError("the save's %s is not a %s" % (FLAGS_VARIABLE, tag))
    if len(kids) != words:
        raise SaveError("the save's %s has %d words, the game's %d" % (FLAGS_VARIABLE, len(kids), words))
    u32h, nameh = ghash("uint32_t"), ghash(fname)
    for i, k in enumerate(kids):
        if k[0] != u32h or k[1] != nameh or k[2] != i:
            raise SaveError("the save's %s word %d is not %s[%d]" % (FLAGS_VARIABLE, i, fname, i))
    count = struct.unpack_from("<I", data, kids[0][4][0])[0]
    if count <= index:
        raise SaveError("the save knows %d flags; flag %d is not one of them" % (count, index))
    w = 1 + index // 32
    if w >= words:
        raise SaveError("flag %d lies past the save's %d words" % (index, words))
    bit = index % 32
    return kids[w][4][0] + bit // 8, 1 << (bit % 8), count


# ------------------------------------------------------------------------------------ the player's saves
def save_files(appdata=None):
    """[(folder name, path of savedata.bin)] under %APPDATA%\\BLEACH Rebirth of Souls\\Savedata\\."""
    appdata = appdata if appdata is not None else os.environ.get("APPDATA", "")
    root = os.path.join(appdata, *SAVE_ROOT) if appdata else ""
    out = []
    if root and os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name, SAVE_NAME)
            if os.path.isfile(p):
                out.append((name, p))
    return out


def masked(folder):
    """A save folder is named by the player's account id: shown only by its last four characters."""
    return "..." + folder[-4:] if len(folder) > 4 else folder


def exe_locked(game_path):
    """True when the game is running: Windows does not let a running exe be opened for writing."""
    p = os.path.join(game_path, EXE_NAME)
    if not os.path.exists(p) or not os.access(p, os.W_OK):
        return False                    # no exe, or a read-only one: not a running game
    try:
        with open(p, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def backup_root():
    root = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(root, "BROS Launcher", "save_backups")


def _write_whole(path, data):
    """The file's new bytes: written beside it, flushed, then moved over it in one step."""
    tmp = path + TMP_SUFFIX
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _one(folder, path, decl, index, write, bdir, log):
    """One save: (status, line). status: already | set | would-set | refused | failed."""
    try:
        before = _read(path)
        off, mask, count = flag_slot(before, decl, index)
    except (OSError, SaveError) as e:
        return "refused", "save %s: not changed -- %s" % (masked(folder), e)
    if before[off] & mask:
        return "already", "save %s: already unlocked; not changed" % masked(folder)
    after = before[:off] + bytes([before[off] | mask]) + before[off + 1:]
    if not write:
        return "would-set", "save %s: locked; Unlock would set flag %d (one bit)" % (masked(folder), index)
    try:
        bd = os.path.join(bdir, folder)
        os.makedirs(bd, exist_ok=True)
        bp = os.path.join(bd, SAVE_NAME)
        _write_whole(bp, before)
        if _read(bp) != before:
            return "failed", "save %s: not changed -- its backup did not read back" % masked(folder)
        if _read(path) != before:
            return "refused", "save %s: not changed -- it changed while being read (is the game running?)" % masked(folder)
        _write_whole(path, after)
    except OSError as e:
        return "failed", "save %s: not changed -- %s" % (masked(folder), e)
    # the proof: the bytes on disk are the planned ones, they parse, the bit is set, and only that byte moved
    try:
        got = _read(path)
        off2, mask2, _c = flag_slot(got, decl, index)
        only_that_byte = (len(got) == len(before) and got[:off] == before[:off] and
                          got[off + 1:] == before[off + 1:] and got[off] == before[off] | mask)
        ok = got == after and off2 == off and bool(got[off] & mask2) and only_that_byte
    except (OSError, SaveError) as e:
        ok, why = False, str(e)
    else:
        why = "the bytes read back are not the planned ones"
    if ok:
        return "set", "save %s: unlocked (flag %d set; one byte changed, read back and checked)" % (masked(folder), index)
    try:
        _write_whole(path, before)
        back = _read(path) == before
    except OSError:
        back = False
    log("[save_unlock] the check after writing failed: %s" % why)
    return "failed", ("save %s: the check after writing failed (%s); %s" % (
        masked(folder), why, "the original was put back" if back else
        "PUT THE BACKUP BACK BY HAND: %s" % os.path.join(bdir, folder, SAVE_NAME)))


def _run(base_dir, game_path, chara, write, appdata, bdir, log):
    who = "%s (%s)" % (NAMES.get(chara, chara), chara)
    if exe_locked(game_path):
        return False, "The game is running: close it first. No save was changed.", []
    try:
        name = unlock_flag(game_path, chara)
        index, total = flag_index(game_path, name)
        try:
            decl = Declaration(_read(os.path.join(game_path, "Script", "define.bin")))
        except (OSError, SaveError) as e:
            raise SaveError("Script\\define.bin: %s" % e)
    except SaveError as e:
        return False, "%s: cannot unlock -- %s. No save was changed." % (who, e), []
    saves = save_files(appdata)
    if not saves:
        return False, ("%s: no save found in %%APPDATA%%\\%s. Start the game once (it makes the save), close it, "
                       "then try again." % (who, "\\".join(SAVE_ROOT))), []
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    bdir = bdir or os.path.join(backup_root(), stamp)
    results = [_one(f, p, decl, index, write, bdir, log) for f, p in saves]
    lines = ["%s is unlocked by the story flag %s (flag %d of %d)." % (who, name, index, total)]
    lines += [line for _s, line in results]
    if any(s == "set" for s, _l in results):
        lines.append("A backup of each changed save: %s" % bdir)
        lines.append("Note: %s is a story flag (that story node finished), so the node may show as cleared." % name)
    ok = all(s in ("set", "already", "would-set") for s, _l in results)
    return ok, "\n".join(lines), results


def status(base_dir, game_path, chara="pl002", appdata=None, log=print):
    return _run(base_dir, game_path, chara, False, appdata, None, log)


def unlock(base_dir, game_path, chara="pl002", appdata=None, backup_dir=None, log=print):
    return _run(base_dir, game_path, chara, True, appdata, backup_dir, log)


# ------------------------------------------------------------------------------------ the online character
ONLINE_VARIABLE = "onlinematch"                                 # the root field: SaveOnlineMatch
ONLINE_FIELDS = ("MyChara", "MyCostume")                        # int, int
VANILLA_ONLINE_CHARA = 0                                        # pl000, Ichigo (Berg, 2026-11-28)
# The characters only the patch makes playable (bros_roster.c's tables: "IsPlayableCharacter admits ids 5 and 15",
# "... ids 5, 9 and 34", "... ids 5, 9, 15 and 34"). A new added character goes here too.
PATCH_ONLY_CHARAS = {5: "Zangetsu", 9: "id 9 (with Orihime)", 15: "Yumichika", 34: "Orihime"}


def online_slots(data, decl):
    """[(offset, value)] of onlinematch's MyChara and MyCostume in a save (ints, 4 bytes each)."""
    root = parse_save(data, decl)
    otype, ocount = decl.field(ONLINE_VARIABLE)
    if otype not in decl.struct_by_name or ocount != 1:
        raise SaveError("define.bin's %s is not one struct" % ONLINE_VARIABLE)
    tag, _flds = decl.struct_by_name[otype]
    found = [e for e in root if e[1] == ghash(ONLINE_VARIABLE)]
    if len(found) != 1:
        raise SaveError("the save holds %d %s" % (len(found), ONLINE_VARIABLE))
    th, _nh, idx, _off, kids = found[0]
    if th != ghash(tag) or idx != 0 or not isinstance(kids, list):
        raise SaveError("the save's %s is not a %s" % (ONLINE_VARIABLE, tag))
    out = []
    for name in ONLINE_FIELDS:
        hit = [k for k in kids if k[1] == ghash(name)]
        if len(hit) != 1:
            raise SaveError("the save's %s holds %d %s" % (ONLINE_VARIABLE, len(hit), name))
        kth, _knh, kidx, _koff, body = hit[0]
        if kth not in (ghash("int"), ghash("int32_t")) or kidx != 0 or not isinstance(body, tuple) or body[1] != 4:
            raise SaveError("the save's %s.%s is not one int" % (ONLINE_VARIABLE, name))
        out.append((body[0], struct.unpack_from("<i", data, body[0])[0]))
    return out


def _one_online(folder, path, decl, write, bdir, log):
    """One save: (status, line). status: kept | set | would-set | refused | failed."""
    try:
        before = _read(path)
        (co, chara), (so, costume) = online_slots(before, decl)
    except (OSError, SaveError) as e:
        return "refused", "save %s: not changed -- %s" % (masked(folder), e)
    if chara not in PATCH_ONLY_CHARAS:
        return "kept", "save %s: online character pl%03d, the Steam game has it; not changed" % (masked(folder), chara)
    who = "%s (pl%03d), costume %d" % (PATCH_ONLY_CHARAS[chara], chara, costume)
    b = bytearray(before)
    struct.pack_into("<i", b, co, VANILLA_ONLINE_CHARA)
    struct.pack_into("<i", b, so, 0)
    after = bytes(b)
    if not write:
        return "would-set", "save %s: online character %s; a vanilla start would set pl%03d, costume 0" % (
            masked(folder), who, VANILLA_ONLINE_CHARA)
    try:
        bd = os.path.join(bdir, folder)
        os.makedirs(bd, exist_ok=True)
        bp = os.path.join(bd, SAVE_NAME)
        _write_whole(bp, before)
        if _read(bp) != before:
            return "failed", "save %s: not changed -- its backup did not read back" % masked(folder)
        if _read(path) != before:
            return "refused", "save %s: not changed -- it changed while being read (is the game running?)" % masked(folder)
        _write_whole(path, after)
    except OSError as e:
        return "failed", "save %s: not changed -- %s" % (masked(folder), e)
    # the proof: the bytes on disk are the planned ones, they parse, the two values are set, nothing else moved
    try:
        got = _read(path)
        (co2, c2), (so2, s2) = online_slots(got, decl)
        a, z = sorted((co, so))
        only_those = (len(got) == len(before) and got[:a] == before[:a] and got[a + 4:z] == before[a + 4:z] and
                      got[z + 4:] == before[z + 4:])
        ok = (got == after and (co2, so2) == (co, so) and (c2, s2) == (VANILLA_ONLINE_CHARA, 0) and only_those)
    except (OSError, SaveError) as e:
        ok, why = False, str(e)
    else:
        why = "the bytes read back are not the planned ones"
    if ok:
        return "set", "save %s: online character %s -> pl%03d, costume 0 (read back and checked)" % (
            masked(folder), who, VANILLA_ONLINE_CHARA)
    try:
        _write_whole(path, before)
        back = _read(path) == before
    except OSError:
        back = False
    log("[save_unlock] the check after writing failed: %s" % why)
    return "failed", ("save %s: the check after writing failed (%s); %s" % (
        masked(folder), why, "the original was put back" if back else
        "PUT THE BACKUP BACK BY HAND: %s" % os.path.join(bdir, folder, SAVE_NAME)))


def vanilla_online(game_path, appdata=None, backup_dir=None, log=print, write=True):
    """At a vanilla start (module docstring, THE ONLINE CHARACTER): every save whose online character only the patch
    has gets pl000, costume 0. (ok, text, results). Never raises; a save it cannot read is left as it is."""
    try:
        if exe_locked(game_path):
            return False, "The game is running: no save was changed.", []
        try:
            decl = Declaration(_read(os.path.join(game_path, "Script", "define.bin")))
        except (OSError, SaveError) as e:
            return False, "Script\\define.bin: %s. No save was changed." % e, []
        saves = save_files(appdata)
        if not saves:
            return True, "No save yet.", []
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        bdir = backup_dir or os.path.join(backup_root(), stamp + "_online")
        results = [_one_online(f, p, decl, write, bdir, log) for f, p in saves]
        lines = [line for _s, line in results]
        if any(s == "set" for s, _l in results):
            lines.append("A backup of each changed save: %s" % bdir)
        return all(s in ("kept", "set", "would-set") for s, _l in results), "\n".join(lines), results
    except Exception as e:                       # an extra of the vanilla start: it never stops one
        return False, "The online character was not checked: %s: %s" % (type(e).__name__, e), []


def _game_from_config(base_dir):
    try:
        with open(os.path.join(base_dir, "Json", "config.json"), encoding="utf-8") as f:
            g = json.load(f).get("GAME_PATH", "")
    except (OSError, ValueError):
        return ""
    return os.path.dirname(g) if g.lower().endswith(".exe") else g


if __name__ == "__main__":
    import argparse
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["status", "unlock", "online", "online-reset"])
    ap.add_argument("--game", default="")
    ap.add_argument("--chara", default="pl002")
    a = ap.parse_args()
    game = a.game or _game_from_config(base)
    if a.what.startswith("online"):
        ok_, text, _r = vanilla_online(game, write=(a.what == "online-reset"))
    else:
        ok_, text, _r = (unlock if a.what == "unlock" else status)(base, game, a.chara)
    print(text)
    sys.exit(0 if ok_ else 1)
