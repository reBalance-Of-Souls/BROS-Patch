"""netcode_mode.py -- the "New netcode" switch: the game's own online netcode (CLASSIC) or the Rebalance netcode (NEW).

IN THE LAUNCHER. The Game Modes page has a "New netcode" switch, independent of the one-game-mode slot. The choice is
kept in Json/netcode.json and applied to <game>\\bros_net.txt when it is switched and at every launch that installs the
master dinput8.dll (the main launcher and the Quick Launch scripts; BalanceInit through Quick Launch Community Patch):

  ON (the default)   NEW: lock 1, sleep 1, window 8, delay -1, probe 1 (build 3). A player who switched ON themselves
                     gets the launched version's own bros_net.txt instead, if its Overlay ships one (V1.2's, which
                     carries the current delay test block); the default never hands out a version's test block.
  OFF                CLASSIC is written: lock 0, sleep 8, window 3, delay 0, probe 0 -- the shipped game's values.

BY HAND, for a game started from BLEACH_Rebirth_of_Souls.exe:

    python launcher\\netcode_mode.py status  [<game folder>]    which netcode the next game start will use (changes nothing)
    python launcher\\netcode_mode.py classic [<game folder>]    the game's own netcode; also sets the launcher's switch OFF
    python launcher\\netcode_mode.py new     [<game folder>]    the Rebalance netcode; also sets the launcher's switch ON

The game folder defaults to Json\\config.json's GAME_PATH, then to D:\\SteamLibrary\\steamapps\\common\\BLEACH Rebirth of Souls.

HOW IT WORKS. The master (dinput8.dll, PART 41 "NETTEST") reads one file, <game>\\bros_net.txt, once, as the game
starts -- before the game has any thread -- and never again. A missing file means the master's built-in values, which
are NEW at delay 0; that is why OFF is written out explicitly. A switch takes effect at the next game start.

  CLASSIC  lock 0, sleep 8, window 3, delay 0, probe 0 -- the shipped game's values. Nothing about the network changes:
           no lock around the send queues, the network thread sleeps 8 ms between passes, 3 inputs per packet, the input
           delay the game computes, no determinism check. The master still MEASURES (its NET lines in patch_ranked.log:
           stalls, the network thread's period), so the two netcodes can be compared like for like.
  NEW      lock 1, sleep 1, window 8, delay -1, probe 1 -- build 3 (NETCODE 04): one lock around the send queues, the
           network thread every 1 ms (with the timer at 1 ms), 8 inputs per packet, one frame off the input delay the
           game computes, the guest's determinism check. Until 2026-09-29 NEW was written with delay 0; a file with
           those values (EARLIER) is still the launcher's own, never a hand edit.

Both seats of a match may use different netcodes: every packet stays readable by the other side (window: the receivers
skip entries they already have; lock and sleep are local; each seat computes and uses its own input delay -- NETCODE 04
section 5). To compare the two, both players use the same. Only the master has PART 41: a game mode that ships its own
dinput8.dll runs the game's own netcode whatever the switch says (the launchers print a note when that happens).

Nothing of yours is lost: a bros_net.txt whose values are neither mode's nor those of a file some version ships (edited
by hand) is kept as bros_net.txt.user-<date>-<time> before it is replaced. Every write goes through a temporary file (the file is always
wholly old or wholly new) and is read back and checked with this module's copy of the master's own parser.
"""
import datetime
import json
import os
import sys

DEFAULT_GAME = r"D:\SteamLibrary\steamapps\common\BLEACH Rebirth of Souls"
EXE = "BLEACH_Rebirth_of_Souls.exe"
NAME = "bros_net.txt"

# The launcher's switch. ON by default since 2026-09-29, for everyone who never touched it; a player who switched keeps
# their own choice. The A/B benchmark on the self-hosted rig (DataChakka, Nilsix researches/Netcode Benchmark) measured
# NEW smoother at the same input delay, and with 2 % packet loss the frozen time fell from ~2 % to 0.1 %. It was OFF by
# default before that (Berg, 2026-09-24: "a simple toggle instead of always on"). The default is NEW as measured,
# delay 0: a version's own test block (V1.2's delay -2) goes only to players who switched ON themselves -- measured the
# same day, delay -2 froze the game ~7 % of the time against 0.1 % at delay 0 (40 ms + 2 % loss). Later that day NEW
# itself moved to delay -1 (the user's call): one frame off the input delay for ~0.3 % more frozen time on the rig
# (Netcode Benchmark §9). Back to delay 0 if real matches show more than ~1 % frozen time or more than one felt stall
# per minute (their NET/match lines in patch_ranked.log).
DEFAULT_ON = True

