#!/usr/bin/env python3
"""fulldiag_read.py -- read what the advanced diagnostics (fulldiag.dll, launcher/fulldiag.py) recorded or sent.
Pass fd, 2026-10-31. Standard library only; E1 records are read with the rollback lab's own reader
(Files/Matchmaking/rbk_lab/e1.py in this checkout, or --lab <folder>), so both tools always agree on the layout.

    python Diagnostics\\fulldiag_read.py join    <zips or folders ...> --out <folder>
        put the parts of one or more sends back together (meta.json, chunks, checksums): <out>\\<batch>\\sessions\\...,
        launcher\\, machine\\ and send.json (the send's comment, the PC's UTC offset, what was left out)
    python Diagnostics\\fulldiag_read.py summary <session folder>
        the session at a glance: the machine and the recorder's settings, every battle, the frame rate in battle and
        in menus, long frames by phase, where the profiler found them, foreign modules and threads, the PC's load,
        the events
    python Diagnostics\\fulldiag_read.py timing  <session folder> [--long] [--battle N]
        one line per frame (or per long frame): the phases, the render hold, fulldiag's own cost, the flags
    python Diagnostics\\fulldiag_read.py frames  <session folder> --battle N [--from TICK] [--count N] [--inputs]
        both fighters every frame (action, serial, clock, position, HP, Konpaku, the commands executed); --inputs adds
        the raw pads, the held keys and BrainPad's masks from fx_bNN.bin
    python Diagnostics\\fulldiag_read.py diff    <session A> <session B> --battle N [--battle-b M] [--key rel|F|tick]
                                                  [--max N]
        the first frame where two PCs' battles disagree (E1's own comparison: every simulation field bit for bit),
        with both PCs' inputs at that frame and the three before it. --key: rel = the frame within the battle (the
        default offline: two PCs' tick counters differ), F = the online lockstep frame (the default online), tick.

The record layouts are in Diagnostics\\FULLDIAG_DATA.md.
"""
import collections
import glob
import hashlib
import importlib.util
import io
import json
import os
import shutil
import struct
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- the plugin's own records (p4_main.c F1) --------------------------------------------------------------------------
TIM = struct.Struct("<IHHQQI7fIIHHIBBBBHH")                        # FdTiming, 80 bytes
TIM_N = ("magic ver size frame qpc tick tick_us post_us pub_us gap_us frame_us rhold_us hook_us cyc_tick cyc_frame rframes "
         "state sceneVt kind flags nticks pad0 battle pad1").split()
EXT = struct.Struct("<IHHQQiI2iIB3x192s192s256s")                  # FdExt without the two FdBrain
BRAIN = struct.Struct("<IBBBBi2f17I")                              # FdBrain, 88 bytes
FX_SIZE = EXT.size + 2 * BRAIN.size                                # 864
TIM_MAGIC, FDX_MAGIC = 0x31544446, 0x31584446                      # "FDT1", "FDX1"
E1_SIZE = 1174
FTF = [(0x01, "LONG"), (0x02, "focus"), (0x04, "battle"), (0x08, "online"), (0x10, "cinematic"), (0x20, "nocyc")]
assert TIM.size == 80 and BRAIN.size == 88 and FX_SIZE == 864


def die(msg):
    print(msg)
    sys.exit(2)


