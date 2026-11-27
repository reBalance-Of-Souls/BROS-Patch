"""zangetsu_mode.py -- the launcher's Zangetsu switch: manual Reawakening (pl005.dll).

IN THE LAUNCHER. The Advanced settings page has a "Zangetsu" card with one switch, ON unless it is switched off:

  Manual Reawakening   ON: Zangetsu's 4th moon stack gives him the Kikon channel -- his Awakened fighting-spirit bar
                       and its sublimation bar, both full, the way training mode's "Kikon channel" setting fills them --
                       and he enters his Reawakening himself, with the full bar, when he chooses to.
                       OFF: the 4th moon stack starts the Reawakening by itself, as it did before this switch.

Berg, 2026-10-18: "instead of entering automatically, it just gives him 'kikon channel' ... add it as a gamemode
instead to the dev build (manual rev ON by default, turning it off turns the game back to how it is right now with the
automatic rev on the 4th moon stack)."

The choice is kept in Json/zangetsu.json and written to <game>\\bros_zangetsu.txt when the switch is clicked and at
every launch that installs the loader (the launcher and its right-click Quick Launch), so a game started from the exe
follows the switch too -- a file, not an environment variable, because an environment variable never reaches a game
started from the exe (the bros_tools.txt pattern, launcher/devtools_mode.py).

ONLINE: the switch changes what happens in a match, so both players need the same setting, like any game mode.

BY HAND, for a game started from BLEACH_Rebirth_of_Souls.exe:

    python launcher\\zangetsu_mode.py status          [<game folder>]   what the next game start will do (changes nothing)
    python launcher\\zangetsu_mode.py manual on|off   [<game folder>]

It also sets the launcher's switch, so the two cannot disagree. The game folder defaults to Json\\config.json's
GAME_PATH, then to D:\\SteamLibrary\\steamapps\\common\\BLEACH Rebirth of Souls.

THE FILE is read once, at game start, by pl005.dll (pl005_read_manual_rev in Files/Matchmaking/pl005_gauge.c), with a
plain fopen in every build -- it is a game mode, not one of the test switches a release build ignores. Its rules, which
parse() below copies byte for byte:
  * the CRT's text mode (CR LF -> LF; a Ctrl-Z ends the file); fgets into 128 bytes, so a chunk is at most 127 bytes; a
    chunk with no LF makes the next chunk the tail of the same line, and a tail is skipped; a chunk ends at a NUL;
  * the first chunk may start with a UTF-8 BOM; leading spaces and tabs go; an empty chunk, '#' or ';' first, or any
    other control character first is skipped;
  * the key runs to a space, tab, '=', ':', CR or LF; "manual_rev" in any case is the switch, nothing else is; its
    value follows any spaces, tabs, '=' and ':';
  * '1', or a value starting "on", "yes" or "true" in any case, is ON; '0', or "off", "no" or "false", is OFF; any
    other value is unreadable and gives the default, ON; the last manual_rev line wins;
  * no file (or one that cannot be opened), or no manual_rev line: ON.
This module writes the file through a temporary file (wholly old or wholly new), reads it back and checks it with
parse(). The launcher's switch is the file's only author: a hand edit is replaced at the next launch.
"""
import json
import os
import sys

DEFAULT_GAME = r"D:\SteamLibrary\steamapps\common\BLEACH Rebirth of Souls"
EXE = "BLEACH_Rebirth_of_Souls.exe"
NAME = "bros_zangetsu.txt"
CHOICE_NAME = "zangetsu.json"            # Json/zangetsu.json: {"MANUAL_REV": "ON"|"OFF"}
PLUGIN = os.path.join("ReBalanceOfSouls", "pl005.dll")   # where setup_matchmaking installs Zangetsu's plugin
DEFAULT_MANUAL = True                    # Berg: "manual rev ON by default"

# this module lives in <repo>/launcher/; the repo's Json/ folder is where the launcher keeps its settings
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ZangetsuModeError(Exception):
    """The switch could not be applied; nothing was changed. A launcher must not start the game on this."""


def text(manual):
    return ("# bros_zangetsu.txt -- the launcher's Zangetsu switch (Advanced settings > Zangetsu, or\n"
            "# launcher\\zangetsu_mode.py). Read once, at game start, by pl005.dll. A missing file is ON.\n"
            "# manual_rev 1: the 4th moon stack gives the Kikon channel (the Awakened fighting-spirit bar and\n"
            "#               its sublimation bar, full); he enters the Reawakening himself.\n"
            "# manual_rev 0: the 4th moon stack starts the Reawakening by itself (as before).\n"
            "manual_rev %d\n" % (1 if manual else 0))


def _value(v):
    """pl005_parse_onoff on the bytes after the key: True / False, or None when it is unreadable."""
    v = v.lstrip(b" \t=:")
    lo = v.lower()
    if v[:1] == b"1" or lo.startswith(b"on") or lo.startswith(b"yes") or lo.startswith(b"true"):
        return True
    if v[:1] == b"0" or lo.startswith(b"off") or lo.startswith(b"no") or lo.startswith(b"false"):
        return False
    return None


def parse(data):
    """pl005.dll's pl005_read_manual_rev, chunk for chunk, on the bytes it would read. Returns (manual, how): manual is
    a boolean; how is "no line" (no manual_rev line: the default), "file" (the last line's value) or "unreadable" (the
    last line's value could not be read: the default)."""
    b = bytes(data).split(b"\x1a", 1)[0].replace(b"\r\n", b"\n")
    manual, how = DEFAULT_MANUAL, "no line"
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
        if k == 10 and s[:10].lower() == b"manual_rev":
            v = _value(s[10:])
            if v is None:
                manual, how = DEFAULT_MANUAL, "unreadable"
            else:
                manual, how = v, "file"
    return manual, how