# Real-match comparison switch. True: the normal version (the Community Patch and every thin layer built on it) runs
# the game's own netcode for EVERYONE, whatever the switch says; V1.2 and V1.3 keep the switch. It was True for one
# comparison session on 2026-09-29 (250ebbb): against the same opponent, CLASSIC played at 7 frames of input delay
# where NEW at delay -1 had played at 5, both smooth, and the user felt the new one a little more responsive -- so it is
# False again and the New netcode is back.
CP_FORCE_CLASSIC = False
CP_VERSION = "Bleach Rebirth of Souls Community Patch"
CHOICE_NAME = "netcode.json"                 # Json/netcode.json: {"NETCODE": "ON"} or {"NETCODE": "OFF"}

# this module lives in <repo>/launcher/; the repo's Json/ folder is where the launcher keeps its settings
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# the master's values: (lock, sleep, window, delay, probe)
DEFAULTS = (1, 1, 8, 0, 1)                   # dinput8_proxy.c: g_net_cfg_* initialisers (no file = these)
CLASSIC = (0, 8, 3, 0, 0)                    # the shipped game ("`lock 0`, `sleep 8`, `window 3` is stock"; delay 0, probe 0)
# delay -1: one frame off the input delay (2026-09-29). delay -2 was tried in real matches the same day (5a3249a) and
# dropped. As guest at RTT' 68 it ran D 2 with ~5,500 micro-stalls per battle (about one frame in three waiting a few
# ms) and 2 % frozen time, and the user found some dashes hard to get out. delay -1 in real play: 77-170 stalls, 0.06 %.
NEW = (1, 1, 8, -1, 1)                       # build 3, one frame off the input delay
EARLIER = {(1, 1, 8, 0, 1), (1, 1, 8, -2, 1)}  # NEW as the launcher wrote it before: still its own file, not a hand edit

TEXT = {
    "classic": (
        "# bros_net.txt -- CLASSIC: the game's own netcode. Written by the netcode toggle (the launcher or netcode_mode.py).\n"
        "# The master (dinput8.dll, PART 41) reads this once, at game start. These are the shipped game's values:\n"
        "# nothing about the network changes; the master only measures (its NET lines in patch_ranked.log).\n"
        "lock 0\nsleep 8\nwindow 3\ndelay 0\nprobe 0\n"),
    "new": (
        "# bros_net.txt -- NEW: the Rebalance netcode, build 3 (NETCODE 04). Written by the netcode toggle (the launcher or\n"
        "# netcode_mode.py).\n"
        "# The master (dinput8.dll, PART 41) reads this once, at game start.\n"
        "# lock 1: one lock around the send queues (the shipped game has none); sleep 1: the network thread every 1 ms\n"
        "# instead of 8; window 8: 8 inputs per packet instead of 3; delay -1: one frame off the input delay the game\n"
        "# computes; probe 1: the guest checks each host snapshot against its own simulation before adopting it\n"
        "# (measurement only).\n"
        "lock 1\nsleep 1\nwindow 8\ndelay -1\nprobe 1\n"),
}
WANT = {"classic": CLASSIC, "new": NEW}


class NetcodeError(Exception):
    """The switch could not be applied; nothing was changed. A launcher must not start the game on this."""


def c_atoi(b, i):
    """the Windows CRT's atoi on bytes b from index i: leading isspace, an optional sign, digits; a value past the int
    range is clamped to INT_MAX / INT_MIN (measured: the master's parser compiled with its toolchain and run on 433
    files, verify/compare.py)"""
    n = len(b)
    while i < n and b[i] in b" \t\n\v\f\r":
        i += 1
    neg = False
    if i < n and b[i] in b"+-":
        neg = b[i] == ord("-")
        i += 1
    v = 0
    while i < n and 48 <= b[i] <= 57:
        v = v * 10 + (b[i] - 48)
        i += 1
    v = -v if neg else v
    return min(max(v, -2 ** 31), 2 ** 31 - 1)