def lab_module(argv):
    lab = argv[argv.index("--lab") + 1] if "--lab" in argv else os.path.join(os.path.dirname(HERE), "Files", "Matchmaking", "rbk_lab")
    p = os.path.join(lab, "e1.py")
    if not os.path.isfile(p):
        die("e1.py not found in %s -- pass --lab <the folder holding the rollback lab's e1.py>" % lab)
    spec = importlib.util.spec_from_file_location("rbk_lab_e1", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def jsonl(path):
    """The JSON lines of a file; a line that is not JSON (the last one, if the game was still writing) is skipped and
    counted."""
    out, bad = [], 0
    if not os.path.isfile(path):
        return out, 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except ValueError:
                bad += 1
    return out, bad


def read_timing(path):
    out = []
    if not os.path.isfile(path):
        return out
    with open(path, "rb") as f:
        data = f.read()
    for o in range(0, len(data) - TIM.size + 1, TIM.size):
        d = dict(zip(TIM_N, TIM.unpack_from(data, o)))
        if d["magic"] != TIM_MAGIC:
            break
        out.append(d)
    return out


def read_fx(path):
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, "rb") as f:
        data = f.read()
    for o in range(0, len(data) - FX_SIZE + 1, FX_SIZE):
        v = EXT.unpack_from(data, o)
        if v[0] != FDX_MAGIC:
            break
        d = dict(frame=v[3], tick=v[4], F=v[5], flags=v[6], scheme=[v[7], v[8]], pad0Extra=v[9], readOk=v[10], pads=[v[11], v[12]],
                 keys=v[13], fb=[])
        for i in range(2):
            w = BRAIN.unpack_from(data, o + EXT.size + i * BRAIN.size)
            d["fb"].append(dict(brainVt=w[0], onA=w[1], onB=w[2], isPad=w[3], ok=w[4], padIdx=w[5], hold=[w[6], w[7]], masks=list(w[8:25])))
        out[d["tick"]] = d
    return out


def pct(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(q / 100.0 * len(s)))]


def flags_text(fl):
    return ",".join(n for b, n in FTF if fl & b) or "-"


def key_entries(blob):
    """The game's keyboard table (exe+0x18D7BA0: 32 entries of {u32 code|flags, f32 repeat}), raw: every entry that is
    not all zero, as code|flags:repeat. Not decoded further."""
    out = []
    for k in range(32):
        code, t = struct.unpack_from("<If", blob, k * 8)
        if code or t:
            out.append("%x:%g" % (code, t))
    return " ".join(out) or "-"


def pad_text(blob):
    """One pad's 0xC0 bytes from the pad manager (pad i at +i*0xA8 + 0x40): the held mask (at 0xA8 of the copy) and a
    short checksum of the whole copy, so a change in the undecoded part still shows."""
    return "held %08x [%s]" % (struct.unpack_from("<I", blob, 0xA8)[0], hashlib.md5(blob).hexdigest()[:8])


# =====================================================================================================================
# join
# =====================================================================================================================

def part_files(args):
    out = []
    for a in args:
        if os.path.isdir(a):
            out += sorted(glob.glob(os.path.join(a, "*.zip")))
        else:
            out += sorted(glob.glob(a)) or [a]
    return out


