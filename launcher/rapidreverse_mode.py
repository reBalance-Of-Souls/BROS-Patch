"""rapidreverse_mode.py -- the launcher's Rapid Reverse switch (rapidreverse.dll).

IN THE LAUNCHER. The Advanced settings page has a "Rapid Reverse" card with one switch, ON unless it is switched off:

  Rapid Reverse   ON (the default): the game as it has been since 2026-10-07 -- Rapid Reverse (two of Light, Heavy and
                  Signature together, or its bound button, once a move has hit, for 1.5 Reverse bars), its Input
                  Settings row, the 1.5-bar marker on the Reverse gauge, the gauge's look, the pop and the sound, the
                  combo scaling and the Reverse lock -- and Diminishing Returns.
                  OFF: Rapid Reverse is gone, as if it had never been added: no pairs and no button, no Input Settings
                  row, no marker, no gauge look, no pop, no sound, no combo scaling, no Reverse lock. Diminishing
                  Returns stays (each SP move over in a combo: 25 % less Fighting Spirit and Reverse for the rest of
                  it, adding up).

Berg, 2026-11-13: "Add a new option in the launcher that would disable Rapid Reverse and its UI and everything about it
as if it was never added without breaking anything." His choices: Diminishing Returns stays; the CPU as it is (it uses
nothing of Rapid Reverse: cpuai.dll 0.4.0); Tag battle's inputs as they are (the pairs and F6 / F7 still tag; with
Rapid Reverse off nobody can Rapid Reverse); this launcher only (the public launcher's beta always has it ON).

THE FILE. OFF writes <game>\\ReBalanceOfSouls\\rapidreverse.txt (`rapid_reverse 0`); ON removes it, so ON leaves the game
folder exactly as it was before this switch existed. Beside the plugins, not as a bros_*.txt beside the exe:
  * the online pool (launcher/content_pool.py) counts it there too, so a player with Rapid Reverse off only meets
    players with it off, and a player with it on -- no file -- keeps the pool he shares with the public beta and with
    every launcher without this switch;
  * the public launcher, run on the same game folder, moves every ReBalanceOfSouls\\*.txt its beta build does not list
    into its quarantine (launcher/leftovers.py, the same file in both repositories), so a beta game never starts with
    Rapid Reverse off; a bros_*.txt switch would have stayed. This launcher keeps the file (launch() names it to
    leftovers.clean) and its vanilla start removes it (launcher/vanilla_revert.py, PLUGIN_DIR_REMOVE).
It is written or removed when the switch is clicked and at every launch that installs the loader (this launcher and
its right-click Quick Launch), so a game started from the exe follows the switch too -- a file, not an environment
variable, because an environment variable never reaches a game started from the exe (devtools_mode.py's pattern).

ONLINE: OFF changes what happens in a match, so both players need the same setting -- the pool sees to it.

GAME MODES: rapidreverse.dll reads the file in the main game only. The RapideReverse game mode is Rapid Reverse itself
(BalanceLeadTools/senkeiLaunch.py's mode) and arms it whatever the file says; every other game mode declines
rapidreverse.dll anyway. The file always follows the switch, so the next main-game start (from the exe too) does.

BY HAND, for a game started from BLEACH_Rebirth_of_Souls.exe:

    python launcher\\rapidreverse_mode.py status     [<game folder>]   what the next game start will do (changes nothing)
    python launcher\\rapidreverse_mode.py rr on|off  [<game folder>]

It also sets the launcher's switch, so the two cannot disagree. The game folder defaults to Json\\config.json's
GAME_PATH, then to D:\\SteamLibrary\\steamapps\\common\\BLEACH Rebirth of Souls.

THE FILE'S RULES. rapidreverse.dll reads it once, at game start (rr_read_switch in Files/Matchmaking/
rapidreverse_plugin.c), with a plain fopen; they are pl005.dll's rules for bros_zangetsu.txt with this key, and parse()
below copies them byte for byte:
  * the CRT's text mode (CR LF -> LF; a Ctrl-Z ends the file); fgets into 128 bytes, so a chunk is at most 127 bytes; a
    chunk with no LF makes the next chunk the tail of the same line, and a tail is skipped; a chunk ends at a NUL;
  * the first chunk may start with a UTF-8 BOM; leading spaces and tabs go; an empty chunk, '#' or ';' first, or any
    other control character first is skipped;
  * the key runs to a space, tab, '=', ':', CR or LF; "rapid_reverse" in any case is the switch, nothing else is; its
    value follows any spaces, tabs, '=' and ':';
  * '1', or a value starting "on", "yes" or "true" in any case, is ON; '0', or "off", "no" or "false", is OFF; any
    other value is unreadable and gives the default, ON; the last rapid_reverse line wins;
  * no file (or one that cannot be opened), or no rapid_reverse line: ON.
This module writes the file through a temporary file (wholly old or wholly new), reads it back and checks it with
parse(). The launcher's switch is the file's only author: a hand edit is replaced or removed at the next launch.
"""
import json
import os
import sys