def parse(data):
    """net_read_cfg (dinput8_proxy.c, PART 41), line for line, on the bytes the master would read (ReadFile of at most
    2,047 bytes). Returns (lock, sleep, window, delay, probe) after the master's clamps."""
    lock, sleep, window, delay, probe = DEFAULTS
    b = bytes(data[:2047])
    b = b.split(b"\0", 1)[0]                          # the master's buffer is a C string
    p, n = 0, len(b)
    if b[:3] == b"\xEF\xBB\xBF":                      # a UTF-8 BOM from an editor
        p = 3
    while p < n:
        while p < n and b[p] in b" \t\r\n":
            p += 1
        if p >= n:
            break
        if b[p] == ord("#"):
            while p < n and b[p] != ord("\n"):
                p += 1
            continue
        key = bytearray()
        while p < n and len(key) < 31 and (65 <= b[p] <= 90 or 97 <= b[p] <= 122):
            key.append(b[p] | 0x20)
            p += 1
        while p < n and b[p] in b" \t=:":
            p += 1
        val = c_atoi(b, p)
        k = bytes(key)
        if k == b"lock":
            lock = 1 if val else 0
        elif k == b"sleep":
            sleep = val
        elif k == b"window":
            window = val
        elif k == b"delay":
            delay = val
        elif k == b"probe":
            probe = 1 if val else 0
        while p < n and b[p] != ord("\n"):
            p += 1
    sleep = min(max(sleep, 1), 8)
    window = min(max(window, 3), 10)
    delay = min(max(delay, -6), 0)
    return (lock, sleep, window, delay, probe)


def describe(v):
    if v == CLASSIC:
        return "CLASSIC (the game's own netcode)"
    if v == NEW:
        return "NEW (the Rebalance netcode, build 3), delay %d" % NEW[3]
    if v in EARLIER:
        return "NEW (the Rebalance netcode, build 3) at delay %d, an earlier setting%s" % (
            v[3], " (the master's built-in values)" if v == DEFAULTS else "")
    return "CUSTOM -- lock %d, sleep %d ms, window %d, delay %d, probe %d (neither classic nor new)" % v


def values(v):
    return "lock %d, sleep %d ms, window %d, delay %d, probe %d" % v


def current(game):
    """(state, values, raw bytes or the error): state is 'absent', 'unreadable', 'classic', 'new' or 'custom'. The master
    treats a file it cannot open as absent (CreateFileA fails -> its built-in values)."""
    path = os.path.join(game, NAME)
    if not os.path.exists(path):
        return "absent", DEFAULTS, None
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return "unreadable", DEFAULTS, e
    v = parse(raw)
    return ("classic" if v == CLASSIC else "new" if v == NEW or v in EARLIER else "custom"), v, raw


# ---------------------------------------------------------------------------------------------------------------------
# The launcher's switch
# ---------------------------------------------------------------------------------------------------------------------

def choice_path(base_dir):
    return os.path.join(base_dir, "Json", CHOICE_NAME)


def load_choice(base_dir):
    """True = the switch is ON. A missing, unreadable or unexpected Json/netcode.json reads as DEFAULT_ON."""
    try:
        with open(choice_path(base_dir), "r", encoding="utf-8") as f:
            v = json.load(f).get("NETCODE")
    except Exception:
        return DEFAULT_ON
    if v == "ON":
        return True
    if v == "OFF":
        return False
    return DEFAULT_ON


def save_choice(base_dir, on):
    """Keep the switch's position in Json/netcode.json (through a temporary file). Raises NetcodeError if it does not
    read back."""
    path = choice_path(base_dir)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"NETCODE": "ON" if on else "OFF"}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise NetcodeError("could not save the netcode switch in %s (%s)" % (path, e))
    if load_choice(base_dir) != bool(on):
        raise NetcodeError("the netcode switch did not read back from %s" % path)


def shipped_file(base_dir, chain):
    """The bros_net.txt a version ships -- GameVersions/<v>/Overlay/bros_net.txt -- along its base.txt chain (root
    first), the last one winning, the order install_overlay copies Overlay files in. None if the chain ships none."""
    found = None
    for v in chain or ():
        p = os.path.join(base_dir, "GameVersions", v, "Overlay", NAME)
        if os.path.isfile(p):
            found = p
    return found


def shipped_contents(base_dir):
    """The bytes of every bros_net.txt any version ships. A file on disk with the values of one of them is the
    launcher's own, whatever its comments say."""
    out = set()
    root = os.path.join(base_dir, "GameVersions")
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for v in names:
        try:
            with open(os.path.join(root, v, "Overlay", NAME), "rb") as f:
                out.add(f.read())
        except OSError:
            pass
    return out


