"""mk_tag_hud.py -- the 2v2 tag mode's HUD scene: both character cards cloned.

The battle HUD (ui/script/scene/Action.bin) holds ONE card per side. The tag
mode shows the benched partner of each side on a small copy of that side's
card, built by the game's own card builder (0x1DF860) on cloned nodes -- Joe's
TEST-mode recipe (dcbossrush 0.16, notes MULTI_FOE_CLONE.md) done for both
sides. For each side this clones three subtrees onto fresh instances:

    ui_bigcounter_<l|r>, ui_cha_HP_<L|R> (the card), ui_reiryoku_<L|R>00

(the builder also looks up the Reiatsu group and the big counter: left out,
it would bind the REAL ones). Every clone gets the next free instance of its
name, parents are remapped to the cloned parents, roots keep their parent and
joint; the clones are appended after the stock nodes and the count updated.
The right side comes out exactly as Joe's dcbossrush_Action.bin (checked
with --check-joe), the left side after it.

    python mk_tag_hud.py <stock Action.bin> <out dir> [--with-reiryoku | --with-gauges] [--before]
        -> <out>/tag2v2_Action.bin, <out>/tag2v2_hudclone.txt

The default clones the card alone; --with-reiryoku adds the Reiatsu group (the
benched fighter's SP / Reverse gauge under its mini card, tag2v2 t2on63+);
--with-gauges (old, 10-21) also the big counter, whose clone breaks the real HUD.
--before (10-27) inserts each cloned subtree BEFORE its stock root instead of
appending it: the stock node stays the later one of its name, so the name-keyed
tail chains and the HUD's layout groups keep binding the real gauges (appended,
the real bottom gauges froze black / white-brushed). The 2v2 mode's layout is
--with-reiryoku --before (tag2v2 t2on99+ hides the clone's brush, which drew
over its bars outside the layout group).

The map file: "stock <size> <fnv1a64>", then one line per cloned node
"<L|R> <name> <stock inst> <clone inst>", and "root <L|R> <name> <inst>"
for the three subtree roots.

--survival N (2026-11-04) writes tag2v2_sv_Action.bin: the stock scene + N copies of the
RIGHT card alone (X1..XN map lines index into it, not into tag2v2_Action.bin), for dcbossrush's
Survival foes (tag2v2 builds them as its "extra cards"): their lines are tagged X1..XN
("X<k> <name> <stock inst> <clone inst>", "root X<k> ui_cha_HP_R <inst>"), which an
older tag2v2 skips. They follow --before like the rest.

--allies N (2026-11-23) adds N copies of the LEFT card alone to that same Survival scene, for dcbossrush's allies
in Adventure group fights (tag2v2's ally cards, stacked under the 1P card): lines "A<k> <name> <stock inst> <clone
inst>" and "root A<k> ui_cha_HP_L <inst>". With --survival 4 --allies 4 the scene is 167 + 8 x 46 = 535 nodes, past
the 320 elements the game's HUD builds in one batch (exe 0x233ED0): tag2v2 raises that batch for this scene.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


class Rd:
    def __init__(self, d):
        self.d, self.o = d, 0

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.o)[0]
        self.o += 4
        return v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.o)[0]
        self.o += 2
        return v

    def s(self):
        n = self.u32()
        v = self.d[self.o:self.o + n]
        if self.d[self.o + n] != 0:
            raise ValueError("string at 0x%x is not NUL-terminated" % (self.o - 4))
        self.o += n + 1
        return v.decode("ascii")


def ws(s):
    b = s.encode("ascii")
    return struct.pack("<I", len(b)) + b + b"\0"


def parse(d):
    r = Rd(d)
    hdr = [r.s(), r.s(), r.s()]
    zero = r.u32()
    cnt = r.u32()
    nodes = []
    for _ in range(cnt):
        n = {"name": r.s(), "inst": r.u32(), "type": r.u32(), "flag": r.u16(), "state": r.s()}
        n["parent"] = r.s()
        n["pinst"] = r.u32()
        n["joint"] = r.s()
        n["tail"] = r.u32()
        nodes.append(n)
    return {"hdr": hdr, "zero": zero, "nodes": nodes, "rest": d[r.o:]}


def build(sc):
    out = b"".join(ws(h) for h in sc["hdr"])
    out += struct.pack("<II", sc["zero"], len(sc["nodes"]))
    for n in sc["nodes"]:
        out += ws(n["name"]) + struct.pack("<IIH", n["inst"], n["type"], n["flag"]) + ws(n["state"])
        out += ws(n["parent"]) + struct.pack("<I", n["pinst"]) + ws(n["joint"]) + struct.pack("<I", n["tail"])
    return out + sc["rest"]


def fnv1a64(d):
    h = 0xcbf29ce484222325
    for c in d:
        h = ((h ^ c) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def subtree(nodes, root_name, root_inst):
    """indices of the root and every node whose parent chain reaches it, in file order"""
    keys = {(root_name, root_inst)}
    out = []
    grew = True
    while grew:
        grew = False
        for i, n in enumerate(nodes):
            k = (n["name"], n["inst"])
            if k in keys:
                continue
            if (n["parent"], n["pinst"]) in keys:
                keys.add(k)
                grew = True
    for i, n in enumerate(nodes):
        if (n["name"], n["inst"]) in keys:
            out.append(i)
    return out


def clone_side(sc, side, nxt, maplines, tag=None, card_only=False):
    nodes = sc["nodes"]
    lo = side.lower()
    tag = tag or side
    # the card alone (10-21): clones of the Reiatsu group and the big counter drew their
    # flames and placeholder texts over the real bottom gauges, hidden or not ("le HUD
    # est toujours buggé", A/B on the rig); the builder's lookups of those two answer
    # with the real nodes, which only the real block updates (tag2v2 skips them)
    roots = [("ui_cha_HP_" + side, 0)]
    if "--with-gauges" in sys.argv:
        roots = [("ui_bigcounter_" + lo, 0), ("ui_cha_HP_" + side, 0), ("ui_reiryoku_" + side + "00", 0)]
    elif "--with-reiryoku" in sys.argv:
        # 10-25 ("afficher sa barre SP/reverse" under the benched ally's card): the Reiatsu
        # group (SP gauge, REVERSE, the SP / Reverse lists) too, driven by tag2v2 with the
        # benched fighter's values and placed under its mini card; never the big counter
        roots = [("ui_cha_HP_" + side, 0), ("ui_reiryoku_" + side + "00", 0)]
    if card_only:
        roots = [("ui_cha_HP_" + side, 0)]
    remap = {}                                   # (name, stock inst) -> clone inst
    new = []
    groups = []                                  # (stock root node, its cloned subtree)
    for rn, ri in roots:
        idx = subtree(nodes, rn, ri)
        if not idx:
            raise ValueError("no %s %d in the stock scene" % (rn, ri))
        grp = []
        for i in idx:
            n = dict(nodes[i])
            ci = nxt.get(n["name"], 0)
            nxt[n["name"]] = ci + 1
            remap[(n["name"], n["inst"])] = ci
            maplines.append("%s %s %d %d" % (tag, n["name"], n["inst"], ci))
            n["inst"] = ci
            new.append(n)
            grp.append(n)
        groups.append((nodes[idx[0]], grp))
        maplines.append("root %s %s %d" % (tag, rn, remap[(rn, ri)]))
    for n in new:                                # parents onto the clones
        if (n["parent"], n["pinst"]) in remap:
            n["pinst"] = remap[(n["parent"], n["pinst"])]
    if "--before" in sys.argv:
        # 10-27: the scene's tail holds animation chains keyed by node NAME only (ui_rei_waza_L
        # active1_in -> active1_loop, ui_rebirth_icon_L rebirth_b_in -> rebirth_b_loop, ...).
        # Appended after the stock nodes, a clone took them from its stock twin and the real
        # Reiatsu gauges froze black / white-brushed from the load on. Inserted BEFORE its stock
        # root, the stock node is the later one again. Lookups (0x2373B0) key on (name,
        # instance): the order changes nothing there.
        for root, grp in groups:
            at = next(k for k, m in enumerate(sc["nodes"]) if m is root)
            sc["nodes"][at:at] = grp
    else:
        sc["nodes"].extend(new)
    return len(new)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    stock = open(sys.argv[1], "rb").read()
    out_dir = sys.argv[2]
    sc = parse(stock)
    if build(sc) != stock:
        raise SystemExit("the stock scene does not round-trip -- nothing written")
    nxt = {}
    for n in sc["nodes"]:
        nxt[n["name"]] = max(nxt.get(n["name"], 0), n["inst"] + 1)
    maplines = ["stock %d %016x" % (len(stock), fnv1a64(stock))]
    nstock = len(sc["nodes"])
    nr = clone_side(sc, "R", nxt, maplines)
    nl = clone_side(sc, "L", nxt, maplines)
    data = build(sc)
    if build(parse(data)) != data:
        raise SystemExit("the clone does not round-trip -- nothing written")
    if "--check-joe" in sys.argv:
        joe = parse(open(sys.argv[sys.argv.index("--check-joe") + 1], "rb").read())
        mine = sc["nodes"][:nstock + nr]
        print("right side == Joe's dcbossrush_Action.bin:", mine == joe["nodes"] and sc["rest"] == joe["rest"])
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "tag2v2_Action.bin"), "wb") as f:
        f.write(data)
    nx = 0
    if "--survival" in sys.argv:
        # 11-04: a scene of its own (stock + the X cards, no Tag clones). Both in one file
        # (441 nodes) crashed the HUD build at exe+0x22A547: the nodes past ~300 never reached
        # the lookup map, so the real ui_add_rebirth_gauge_R answered NULL. 303 is known good.
        sv = parse(stock)
        nxs = {}
        for n in sv["nodes"]:
            nxs[n["name"]] = max(nxs.get(n["name"], 0), n["inst"] + 1)
        for k in range(1, int(sys.argv[sys.argv.index("--survival") + 1]) + 1):
            nx += clone_side(sv, "R", nxs, maplines, tag="X%d" % k, card_only=True)
        if "--allies" in sys.argv:              # 11-23: the allies' cards, copies of the LEFT card (A1..AN)
            for k in range(1, int(sys.argv[sys.argv.index("--allies") + 1]) + 1):
                nx += clone_side(sv, "L", nxs, maplines, tag="A%d" % k, card_only=True)
        svd = build(sv)
        if build(parse(svd)) != svd:
            raise SystemExit("the Survival clone does not round-trip -- nothing written")
        with open(os.path.join(out_dir, "tag2v2_sv_Action.bin"), "wb") as f:
            f.write(svd)
    with open(os.path.join(out_dir, "tag2v2_hudclone.txt"), "w", newline="\n") as f:
        f.write("\n".join(maplines) + "\n")
    print("tag2v2_Action.bin: %d stock nodes + %d right + %d left = %d (%d B); Survival scene + %d; map %d lines"
          % (nstock, nr, nl, len(sc["nodes"]), len(data), nx, len(maplines)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