def cmd_join(args, out):
    batches = collections.defaultdict(lambda: {"parts": {}, "entries": collections.defaultdict(list), "common": None, "bad": []})
    for p in part_files(args):
        try:
            z = zipfile.ZipFile(p)
            meta = json.loads(z.read("meta.json").decode("utf-8"))
        except Exception as e:
            print("NOT A PART: %s (%s)" % (p, e))
            continue
        b = batches[meta.get("batch", "?")]
        b["common"] = dict((k, v) for k, v in meta.items() if k not in ("part", "files"))
        if meta.get("part") in b["parts"]:
            print("duplicate part %s of batch %s: %s (kept the first)" % (meta.get("part"), meta.get("batch", "?")[:8], p))
            continue
        b["parts"][meta.get("part")] = p
        for e in meta.get("files", []):
            try:
                data = z.read(e["zip_name"])
            except KeyError:
                b["bad"].append("%s: listed but missing in %s" % (e["zip_name"], os.path.basename(p)))
                continue
            except Exception as x:                       # a damaged entry: bad CRC, a broken deflate stream
                b["bad"].append("%s: damaged in %s (%s)" % (e["zip_name"], os.path.basename(p), x))
                continue
            if hashlib.sha256(data).hexdigest() != e.get("sha256"):
                b["bad"].append("%s: checksum differs in %s" % (e["zip_name"], os.path.basename(p)))
                continue
            key = (e.get("kind"), e.get("session"), e.get("name"))
            b["entries"][key].append((e, data))
    rc = 0
    for batch, b in batches.items():
        n = (b["common"] or {}).get("parts")
        have = sorted(b["parts"])
        missing = [i for i in range(1, (n or 0) + 1) if i not in b["parts"]]
        root = os.path.join(out, batch[:12])
        os.makedirs(root, exist_ok=True)
        print("batch %s: %d of %s part(s)%s" % (batch[:12], len(have), n, (" -- MISSING %s" % missing) if missing else ""))
        done, incomplete = 0, []
        for (kind, sess, name), got in sorted(b["entries"].items(), key=lambda kv: tuple(str(x) for x in kv[0])):
            got.sort(key=lambda t: t[0]["offset"])
            off, buf, ok = 0, [], True
            for e, data in got:
                if e["offset"] != off:
                    ok = False
                    break
                buf.append(data)
                off += len(data)
            last = got[-1][0]
            whole = b"".join(buf)
            ok = ok and last.get("last") and last.get("file_bytes") == len(whole) and last.get("file_sha256") == hashlib.sha256(whole).hexdigest()
            sub = {"session": os.path.join("sessions", sess or "?"), "snapshot": "launcher", "machine": "machine", "readme": ""}.get(kind, "other")
            dst = os.path.join(root, sub, *(name or "unnamed").replace("\\", "/").split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not ok:
                dst += ".INCOMPLETE"
                incomplete.append("%s/%s" % (sub, name))
            with open(dst, "wb") as f:
                f.write(whole)
            done += 1
        info = dict(b["common"] or {})
        info.update({"parts_found": have, "parts_missing": missing, "incomplete_files": incomplete, "checksum_problems": b["bad"]})
        with open(os.path.join(root, "send.json"), "w", encoding="utf-8") as f:
            json.dump(info, f, indent=1, sort_keys=True)
        print("  %d file(s) written to %s%s" % (done, root, ("; INCOMPLETE: %s" % ", ".join(incomplete)) if incomplete else ""))
        for x in b["bad"]:
            print("  PROBLEM: %s" % x)
        if (b["common"] or {}).get("comment"):
            print("  comment: %s" % b["common"]["comment"])
        for s in sorted(glob.glob(os.path.join(root, "sessions", "*"))):
            print("  session %s" % os.path.basename(s))
        if missing or incomplete or b["bad"]:
            rc = 1
    return rc


# =====================================================================================================================
# summary
# =====================================================================================================================

def phase_of(e):
    ph = {"tick": e.get("prev_tick_ms", 0), "post": e.get("prev_post_ms", 0), "publish": e.get("prev_pub_ms", 0), "gap": e.get("gap_ms", 0)}
    return max(ph, key=lambda k: ph[k])


def stats_line(fr):
    ms = [t["frame_us"] / 1000.0 for t in fr]
    if not ms:
        return "no frames"
    total = sum(ms) / 1000.0
    return ("%d frames, %.1f s, %.1f fps; frame ms p50 %.2f p95 %.2f p99 %.2f max %.1f; long %d; fulldiag's own ms p50 %.3f p95 %.3f"
            % (len(ms), total, len(ms) / total if total else 0, pct(ms, 50), pct(ms, 95), pct(ms, 99), max(ms),
               sum(1 for t in fr if t["flags"] & 1), pct([t["hook_us"] / 1000.0 for t in fr], 50), pct([t["hook_us"] / 1000.0 for t in fr], 95)))


def cmd_summary(sess):
    if not os.path.isdir(sess):
        die("no such folder: %s" % sess)
    p = lambda n: os.path.join(sess, n)
    s = {}
    if os.path.isfile(p("session.json")):
        with open(p("session.json"), encoding="utf-8") as f:
            s = json.load(f)
    ev, bad_ev = jsonl(p("events.jsonl"))
    print("== session %s" % os.path.basename(os.path.normpath(sess)))
    print("plugin %s build %s; exe md5 %s; game folder '%s'" % (s.get("plugin"), s.get("build"), (s.get("exe") or {}).get("md5"),
                                                                s.get("game_folder_name")))
    m = s.get("machine") or {}
    print("machine: Windows %s%s, %s, %s logical CPUs, %s MB RAM, timer %s ms, priority class %s" % (
        m.get("windows"), " (Wine)" if m.get("wine") else "", m.get("cpu"), m.get("logical_cpus"), m.get("ram_mb"),
        (m.get("timer_ms") or {}).get("current"), m.get("priority_class")))
    print("recorder: frame hooks %s; profiler %s; config %s" % (s.get("frame_hooks"), s.get("profiler"), json.dumps(s.get("config"))))
    print("plugins: %s" % ", ".join(s.get("plugins") or []))
    print("beside the exe: %s" % ", ".join(f.get("name", "?") for f in (s.get("beside_exe") or [])))
    if s.get("env"):
        print("environment: %s" % ", ".join("%s=%s" % kv for kv in sorted(s["env"].items())))
    end = [e for e in ev if e.get("t") == "session_end"]
    print("end: %s" % (("%s; %s frames, %s battles, %s records dropped" % (end[-1].get("why"), end[-1].get("frames"), end[-1].get("battles"),
                                                                          end[-1].get("dropped_records"))) if end
                        else "NO session_end -- the game was still running when this was copied, or it ended abruptly"))
    if bad_ev:
        print("events.jsonl: %d line(s) not JSON (a half-written last line)" % bad_ev)

    tim = read_timing(p("timing.bin"))
    print("\n== frames (timing.bin)")
    print("all:       " + stats_line(tim))
    print("in battle: " + stats_line([t for t in tim if t["flags"] & 4]))
    print("menus:     " + stats_line([t for t in tim if not t["flags"] & 4]))
    nofocus = sum(1 for t in tim if not t["flags"] & 2)
    if nofocus:
        print("frames without the window's focus: %d" % nofocus)
    rh = [t["rhold_us"] / 1000.0 for t in tim if t["rhold_us"] > 0]
    if rh:
        print("render thread's hold per frame: p50 %.2f ms, p95 %.2f, max %.1f" % (pct(rh, 50), pct(rh, 95), max(rh)))

    print("\n== battles")
    begins = dict((e.get("battle"), e) for e in ev if e.get("t") == "battle_begin")
    ends = dict((e.get("battle"), e) for e in ev if e.get("t") == "battle_end")
    for b in sorted(set(begins) | set(ends)):
        bb, be = begins.get(b, {}), ends.get(b, {})
        fighters = "; ".join("pl%03d slot %s ctrl %s %s" % (f.get("chara", -1), f.get("slot"), f.get("ctrl"), f.get("brain", "")) for f in bb.get("fighters", []))
        e1n = os.path.getsize(p("e1_b%02d.bin" % b)) // E1_SIZE if os.path.isfile(p("e1_b%02d.bin" % b)) else 0
        fxn = os.path.getsize(p("fx_b%02d.bin" % b)) // FX_SIZE if os.path.isfile(p("fx_b%02d.bin" % b)) else 0
        bt = [t for t in tim if t["battle"] == b]
        print("battle %d: %s%s, frames %s..%s (%s s), ended: %s; profiled: %s" % (
            b, bb.get("kind", "?"), " ONLINE" if bb.get("online") else "", bb.get("frame"), be.get("frame"), be.get("secs"),
            be.get("why", "not ended"), {1: "yes", 0: "no"}.get(be.get("sampled"), "?")))
        print("   fighters: %s; schemes %s" % (fighters, bb.get("scheme")))
        print("   E1 %d records, fx %d; %s" % (e1n, fxn, stats_line(bt)))
    lf = [e for e in ev if e.get("t") == "long_frame"]
    if lf:
        print("\n== long frames (events.jsonl): %d" % len(lf))
        by = collections.Counter((e.get("battle", 0), phase_of(e)) for e in lf)
        for (b, ph), c in sorted(by.items()):
            print("   %s, mostly %s: %d" % ("battle %d" % b if b else "menus", ph, c))
        for e in sorted(lf, key=lambda e: -e.get("frame_ms", 0))[:8]:
            print("   frame %s (%s): %.1f ms = tick %.1f + post %.1f + publish %.1f + gap %.1f; fulldiag %.2f; render hold %.1f%s" % (
                e.get("frame"), "battle %d" % e["battle"] if e.get("battle") else "menu", e.get("frame_ms", 0), e.get("prev_tick_ms", 0),
                e.get("prev_post_ms", 0), e.get("prev_pub_ms", 0), e.get("gap_ms", 0), e.get("hook_ms", 0), e.get("render_hold_ms", 0),
                " cinematic" if e.get("demo") else ""))
    for csvp in sorted(glob.glob(p("prof_b*_top.csv"))):
        rows = []
        with open(csvp, encoding="utf-8", errors="replace") as f:
            head = f.readline().strip().split(",")
            for ln in f:
                v = ln.rstrip("\n").split(",")
                if len(v) == len(head):
                    rows.append(dict(zip(head, v)))
        print("\n== profile %s (where the game and render threads were sampled; prof.py reads prof_bNN.bin for more)" % os.path.basename(csvp))
        for st in sorted(set(r["set"] for r in rows)):
            top = [r for r in rows if r["set"] == st and r["kind"] == "exclusive"][:4]
            print("   %-22s %s" % (st, "; ".join("%s+%s %s%%" % (r["module"], r["rva"], r["pct_of_set"]) for r in top)))

    mods, _ = jsonl(p("modules.jsonl"))
    where = collections.Counter(x.get("where") for x in mods if x.get("t") == "module")
    print("\n== modules (%d: %s)" % (sum(where.values()), ", ".join("%s %d" % kv for kv in sorted(where.items()))))
    for x in mods:
        if x.get("t") == "module" and x.get("where") == "other":
            print("   NOT GAME OR WINDOWS: %s %s%s" % (x.get("path"), x.get("version", ""), (" -- %s / %s / %s" % (x.get("desc"), x.get("product"),
                                                                                                           x.get("company"))) if x.get("desc") or x.get("company") else ""))
    for e in ev:
        if e.get("t") in ("module_loaded", "module_unloaded"):
            print("   %s during the session: %s (%s)" % ("loaded" if e["t"] == "module_loaded" else "unloaded", e.get("name"), e.get("where")))
    th, _ = jsonl(p("threads.jsonl"))
    print("\n== threads")
    roles = collections.Counter(x.get("role") or "other" for x in th if x.get("t") == "thread")
    print("   " + ", ".join("%s %d" % kv for kv in sorted(roles.items())))
    mwhere = dict((os.path.basename(str(x.get("path", "")).replace("\\", "/")).lower(), x.get("where")) for x in mods if x.get("t") == "module")
    starts = collections.Counter(str(x.get("start") or "?").split("+")[0] for x in th if x.get("t") == "thread")
    print("   started in: " + ", ".join("%s %d (%s)" % (m, c, mwhere.get(m.lower(), "?")) for m, c in starts.most_common()))
    for x in th:
        m = str(x.get("start") or "?").split("+")[0]
        if x.get("t") == "thread" and mwhere.get(m.lower()) not in ("game", "windows"):
            print("   thread %s starts outside the game and Windows: %s%s" % (x.get("tid"), x.get("start"), (" '%s'" % x["name"]) if x.get("name") else ""))
    busy = collections.Counter()
    for x in th:
        if x.get("t") == "cpu":
            for row in x.get("busy", []):
                busy[row[0]] += row[1]
    if busy:
        names = dict((x.get("tid"), x.get("role") or x.get("start")) for x in th if x.get("t") == "thread")
        print("   busiest: " + "; ".join("%s (%s) %.1f s" % (tid, names.get(tid, "?"), ms / 1000.0) for tid, ms in busy.most_common(5)))
    sysl, _ = jsonl(p("sys.jsonl"))
    sysl = [x for x in sysl if x.get("t") == "sys"]
    if sysl:
        num = lambda k: [x[k] for x in sysl if isinstance(x.get(k), (int, float)) and x[k] >= 0]
        print("\n== the PC once a second (%d samples)" % len(sysl))
        print("   game CPU %% p50 %.0f max %.0f; system CPU %% p50 %.0f max %.0f; working set max %.0f MB; hard faults %d; free disk min %s MB" % (
            pct(num("cpu_proc_pct"), 50), max(num("cpu_proc_pct") or [0]), pct(num("cpu_sys_pct"), 50), max(num("cpu_sys_pct") or [0]),
            max(num("ws_mb") or [0]), sum(num("hard_faults")), min(num("disk_free_mb") or [0])))
        print("   refresh rates %s; timer ms %s; HID game controllers %s; power %s; dropped (max) %s; disk guard %s" % (
            sorted(set(num("refresh_hz"))), sorted(set(num("timer_ms"))), sorted(set(x.get("hid") for x in sysl)),
            sorted(set("AC" if x.get("ac") == 1 else "battery" if x.get("ac") == 0 else "?" for x in sysl)),
            [max(x["dropped"][i] for x in sysl if "dropped" in x) for i in range(5)] if all("dropped" in x for x in sysl) else "?",
            "TRIPPED" if any(x.get("disk_stop") for x in sysl) else "never"))
    print("\n== events")
    c = collections.Counter(e.get("t") for e in ev)
    print("   " + ", ".join("%s %d" % kv for kv in sorted(c.items())))
    for e in ev:
        if e.get("t") in ("focus", "display", "input_devices", "bindings", "disk_guard", "profiler_late_start"):
            print("   %7.1f s  %s" % (e.get("ms", 0) / 1000.0, json.dumps(dict((k, v) for k, v in e.items() if k != "ms"))))
    return 0


# =====================================================================================================================
# timing, frames, diff
# =====================================================================================================================

def cmd_timing(sess, long_only, battle):
    for t in read_timing(os.path.join(sess, "timing.bin")):
        if long_only and not t["flags"] & 1:
            continue
        if battle is not None and t["battle"] != battle:
            continue
        print("frame %6d tick %8d b%-2d | frame %7.2f ms = gap %6.2f + tick %6.2f + post %5.2f + pub %5.2f | hold %5.2f (%d) | fd %5.3f | ticks %d | %s"
              % (t["frame"], t["tick"], t["battle"], t["frame_us"] / 1000, t["gap_us"] / 1000, t["tick_us"] / 1000, t["post_us"] / 1000,
                 t["pub_us"] / 1000, t["rhold_us"] / 1000, t["rframes"], t["hook_us"] / 1000, t["nticks"], flags_text(t["flags"])))
    return 0


def battle_records(e1, sess, b):
    path = os.path.join(sess, "e1_b%02d.bin" % b)
    if not os.path.isfile(path):
        die("%s has no battle %d (e1_b%02d.bin)" % (sess, b, b))
    return list(e1.records(path)), read_fx(os.path.join(sess, "fx_b%02d.bin" % b))


def inputs_line(fx, tick, indent="      "):
    x = fx.get(tick)
    if not x:
        return indent + "(no fx record)"
    out = [indent + "inputs: schemes %s, pad0 %s (+extra %x), pad1 %s, keys %s%s" % (x["scheme"], pad_text(x["pads"][0]), x["pad0Extra"], pad_text(x["pads"][1]), key_entries(x["keys"]), "" if x["readOk"] == 31 else " (read mask %d of 31)" % x["readOk"])]
    for i, f in enumerate(x["fb"]):
        if f["ok"]:
            out.append(indent + "  f%d brain %08x pad %d active %d/%d hold %.2f/%.2f masks %s" % (
                i, f["brainVt"], f["padIdx"], f["onA"], f["onB"], f["hold"][0], f["hold"][1], " ".join("%x" % m for m in f["masks"] if m)))
    return "\n".join(out)


def cmd_frames(e1, sess, b, start, count, inputs):
    recs, fx = battle_records(e1, sess, b)
    shown = 0
    for r in recs:
        if start is not None and r["tick"] < start:
            continue
        print("tick %d F %d state 0x%X t %.2f rng %d/%016x" % (r["tick"], r["F"], r["state"], r["stateTime"], r["rngIdx"], r["rngHash"]))
        for k, f in enumerate(r["f"][:r["nf"]]):
            print("   f%d pl%03d %-24s ser %6d t %6.2f pos (%.3f %.3f %.3f) hp %.0f/%.0f konpaku %.0f rev %.0f form %d cmds %s"
                  % (k, f["charaId"], f["actName"], f["actSerial"], f["actTime"], f["pos0"], f["pos1"], f["pos2"], f["hp"], f["hpMax"],
                     f["konpaku"], f["rev"], f["form"], e1.fmt_cmds(f["cmds"]) or "-"))
        if inputs:
            print(inputs_line(fx, r["tick"]))
        shown += 1
        if count and shown >= count:
            break
    return 0


def cmd_diff(e1, sa, sb, ba, bb, key, maxshow):
    ra, fxa = battle_records(e1, sa, ba)
    rb, fxb = battle_records(e1, sb, bb)
    if not ra or not rb:
        die("a battle without records")
    if key is None:
        key = "F" if ra[0]["F"] >= 0 and rb[0]["F"] >= 0 and ra[-1]["F"] > 0 else "rel"

    def keyed(recs):
        t0 = recs[0]["tick"]
        return dict(((r["tick"] - t0) if key == "rel" else r[key], r) for r in recs)
    A, B = keyed(ra), keyed(rb)
    common = sorted(k for k in A if k in B)
    print("A: %s battle %d, %d records; B: %s battle %d, %d records; %d in common by %s" % (sa, ba, len(ra), sb, bb, len(rb), len(common), key))
    ignore = {"tick"} if key != "tick" else set()
    first, nd, fields = None, 0, collections.Counter()
    for k in common:
        x, y = e1.flat(A[k]), e1.flat(B[k])
        badf = [f for f in x if f in y and f not in ignore and e1.bits(x[f]) != e1.bits(y[f])]
        if badf:
            nd += 1
            fields.update(badf)
            if first is None:
                first = k
            if nd <= maxshow:
                print("%s %d differs in %d field(s): %s" % (key, k, len(badf), ", ".join("%s %r != %r" % (f, x[f], y[f]) for f in badf[:8])))
    print("records that differ: %d of %d%s" % (nd, len(common), (" -- FIRST at %s %d" % (key, first)) if first is not None else " -- IDENTICAL"))
    for f, c in fields.most_common(20):
        print("   %6d x %s" % (c, f))
    if first is not None:
        print("\ninputs around the first difference (A then B):")
        for k in [k for k in common if first - 3 <= k <= first]:
            print("%s %d" % (key, k))
            for nm, R, FX in (("A", A, fxa), ("B", B, fxb)):
                r = R[k]
                print("  %s tick %d: %s" % (nm, r["tick"], " | ".join("f%d %s ser %d cmds %s" % (i, f["actName"], f["actSerial"], e1.fmt_cmds(f["cmds"]) or "-")
                                                                   for i, f in enumerate(r["f"][:r["nf"]]))))
                print(inputs_line(FX, r["tick"], "    "))
    return 1 if first is not None else 0


def opt(argv, name, cast=str, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return cast(argv[i + 1])
    return default


def main(argv):
    if len(argv) < 3 or argv[1] not in ("join", "summary", "timing", "frames", "diff"):
        print(__doc__)
        return 2
    cmd = argv[1]
    flags_with_value = {"--out", "--battle", "--battle-b", "--from", "--count", "--key", "--max", "--lab"}
    pos, skip = [], False
    for i, a in enumerate(argv[2:], 2):
        if skip:
            skip = False
            continue
        if a in flags_with_value:
            skip = True
            continue
        if a.startswith("--"):
            continue
        pos.append(a)
    if cmd == "join":
        out = opt(argv, "--out")
        if not out:
            die("join needs --out <folder>")
        return cmd_join(pos, out)
    if cmd == "summary":
        return cmd_summary(pos[0])
    if cmd == "timing":
        return cmd_timing(pos[0], "--long" in argv, opt(argv, "--battle", int))
    e1 = lab_module(argv)
    if cmd == "frames":
        b = opt(argv, "--battle", int)
        if b is None:
            die("frames needs --battle N")
        return cmd_frames(e1, pos[0], b, opt(argv, "--from", int), opt(argv, "--count", int, 0), "--inputs" in argv)
    if len(pos) < 2:
        die("diff needs two session folders")
    b = opt(argv, "--battle", int)
    if b is None:
        die("diff needs --battle N")
    return cmd_diff(e1, pos[0], pos[1], b, opt(argv, "--battle-b", int, b), opt(argv, "--key"), opt(argv, "--max", int, 20))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    try:
        sys.exit(main(sys.argv))
    except BrokenPipeError:                 # the output was cut short (| more, | head): not an error
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        sys.exit(0)
