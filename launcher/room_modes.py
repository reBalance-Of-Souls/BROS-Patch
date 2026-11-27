"""
room_modes.py -- the files the room battle modes read beside their plugins, written at every launch.

Team battle, Tag battle, Multiplayer Team battle and the Create room's Game Mode row ship in
Files/Matchmaking/Plugins like every plugin (roomtrain.dll, tag2v2.dll, gamemode.dll) since
2026-11-02 ("ça doit être dans main"). Two of them read files that depend on the install, so every
launcher that installs the plugins calls install() right after them:

  gamemodes.txt            the Game Mode row's modes, from GameModes/*/Mode.json + CharaStatus.json
                           (launcher/gamemode_list.py). A room plays a mode only when every member
                           has the same file, so it is written from the commit, never by hand.
  tag2v2_Action.bin        the benched Tag battle partner's mini card and SP / Reverse gauge: a clone
  tag2v2_hudclone.txt      of the installed ui/script/scene/Action.bin (launcher/mk_tag_hud.py
                           --with-reiryoku --before --survival 4 --allies 4: + four enemy cards and four
                           ally cards for dcbossrush's Survival / Adventure group fights; 2026-11-23, tag2v2
                           with tag2v2_register_ally). Without them Tag battle plays with no mini cards.

and a rig's <game>/tag2v2_arm.txt goes: it puts tag2v2 in its test mode, whose tag2v2.txt overrides
(1 HP, Konpaku) apply to real Tag and Team rooms.

Nothing here may stop a launch: each step says what it could not do and the game starts anyway.
"""
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HUD_FILES = ("tag2v2_Action.bin", "tag2v2_hudclone.txt", "tag2v2_sv_Action.bin")


def _say(msg):
    print("[room modes] " + msg, flush=True)


def _gamemode_list():
    spec = importlib.util.spec_from_file_location("bros_gamemode_list", os.path.join(HERE, "gamemode_list.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_hud(action_bin, out_dir, say=_say):
    """Write the two Tag battle HUD files into out_dir; True if made."""
    for f in HUD_FILES:
        p = os.path.join(out_dir, f)
        if os.path.exists(p):
            os.remove(p)
    if not os.path.exists(action_bin):
        say("WARNING: no %s -- no Tag battle mini cards" % action_bin)
        return False
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "mk_tag_hud.py"), action_bin, out_dir,
                        "--with-reiryoku", "--before", "--survival", "4", "--allies", "4"], capture_output=True, text=True)
    line = (r.stdout.strip() or r.stderr.strip()).splitlines()[-1:] or [""]
    ok = r.returncode == 0 and all(os.path.exists(os.path.join(out_dir, f)) for f in HUD_FILES)
    say(("Tag battle HUD clone: " if ok else "WARNING: no Tag battle HUD clone (no mini cards): ") + line[0])
    return ok


def install(repo, game, say=_say):
    """After the plugins: gamemodes.txt and the Tag battle HUD clone beside them, no rig arm."""
    dst = os.path.join(game, "ReBalanceOfSouls")
    try:
        if os.path.exists(os.path.join(dst, "gamemode.dll")):
            _gamemode_list().write(repo, dst, say)
    except Exception as e:
        say("WARNING: gamemodes.txt not written (no Game Mode row modes): %s" % e)
    try:
        if os.path.exists(os.path.join(dst, "tag2v2.dll")):
            make_hud(os.path.join(game, "ui", "script", "scene", "Action.bin"), dst, say)
    except Exception as e:
        say("WARNING: no Tag battle HUD clone (no mini cards): %s" % e)
    try:
        arm = os.path.join(game, "tag2v2_arm.txt")
        if os.path.exists(arm):
            os.remove(arm)
            say("removed a rig's tag2v2_arm.txt (tag2v2 stays in its player mode)")
    except Exception as e:
        say("WARNING: could not remove tag2v2_arm.txt: %s" % e)
