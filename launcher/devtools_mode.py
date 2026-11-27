"""devtools_mode.py -- the launcher's developer-tool switches: BRoS Studio (studio.dll) and F9 (hide / show the HUD).

IN THE LAUNCHER. The Advanced settings page has a "Developer tools" card with two switches, both OFF unless switched on:

  BRoS Studio        studio.dll arms -- its hooks, its thread, its hotkeys, studio.txt -- only when this is ON.
                     OFF, it writes one line to patch_ranked.log and does nothing else.
  F9 hides the HUD   the exe's F9 toggle (the HUD cave, V1.2 / V1.3 / the Community Patch / CRE / V1.6) reads its key
                     only when this is ON: studio.dll sets the exe's enable byte (0x1DC13F2) at game start. It works
                     with BRoS Studio OFF.

Berg, 2026-09-30: studio.dll "Have it be always off, and only activate under a gamemode switch toggle"; "F9 hotkey
should be enabled through the launcher. Same as all other stuff." Both are development tools; neither is live unless
someone switches it on.

The choice is kept in Json/devtools.json and written to <game>\\bros_tools.txt when a switch is clicked and at every
launch that installs the loader (the launcher and its right-click Quick Launch), so a game started from the exe
follows the switches too -- a file, not an environment variable, because an environment variable never reaches a game
started from the exe (the bros_net.txt pattern, launcher/netcode_mode.py).

BY HAND, for a game started from BLEACH_Rebirth_of_Souls.exe:

    python launcher\\devtools_mode.py status          [<game folder>]   what the next game start will do (changes nothing)
    python launcher\\devtools_mode.py studio on|off   [<game folder>]
    python launcher\\devtools_mode.py f9 on|off       [<game folder>]

Each also sets the launcher's switch, so the two cannot disagree. The game folder defaults to Json\\config.json's
GAME_PATH, then to D:\\SteamLibrary\\steamapps\\common\\BLEACH Rebirth of Souls.

THE FILE is read once, at game start, by studio.dll (tools_read in studio_plugin.c): one switch per line, "studio"
or "f9", then a value; "1", "on", "yes" or "true" is on, anything else -- or a missing line, or no file -- is off.
This module writes it through a temporary file (wholly old or wholly new), reads it back and checks it with its own
copy of studio.dll's reader (parse). The launcher's switches are the file's only author: a hand edit is replaced at
the next launch (every value a hand edit can hold is one the switches can hold, so nothing is lost).
"""
import json
import os
import sys

DEFAULT_GAME = r"D:\SteamLibrary\steamapps\common\BLEACH Rebirth of Souls"
EXE = "BLEACH_Rebirth_of_Souls.exe"
NAME = "bros_tools.txt"
CHOICE_NAME = "devtools.json"            # Json/devtools.json: {"STUDIO": "ON"|"OFF", "F9": "ON"|"OFF"}
PLUGIN = os.path.join("ReBalanceOfSouls", "studio.dll")   # where setup_matchmaking installs the plugin

# this module lives in <repo>/launcher/; the repo's Json/ folder is where the launcher keeps its settings
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class DevtoolsError(Exception):
    """The switches could not be applied; nothing was changed. A launcher must not start the game on this."""


def text(studio, f9):
    return ("# bros_tools.txt -- the launcher's developer-tool switches (Advanced settings > Developer tools, or\n"
            "# launcher\\devtools_mode.py). Read once, at game start, by studio.dll. A missing file is both off.\n"
            "# studio 1: BRoS Studio arms (hooks, hotkeys, studio.txt); 0: it stays inert.\n"
            "# f9 1: F9 hides / shows the HUD; 0: F9 does nothing.\n"
            "studio %d\nf9 %d\n" % (1 if studio else 0, 1 if f9 else 0))


def _on(v):
    """tools_on: "1", "on" (either case), or a first letter y / Y / t / T."""
    return v[:1] == b"1" or v[:2].lower() == b"on" or v[:1] in (b"y", b"Y", b"t", b"T")


def parse(data):
    """studio.dll's tools_read, chunk for chunk, on the bytes it would read: fopen(..., "r") is the CRT's TEXT mode
    (CR LF -> LF; a Ctrl-Z ends the file); fgets into 128 bytes (at most 127 per chunk, ending after a LF); each chunk
    is a C string (it ends at a NUL); a chunk that holds no LF marks the next chunk as the tail of the same line, and
    a tail is skipped. Returns (studio, f9) as booleans."""
    b = bytes(data).split(b"\x1a", 1)[0].replace(b"\r\n", b"\n")
    studio = f9 = False
    tail = False
    p = 0
    while p < len(b):
        e = b.find(b"\n", p, p + 127)
        chunk = b[p:e + 1] if e >= 0 else b[p:p + 127]
        p += len(chunk)
        s = chunk.split(b"\0", 1)[0]
        was_tail, tail = tail, b"\n" not in s
        if was_tail:
            continue
        if s[:3] == b"\xef\xbb\xbf":
            s = s[3:]
        s = s.lstrip(b" \t")
        if not s or s[:1] in (b"#", b";") or s[0] < 0x20:
            continue
        k = 0
        while k < len(s) and s[k:k + 1] not in (b" ", b"\t", b"=", b":", b"\r", b"\n"):
            k += 1
        key, v = s[:k], s[k:].lstrip(b" \t=:")
        if len(key) == 6 and key.lower() == b"studio":
            studio = _on(v)
        elif len(key) == 2 and key.lower() == b"f9":
            f9 = _on(v)
    return studio, f9