def current(game):
    """(state, manual, raw bytes or the error): state is 'absent', 'unreadable', 'launcher' (a file this module writes)
    or 'hand' (anything else). pl005.dll treats a file it cannot open as absent (ON)."""
    path = os.path.join(game, NAME)
    if not os.path.exists(path):
        return "absent", DEFAULT_MANUAL, None
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return "unreadable", DEFAULT_MANUAL, e
    v = parse(raw)[0]
    return ("launcher" if raw == text(v).encode() else "hand"), v, raw


def describe(manual):
    return ("manual Reawakening ON (the 4th moon stack gives the Kikon channel)" if manual else
            "manual Reawakening OFF (the 4th moon stack starts the Reawakening)")


# ---------------------------------------------------------------------------------------------------------------------
# The launcher's switch
# ---------------------------------------------------------------------------------------------------------------------

def choice_path(base_dir):
    return os.path.join(base_dir, "Json", CHOICE_NAME)


def load_choice(base_dir):
    """True = ON. A missing, unreadable or unexpected Json/zangetsu.json, or value, reads as the default (ON); only
    "OFF" is OFF."""
    try:
        with open(choice_path(base_dir), "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return DEFAULT_MANUAL
    if not isinstance(d, dict):
        return DEFAULT_MANUAL
    v = d.get("MANUAL_REV")
    return False if v == "OFF" else True if v == "ON" else DEFAULT_MANUAL


def save_choice(base_dir, manual):
    """Keep the switch in Json/zangetsu.json (through a temporary file). Raises ZangetsuModeError if it does not read
    back."""
    path = choice_path(base_dir)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"MANUAL_REV": "ON" if manual else "OFF"}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise ZangetsuModeError("could not save the Zangetsu switch in %s (%s)" % (path, e))
    if load_choice(base_dir) != bool(manual):
        raise ZangetsuModeError("the Zangetsu switch did not read back from %s" % path)


def _write(path, data):
    """Write through <path>.zangetsu_mode_tmp and os.replace, so the file is wholly old or wholly new; read back."""
    tmp = path + ".zangetsu_mode_tmp"
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


def apply(game, manual):
    """Write <game>/bros_zangetsu.txt for the switch. Returns one line for the console. Raises ZangetsuModeError --
    with bros_zangetsu.txt unchanged -- if the folder is not the game's, or the file cannot be read or written."""
    if not os.path.isfile(os.path.join(game, EXE)):
        raise ZangetsuModeError("%s is not the game folder (no %s)" % (game, EXE))
    path = os.path.join(game, NAME)
    want = text(manual).encode()
    state, v, raw = current(game)
    if state == "unreadable":
        raise ZangetsuModeError("%s cannot be read (%s) -- close whatever holds it, or fix or remove it by hand"
                                % (path, raw))
    if raw != want:
        try:
            _write(path, want)
        except OSError as e:
            raise ZangetsuModeError("could not write %s (%s)" % (path, e))
    got = parse(want)
    if got != (bool(manual), "file"):
        raise ZangetsuModeError("%s reads back as %s -- check it" % (NAME, describe(got[0])))
    line = describe(got[0]) + ("" if raw != want else " (already in place)")
    if state == "hand":
        line += "; the hand-edited %s (%s) was replaced" % (NAME, describe(v))
    if not os.path.isfile(os.path.join(game, PLUGIN)):
        line += " -- note: %s is not installed, so Zangetsu is not in this game at all" % PLUGIN
    return line


def launch_step(base_dir, game):
    """The launch-time step for the launchers, after the loader and the plugins are in (setup_matchmaking): applies the
    saved switch, prints what it did and returns that line. Raises ZangetsuModeError -- the caller must then not start
    the game (a match on a setting the switch does not show is the "works for me" bug)."""
    line = apply(game, load_choice(base_dir))
    print("[zangetsu] " + line)
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
        print("  %s: none -- the default, ON" % NAME)
    elif state == "unreadable":
        print("  %s: cannot be read (%s) -- pl005.dll treats that as none: ON" % (NAME, raw))
    else:
        how = parse(raw)[1]
        print("  %s: %d bytes%s%s" % (NAME, len(raw), "" if state == "launcher" else " (edited by hand)",
                                      "" if how == "file" else " -- %s: the default, ON" %
                                      ("no manual_rev line" if how == "no line" else "its value cannot be read")))
    print("  => the next game start: %s" % describe(v))
    if not os.path.isfile(os.path.join(game, PLUGIN)):
        print("  (%s is not installed: Zangetsu is not in the game until a launch installs it)" % PLUGIN)
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
        print("NOTHING CHANGED: %s cannot be read (%s) -- fix or remove it by hand first" % (os.path.join(game, NAME), raw))
        return 1
    try:
        line = apply(game, on)
    except ZangetsuModeError as e:
        print("NOTHING CHANGED: %s" % e)
        return 1
    print("wrote  %s: %s" % (NAME, line))
    if _repo_json():
        try:
            save_choice(REPO, on)
            print("the launcher's switch is now: %s" % describe(on))
        except ZangetsuModeError as e:
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
    if len(argv) >= 3 and argv[1] == "manual" and argv[2] in ("on", "off"):
        game = argv[3] if len(argv) > 3 else default_game()
        if not os.path.isdir(game):
            print("no such folder: %s -- pass the game folder as the third argument" % game)
            return 2
        return switch(game, argv[2] == "on")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