DEFAULT_GAME = r"D:\SteamLibrary\steamapps\common\BLEACH Rebirth of Souls"
EXE = "BLEACH_Rebirth_of_Souls.exe"
DIR = "ReBalanceOfSouls"                 # the plugins' folder (setup_matchmaking): the file sits beside them
NAME = "rapidreverse.txt"
CHOICE_NAME = "rapidreverse.json"        # Json/rapidreverse.json: {"RAPID_REVERSE": "ON"|"OFF"}
PLUGIN = os.path.join(DIR, "rapidreverse.dll")
DEFAULT_ON = True                        # Berg: an option that disables it -- the game as before unless switched off
KEY = b"rapid_reverse"
OWN_MODE = "RapideReverse"               # the game mode that is Rapid Reverse itself: rapidreverse.dll does not read the file
# False since 2026-11-17 (Nilsix: Rapid Reverse out of the public release of 2026-11-27, back later): rapidreverse.dll
# is built with RR_MAIN_GAME 0 and never reads the file, so the launcher hides the card and every launch removes the
# file (an OFF left from before would only split the online pool). True again together with RR_MAIN_GAME 1.
IN_GAME = False

# this module lives in <repo>/launcher/; the repo's Json/ folder is where the launcher keeps its settings
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RapidReverseModeError(Exception):
    """The switch could not be applied; nothing was changed. A launcher must not start the game on this."""


def text():
    """The file's text. Only OFF is ever written: ON is no file."""
    return ("# rapidreverse.txt -- the launcher's Rapid Reverse switch (Advanced settings > Rapid Reverse, or\n"
            "# launcher\\rapidreverse_mode.py). Read once, at game start, by rapidreverse.dll. While this file is\n"
            "# here Rapid Reverse is OFF: none of it is installed (no pairs, no button, no Input Settings row, no\n"
            "# marker, no gauge look, no pop, no sound, no combo scaling, no Reverse lock). Diminishing Returns stays.\n"
            "# The switch ON removes this file. Do not edit it: the next launch writes or removes it again.\n"
            "rapid_reverse 0\n")


def _value(v):
    """rr_parse_onoff on the bytes after the key: True / False, or None when it is unreadable."""
    v = v.lstrip(b" \t=:")
    lo = v.lower()
    if v[:1] == b"1" or lo.startswith(b"on") or lo.startswith(b"yes") or lo.startswith(b"true"):
        return True
    if v[:1] == b"0" or lo.startswith(b"off") or lo.startswith(b"no") or lo.startswith(b"false"):
        return False
    return None


def parse(data):
    """rapidreverse.dll's rr_read_switch, chunk for chunk, on the bytes it would read. Returns (on, how): on is a
    boolean; how is "no line" (no rapid_reverse line: the default), "file" (the last line's value) or "unreadable"
    (the last line's value could not be read: the default)."""
    b = bytes(data).split(b"\x1a", 1)[0].replace(b"\r\n", b"\n")
    on, how = DEFAULT_ON, "no line"
    first, tail = True, False
    p = 0
    while p < len(b):
        e = b.find(b"\n", p, p + 127)
        chunk = b[p:e + 1] if e >= 0 else b[p:p + 127]
        p += len(chunk)
        s = chunk.split(b"\0", 1)[0]
        was_tail, tail = tail, b"\n" not in s
        if was_tail:
            first = False
            continue
        if first and s[:3] == b"\xef\xbb\xbf":
            s = s[3:]
        first = False
        s = s.lstrip(b" \t")
        if not s or s[:1] in (b"#", b";") or s[0] < 0x20:
            continue
        k = 0
        while k < len(s) and s[k:k + 1] not in (b" ", b"\t", b"=", b":", b"\r", b"\n"):
            k += 1
        if k == len(KEY) and s[:k].lower() == KEY:
            v = _value(s[k:])
            if v is None:
                on, how = DEFAULT_ON, "unreadable"
            else:
                on, how = v, "file"
    return on, how


