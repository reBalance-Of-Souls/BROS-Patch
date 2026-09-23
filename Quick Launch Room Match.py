import os
import json
import shutil
import subprocess
import sys
import platform
import zlib
try:
    import requests
except:
    pass
try:
    import hashlib
except:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

GAME_VERSION = "Bleach Rebirth of Souls Community Patch"

config_path = os.path.join(BASE_DIR, "Json", "config.json")
with open(config_path, "r") as f:
    config = json.load(f)



game_path = config.get("GAME_PATH", "")

if game_path == "":
    input("Your game path is empty, please run the normal launcher first to set a game path, press Enter to quit")
    exit()
# RoomMatchBoot: the game boots straight to the ONLINE ROOM MATCH menu
# (Create room / Find room), skipping the title screen and the menu walk. Same
# shape as TrainingBoot -- a launch shortcut, no Script/, no pool tag. The
# It installs the SHIPPED loader, Files/Matchmaking/dinput8.dll, and asks it for
# this destination through BROS_BOOT_MODE -- so it is the normal loader, always,
# and cannot drift from it.
#
# KNOWN: pressing Return from the room-match menu does not land on the ONLINE
# menu -- see GameModes/RoomMatchBoot/README.md.
gameMode = "RoomMatchBoot"
# What this launcher asks the loader for, through BROS_BOOT_MODE.
BOOT_MODE = "roommatch"
reworks = ["OFF"]