def loader_reads_it(dll):
    """True if this dinput8.dll has PART 41 (its code names bros_net.txt), False if not, None if it cannot be read.
    Read out of the DLL itself, the way setup_matchmaking reads the plugin host's ABI tag."""
    try:
        with open(dll, "rb") as f:
            return NAME.encode() in f.read()
    except OSError:
        return None


def _keep_copy(path, raw):
    """Keep a file that is about to be replaced as <name>.user-<date>-<time>: created new, never over an earlier copy
    (-2, -3 ... when the name is taken); read back. Returns the copy's path."""
    keep = path + ".user-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base, k = keep, 1
    while True:
        try:
            with open(keep, "xb") as f:
                f.write(raw)
            break
        except FileExistsError:
            k += 1
            keep = "%s-%d" % (base, k)
    with open(keep, "rb") as f:
        if f.read() != raw:
            raise OSError("the copy %s did not read back" % keep)
    return keep


def _write(path, data):
    """Write through <path>.netcode_mode_tmp and os.replace, so the file is wholly old or wholly new; read back."""
    tmp = path + ".netcode_mode_tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        with open(tmp, "rb") as f:
            if f.read() != data:
                raise OSError("the temporary file did not read back")
        os.replace(tmp, path)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise
    with open(path, "rb") as f:
        if f.read() != data:
            raise OSError("%s did not read back as written" % os.path.basename(path))


def apply(game, on, shipped=None, base_dir=None):
    """Write <game>/bros_net.txt for the switch: CLASSIC when off; when on, the version's own file (`shipped`, a path
    from shipped_file()) or, if the version ships none, NEW. A file whose values are neither mode's nor any version's
    shipped file's (edited by hand; `base_dir` says where the versions are) is kept first. Returns one line for the
    console. Raises NetcodeError -- with bros_net.txt unchanged -- if the folder is not the game's, or a file cannot be
    read or written."""
    if not os.path.isfile(os.path.join(game, EXE)):
        raise NetcodeError("%s is not the game folder (no %s)" % (game, EXE))
    path = os.path.join(game, NAME)
    if on and shipped:
        try:
            with open(shipped, "rb") as f:
                want = f.read()
        except OSError as e:
            raise NetcodeError("cannot read the version's %s (%s)" % (shipped, e))
        what = "ON -- the version's own %s" % NAME
    elif on:
        want = TEXT["new"].encode()
        what = "ON -- NEW, build 3"
    else:
        want = TEXT["classic"].encode()
        what = "OFF -- CLASSIC, the game's own netcode"
    state, _v, raw = current(game)
    if state == "unreadable":
        raise NetcodeError("%s cannot be read (%s) -- close whatever holds it, or fix or remove it by hand"
                           % (path, raw))
    kept = None
    if raw is not None and raw != want:
        # a hand edit is a file whose VALUES are none the launcher writes: comments do not count (an older revision of
        # a version's own file, with other comments, is still that version's file), as for CLASSIC and NEW by hand
        known = {CLASSIC, NEW} | EARLIER | ({parse(c) for c in shipped_contents(base_dir)} if base_dir else set())
        if parse(raw) not in known:
            try:
                kept = _keep_copy(path, raw)
            except OSError as e:
                raise NetcodeError("could not keep a copy of your hand-edited %s (%s)" % (NAME, e))
    if raw != want:
        try:
            _write(path, want)
        except OSError as e:
            raise NetcodeError("could not write %s (%s)" % (path, e))
    got = parse(want)
    if (not on and got != CLASSIC) or (on and not shipped and got != NEW):
        raise NetcodeError("%s reads back as %s -- check it" % (NAME, describe(got)))
    line = "%s (%s)%s" % (what, values(got), "" if raw != want else ", already in place")
    if kept:
        line += "; your hand-edited %s was kept as %s" % (NAME, os.path.basename(kept))
    return line