def switch_path(game):
    return os.path.join(game, DIR, NAME)


def current(game):
    """(state, on, raw bytes or the error): state is 'absent', 'unreadable', 'launcher' (the file this module writes)
    or 'hand' (anything else). rapidreverse.dll treats a file it cannot open as absent (ON)."""
    path = switch_path(game)
    if not os.path.exists(path):
        return "absent", DEFAULT_ON, None
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return "unreadable", DEFAULT_ON, e
    v = parse(raw)[0]
    return ("launcher" if raw == text().encode() else "hand"), v, raw


def describe(on):
    return ("Rapid Reverse ON (the game as before)" if on else
            "Rapid Reverse OFF (none of it in the game; Diminishing Returns stays)")


# ---------------------------------------------------------------------------------------------------------------------
# The launcher's switch
# ---------------------------------------------------------------------------------------------------------------------

def choice_path(base_dir):
    return os.path.join(base_dir, "Json", CHOICE_NAME)


def load_choice(base_dir):
    """True = ON. A missing, unreadable or unexpected Json/rapidreverse.json, or value, reads as the default (ON); only
    "OFF" is OFF."""
    try:
        with open(choice_path(base_dir), "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return DEFAULT_ON
    if not isinstance(d, dict):
        return DEFAULT_ON
    v = d.get("RAPID_REVERSE")
    return False if v == "OFF" else True if v == "ON" else DEFAULT_ON


def save_choice(base_dir, on):
    """Keep the switch in Json/rapidreverse.json (through a temporary file). Raises RapidReverseModeError if it does not
    read back."""
    path = choice_path(base_dir)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"RAPID_REVERSE": "ON" if on else "OFF"}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise RapidReverseModeError("could not save the Rapid Reverse switch in %s (%s)" % (path, e))
    if load_choice(base_dir) != bool(on):
        raise RapidReverseModeError("the Rapid Reverse switch did not read back from %s" % path)


def _write(path, data):
    """Write through <path>.rapidreverse_mode_tmp and os.replace, so the file is wholly old or wholly new; read back."""
    tmp = path + ".rapidreverse_mode_tmp"
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


def apply(game, on, mode=None):
    """Remove <game>/ReBalanceOfSouls/rapidreverse.txt (ON) or write it (OFF). Returns one line for the console. Raises
    RapidReverseModeError -- with the file as it was -- if the folder is not the game's, or the file cannot be read,
    written or removed. mode: the launch's game mode, for the note on the RapideReverse mode only."""
    if not os.path.isfile(os.path.join(game, EXE)):
        raise RapidReverseModeError("%s is not the game folder (no %s)" % (game, EXE))
    path = switch_path(game)
    state, v, raw = current(game)
    if state == "unreadable":
        raise RapidReverseModeError("%s cannot be read (%s) -- close whatever holds it, or remove it by hand"
                                    % (path, raw))
    if on:
        if state == "absent":
            line = describe(True) + " (no %s\\%s)" % (DIR, NAME)
        else:
            try:
                os.remove(path)
            except OSError as e:
                raise RapidReverseModeError("could not remove %s (%s) -- the game would start with Rapid Reverse off "
                                            "although the switch is ON" % (path, e))
            if os.path.exists(path):
                raise RapidReverseModeError("%s is still there after its removal" % path)
            line = describe(True) + " (%s\\%s removed%s)" % (
                DIR, NAME, "" if state == "launcher" else ", a hand-edited one that said %s" % ("ON" if v else "OFF"))
    else:
        if not os.path.isdir(os.path.join(game, DIR)):
            return (describe(False) + " -- note: the game folder has no %s\\ (no plugin is installed), so nothing was "
                    "written; the next launch that installs the plugins writes %s" % (DIR, NAME))
        want = text().encode()
        if raw != want:
            try:
                _write(path, want)
            except OSError as e:
                raise RapidReverseModeError("could not write %s (%s)" % (path, e))
        got = parse(want)
        if got != (False, "file"):
            raise RapidReverseModeError("%s reads back as %s -- check it" % (NAME, describe(got[0])))
        line = describe(False) + ("" if raw != want else " (already in place)")
        if state == "hand":
            line += "; the hand-edited %s (it said %s) was replaced" % (NAME, "ON" if v else "OFF")
        if mode == OWN_MODE:
            line += (" -- note: the %s game mode is Rapid Reverse itself and does not read %s; the switch is for the "
                     "main game" % (OWN_MODE, NAME))
    if not os.path.isfile(os.path.join(game, PLUGIN)):
        line += " -- note: %s is not installed, so Rapid Reverse is not in this game at all" % PLUGIN
    return line