def get_snapshot():
    try:
        result = subprocess.run(
            ["git", "-C", BASE_DIR, "rev-parse", "--short", "HEAD"],
            check=True, capture_output=True, text=True
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def pulling_from_git():
    # Ensure git can write the deep Effect/spfx/... paths that blow past the
    # legacy 260-char Windows limit. core.longpaths makes git use \\?\ extended
    # paths internally -- no admin, no registry change, no reboot. A partial
    # "Filename too long" clone then self-heals on launch: the objects are
    # already downloaded, so the reset --hard below writes the missing
    # long-path files with zero action from the user.
    subprocess.run(["git", "-C", BASE_DIR, "config", "core.longpaths", "true"], capture_output=True, text=True)
    if not os.path.exists(os.path.join(BASE_DIR, "BalanceLeadTools", "DevToken.txt")):
        subprocess.run(["git", "-C", BASE_DIR, "fetch"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", BASE_DIR, "reset", "--hard", "origin/main"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", BASE_DIR, "clean", "-fd", "-e", "Json"], check=True, capture_output=True, text=True)
    return subprocess.run(["git", "-C", BASE_DIR, "pull"], check=True, capture_output=True, text=True)


def open_file(path):
    if platform.system() == "Windows":
        os.startfile(path)
    elif platform.system() == "Darwin":
        subprocess.run(["open", path])
    else:
        subprocess.run(["xdg-open", path])


# ---------------------------------------------------------------------------
# Hand the game back from a development launch
#
# The development launchers install loose overlay files -- Byakuya's gauge UI
# among them -- record every one in launcher_patch_state.json, and put the
# stock copy back from _launcher_vanilla_backup the next time a version that
# does not want them is installed. This patch ships no Overlay, and its
# launchers never ran that revert, so switching from a development launch to
# this one left the development files in the game. Stock Pl22 code then read a
# UI scene built for the gauge, got a NULL element, and crashed at
# exe+0x22A547 on the switch to the evolved form -- an online evo, or the
# training "awakening" option. Measured 2026-09-22 and again 2026-09-23.
#
# So this is the revert half, under the same rules as the development side:
# restore what has a stock backup, delete only the roster switches (their mere
# presence changes the select grid), and LEAVE anything else -- a leftover file
# is recoverable, a deleted stock file is not. What is left stays listed in the
# state file, so the next launcher that wants the path does not back up our
# file as if it were stock.
# ---------------------------------------------------------------------------
_OVERLAY_ALWAYS_REMOVE = ("bros_roster_v12.txt", "bros_roster_v13.txt")


def revert_foreign_overlay(game_path, gameVersion):
    state_path = os.path.join(game_path, "launcher_patch_state.json")
    try:
        with open(state_path, "r") as f:
            state = json.load(f)
    except Exception:
        return 0                       # no state file: nothing was ever overlaid
    prev = list(state.get("overlay", []))
    if not prev:
        return 0
    backup_root = os.path.join(game_path, "_launcher_vanilla_backup")
    restored, left = 0, []
    for rel in prev:
        dst = os.path.join(game_path, *rel.split("/"))
        bak = os.path.join(backup_root, *rel.split("/"))
        try:
            if os.path.exists(bak):
                shutil.copy2(bak, dst)
                os.remove(bak)
                restored += 1
            elif os.path.exists(dst) and rel in _OVERLAY_ALWAYS_REMOVE:
                os.remove(dst)
                restored += 1
            elif os.path.exists(dst):
                left.append(rel)
        except Exception as e:
            # Keep it listed: dropping a path whose revert failed would let the
            # next launcher capture the development file as the stock backup.
            print(f"[overlay] could not revert {rel}: {e}")
            left.append(rel)
    state["overlay"] = sorted(left)
    state["version"] = gameVersion
    try:
        with open(state_path, "w") as f:
            json.dump(state, f, indent=1)
    except Exception as e:
        print(f"[overlay] could not write patch state: {e}")
    msg = f"[overlay] {restored} file(s) left by a previous launch put back to stock"
    if left:
        msg += f", {len(left)} left in place (no stock backup recorded)"
    print(msg)
    return restored


def injectFolder(files, folderName, fullFolder=True):
    folder_src = os.path.join(BASE_DIR, "GameVersions", f"{files}", f"{folderName}")
    folder_dst = os.path.join(game_path, f"{folderName}")
    if fullFolder:
        try:
            subprocess.run(["robocopy", folder_src, folder_dst, "/MIR"], capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            shutil.rmtree(folder_dst)
            shutil.copytree(folder_src, folder_dst)
    else:
        shutil.copytree(folder_src, folder_dst, dirs_exist_ok=True)


def injectPerformanceFiles(folderName, lowspecmodornot):
    try:
        shutil.copytree(os.path.join(BASE_DIR, "Files", "Spec Mod", f"{folderName}", f"{lowspecmodornot}"),
                         os.path.join(game_path, "00HIGH", "Effect", "spfx", "com"), dirs_exist_ok=True)
        shutil.copytree(os.path.join(BASE_DIR, "Files", "Spec Mod", f"{folderName}", f"{lowspecmodornot}"),
                         os.path.join(game_path, "01MIDDLE", "Effect", "spfx", "com"), dirs_exist_ok=True)
    except Exception as e:
        print(f"Error injecting performance files: {e}")


def setup_matchmaking(target_path, gameVersion):
    # This launcher is the Community Patch launcher plus a boot shortcut, so it
    # installs the SAME loader the normal launcher does. It used to prefer
    # GameModes/<mode>/dinput8.dll, and because that frozen binary SHADOWS the
    # shipped one, anything added to Files/Matchmaking/dinput8.dll never reached
    # a player who launched through here. That is exactly how the held backstep
    # shipped in the patch and was still reported as "does not work in game":
    # the mode loaders had been built before it and nobody rebuilt them.
    # The boot shortcut now travels as BROS_BOOT_MODE (see launch_patched) and
    # the loader reads it at startup, so one dll serves every shortcut and
    # cannot go stale.
    src = os.path.join(BASE_DIR, "Files", "Matchmaking", "dinput8.dll")
    try:
        shutil.copy(src, os.path.join(target_path, "dinput8.dll"))
    except Exception as e:
        print(f"[matchmaking] could not install dinput8.dll: {e}")
        return

    # ---- PLUGINS ------------------------------------------------------------
    # Mirrored: whatever is in Files/Matchmaking/Plugins goes to
    # <game>/ReBalanceOfSouls, and anything else there is removed. Clearing a
    # plugin this version does not ship matters as much as installing one -- a DLL
    # left by an older install keeps patching the exe beside the loader that
    # replaced it, and the failure reads as a crash with no cause.
    try:
        plug_src = os.path.join(BASE_DIR, "Files", "Matchmaking", "Plugins")
        plug_dst = os.path.join(target_path, "ReBalanceOfSouls")
        want = sorted(f for f in os.listdir(plug_src)
                      if f.lower().endswith(".dll")) if os.path.isdir(plug_src) else []
        with open(os.path.join(target_path, "dinput8.dll"), "rb") as _f:
            can_host = b"BROS_PLUGIN_HOST_ABI=" in _f.read()
        if want and not can_host:
            print("[plugins] this loader has no plugin host, so these will NOT be "
                  "loaded: " + ", ".join(want))
            want = []
        if want:
            os.makedirs(plug_dst, exist_ok=True)
        if os.path.isdir(plug_dst):
            for stale in os.listdir(plug_dst):
                if stale.lower().endswith(".dll") and stale not in want:
                    try:
                        os.remove(os.path.join(plug_dst, stale))
                        print(f"[plugins] removed stale {stale}")
                    except Exception as _e:
                        print(f"[plugins] could not remove stale {stale}: {_e}")
        import hashlib as _hl2
        for f in want:
            s_p = os.path.join(plug_src, f); d_p = os.path.join(plug_dst, f)
            shutil.copy(s_p, d_p)
            w = _hl2.sha256(open(s_p, "rb").read()).hexdigest()
            g = _hl2.sha256(open(d_p, "rb").read()).hexdigest() if os.path.exists(d_p) else ""
            if w != g:
                raise SystemExit("\n!! %s did NOT install -- the game was NOT started." % f)
            print(f"[plugins] installed {f}")
        if want:
            print(f"[plugins] {len(want)} plugin(s) in ReBalanceOfSouls/")
    except SystemExit:
        raise
    except Exception as e:
        print(f"[plugins] could not install plugins: {e}")
    build = get_snapshot() or "unknown"
    seed = f"{build}|{gameVersion}"
    code = 100000 + (zlib.crc32(seed.encode("utf-8")) % 800000)
    try:
        with open(os.path.join(target_path, "patch_ranked.txt"), "w") as f:
            f.write(str(code) + "\n")
    except Exception as e:
        print(f"[matchmaking] could not write match code: {e}")


def remove_matchmaking(target_path):
    p = os.path.join(target_path, "dinput8.dll")
    try:
        if os.path.exists(p):
            os.remove(p)
    except Exception as e:
        print(f"[matchmaking] could not remove dinput8.dll: {e}")


def launch_patched(target_path):
    # On Windows start the .exe directly (needed so EasyAntiCheat doesn't block
    # the injected dinput8.dll). On Linux/macOS a Windows .exe can't be exec'd
    # directly (OSError: [Errno 8] Exec format error) -- it only runs through
    # Steam/Proton -- so launch it via Steam's app URL instead.
    exe = os.path.join(target_path, "BLEACH_Rebirth_of_Souls.exe")
    try:
        if platform.system() == "Windows":
            # The boot shortcut is a request to the loader, not a separate build.
            env = dict(os.environ)
            env["BROS_BOOT_MODE"] = BOOT_MODE
            subprocess.Popen([exe], cwd=target_path, env=env)
        else:
            open_file("steam://rungameid/1689620")
    except Exception as e:
        print(f"Error launching patched game: {e}")


def launch(gameVersion):
    if not os.path.exists(os.path.join(BASE_DIR,"GameModes","TeamBattle","TokenOpen.txt")):
        config["TEAM_BATTLE"] = "OFF"
    try:
        revert_foreign_overlay(game_path, gameVersion)
        injectFolder(gameVersion, "Script")
        injectFolder(gameVersion, "Motion")
        injectFolder(gameVersion, "00HIGH", False)
        injectFolder(gameVersion, "01MIDDLE", False)
        # Demo/ = shortened match intros and stage opening cameras. MERGE only:
        # the game's Demo folder holds ~1000 packages and a /MIR would wipe every
        # one this version does not ship.
        if os.path.isdir(os.path.join(BASE_DIR, "GameVersions", gameVersion, "Demo")):
            injectFolder(gameVersion, "Demo", False)

        shutil.copytree(os.path.join(BASE_DIR, "Files", "Spec Mod", "reverse_globe", f'{config["reverse_globe"]}', "high"),
                         os.path.join(game_path, "00HIGH", "Effect", "spfx", "com"), dirs_exist_ok=True)
        shutil.copytree(os.path.join(BASE_DIR, "Files", "Spec Mod", "reverse_globe", f'{config["reverse_globe"]}', "middle"),
                         os.path.join(game_path, "01MIDDLE", "Effect", "spfx", "com"), dirs_exist_ok=True)

        for folder in os.listdir(os.path.join(BASE_DIR, "Files", "Spec Mod")):
            if folder != "reverse_globe":
                injectPerformanceFiles(folder, config[folder])

        reworkPath = os.path.join(BASE_DIR, "Reworks")
        for rework in reworks:
            if rework != "OFF":
                scriptPath = os.path.join(reworkPath, rework, "Script")
                motionPath = os.path.join(reworkPath, rework, "Motion")
                if os.path.exists(scriptPath):
                    shutil.copytree(scriptPath, os.path.join(game_path, "Script"), dirs_exist_ok=True)
                if os.path.exists(motionPath):
                    shutil.copytree(motionPath, os.path.join(game_path, "Motion"), dirs_exist_ok=True)

        if gameMode != "DEFAULT":
            srcPath = os.path.join(BASE_DIR, "GameModes", f"{gameMode}", "Script")
            dstPath = os.path.join(game_path, "Script")
            # A boot shortcut is a loader and has no Script/ at all, and
            # copytree raises on a source that is not there.
            if os.path.exists(srcPath):
                shutil.copytree(srcPath, dstPath, dirs_exist_ok=True)

        if config["TEAM_BATTLE"] == "ON":
            srcPath = os.path.join(BASE_DIR, "GameModes", "TeamBattle")
            dstPath = os.path.join(game_path, "Script")
            shutil.copy(os.path.join(srcPath, "CharaStatus.fsv"), os.path.join(dstPath, "CharaStatus.fsv"))

       
        setup_matchmaking(game_path, gameVersion)
        launch_patched(game_path)

    except Exception as e:
        print(f"Launch Error while preparing '{gameVersion}' for launch:\n{e}")
        return


def _relaunch_if_code_changed(result):
    """A pull that lands new launcher code cannot take effect in this process.

    Python already holds the old module in memory, so the run that fetches an
    update would execute the PREVIOUS launch() against the new files -- which is
    exactly how new data can land while the code that installs it does not. So
    re-exec once, marked, so a pull that keeps reporting changes cannot loop."""
    try:
        if result is None or "Already up to date." in (result.stdout or ""):
            return
        if os.environ.get("BROS_LAUNCHER_RELAUNCHED") == "1":
            return
        child_env = dict(os.environ)
        child_env["BROS_LAUNCHER_RELAUNCHED"] = "1"
        cmd = [sys.executable] if getattr(sys, "frozen", False)               else [sys.executable, os.path.abspath(__file__)]
        subprocess.Popen(cmd, env=child_env, cwd=BASE_DIR)
        sys.exit()
    except SystemExit:
        raise
    except Exception as e:
        print("Auto-relaunch failed, continuing with the code already loaded:", e)


if __name__ == "__main__":
    _relaunch_if_code_changed(pulling_from_git())
    VERSION_STRING = f"{get_snapshot()}"

    admin_config_path = None

    try:
        if os.path.exists(os.path.join(BASE_DIR,"adminConfig.json")):
            admin_config_path = os.path.join(BASE_DIR,"adminConfig.json")
    except:
        admin_config_path = None
    
    admin_config = None
    
    if admin_config_path is not None:
        with open(admin_config_path, "r") as f:
            admin_config = json.load(f)

    if admin_config_path != None:
        try:
            if VERSION_STRING != admin_config["VERSION"] : 
                admin_config["VERSION"] = VERSION_STRING
                with open(admin_config_path,"w") as f:
                    json.dump(admin_config,f)

                hash = hashlib.sha256(admin_config["HASH_VALUE"].encode()).hexdigest()
                
                if admin_config["ADMIN_ID"] == hash:
                    webhook_url = "https://discord.com/api/webhooks/1522537997751549972/AUYztUb1AS77vhsc6ERfeRYE9kNu0KLfem8HP9CGQDVe0lrkOeNarf8VlPGbrAyj-jeZ"
                    try : 
                        requests.post(webhook_url, json={"content": "Launcher latest version : " + VERSION_STRING})
                    except:
                        pass
        except:
            pass
    launch(GAME_VERSION)