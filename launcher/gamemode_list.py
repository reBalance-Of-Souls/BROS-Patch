"""<game>/ReBalanceOfSouls/gamemodes.txt: the game modes a Room Match can play.

gamemode.dll (Files/Matchmaking/gamemode_plugin.c) reads it at boot; roomtrain's Create room
dialog offers its modes on the Game Mode row. A mode is listed when its folder
has a Mode.json; its CharaStatus cells are its CharaStatus.json, the same file
launcher/mode_status.py writes into the table for a launch in that mode, so a
room mode and a launch mode play the same stats on top of the same version.

    [ReawakeningBattle]
    name=Reawakening Battle
    name_fr=Combat en Réveil
    flags=start_reawakened
    cell=pl003 rev_soul_num 10
    rule=Start Reawakened|Ichigo (Bankai), Uryu, ...
    rule_fr=Départ en Réveil|...

The modes come out sorted by folder name and the cells sorted, so two PCs on
the same commit write the same file byte for byte: gamemode.dll's mode id is a
hash of the key, flags and cells, and a room plays a mode only when every
member has that id.

    python gamemode_list.py [<out dir>]     print it, or write it there
"""

from __future__ import annotations

import json
import os
import re

FILE = "gamemodes.txt"
# gamemode.dll's GM_FLAGS: a flag it does not know drops the mode there; this
# refuses it here first, louder.
FLAGS = ("first_kill_cap", "six_arms_spirit_drive", "start_reawakened", "start_awakened", "side_camera", "motion_inputs")
_ROW = re.compile(r"^(\*|pl\d{3})$")
_COL = re.compile(r"^[A-Za-z0-9_]{1,39}$")
_NUM = re.compile(r"^[+-]?\d+(\.\d+)?$")


def _one_line(s):
    return " ".join(str(s).split())


def _rules(pairs, where):
    out = []
    for p in pairs or []:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise ValueError("%s: a rule is a [title, text] pair" % where)
        title, text = _one_line(p[0]), _one_line(p[1])
        if "|" in title:
            raise ValueError("%s: a rule title cannot hold '|'" % where)
        out.append("%s|%s" % (title, text))
    if len(out) > 8:
        raise ValueError("%s: 8 rules at most" % where)
    return out


def modes(repo):
    """[(key, [lines])] for every GameModes/<key>/Mode.json, sorted by key."""
    root = os.path.join(repo, "GameModes")
    out = []
    for key in sorted(os.listdir(root)):
        mj = os.path.join(root, key, "Mode.json")
        if not os.path.isfile(mj):
            continue
        with open(mj, encoding="utf-8") as f:
            m = json.load(f)
        flags = list(m.get("flags") or [])
        for fl in flags:
            if fl not in FLAGS:
                raise ValueError("%s: flag %r is not one gamemode.dll knows %s" % (mj, fl, FLAGS))
        cells = []
        cj = os.path.join(root, key, "CharaStatus.json")
        if os.path.isfile(cj):
            with open(cj, encoding="utf-8") as f:
                cs = json.load(f).get("cells") or {}
            for row in sorted(cs):
                if not _ROW.match(row):
                    raise ValueError("%s: row %r is not plNNN or *" % (cj, row))
                for col in sorted(cs[row]):
                    spec = str(cs[row][col]).strip()
                    if not _COL.match(col) or not _NUM.match(spec):
                        raise ValueError("%s: %s.%s = %r is not a column and a number" % (cj, row, col, spec))
                    cells.append("%s %s %s" % (row, col, spec))
        if len(cells) > 96:
            raise ValueError("%s: 96 cells at most" % cj)
        lines = ["[%s]" % key,
                 "name=%s" % _one_line(m.get("name") or key),
                 "name_fr=%s" % _one_line(m.get("name_fr") or m.get("name") or key)]
        if flags:
            lines.append("flags=%s" % " ".join(flags))
        lines += ["cell=%s" % c for c in cells]
        lines += ["rule=%s" % r for r in _rules(m.get("rules"), mj)]
        lines += ["rule_fr=%s" % r for r in _rules(m.get("rules_fr"), mj)]
        out.append((key, lines))
    return out


def text(repo):
    head = ["# Written by the launcher (launcher/gamemode_list.py) from GameModes/*/Mode.json"
            " + CharaStatus.json. Do not edit: the next launch rewrites it."]
    body = []
    for _key, lines in modes(repo):
        body += [""] + lines
    return "\n".join(head + body) + "\n"


def write(repo, dst, say=print):
    """Write <dst>/gamemodes.txt (only when it changed); the number of modes."""
    want = text(repo).encode("utf-8")
    path = os.path.join(dst, FILE)
    have = None
    if os.path.exists(path):
        with open(path, "rb") as f:
            have = f.read()
    if have != want:
        with open(path, "wb") as f:
            f.write(want)
    n = want.count(b"\n[")
    say("gamemodes.txt: %d room game mode(s) -- %s" % (n, ", ".join(k for k, _l in modes(repo))))
    return n


if __name__ == "__main__":
    import sys
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    if len(sys.argv) > 1:
        write(repo, sys.argv[1])
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(text(repo))