def launch_step(base_dir, game, chain, loader=None):
    """The launch-time step for the launchers: applies the saved switch for the version whose base.txt chain (root
    first) is `chain`, prints what it did, and returns that line. `loader` is the dinput8.dll installed for this launch;
    one without PART 41 gets a note. Raises NetcodeError -- the caller must then not start the game."""
    forced = CP_FORCE_CLASSIC and CP_VERSION in (chain or ())
    on = False if forced else load_choice(base_dir)
    chose = os.path.exists(choice_path(base_dir))      # a version's test block only for a player who switched ON
    line = apply(game, on, shipped_file(base_dir, chain) if on and chose else None, base_dir)
    if forced:
        line += " -- forced on the Community Patch, whatever the switch says (CP_FORCE_CLASSIC)"
    print("[netcode] " + line)
    if loader and loader_reads_it(loader) is False:
        print("[netcode] note: the dinput8.dll installed for this launch has no netcode switch (a game mode's own "
              "loader), so this game runs the game's own netcode whatever the switch says")
    return line


# ---------------------------------------------------------------------------------------------------------------------
# By hand
# ---------------------------------------------------------------------------------------------------------------------

def _repo_json():
    """The repo's Json/ folder when this module sits in <repo>/launcher/, else None."""
    j = os.path.join(REPO, "Json")
    return j if os.path.isdir(j) else None


def default_game():
    """Json/config.json's GAME_PATH (the launcher's game folder) when it names a folder, else DEFAULT_GAME."""
    j = _repo_json()
    if j:
        try:
            with open(os.path.join(j, "config.json"), "r", encoding="utf-8") as f:
                g = json.load(f).get("GAME_PATH", "")
            if g and os.path.isdir(g):
                return g
        except Exception:
            pass
    return DEFAULT_GAME


def status(game):
    state, v, raw = current(game)
    print("game folder: %s%s" % (game, "" if os.path.isfile(os.path.join(game, EXE)) else "   !! %s not found here" % EXE))
    if state == "absent":
        print("  %s: none -- the master uses its built-in values" % NAME)
    elif state == "unreadable":
        print("  %s: cannot be read (%s) -- the master uses its built-in values" % (NAME, raw))
    else:
        print("  %s: %d bytes%s" % (NAME, len(raw), "" if raw in (TEXT["classic"].encode(), TEXT["new"].encode())
                                     else " (not written by the netcode toggle)"))
    print("  => the next game start uses: %s" % describe(v))
    if _repo_json():
        print("  the launcher's New netcode switch: %s%s" % ("ON" if load_choice(REPO) else "OFF",
              "" if os.path.exists(choice_path(REPO)) else " (never switched: the default)"))
    return state


def _record_choice(on):
    """After a switch by hand, set the launcher's switch the same way, so the two cannot disagree."""
    if not _repo_json():
        return
    try:
        save_choice(REPO, on)
        print("the launcher's New netcode switch is now %s" % ("ON" if on else "OFF"))
    except NetcodeError as e:
        print("!! %s -- the launcher's switch was not changed" % e)


def switch(game, mode):
    path = os.path.join(game, NAME)
    if not os.path.isfile(os.path.join(game, EXE)):
        print("NOTHING CHANGED: %s is not the game folder (no %s)" % (game, EXE))
        return 1
    state, v, raw = current(game)
    if state == "unreadable":
        print("NOTHING CHANGED: %s cannot be read (%s) -- fix or remove it by hand first" % (path, raw))
        return 1
    want = TEXT[mode].encode()
    if raw == want:
        print("Already %s. Nothing to do." % describe(v))
        _record_choice(mode == "new")
        return 0
    if state == "custom" or (raw is not None and parse(raw) not in {CLASSIC, NEW} | EARLIER):
        try:
            keep = _keep_copy(path, raw)
        except OSError as e:
            print("NOTHING CHANGED: could not keep a copy of your %s (%s)" % (NAME, e))
            return 1
        print("kept   your %s as %s" % (NAME, os.path.basename(keep)))
    try:
        _write(path, want)
    except OSError as e:
        print("NOTHING CHANGED: could not write %s (%s)" % (path, e))
        return 1
    got = parse(open(path, "rb").read())
    if got != WANT[mode]:
        print("!! %s was written but reads back as %s -- check it" % (NAME, describe(got)))
        return 1
    print("wrote  %s: %s" % (NAME, describe(got)))
    _record_choice(mode == "new")
    print("It takes effect at the next game start (launcher or exe). For a fair comparison, both players use the same.")
    return 0


def main(argv):
    if len(argv) < 2 or argv[1] not in ("status", "classic", "new"):
        print(__doc__)
        return 2
    game = argv[2] if len(argv) > 2 else default_game()
    if not os.path.isdir(game):
        print("no such folder: %s -- pass the game folder as the second argument" % game)
        return 2
    if argv[1] == "status":
        status(game)
        return 0
    return switch(game, argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
