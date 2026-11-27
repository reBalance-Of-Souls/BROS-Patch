"""A game mode's own CharaStatus values, applied at launch.

WHY
---
A data game mode used to own its CharaStatus by shipping a whole copy of
Script/CharaStatus.fsv in GameModes/<mode>/Script/ (BaseOnly, EightKonpakus,
InstantEvoAndSublimation, ReawakeningBattle). That copy is frozen on the day it
was made: every Community Patch balance change after it is silently undone
inside the mode, and on V1.2 / V1.3 it replaces the fork's own numbers with
someone else's. It is the frozen-loader trap again, in data.

So a mode that needs different stats lists only the CELLS it changes, in
GameModes/<mode>/CharaStatus.json, and they are written over the CharaStatus
the version just installed:

    {
      "cells": {
        "pl037": { "evo_kikonsyouka_param": "+0.5" }
      }
    }

  "+x" / "-x"   added to the installed value
  "x"           replaces it

A row named "*" applies to every character row (every row whose key starts
with "pl"); a character's own row wins for the columns it names:

    "*":     { "soul_num": "-1" },     every character one Konpaku down
    "pl044": { "soul_num": "+0" }      except this one

Everything else in the table is whatever the version ships, today and after
every future balance change.

WHEN
----
Every launcher calls apply() after the version, the reworks, the mode's
Script/ and Team Battle are in place, so these cells are the last word -- and
it calls it on every launch, mode or not. The version's Script/ is mirrored
(robocopy /MIR) on every launch, so the base is always fresh and a "+0.5"
cannot pile up across launches; a sidecar next to the table (see apply())
turns "the mirror did not happen" into a refusal instead of a stacked value or
a normal launch on a mode's stats.

Only where the mode is really armed. 4-5 and Universal Step Cancel live in the
DLLs and arm on BROS_GAME_MODE, which reaches the game only when the launcher
starts the exe itself -- on Windows. Through Steam (Linux, macOS) the game runs
stock rules in the normal pool, and stats that differ from that pool's would
desync every match. So off Windows nothing is written, and the launcher says so.

It raises on anything it cannot do (a missing row or column, a value that is
not a number, a table that does not decode): a mode must not start with stats
its opponent does not have. The launchers' own error handling then keeps the
game from starting.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import re

STATUS_JSON = "CharaStatus.json"
TABLE = os.path.join("Script", "CharaStatus.fsv")
SIDECAR = ".modestatus"

# The encoder appends 16 null bytes after the ciphertext, and decoding them
# yields noise; they come off before decoding and go back on after encoding
# (launcher/version_inherit.py's cso codec does the same).
_PAD = b"\x00" * 16
_ROW_SPLIT = re.compile(rb"\r\n|\n")


def _load_cso(base_dir):
    """FileInjector/fsv2csv.py, loaded from its path: FileInjector holds both a module fsv2csv.py and a folder
    fsv2csv/, so an import by name can resolve to either."""
    path = os.path.join(base_dir, "FileInjector", "fsv2csv.py")
    spec = importlib.util.spec_from_file_location("_bros_fsv2csv_modestatus", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fmt(v):
    """3.0 -> "3", 3.5 -> "3.5": how the table writes its numbers."""
    s = "%.6f" % v
    s = s.rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def load_cells(base_dir, mode):
    """{row: {column: "spec"}} declared by the mode, or {} if it declares none."""
    path = os.path.join(base_dir, "GameModes", mode, STATUS_JSON)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    cells = data.get("cells") or {}
    if not isinstance(cells, dict):
        raise ValueError("%s: 'cells' must be an object" % path)
    return cells


def patch_table(cso, raw, cells):
    """(new_raw, [(row, column, old, new)]) for an encoded CharaStatus table."""
    # Not raw.endswith(_PAD): V1.7's table (since 20fc2b2) ends in 16 ENCODED
    # bytes instead of the nulls, and the game reads it all the same. Whatever
    # the last 16 are, they come off; the nulls go back on.
    if not raw.startswith(b"_cso_") or len(raw) <= len(_PAD):
        raise ValueError("CharaStatus.fsv is not an encoded table")
    text = cso.decode_cso_bytes(raw[:-len(_PAD)])
    sep = b"\r\n" if b"\r\n" in text else b"\n"
    rows = _ROW_SPLIT.split(text)
    header = rows[0].split(b",")
    col_of = dict((name.strip().decode("utf-8", "replace"), i) for i, name in enumerate(header))
    row_of = {}
    for i, r in enumerate(rows[1:], 1):
        key = r.split(b",", 1)[0].strip().decode("utf-8", "replace")
        if key and key not in row_of:
            row_of[key] = i

    # "*" first, then each named row over it: a row's own column wins.
    every = cells.get("*") or {}
    wanted = {}
    if every:
        for key in row_of:
            if key.startswith("pl"):
                wanted[key] = dict(every)
    for key, cols in cells.items():
        if key == "*":
            continue
        if key not in row_of:
            raise ValueError("CharaStatus has no row %r" % key)
        wanted.setdefault(key, {}).update(cols)

    changes = []
    for key, cols in sorted(wanted.items()):
        i = row_of[key]
        fields = rows[i].split(b",")
        for col, spec in sorted(cols.items()):
            if col not in col_of:
                raise ValueError("CharaStatus has no column %r" % col)
            c = col_of[col]
            if c >= len(fields):
                raise ValueError("row %r is shorter than column %r" % (key, col))
            old = fields[c].strip().decode("utf-8", "replace")
            spec = str(spec).strip()
            try:
                if spec[:1] in "+-":
                    new = _fmt(float(old) + float(spec))
                else:
                    new = _fmt(float(spec))
            except ValueError:
                raise ValueError("%s.%s: %r / %r is not a number" % (key, col, old, spec))
            fields[c] = new.encode("ascii")
            changes.append((key, col, old, new))
        rows[i] = b",".join(fields)

    out = sep.join(rows)
    return cso.encode_cso_bytes(out) + _PAD, changes


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _read_sidecar(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def apply(base_dir, game_path, mode, log=print):
    """Write the mode's own cells into <game>/Script/CharaStatus.fsv.

    Call it on EVERY launch, mode or not: it is also the check that a mode's
    values are not still sitting in the game folder.

    Returns the list of changes; [] when the mode declares nothing, or when the
    mode cannot be armed on this platform (and says so).

    THE SIDECAR. Next to the table it leaves CharaStatus.fsv.modestatus: the
    mode, its cells, and the hash of the bytes it wrote. The version's mirror
    (/MIR) deletes that file along with the patched table on the next launch.
    If both are still there, byte for byte, the table was NOT refreshed, and
    applying "+0.5" again would stack on the last launch's value; a normal
    launch would play the mode's stats in the normal pool. Both refuse."""
    path = os.path.join(game_path, TABLE)
    side = path + SIDECAR
    raw = None
    if os.path.exists(path):
        with open(path, "rb") as f:
            raw = f.read()
    cells = load_cells(base_dir, mode) if mode and mode != "DEFAULT" else {}

    prev = _read_sidecar(side) if os.path.exists(side) else None
    if prev and raw is not None and prev.get("sha256") == _sha(raw):
        if cells and prev.get("mode") == mode and prev.get("cells") == cells:
            log("[%s] CharaStatus: its own values are already in place (the table was"
                " not re-mirrored since the last launch) -- left as is." % mode)
            return []
        raise RuntimeError(
            "Script/CharaStatus.fsv still holds the %s game mode's own values from an"
            " earlier launch -- the version's Script/ was not mirrored over it. Not"
            " starting on those stats: reinstall the version (or delete %s and its"
            " .modestatus file) and launch again." % (prev.get("mode"), path))
    if not cells:
        return []
    if platform.system() != "Windows":
        log("[%s] CharaStatus: its own values are NOT applied -- through Steam the"
            " game runs stock rules in the normal pool, and different stats would"
            " desync every match there." % mode)
        return []
    if raw is None:
        raise RuntimeError("the %s game mode needs %s, and it is not there" % (mode, path))

    cso = _load_cso(base_dir)
    new_raw, changes = patch_table(cso, raw, cells)

    # Prove the write before making it: decode what is about to go to disk
    # and check that only the declared cells moved.
    before = _ROW_SPLIT.split(cso.decode_cso_bytes(raw[:-len(_PAD)]))
    after = _ROW_SPLIT.split(cso.decode_cso_bytes(new_raw[:-len(_PAD)]))
    if len(before) != len(after):
        raise ValueError("CharaStatus re-encode changed the row count")
    moved = sum(1 for a, b in zip(before, after) if a != b)
    if moved != len(set(k for k, _c, o, n in changes if o != n)):
        raise ValueError("CharaStatus re-encode changed rows it was not asked to")

    with open(path, "wb") as f:
        f.write(new_raw)
    with open(side, "w", encoding="utf-8") as f:
        json.dump({"mode": mode, "cells": cells, "sha256": _sha(new_raw)}, f, indent=1)
    for key, col, old, new in changes:
        log("[%s] CharaStatus: %s %s %s -> %s" % (mode, key, col, old, new))
    return changes


if __name__ == "__main__":
    # Dry run against a table on disk:
    #   python launcher/mode_status.py 4-5 "GameVersions/<version>/Script/CharaStatus.fsv"
    import sys
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mode, table = sys.argv[1], sys.argv[2]
    cso = _load_cso(base)
    raw = open(table, "rb").read()
    _new, ch = patch_table(cso, raw, load_cells(base, mode))
    for key, col, old, new in ch:
        print("%s %s %s -> %s" % (key, col, old, new))
    if not ch:
        print("(the mode declares no CharaStatus cells)")