def launch_step(base_dir, game, mode=None):
    """The launch-time step for the launchers, after the loader and the plugins are in (setup_matchmaking): applies the
    saved switch, prints what it did and returns that line. Raises RapidReverseModeError -- the caller must then not
    start the game (a match on a setting the switch does not show is the "works for me" bug)."""
    line = apply(game, load_choice(base_dir) if IN_GAME else True, mode)
    if not IN_GAME:   # no file whatever was saved; the DLL says ON/OFF no more
        line = "out of this release (rapidreverse.dll: Diminishing Returns only); the switch's file: " + line
    print("[rapidreverse] " + line)
    return line


def set_choice(base_dir, game, on):
    """The Advanced settings toggle: keep the choice and apply it to the game folder now, so a game started from the
    exe follows it too. Raises RapidReverseModeError only when the choice itself could not be saved; returns what was
    done to the game folder (a failure there is said, and the next launch applies the switch or stops)."""
    save_choice(base_dir, on)
    try:
        return apply(game, on)
    except RapidReverseModeError as e:
        return "the switch is saved, but the game folder could not follow it now (%s); the next launch applies it" % e


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
        print("  %s\\%s: none -- the default, ON" % (DIR, NAME))
    elif state == "unreadable":
        print("  %s\\%s: cannot be read (%s) -- rapidreverse.dll treats that as none: ON" % (DIR, NAME, raw))
    else:
        how = parse(raw)[1]
        print("  %s\\%s: %d bytes%s%s" % (DIR, NAME, len(raw), "" if state == "launcher" else " (edited by hand)",
                                          "" if how == "file" else " -- %s: the default, ON" %
                                          ("no rapid_reverse line" if how == "no line" else "its value cannot be read")))
    print("  => the next game start (the main game): %s" % describe(v))
    if not os.path.isfile(os.path.join(game, PLUGIN)):
        print("  (%s is not installed: Rapid Reverse is not in the game until a launch installs it)" % PLUGIN)
    if _repo_json():
        print("  the launcher's switch: %s%s" % (describe(load_choice(REPO)),
              "" if os.path.exists(choice_path(REPO)) else " (never switched: the default)"))
    return state


def switch(game, on):
    if not os.path.isfile(os.path.join(game, EXE)):
        print("NOTHING CHANGED: %s is not the game folder (no %s)" % (game, EXE))
        return 1
    state, _v, raw = current(game)
    if state == "unreadable":
        print("NOTHING CHANGED: %s cannot be read (%s) -- fix or remove it by hand first" % (switch_path(game), raw))
        return 1
    try:
        line = apply(game, on)
    except RapidReverseModeError as e:
        print("NOTHING CHANGED: %s" % e)
        return 1
    print("done: %s" % line)
    if _repo_json():
        try:
            save_choice(REPO, on)
            print("the launcher's switch is now: %s" % describe(on))
        except RapidReverseModeError as e:
            print("!! %s -- the launcher's switch was not changed" % e)
    print("It takes effect at the next game start (launcher or exe).")
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "status":
        game = argv[2] if len(argv) > 2 else default_game()
        if not os.path.isdir(game):
            print("no such folder: %s -- pass the game folder as the second argument" % game)
            return 2
        status(game)
        return 0
    if len(argv) >= 3 and argv[1] == "rr" and argv[2] in ("on", "off"):
        game = argv[3] if len(argv) > 3 else default_game()
        if not os.path.isdir(game):
            print("no such folder: %s -- pass the game folder as the third argument" % game)
            return 2
        return switch(game, argv[2] == "on")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
