"""The game exe for the Quick Launches: the stock one back when the version ships no exe recipe.

The main launcher's setup_exe patches the exe for a version whose base.txt chain ships Exe/exe_patch.recipe, and puts
the stock exe back (from _launcher_vanilla_backup/) for a chain that does not. The Quick Launches never touched the
exe. Since the V1.5 rework (2026-11-03) no version ships a recipe (v15exe.dll makes V1.5's exe edits in memory), so a
Quick Launch after the main launcher had patched the exe for an old version (old V1.7, V1.6, CRE) started that
patched exe under V1.5, and the Room Match screen crashed 5 s in at exe+0x8B3092 reading 0x258. This is the main
launcher's no-recipe branch, for them. A chain that does ship a recipe is left to the main launcher (said, never
blocking).

    restore_stock(base_dir, game_path, chain) -> a line to print, or None
"""
import json
import os
import shutil

EXE_NAME = "BLEACH_Rebirth_of_Souls.exe"
STATE_NAME = "launcher_patch_state.json"
BACKUP_DIR = "_launcher_vanilla_backup"


def recipe(base_dir, chain):
    """The chain's exe recipe (the last one, as setup_exe picks it), or None."""
    found = None
    for v in chain:
        p = os.path.join(base_dir, "GameVersions", v, "Exe", "exe_patch.recipe")
        if os.path.exists(p):
            found = p
    return found


def restore_stock(base_dir, game_path, chain):
    if recipe(base_dir, chain):
        return ("[exe] this version patches the game exe and a Quick Launch does not: start it once from the "
                "main launcher")
    state_path = os.path.join(game_path, STATE_NAME)
    try:
        with open(state_path, "r") as f:
            state = json.load(f)
    except Exception:
        return None                     # no state: the launchers never patched this exe
    if not state.get("exe"):
        return None
    bak = os.path.join(game_path, BACKUP_DIR, EXE_NAME)
    if os.path.exists(bak):
        try:
            shutil.copy2(bak, os.path.join(game_path, EXE_NAME))
        except Exception as e:
            return f"[exe] could not restore stock exe: {e}"
    state["exe"] = False
    try:
        with open(state_path, "w") as f:
            json.dump(state, f, indent=1)
    except Exception as e:
        return f"[exe] could not write patch state: {e}"
    return "[exe] stock exe restored (this version ships no exe recipe)"