def current(game):
    """(state, (studio, f9), raw bytes or the error): state is 'absent', 'unreadable', 'launcher' (a file this module
    writes) or 'hand' (anything else). studio.dll treats a file it cannot open as absent (both off)."""
    path = os.path.join(game, NAME)
    if not os.path.exists(path):
        return "absent", (False, False), None
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return "unreadable", (False, False), e
    v = parse(raw)
    return ("launcher" if raw == text(*v).encode() else "hand"), v, raw


def describe(v):
    return "BRoS Studio %s, F9 %s" % ("ON" if v[0] else "OFF", "ON" if v[1] else "OFF")


# ---------------------------------------------------------------------------------------------------------------------
# The launcher's switches
# ---------------------------------------------------------------------------------------------------------------------

def choice_path(base_dir):
    return os.path.join(base_dir, "Json", CHOICE_NAME)


def load_choice(base_dir):
    """(studio, f9): True = ON. A missing, unreadable or unexpected Json/devtools.json, or key, reads as OFF."""
    try:
        with open(choice_path(base_dir), "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return False, False
    if not isinstance(d, dict):
        return False, False
    return d.get("STUDIO") == "ON", d.get("F9") == "ON"


def save_choice(base_dir, studio, f9):
    """Keep both switches in Json/devtools.json (through a temporary file). Raises DevtoolsError if they do not read
    back."""
    path = choice_path(base_dir)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"STUDIO": "ON" if studio else "OFF", "F9": "ON" if f9 else "OFF"}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise DevtoolsError("could not save the developer-tool switches in %s (%s)" % (path, e))
    if load_choice(base_dir) != (bool(studio), bool(f9)):
        raise DevtoolsError("the developer-tool switches did not read back from %s" % path)


def _write(path, data):
    """Write through <path>.devtools_mode_tmp and os.replace, so the file is wholly old or wholly new; read back."""
    tmp = path + ".devtools_mode_tmp"
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


def apply(game, studio, f9):
    """Write <game>/bros_tools.txt for the two switches. Returns one line for the console. Raises DevtoolsError --
    with bros_tools.txt unchanged -- if the folder is not the game's, or the file cannot be read or written."""
    if not os.path.isfile(os.path.join(game, EXE)):
        raise DevtoolsError("%s is not the game folder (no %s)" % (game, EXE))
    path = os.path.join(game, NAME)
    want = text(studio, f9).encode()
    state, _v, raw = current(game)
    if state == "unreadable":
        raise DevtoolsError("%s cannot be read (%s) -- close whatever holds it, or fix or remove it by hand"
                            % (path, raw))
    if raw != want:
        try:
            _write(path, want)
        except OSError as e:
            raise DevtoolsError("could not write %s (%s)" % (path, e))
    got = parse(want)
    if got != (bool(studio), bool(f9)):
        raise DevtoolsError("%s reads back as %s -- check it" % (NAME, describe(got)))
    line = describe(got) + ("" if raw != want else " (already in place)")
    if state == "hand":
        line += "; the hand-edited %s (%s) was replaced" % (NAME, describe(_v))
    if (studio or f9) and not os.path.isfile(os.path.join(game, PLUGIN)):
        line += " -- note: %s is not installed, so neither switch has any effect this time" % PLUGIN
    return line


def launch_step(base_dir, game):
    """The launch-time step for the launchers, after the loader and the plugins are in (setup_matchmaking): applies the
    saved switches, prints what it did and returns that line. Raises DevtoolsError -- the caller must then not start
    the game (a tool running that the switch shows off, or the reverse, is the "works for me" bug)."""
    studio, f9 = load_choice(base_dir)
    line = apply(game, studio, f9)
    print("[devtools] " + line)
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
        print("  %s: none -- both tools off" % NAME)
    elif state == "unreadable":
        print("  %s: cannot be read (%s) -- studio.dll treats that as none: both tools off" % (NAME, raw))
    else:
        print("  %s: %d bytes%s" % (NAME, len(raw), "" if state == "launcher" else " (edited by hand)"))
    print("  => the next game start: %s" % describe(v))
    if not os.path.isfile(os.path.join(game, PLUGIN)):
        print("  (%s is not installed: neither tool can run until a launch installs it)" % PLUGIN)
    if _repo_json():
        s, f = load_choice(REPO)
        print("  the launcher's switches: %s%s" % (describe((s, f)),
              "" if os.path.exists(choice_path(REPO)) else " (never switched: the default)"))
    return state


def switch(game, which, on):
    """`which` is 'studio' or 'f9'. The other switch keeps the launcher's value (or, outside a repo, the file's)."""
    if not os.path.isfile(os.path.join(game, EXE)):
        print("NOTHING CHANGED: %s is not the game folder (no %s)" % (game, EXE))
        return 1
    state, v, raw = current(game)
    if state == "unreadable":
        print("NOTHING CHANGED: %s cannot be read (%s) -- fix or remove it by hand first" % (os.path.join(game, NAME), raw))
        return 1
    base = load_choice(REPO) if _repo_json() else v
    studio, f9 = (on, base[1]) if which == "studio" else (base[0], on)
    try:
        line = apply(game, studio, f9)
    except DevtoolsError as e:
        print("NOTHING CHANGED: %s" % e)
        return 1
    print("wrote  %s: %s" % (NAME, line))
    if _repo_json():
        try:
            save_choice(REPO, studio, f9)
            print("the launcher's switches are now: %s" % describe((studio, f9)))
        except DevtoolsError as e:
            print("!! %s -- the launcher's switches were not changed" % e)
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
    if len(argv) >= 3 and argv[1] in ("studio", "f9") and argv[2] in ("on", "off"):
        game = argv[3] if len(argv) > 3 else default_game()
        if not os.path.isdir(game):
            print("no such folder: %s -- pass the game folder as the third argument" % game)
            return 2
        return switch(game, argv[1], argv[2] == "on")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
