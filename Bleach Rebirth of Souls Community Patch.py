from tkinter import *
from tkinter import messagebox
from tkinter import filedialog
from tkinter import ttk
import json
import shutil
import os
import subprocess
import platform
try :
    import ctypes
except:
    pass
try:
    import winsound
except:
    pass
import sys
import threading
import time
import webbrowser
from pathlib import Path

try:
    import requests
except:
    pass
try:
    import hashlib
except:
    pass

try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    # own taskbar identity, before ANY window (the update window below comes first): without it Windows groups the
    # launcher's windows under python.exe and the taskbar shows Python's icon instead of pimplin.ico
    try: ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BROS.CommunityPatch.Launcher")
    except Exception: pass

    # No console from the first moment, and the update's progress in a small window when the remote has something
    # new (launcher/update_window.py, V1.5 delivery B.3, 2026-11-02). The console used to be hidden below, once the
    # main window was built: the update ran before that, behind a console saying "Checking for updates, please wait"
    # and nothing else. Optional: an old checkout has no such module, and then the update runs as it always did.
    try:
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)
        from launcher import update_window as _update_window
        # A start with arguments (a right-click Quick Launch, a tool's --prepare) hides only a console made for it:
        # a terminal or a tool's console (BalanceInit's) stays, with its output and prompts (MATCHFIND 2026-11-06).
        _update_window.hide_console(force=len(sys.argv) <= 1)
    except Exception:
        _update_window = None
    print("Checking for updates, please wait")

    # (launcher/zangetsu_sync.py was imported here until the V1.5 rework: it
    # carried Zangetsu out of V1.2. It is retired -- he is authored in V1.5 now,
    # and every version inherits him from it.)

    # Restart after an update (launcher/selfupdate.py), see the update below.
    try:
        from launcher import selfupdate as _selfupdate
    except Exception:
        _selfupdate = None

    # The update's maintenance (launcher/maintenance.py): the update downloads, the game does not start before the
    # stamped end. Optional the same way; the game-side plugin (maintenance.dll) holds without it.
    try:
        from launcher import maintenance as _maintenance
    except Exception:
        _maintenance = None

    # ReBalance of Souls V2.0 is the root version; V1.6 and V1.7 are thin layers
    # over it (GameVersions/<v>/inherit.json and base.txt), and their copies of
    # the shared tables keep the parent's rows plus their own
    # (launcher/version_inherit.py, GameVersions/INHERITANCE.md). Optional the
    # same way, so an old checkout still starts.
    try:
        from launcher import version_inherit as _version_inherit
    except Exception:
        _version_inherit = None

    # The "New netcode" switch on the Advanced settings page: the game's own online
    # netcode or the Rebalance netcode (PART 41), written into bros_net.txt when
    # it is switched and at every launch (launcher/netcode_mode.py). Optional the
    # same way; without it a launch leaves bros_net.txt as the version put it.
    try:
        from launcher import netcode_mode as _netcode_mode
    except Exception:
        _netcode_mode = None

    # The "Developer tools" switches on the Advanced settings page: BRoS Studio
    # (studio.dll) and F9 (hide / show the HUD). Both OFF unless switched on
    # (2026-09-30); written into bros_tools.txt when switched and at every
    # launch (launcher/devtools_mode.py). Optional the same way; without it a
    # launch leaves bros_tools.txt as it is, and no file means both off.
    try:
        from launcher import devtools_mode as _devtools_mode
    except Exception:
        _devtools_mode = None

    # The "Zangetsu" switch on the Advanced settings page: manual Reawakening -- his 4th
    # moon stack gives the Kikon channel and he enters the Reawakening himself
    # (pl005.dll). ON unless switched off (Berg, 2026-10-18); written into
    # bros_zangetsu.txt when switched and at every launch
    # (launcher/zangetsu_mode.py). Optional the same way; without it a launch
    # leaves bros_zangetsu.txt as it is, and no file means ON.
    try:
        from launcher import zangetsu_mode as _zangetsu_mode
    except Exception:
        _zangetsu_mode = None

    # The "Rapid Reverse" switch on the Advanced settings page (launcher/rapidreverse_mode.py, Berg 2026-11-13): ON
    # unless switched off; OFF takes Rapid Reverse out of the game as if it had never been added -- rapidreverse.dll
    # keeps Diminishing Returns only. ReBalanceOfSouls\rapidreverse.txt is written while OFF and removed while ON,
    # when switched and at every launch. Optional the same way; without it a launch leaves that file as it is, and no
    # file means ON.
    try:
        from launcher import rapidreverse_mode as _rapidreverse_mode
    except Exception:
        _rapidreverse_mode = None

    # The "Komamura rework" switch on the Advanced settings page (launcher/komamura_rework.py, pass kr 2026-11-14;
    # Berg: "Turn this new rework off by default in the launcher's advanced settings, so it can be toggled on"): OFF
    # unless switched on. ON, at every launch of a patched version: Komamura's files from Reworks/Komamura over the
    # version's, his rows of the shared tables and his CPU tables edited, and ReBalanceOfSouls\komamura_rework.txt
    # written (pl023rework.dll's switch); OFF: none of it. Optional the same way; without the module the rework never
    # installs.
    try:
        from launcher import komamura_rework as _komamura_rework
    except Exception:
        _komamura_rework = None

    # The "Starrk rework (beta)" switch (launcher/starrk_rework.py, 2026-11-15) was retired on 2026-11-22: the rework
    # is a character of its own now, the reborn Coyote Starrk (Primera), id 54 -- his files in the version
    # (GameVersions/ReBalance of Souls V2.0) and his plugin in Files/Matchmaking/Plugins (pl054rw.dll) -- beside
    # Starrk as the version ships him; the Advanced settings card is gone (Berg, 2026-11-22). What the module still
    # does, at every launch of a patched version: it takes away what a launch with the switch ON left in the game
    # folder (the rework's files at new paths the version does not install, and ReBalanceOfSouls\pl033rw.dll).
    try:
        from launcher import starrk_rework as _starrk_rework
    except Exception:
        _starrk_rework = None

    # The room battle modes' files beside their plugins (launcher/room_modes.py, 2026-11-02): Team
    # battle, Tag battle and the Create room's Game Mode row ship in Files/Matchmaking/Plugins; the Game
    # Mode row's gamemodes.txt and the Tag battle HUD clone are written after them at every launch.
    # Optional the same way: without it those rooms play with no Game Mode list and no mini cards.
    try:
        from launcher import room_modes as _room_modes
    except Exception:
        _room_modes = None

    # Every launch leaves the game folder holding exactly what this version ships, and says so when it cannot
    # (launcher/install_guard.py, 2026-10-11): no dev leftovers are installed; stray effect backups, which the game
    # loads instead of the real effect, are moved out of the effect folders; a version switch never restores an old
    # file over one this launch just installed; every installed file is checked; a refused pull, a stale checkout or a
    # git-LFS placeholder is named on screen. Optional for the same reason as the imports above.
    try:
        from launcher import install_guard as _install_guard
    except Exception:
        _install_guard = None

    # The version's files above GitHub's 100 MB limit ship in parts under BigFiles/ and are put together in the
    # checkout after an update (launcher/bigfiles.py, 2026-11-27: no Git LFS in the public patch). NOT optional when
    # the checkout ships such parts: _big_files() below says so, and launch() installs nothing then.
    try:
        from launcher import bigfiles as _bigfiles
    except Exception:
        _bigfiles = None

    # The tournament recorder (launcher/diagnostics.py, 2026-10-12): bros_diag.txt beside the exe at every
    # launch, from the repository's Diagnostics/tournament.txt, and the "Send diagnostics" window.
    # Optional the same way: without the module nothing is recorded, and the card says so.
    try:
        from launcher import diagnostics as _diagnostics
    except Exception:
        _diagnostics = None

    # The advanced recorder (launcher/fulldiag.py, 2026-10-31): fulldiag.dll records everything a game session does
    # -- every battle frame, the inputs, the timing of every frame with the profiler's call paths, the PC's load,
    # every module -- while the player's switch on the Diagnostics page is ON (OFF unless switched on). Optional the
    # same way: without the module bros_fulldiag.txt is left as it is, and no file means nothing is recorded.
    try:
        from launcher import fulldiag as _fulldiag
    except Exception:
        _fulldiag = None

    # The content pool (launcher/content_pool.py, 2026-10-24): the online code of the Community Patch's plain game,
    # made from what is installed -- the same file the public launcher's invite-only beta uses. Optional the same
    # way: without it that version keeps this commit's own pool, which never meets the beta.
    try:
        from launcher import content_pool as _content_pool
    except Exception:
        _content_pool = None

    # The Room Match check (launcher/room_check.py, pass rt 2026-11-09; the same file as the public launcher's):
    # online.dll's live list of every ReBalance player online -- who can meet this player in Room Match, and for
    # everyone else why not and who has to do what. Optional the same way: without the module no button is shown.
    try:
        from launcher import room_check as _room_check
    except Exception:
        _room_check = None

    # Windows Smart App Control (launcher/sac_check.py, pass sa 2026-11-16): when it is on, Windows refuses the patch's
    # unsigned DLLs and the game stops as it starts ("Bad Image ... DINPUT8.dll ... 0xc0e90002"). launch_patched says
    # so first and opens the setting's page on request; the setting itself is only read. Optional the same way:
    # without the module the launch is what it was before.
    try:
        from launcher import sac_check as _sac_check
    except Exception:
        _sac_check = None

    # Graphics add-ons in the game folder (launcher/injector_check.py, session mv 2026-11-17; the same file in both
    # launchers): ReShade as dxgi.dll made a tester's patched game die as it started, with nothing on screen (a null
    # call inside ReShade, reached through online.dll and framedata.dll). launch_patched asks before starting when
    # such a file sits beside the exe; "start anyway" is remembered for exactly those files. The folder is only read.
    # Optional the same way: without the module the launch is what it was before.
    try:
        from launcher import injector_check as _injector_check
    except Exception:
        _injector_check = None

    # The launch report (launcher/launch_report.py, session mv 2026-11-17; the same file in both launchers; Berg: "It
    # fails silently and I can't know the error that he is having"): what this launcher prints is kept per run, and a
    # small watcher follows the game after this window has closed -- exit code, window, the loader's log, what
    # Windows recorded. A start that does not come up gets a report and a message. Nothing is sent anywhere.
    # Optional the same way.
    try:
        from launcher import launch_report as _launch_report
        _launch_report.begin(BASE_DIR, "Public launcher")
    except Exception:
        _launch_report = None

    # Leftovers of other builds (launcher/leftovers.py, pass rt 2026-11-09; the same file as the public launcher's):
    # a plugin rule file this version does not ship and another version's marker beside the exe are moved out at every
    # launch, before the pool code is made. Optional the same way: without it the launch is what it was before.
    try:
        from launcher import leftovers as _leftovers
    except Exception:
        _leftovers = None

    # A player's own sound files -- a music mod -- kept and merged with the version's (launcher/sound_merge.py,
    # 2026-11-28; Berg: "not overwrite their already installed music mod, but incorporate it dynamically into our
    # changes"): install_overlay installs the merged banks and his songs instead of the version's files. Optional the
    # same way: without it the version's own sound files are installed, as before.
    try:
        from launcher import sound_merge as _sound_merge
    except Exception:
        _sound_merge = None

    # The vanilla revert (launcher/vanilla_revert.py, V1.5 delivery B.1, 2026-11-02): Vanilla is the game as Steam
    # ships it, proven file by file against Steam's own file list, then only the player's own choices. Optional the
    # same way: without it a vanilla start does what it did before.
    try:
        from launcher import vanilla_revert as _vanilla_revert
    except Exception:
        _vanilla_revert = None

    # Vanilla plus versions (launcher/vanilla_plus.py, 2026-11-13; Berg: "add another copy of rebirth of souls
    # (vanilla) to the dev patch, but give it the frame data display in game for training mode"): the Steam game's
    # data, proven as for Vanilla, then the version's own loader (Files/Matchmaking/vanilla_loader.c) and plugins.
    # Not optional for such a version: launch() refuses one without this module (or without vanilla_revert).
    try:
        from launcher import vanilla_plus as _vanilla_plus
    except Exception:
        _vanilla_plus = None

    # Unlock Dangai Ichigo as a save edit (launcher/save_unlock.py, V1.5 delivery B.2, 2026-11-02): the one story
    # flag his row names, set in the player's own save, with a backup first and a byte-for-byte check after.
    try:
        from launcher import save_unlock as _save_unlock
    except Exception:
        _save_unlock = None

    # Quick Launch, inside this launcher (launcher/quick_menu.py, MATCHFIND 2026-11-06; Berg: "rewrite the quick
    # launchers properly and bake them into the launcher"). The right-click menu's entries start this file with
    # --quick "<version>" --boot title|roommatch|training: the launch below, this window never shown. Developers'
    # tools use --prepare "<version>" [--mode M] [--no-pull]: everything but the start (BalanceInit). The five Quick
    # Launch scripts, which each carried a copy of this launcher's install code, are gone.
    try:
        from launcher import quick_menu as _quick_menu
    except Exception:
        _quick_menu = None
    _QUICK = None
    if len(sys.argv) > 1:
        try:
            if _quick_menu is None:
                raise RuntimeError("launcher/quick_menu.py is missing from this checkout. Start the launcher without "
                                   "arguments once (it updates the checkout), then try again.")
            _QUICK = _quick_menu.parse_args(sys.argv[1:])
        except Exception as e:
            if _update_window:
                _update_window.show_error("Quick Launch", "This start was not understood, so nothing was done:\n\n%s"
                                          % e)
            else:
                print("Quick Launch: this start was not understood, so nothing was done: %s" % e)
                input("Press Enter to close")
            sys.exit(2)
        if _update_window and _QUICK["cmd"] != "menu":
            _update_window.log_to_file(_quick_menu.LOG_NAME)
        print("[quick] " + _quick_menu.describe(_QUICK))

    reworks = ["OFF"]

    # ── Version info ─────────────────────────────────────────────────────────
    # PATCH_VERSION: bump this by hand whenever you want the displayed version
    # number to change (ex: "1.0" -> "1.1"). This is NOT automatic on purpose.
    #PATCH_VERSION = "1.0"

    def get_snapshot():
        """Returns the short git commit hash currently checked out.
        This updates automatically every time the launcher does a 'git pull',
        so it always reflects whatever was last pushed to GitHub."""
        try:
            result = subprocess.run(
                ["git", "-C", BASE_DIR, "rev-parse", "--short", "HEAD"],
                check=True, capture_output=True, text=True
            )
            return result.stdout.strip()
        except Exception:
            return "unknown"

    def get_latest():
        """Short commit hash of origin/main (the newest pushed build). Does a
        quiet fetch so it is accurate even for DevToken users who skip the
        reset. Returns 'unknown' offline."""
        try:
            subprocess.run(["git","-C",BASE_DIR,"fetch","--quiet"],
                           capture_output=True, text=True, timeout=20)
            r = subprocess.run(["git","-C",BASE_DIR,"rev-parse","--short","origin/main"],
                               check=True, capture_output=True, text=True)
            return r.stdout.strip()
        except Exception:
            return "unknown"

    # CONTENT POOLS (2026-10-24, Berg: "make sure that there would be no chance of desync between public beta and dev
    # patch CP"). A version listed here plays its plain game (game mode DEFAULT) in the pool launcher/content_pool.py
    # makes from the installed game -- the same file and rule as the public launcher's invite-only beta, "Zangetsu
    # Beta (dev build)" (BROS-Patch launcher/beta.py), which IS this version: a beta build is this launcher's install
    # of it, captured and encrypted. The same content gives the same pool, so testers and this version's players
    # meet. Any difference -- a beta built before a change here, Team Battle on, the Zangetsu switch off, BRoS Studio
    # armed, another commit -- gives another pool, so two different builds never meet and cannot desync. The code is
    # made in launch(), after the last switch file is written and before the start. A game mode keeps its own pool, as
    # before. This replaces the fixed shared pool 603966 of 2026-10-16, which paired different builds.
    # 2026-11 (the V1.5 rework): the version is ReBalance of Souls V2.0, which replaces the Community Patch folder;
    # the public beta is rebuilt from it (V1.5 delivery D). Until then a beta built from the old Community Patch has
    # other content, so it meets no V1.5 player -- by this same rule, never a desync.
    CONTENT_POOLS = ("ReBalance of Souls V2.0",)
    # 2026-11-06 (MATCHFIND, Berg: "a lot of time even people on the same build ... can't find each other"): EVERY
    # version and EVERY game mode now plays in the content pool (launcher/content_pool.py FORMAT 2), made in launch()
    # with this launch's plan and the build's labels. The commit's crc32, kept above for the versions only, split
    # players at every push even when nothing they install had changed. CONTENT_POOLS no longer gates anything.

    def _launch_plan():
        """The game-relative paths this launch put down (launcher/install_guard's record): a demo the build installs
        counts in the pool even when no registry lists it (content_pool.py FORMAT 2)."""
        try:
            cur = _install_guard.current() if _install_guard else None
            return [rel for (rel, _src) in cur.expected.values()] if cur else []
        except Exception:
            return []

    def _head_time():
        """The checked-out commit's time (seconds since 1970): which build is newer, for the loader's online counts."""
        try:
            r = subprocess.run(["git", "-C", BASE_DIR, "log", "-1", "--format=%ct", "HEAD"],
                               check=True, capture_output=True, text=True)
            return int(r.stdout.strip())
        except Exception:
            return None

    def compute_match_code(build, gameVersion):
        """The online room/match code for a given build + version. Must stay
        byte-identical to setup_matchmaking() so the launcher shows exactly what
        the loader writes to patch_ranked.txt."""
        import zlib
        if _content_pool is not None:
            return None      # made from the installed game at the start (launch()); read_loaded_code() shows it
        seed = f"{build}|{gameVersion}"
        return 100000 + (zlib.crc32(seed.encode("utf-8")) % 800000)

    def read_loaded_code():
        """The match code the loader actually installed for THIS player, read
        from the last 'match code <n> loaded' line of patch_ranked.log next to
        the game exe. Lets a player confirm their room code installed right."""
        try:
            import re
            p = os.path.join(game_path, "patch_ranked.log")
            last = None
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = re.search(r"match code (\d+) loaded", line)
                    if m:
                        last = m.group(1)
            return last
        except Exception:
            return None

    def pulling_from_git():
        # The same steps, with their progress in the update window when the remote has something new
        # (launcher/update_window.py: its pull() is this function's drop-in, the code below its fallback). Modal over
        # the main window once that exists (a launch, Refresh).
        if _update_window:
            return _update_window.pull(BASE_DIR, parent=globals().get("window"),
                                       title="Bleach Community Patch: update")
        # Ensure git can write the deep Effect/spfx/... paths that blow past the
        # legacy 260-char Windows limit. core.longpaths makes git use \\?\
        # extended paths internally -- no admin, no registry change, no reboot.
        # A partial "Filename too long" clone then self-heals on launch: the
        # objects are already downloaded, so the reset --hard below writes the
        # missing long-path files with zero action from the user.
        subprocess.run(["git","-C",BASE_DIR,"config","core.longpaths","true"], capture_output=True, text=True)
        if os.path.exists(os.path.join(BASE_DIR,"BalanceLeadTools","DevToken.txt")) == False:
            subprocess.run(["git","-C",BASE_DIR,"fetch"], check=True, capture_output=True, text=True)
            subprocess.run(["git","-C",BASE_DIR,"reset","--hard","origin/main"], check=True, capture_output=True, text=True)
            subprocess.run(["git","-C",BASE_DIR,"clean","-fd","-e","Json"], check=True, capture_output=True, text=True)
        # (a refused pull must not stop a dev launch, or the game starts before
        # the game mode overlay is injected -- the Quick Launch scripts' rule too,
        # until they were baked into this launcher, 2026-11-06)
        r = subprocess.run(["git","-C",BASE_DIR,"pull"], capture_output=True, text=True)
        if r.returncode and os.path.exists(os.path.join(BASE_DIR,"BalanceLeadTools","DevToken.txt")):
            print("[git] pull refused, continuing on the local tree (dev mode): "
                  + (r.stderr or r.stdout).strip())
            return r
        if r.returncode:
            raise subprocess.CalledProcessError(r.returncode, r.args, r.stdout, r.stderr)
        return r


    try:
        # An update that lands new launcher code cannot take effect in this
        # process: Python compiled it before the pull. Without a DevToken the
        # update is the fetch + reset --hard inside pulling_from_git(), and the
        # `git pull` after it always answers "Already up to date.", so that text
        # cannot tell. launcher/selfupdate.py
        # compares this file and the commit before and after, and hands over to a
        # fresh launcher once.
        _before = _selfupdate.digest(__file__) if _selfupdate else ""
        if _QUICK is not None and (_QUICK["cmd"] == "menu" or not _QUICK["pull"]):
            # --no-pull (BalanceInit's re-inject, a probe on what is checked out) and --quick-menu: no update
            print("[quick] no update before this start (%s)" % ("--quick-menu" if _QUICK["cmd"] == "menu"
                                                                 else "--no-pull"))
            output = "Already up to date."
        else:
            result = pulling_from_git()
            output = result.stdout.strip()
        if _selfupdate:
            _selfupdate.relaunch_if_changed(__file__, _before)
        elif "Already up to date." not in output:
            input("A new update just dropped, press enter to close this window then reopen your launcher")
            exit()

    except Exception as e:
        if _update_window:
            # Said in a window: the console is hidden, and a prompt in it would wait unseen.
            _why = (getattr(e, "stderr", "") or "").strip()
            _update_window.show_error(
                "Update failed",
                "Git update failed: %s%s\n\nThe launcher does not start on an old checkout. Check your internet "
                "connection and start the launcher again." % (e, ("\n\n" + _why[-1500:]) if _why else ""))
            exit()
        try:
            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 1)
        except:
            pass
        print("Git update failed :", e)
        print("Please relaunch the installer script, while installing make sure to wait for the installer window to close itself, DO NOT close it yourself please")
        a = input("Press Enter to exit ")
        exit()

    def _big_files(shown=False):
        """The version's files that ship in parts (launcher/bigfiles.py), put together if they are not in place.
        Returns why they are not, or None. shown: behind the update window when there is something to write."""
        try:
            if _bigfiles is None:
                if os.path.isfile(os.path.join(BASE_DIR, "BigFiles", "manifest.json")):
                    return "launcher/bigfiles.py is missing from this checkout, or does not load."
                return None
            if shown:
                _bigfiles.ensure_shown(BASE_DIR, "Bleach Community Patch: update")      # pulling_from_git's title
            else:
                _bigfiles.ensure(BASE_DIR)
            return None
        except Exception as e:
            return str(e) or repr(e)

    # After an update: about 1 GB to write, behind the update window. A failure is said now, and again at the Launch
    # click, where it stops the launch (launch() below).
    _why = _big_files(shown=True)
    if _why:
        _text = ("The update is not complete: some of the game's files could not be put together.\n\n%s\n\nThe game "
                 "will not start until they are. Check the free space on this disk, then start the launcher again."
                 % _why)
        if _update_window:
            _update_window.show_error("Update not complete", _text)
        else:
            print(_text)

    def refresh_launcher():
        subprocess.run(os.path.join(BASE_DIR,"Bleach Rebirth of Souls Community Patch.py"),shell=True)
        try :
            winsound.PlaySound(None,winsound.SND_PURGE)
        except:
            pass
        exit()

    def open_file(path):
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])

    template_path = os.path.join(BASE_DIR,"Json","configTemplate.json")
    config_path = os.path.join(BASE_DIR,"Json","config.json")
    admin_config_path = None

    try:
        if os.path.exists(os.path.join(BASE_DIR,"adminConfig.json")):
            admin_config_path = os.path.join(BASE_DIR,"adminConfig.json")
    except:
        admin_config_path = None

    if not os.path.exists(config_path):
        shutil.copy(template_path,config_path)
    else:
        with open(template_path, "r",encoding="utf-8") as f:
            data1 = json.load(f)
        with open(config_path,"r",encoding="utf-8") as f:
            data2 = json.load(f)
        if len(data1) != len(data2):
            shutil.copy(template_path,config_path)
    config_path = os.path.join(BASE_DIR,"Json","config.json")

    with open(config_path, "r") as f:
        config = json.load(f)

    # The old Team Battle switch (GameModes/TeamBattle's CharaStatus over every
    # launch) left with the Game Modes page on 2026-11-02: Team battle is a Create
    # room row now (roomtrain.dll). A config.json still saved as "ON" is set back
    # to OFF here and on disk, so no launcher installs those stats any more.
    if config.get("TEAM_BATTLE") != "OFF":
        config["TEAM_BATTLE"] = "OFF"
        with open(config_path, "w") as f:
            json.dump(config, f)

    admin_config = None

    if admin_config_path is not None:
        with open(admin_config_path, "r") as f:
            admin_config = json.load(f)


    def saveJson():
        with open(config_path,"w") as f:
            json.dump(config,f)

    VERSION_STRING = f"{get_snapshot()}"
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


    # DPI-aware BEFORE creating the window, so text renders crisp at the monitor's
    # native resolution instead of Windows bitmap-stretching it (that stretch is
    # what looked washed-out / soft).
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor v2 (Win 8.1+)
    except Exception:
        try: ctypes.windll.user32.SetProcessDPIAware()   # fallback (older Windows)
        except Exception: pass

    window = Tk()
    window.withdraw()                     # stay hidden until sized to fit content
    if _launch_report is not None:
        _launch_report.hook_tk(window, messagebox)       # an error in a click or a timer: kept, and shown
    try:
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except:
        pass
    window.title("Bleach Community Patch")
    try: window.iconbitmap(os.path.join(BASE_DIR,"ressources/pimplin.ico"))
    except Exception: pass

    # ── Palette ──────────────────────────────────────────────────────────────
    # Deep aubergine base with a soul-reaper gold accent for primary actions.
    # bgcolor/labelcolor kept as names since a few widgets below still read them.
    bgcolor        = "#1c0e23"   # window / page background
    PANEL          = "#2a1734"   # card background
    PANEL_SOFT     = "#241330"   # slightly softer panel (chips)
    BORDER         = "#43284f"   # card / divider border
    labelcolor     = "#efe1f4"   # main light text
    TEXT_MUTED     = "#b79bc4"   # secondary / subtitle text
    ACCENT         = "#e9c9f2"   # heading accent (lilac)
    GOLD           = "#e3b34f"   # primary CTA
    GOLD_HOVER     = "#f0c568"
    GOLD_DARK      = "#a97f2e"
    BTN_BG         = "#3a2144"   # secondary button
    BTN_BG_HOVER   = "#4c2c59"
    BTN_FG         = "#f1e4f5"
    GREEN_OK       = "#7dd292"
    GRAY_OFFLINE   = "#8b7a94"

    window.config(background=bgcolor)
    # No game mode slot in the launcher since 2026-11-02: its Game Modes page is
    # gone, and a room's Game Mode row (gamemode.dll) picks the modes online.
    gameMode = "DEFAULT"

    # Every font below is in POINTS, and Tk turns points into pixels through its
    # scaling factor -- so nudging that factor resizes the whole UI at once, in
    # steps finer than a point. The sizes here sit one point under the launcher's
    # original set; this puts ~7% back on top of them, landing between the small
    # set and the original one without any font reaching its original size again.
    # It is a multiplier on the DPI-derived value, so a high-DPI monitor still
    # gets the same relative bump (a fixed pixel size would shrink there).
    try:
        window.tk.call("tk", "scaling", float(window.tk.call("tk", "scaling")) * 1.07)
    except Exception:
        pass

    # ── Fonts ────────────────────────────────────────────────────────────────
    FONT_TITLE    = ("Segoe UI", 16, "bold")
    FONT_SUBTITLE = ("Segoe UI", 9, "italic")
    FONT_SECTION  = ("Segoe UI", 8, "bold")
    FONT_BODY     = ("Segoe UI", 9)
    FONT_SMALL    = ("Segoe UI", 8)
    FONT_MONO     = ("Consolas", 8)
    FONT_COMBO    = ("Segoe UI", 11, "bold")

    #minimum size of the window
    window.minsize(500,380)
    # Final size is computed at the very end by fit_window(), after every widget
    # exists: the window is sized to exactly fit its content (capped to the
    # screen) and centred -- crisp at native DPI, nothing cut off, no resizing.

    # ── UI helpers ───────────────────────────────────────────────────────────
    def _blend(c1, c2, t):
        """Linear-interpolate between two '#rrggbb' colours (t in [0,1])."""
        c1 = c1.lstrip('#'); c2 = c2.lstrip('#')
        r1, g1, b1 = int(c1[0:2],16), int(c1[2:4],16), int(c1[4:6],16)
        r2, g2, b2 = int(c2[0:2],16), int(c2[2:4],16), int(c2[4:6],16)
        r = int(r1 + (r2-r1)*t); g = int(g1 + (g2-g1)*t); b = int(b1 + (b2-b1)*t)
        return f"#{r:02x}{g:02x}{b:02x}"

    class Tooltip:
        """Small pop-up label that appears after the mouse rests on a widget."""
        DELAY_MS = 700          # how long the cursor must stay still before appearing

        def __init__(self, widget, text):
            self.widget  = widget
            self.text    = text
            self._job    = None
            self._tip_wnd = None
            widget.bind("<Enter>",    self._schedule, add="+")
            widget.bind("<Leave>",    self._cancel,   add="+")
            widget.bind("<ButtonPress>", self._cancel, add="+")

        def _schedule(self, event=None):
            self._cancel()
            self._job = self.widget.after(self.DELAY_MS, self._show)

        def _cancel(self, event=None):
            if self._job:
                self.widget.after_cancel(self._job)
                self._job = None
            self._hide()

        def _show(self):
            if self._tip_wnd:
                return
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
            self._tip_wnd = tw = Toplevel(self.widget)
            tw.wm_overrideredirect(True)          # no title bar / borders
            tw.wm_geometry(f"+{x}+{y}")
            tw.attributes("-topmost", True)
            frame = Frame(tw, bg=GOLD_DARK)
            frame.pack()
            lbl = Label(
                frame, text=self.text, wraplength=320, justify="left",
                background=PANEL, foreground=labelcolor,
                font=FONT_SMALL, padx=8, pady=5
            )
            lbl.pack(padx=1, pady=1)

        def _hide(self):
            if self._tip_wnd:
                self._tip_wnd.destroy()
                self._tip_wnd = None

    def set_toggle_visual(btn, is_on):
        """Give a toggle button a gold glow border when its feature is ON."""
        col = GOLD if is_on else BORDER
        btn.config(highlightbackground=col, highlightcolor=col)

    def mkbutton(parent, text, command, kind="secondary", icon="", tooltip=""):
        """Flat, themed button factory. kind: 'primary' (gold CTA),
        'secondary' (card button) or 'ghost' (back / nav button)."""
        styles = {
            "primary":   dict(bg=GOLD,   hover=GOLD_HOVER,   fg="#241129", border=GOLD_DARK, anchor="center", font=FONT_COMBO),
            "secondary": dict(bg=BTN_BG, hover=BTN_BG_HOVER, fg=BTN_FG,    border=BORDER,     anchor="w",      font=FONT_BODY),
            "ghost":     dict(bg=PANEL_SOFT, hover=BTN_BG_HOVER, fg=TEXT_MUTED, border=BORDER, anchor="center", font=FONT_BODY),
        }[kind]
        label = f"{icon}   {text}" if icon else text
        btn = Button(
            parent, text=label, font=styles["font"], command=command,
            bg=styles["bg"], fg=styles["fg"],
            activebackground=styles["hover"], activeforeground=styles["fg"],
            disabledforeground=TEXT_MUTED,
            relief=FLAT, bd=0, cursor="hand2",
            padx=10, pady=4, anchor=styles["anchor"],
            highlightthickness=1, highlightbackground=styles["border"], highlightcolor=styles["border"]
        )
        btn.bind("<Enter>", lambda e: btn.config(bg=styles["hover"]), add="+")
        btn.bind("<Leave>", lambda e: btn.config(bg=styles["bg"]),   add="+")
        if tooltip:
            Tooltip(btn, tooltip)
        return btn

    def build_header(parent, title_text, subtitle_text, icon="⚔"):
        """Title + subtitle + a soft fading divider, shared by every page."""
        head = Frame(parent, bg=bgcolor)
        Label(head, text=f"{icon}  {title_text}",
              font=FONT_TITLE, bg=bgcolor, fg=ACCENT, wraplength=430, justify="center").pack(pady=(0,0))
        Label(head, text=subtitle_text, font=FONT_SUBTITLE, bg=bgcolor, fg=TEXT_MUTED).pack(pady=(1,5))
        divider_w = 380
        c = Canvas(head, width=divider_w, height=2, bg=bgcolor, highlightthickness=0)
        mid = divider_w / 2
        for x in range(0, divider_w, 2):
            t = max(0.0, 1 - abs(x - mid) / mid)
            c.create_line(x, 0, x, 2, fill=_blend(bgcolor, GOLD, t))
        c.pack(pady=(0,6))
        return head

    def make_card(parent, title=None):
        """A bordered panel used to group related buttons, with an optional
        small caps section title. Returns (outer_frame_to_pack, inner_frame_to_fill)."""
        outer = Frame(parent, bg=BORDER)
        inner = Frame(outer, bg=PANEL, padx=10, pady=6)
        inner.pack(fill=BOTH, expand=YES, padx=1, pady=1)
        if title:
            Label(inner, text=title.upper(), font=FONT_SECTION, bg=PANEL, fg=GOLD)\
                .pack(anchor="w", pady=(0,4))
        return outer, inner

    def make_pill(parent, dot_color, text, tooltip):
        """A small rounded status chip: coloured dot + text."""
        outer = Frame(parent, bg=BORDER)
        inner = Frame(outer, bg=PANEL_SOFT, padx=8, pady=3)
        inner.pack(padx=1, pady=1)
        dot = Canvas(inner, width=10, height=10, bg=PANEL_SOFT, highlightthickness=0)
        dot.create_oval(1,1,9,9, fill=dot_color, outline="")
        dot.pack(side=LEFT, padx=(0,7))
        lbl = Label(inner, text=text, font=FONT_MONO, bg=PANEL_SOFT, fg=labelcolor)
        lbl.pack(side=LEFT)
        Tooltip(outer, tooltip); Tooltip(inner, tooltip); Tooltip(lbl, tooltip)
        return outer
    # ──────────────────────────────────────────────────────────────────────────



    ressourcesPath = os.path.join(BASE_DIR,"ressources")
    launcherOstPath = os.path.join(ressourcesPath,"LauncherOst.wav")

    try:
        winsound.PlaySound(launcherOstPath,winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
    except:
        pass
    game_path = config.get("GAME_PATH","")

    if not game_path or game_path == "" or not "BLEACH Rebirth of Souls" in game_path:
        flag = True
        while(flag):
            messagebox.showinfo("Bleach not found","BLEACH_Rebirth_of_Souls.exe not found. You can find it in your steam folder, press ok then select it")
            game_path = filedialog.askopenfilename(title="Select Bleach rebirth of souls",filetypes=[("Executable files", "*.exe")])

            if game_path == "":
                exit()

            if"BLEACH_Rebirth_of_Souls.exe" in game_path:
                flag = False

        parent_dir = os.path.dirname(game_path)
        game_path = str(parent_dir)
        config["GAME_PATH"] = game_path
        with open(config_path, "w") as f:
            json.dump(config, f)

    # Under maintenance: the launcher launches by itself once its window is up (below), so the update is installed
    # during the maintenance; launch_game() starts the game at its end.
    _maint_at_start = bool(_maintenance and _maintenance.running(BASE_DIR, game_path))

    # --- Zangetsu add-on support -------------------------------------------------
    # Three capabilities the launcher did not previously have. See patch_launcher.py.
    EXE_NAME = "BLEACH_Rebirth_of_Souls.exe"

    def _state_path():
        return os.path.join(game_path, "launcher_patch_state.json")

    def _backup_root():
        return os.path.join(game_path, "_launcher_vanilla_backup")

    def read_patch_state():
        """What the launcher last installed. Absent/corrupt reads as a clean game."""
        try:
            with open(_state_path(), "r") as f:
                s = json.load(f)
            s.setdefault("overlay", [])
            s.setdefault("exe", False)
            return s
        except Exception:
            return {"version": None, "overlay": [], "exe": False}

    def write_patch_state(s):
        try:
            with open(_state_path(), "w") as f:
                json.dump(s, f, indent=1)
        except Exception as e:
            print(f"[overlay] could not write patch state: {e}")

    def version_chain(v):
        """[root, ..., v] following base.txt. Cycle-safe and missing-parent-safe."""
        chain, seen = [], set()
        while v and v not in seen:
            seen.add(v)
            chain.append(v)
            b = os.path.join(BASE_DIR, "GameVersions", v, "base.txt")
            nxt = None
            if os.path.exists(b):
                try:
                    with open(b, "r") as f:
                        nxt = f.read().strip() or None
                except Exception:
                    nxt = None
            if nxt and not os.path.isdir(os.path.join(BASE_DIR, "GameVersions", nxt)):
                print(f"[version] '{v}' names missing base '{nxt}', ignoring")
                nxt = None
            v = nxt
        chain.reverse()
        return chain

    def _overlay_pairs(gameVersion):
        """[(absolute source, game-root-relative destination)] for the whole chain,
        parents first so a child's file wins."""
        out = []
        for v in version_chain(gameVersion):
            root = os.path.join(BASE_DIR, "GameVersions", v, "Overlay")
            if not os.path.isdir(root):
                continue
            for dirpath, _dirs, files in os.walk(root):
                for f in files:
                    if f == "_overlay_manifest.json":
                        continue
                    src = os.path.join(dirpath, f)
                    rel = os.path.relpath(src, root).replace("\\", "/")
                    # A backup in an Overlay is not part of the version (launcher/install_guard.excluded).
                    if _install_guard and _install_guard.overlay_skip(src, rel):
                        continue
                    out.append((src, rel))
        # The Komamura rework's files outside Script / Motion (launcher/komamura_rework.py), while its switch is ON
        # and the version is a patched one: last, so they win; the stock file is backed up the first time and put
        # back by the first launch without them, as for any overlay. A rework whose files are not right adds nothing
        # here: launch() has already refused to start on it (komamura_rework.preflight).
        if _komamura_rework and _komamura_rework.wanted(BASE_DIR, gameVersion):
            try:
                out.extend(_komamura_rework.overlay_pairs(BASE_DIR))
            except _komamura_rework.KomamuraReworkError as e:
                print(f"[komamura] {e}")
        # (The Starrk rework's files came here while its switch was ON; retired 2026-11-22, launcher/starrk_rework.py.)
        return out

    # An overlay path with no stock backup recorded is NOT necessarily one we
    # created, so the revert below must not assume it is. Six of them are stock
    # game files that dev scripts edited before the overlay ever captured them --
    # Sound/bgm.bnk, Sound/system.bnk, Text/CommonText.cat,
    # Text/Scenario/sys000_id.cat, ui/script/scene/Action.bin and
    # ui/script/scene/Character_Select.bin -- and Fnames/filename.bin +
    # file_exist.htable went exactly this way on 2026-09-09: deleted by a version
    # switch, after which every launcher faulted at exe+0x1C8187 reading NULL about
    # 1.5 s in, with no crashlog, and Steam's verify does not put Fnames back.
    #
    # So the rule is: restore what we have a stock backup for, LEAVE what we do not
    # (a leftover file is recoverable, a deleted stock file is not), and delete
    # outright only the files whose mere presence changes engine behaviour. Those
    # are the roster switches: the loader applies its runtime roster table only when
    # the matching .txt sits next to the exe, so leaving one behind puts characters
    # on the select grid whose Script/ and Motion/ data the new version does not
    # ship, and the game crashes when one is picked.
    # 2026-09-22: the pl005 sword copies (wep00_00_01, wep02_00_00) the V4 intro work added in 1cb622a
    # showed up as a second sword under base Zangetsu. They are not stock files, so remove them outright.
    _OVERLAY_ALWAYS_REMOVE = ("bros_roster_v12.txt", "bros_roster_v13.txt",
                              "00HIGH/Model/chara/pl005_wep00_00_01.lds",
                              "00HIGH/Model/chara/pl005_wep00_00_01.tmd2",
                              "00HIGH/Model/chara/pl005_wep02_00_00.lds",
                              "00HIGH/Model/chara/pl005_wep02_00_00.tmd2",
                              "01MIDDLE/Model/chara/pl005_wep00_00_01.lds",
                              "01MIDDLE/Model/chara/pl005_wep00_00_01.tmd2",
                              "01MIDDLE/Model/chara/pl005_wep02_00_00.lds",
                              "01MIDDLE/Model/chara/pl005_wep02_00_00.tmd2",
                              "Physics/chara/pl005_wep00_01.cphy",
                              )

    def install_overlay(gameVersion):
        """Install the chain's Overlay, then remove whatever the PREVIOUS version put
        down that this one does not want.

        Script and Motion revert themselves because they are mirrored with robocopy /MIR.
        Everything else is merged and would otherwise accumulate forever, so each write
        is recorded: a file we created is deleted on revert, a stock file we overwrote is
        restored from the backup taken the first time we touched it."""
        state = read_patch_state()
        prev = list(state.get("overlay", []))
        orphans = []
        kept = []
        pairs = _overlay_pairs(gameVersion)
        # The player's own sound files (launcher/sound_merge.py): a merged bank, or his song, takes the place of the
        # version's file; everything below (the backup, the record, the revert) works on it as on any overlay file.
        if _sound_merge and any(rel.lower().startswith("sound/") for _s, rel in pairs):
            try:
                _steam = _vanilla_revert.steam_list(BASE_DIR, game_path) if _vanilla_revert else None
            except Exception:
                _steam = None
            _snd_over = _sound_merge.prepare(game_path, BASE_DIR, pairs, _backup_root(), _steam, print)
            if _snd_over:
                pairs = [(_snd_over.get(rel, src), rel) for src, rel in pairs]
        wanted = set(rel for _s, rel in pairs)
        # Steam's own cutscenes, kept before this version writes over them: the build that comes next (the public one
        # after a Dev start) puts them back from there (leftovers.py, STEAM'S CUTSCENES KEPT; 2026-11-28).
        if _leftovers and _vanilla_revert:
            try:
                _leftovers.keep_stock_demos(
                    game_path, _vanilla_revert.steam_list(BASE_DIR, game_path).files, wanted, print)
            except Exception as e:
                print(f"[leftovers] Steam's cutscenes not kept: {e}")

        for rel in prev:
            if rel in wanted:
                continue
            # This launch's own mirror or merge has just written rel. Restoring the backup now would put an older
            # file over it: the backup holds whatever was on disk when an overlay first wrote rel, which is often
            # another version's file, not a stock one. Keep the backup and keep rel in the state, so a later switch
            # to a version that ships neither can still restore it (launcher/install_guard, 2026-10-11).
            if _install_guard and _install_guard.installed_by_this_launch(rel):
                kept.append(rel)
                _install_guard.note_kept(rel)
                continue
            dst = os.path.join(game_path, *rel.split("/"))
            bak = os.path.join(_backup_root(), *rel.split("/"))
            try:
                if os.path.exists(bak):
                    shutil.copy2(bak, dst)
                    os.remove(bak)
                elif os.path.exists(dst) and rel in _OVERLAY_ALWAYS_REMOVE:
                    os.remove(dst)
                elif os.path.exists(dst):
                    orphans.append(rel)
            except Exception as e:
                print(f"[overlay] could not revert {rel}: {e}")

        written = []
        for src, rel in pairs:
            # A git-LFS placeholder is not the file: the game's own copy stays (launcher/install_guard).
            if _install_guard and _install_guard.lfs_skip(src, rel):
                if rel in prev:
                    kept.append(rel)
                continue
            dst = os.path.join(game_path, *rel.split("/"))
            bak = os.path.join(_backup_root(), *rel.split("/"))
            # Recorded before the copy, so a copy that fails is caught by the check.
            if _install_guard:
                _install_guard.note_overlay(src, rel)
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                # back up the stock file the FIRST time we overwrite it. If rel is in
                # prev, what is on disk is our own file, not the player's -- do not
                # capture it as if it were stock. Nor if this launch's mirror or merge
                # has just written it: that is this version's file, not a stock one.
                if os.path.exists(dst) and not os.path.exists(bak) and rel not in prev:
                    if _install_guard and _install_guard.installed_by_this_launch(rel):
                        _install_guard.note_not_captured(rel)
                    else:
                        os.makedirs(os.path.dirname(bak), exist_ok=True)
                        shutil.copy2(dst, bak)
                (_install_guard.copy_if_changed if _install_guard else shutil.copy2)(src, dst)
                written.append(rel)
            except Exception as e:
                print(f"[overlay] could not install {rel}: {e}")

        if orphans:
            print(f"[overlay] {len(orphans)} file(s) have no stock backup recorded and were LEFT "
                  f"in place rather than deleted; first few: {orphans[:4]}")
        # Orphans stay in the state list on purpose. Drop them and the next version
        # that wants one of these paths sees rel not in prev, finds no backup, and
        # captures our OWN modified file as if it were stock.
        state["overlay"] = sorted(set(written) | set(orphans) | set(kept))
        state["version"] = gameVersion
        write_patch_state(state)
        return len(written)

    def _accepted_exe_md5s(recipe):
        """Every source build this recipe can start from, canonical first."""
        try:
            R = _recipe_meta(recipe)
        except Exception:
            return []
        return [R["src_md5"]] + [a["md5"] for a in R.get("alt_sources", [])]

    def _apply_exe_recipe(recipe_path, src_path, dst_path):
        """Rebuild the patched exe from a supported source build.

        More than one source is accepted. The stock Steam exe and this project's
        reference exe differ by a single hand-applied edit, so a source that is not the
        canonical one is first NORMALISED up to it -- everyone lands on one identical
        binary, which matters because they share an online match pool. Both ends are
        md5-checked, so a wrong build or an already-patched input fails loudly rather
        than producing something subtly broken."""
        import zlib, struct, hashlib
        with open(recipe_path, "rb") as f:
            R = json.loads(zlib.decompress(f.read()))
        with open(src_path, "rb") as f:
            d = bytearray(f.read())
        have = hashlib.md5(d).hexdigest()
        if have != R["src_md5"]:
            alt = next((a for a in R.get("alt_sources", [])
                        if a["md5"] == have and len(d) == a.get("size", len(d))), None)
            if alt is None:
                raise ValueError(
                    "this exe is not a build the patch supports (md5 %s).\n"
                    "Supported: BLEACH_Rebirth_of_Souls.exe v1.3.0.0, stock from Steam "
                    "or the community reference build." % have[:12])
            for off, hx in alt.get("ops", []):
                b = bytes.fromhex(hx)
                d[off:off + len(b)] = b
            now = hashlib.md5(d).hexdigest()
            if now != R["src_md5"]:
                raise ValueError("could not normalise '%s' to the reference build"
                                 % alt.get("name", have[:12]))
            print(f"[exe] normalised {alt.get('name', have[:12])} to the reference build")
        if len(d) != R["src_size"]:
            raise ValueError("source exe is %d bytes, expected %d" % (len(d), R["src_size"]))
        g = R["grow_at"]
        d = d[:g] + bytearray(R["grow"]) + d[g:]
        for off, val in R["sec_hdr"]:
            struct.pack_into("<I", d, off, val)
        for off, hx in R["ops"]:
            b = bytes.fromhex(hx)
            d[off:off + len(b)] = b
        if hashlib.md5(d).hexdigest() != R["md5"]:
            raise ValueError("the patched exe failed its own checksum; nothing written")
        with open(dst_path, "wb") as f:
            f.write(bytes(d))

    def _recipe_meta(path):
        import zlib
        with open(path, "rb") as f:
            return json.loads(zlib.decompress(f.read()))

    def _md5_file(path):
        import hashlib
        h = hashlib.md5()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
        except Exception:
            return None
        return h.hexdigest()

    def setup_exe(gameVersion):
        """Install or remove the exe patch for this version. Returns True on success."""
        state = read_patch_state()
        recipe = None
        for v in version_chain(gameVersion):
            p = os.path.join(BASE_DIR, "GameVersions", v, "Exe", "exe_patch.recipe")
            if os.path.exists(p):
                recipe = p
        exe = os.path.join(game_path, EXE_NAME)
        bak = os.path.join(_backup_root(), EXE_NAME)

        if recipe is None:
            if state.get("exe") and os.path.exists(bak):
                try:
                    shutil.copy2(bak, exe)
                except Exception as e:
                    print(f"[exe] could not restore stock exe: {e}")
                    return True
            state["exe"] = False
            write_patch_state(state)
            return True

        accepted = _accepted_exe_md5s(recipe)
        if not accepted:
            messagebox.showerror("Launch Error", "Could not read the exe patch recipe.")
            return False

        # Find an UNPATCHED exe by checksum rather than assuming the one on disk is clean.
        # Someone who has already patched by hand would otherwise get their patched exe
        # captured as "vanilla", and every future revert would restore that instead -- a
        # corruption that survives reinstalling the launcher.
        if _md5_file(bak) not in accepted:
            cands = [exe]
            cands += [exe + s for s in (".pre_gridpatch_bak", ".bak", ".orig_bak",
                                        ".vanilla_bak")]
            # a clean exe parked in the dev environment, for anyone whose own copy is
            # already modified
            cands.append(os.path.join(BASE_DIR, "Clean_EXE", EXE_NAME))
            for v in version_chain(gameVersion):
                cands.append(os.path.join(BASE_DIR, "GameVersions", v, "Exe", EXE_NAME))
            stock = next((c for c in cands
                          if os.path.exists(c) and _md5_file(c) in accepted), None)
            if stock is None:
                messagebox.showerror(
                    "Launch Error",
                    "This add-on patches the game executable, and no supported copy of "
                    "BLEACH_Rebirth_of_Souls.exe could be found.\n\n"
                    "Put an unmodified v1.3.0.0 executable in:\n"
                    "    %s\n\n"
                    "or use Repair with a clean backup of the game. The game was not "
                    "launched and nothing was changed."
                    % os.path.join(BASE_DIR, "Clean_EXE"))
                return False
            try:
                os.makedirs(_backup_root(), exist_ok=True)
                shutil.copy2(stock, bak)
            except Exception as e:
                messagebox.showerror("Launch Error", f"Could not back up your exe:\n\n{e}")
                return False

        try:
            # ALWAYS build from the verified backup, never from the live exe -- otherwise
            # a second launch would patch an already-patched file.
            _apply_exe_recipe(recipe, bak, exe)
        except Exception as e:
            messagebox.showerror(
                "Launch Error",
                f"Could not apply the executable patch:\n\n{e}\n\nThe game was not launched.")
            return False
        state["exe"] = True
        write_patch_state(state)
        return True

    def injectFolder(files,folderName,fullFolder=True):
            folder_src = os.path.join(BASE_DIR,"GameVersions",f"{files}",f'{folderName}')
            folder_dst = os.path.join(game_path,f'{folderName}')

            if fullFolder:
                if _install_guard:
                    # a file that already holds its source's bytes (another checkout's copy) gets its time, not a copy
                    _install_guard.retime_tree(folder_src, folder_dst)
                try:
                    subprocess.run(["robocopy",folder_src,folder_dst,"/MIR"],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                except Exception as e:
                    shutil.rmtree(folder_dst)
                    shutil.copytree(folder_src, folder_dst)
                if _install_guard:
                    _install_guard.note_mirror(folder_src, folderName)
            elif _install_guard:
                # copytree minus the dev leftovers and git-LFS placeholders, recorded for the check
                _install_guard.merge_tree(folder_src, folder_dst, folderName)
            else:
                shutil.copytree(folder_src, folder_dst,dirs_exist_ok=True)

    def injectEffects(files,effectFolder):
        effect_src = os.path.join(BASE_DIR,"GameVersions",f"{files}",f'{effectFolder}',"Effect","spfx","com")
        effect_dst = os.path.join(game_path,f'{effectFolder}',"Effect","spfx","com")
        try:
            subprocess.run(["robocopy",effect_src,effect_dst,"/MIR"],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as e:
            shutil.rmtree(effect_dst)
            shutil.copytree(effect_src, effect_dst)



    def injectPerformanceFiles(folderName,lowspecmodornot):
        try:
            src = os.path.join(BASE_DIR,"Files","Spec Mod",f'{folderName}',f'{lowspecmodornot}')
            shutil.copytree(src,
                            os.path.join(game_path,"00HIGH","Effect","spfx","com"),dirs_exist_ok=True)
            shutil.copytree(src,
                            os.path.join(game_path,"01MIDDLE","Effect","spfx","com"),dirs_exist_ok=True)
            # A value's folder holds the HIGH tier's bytes. Where the Middle tier's own files
            # differ, they sit beside it as <value>_middle and go on top here. Without them, a
            # player on a lower graphics preset got the High effects: the evolve aura at 4.3
            # times its Middle size, the hit sparks at 3 times, on every hit.
            if os.path.isdir(src + "_middle"):
                shutil.copytree(src + "_middle",
                                os.path.join(game_path,"01MIDDLE","Effect","spfx","com"),dirs_exist_ok=True)
        except Exception as e:
            print(f"Error injecting performance files: {e}")

    def repair():
        messagebox.showinfo("Repair", "Please select the BLEACH_Rebirth_of_Souls.exe file from a clean backup folder of the game (your backup folder, not your main Bros folder)")
        repair_game_path = ""
        parent_dir = ""
        if not repair_game_path or repair_game_path == "" or not "BLEACH Rebirth of Souls" in repair_game_path:
            flag = True
            while(flag):
                repair_game_path = filedialog.askopenfilename(title="Select Bleach rebirth of souls",filetypes=[("Executable files", "*.exe")])

                if repair_game_path == "":
                    messagebox.showinfo("Repair", "You cancelled the repair process.")
                    return
                elif"BLEACH_Rebirth_of_Souls.exe" in repair_game_path:
                    parent_dir = os.path.dirname(repair_game_path)
                    repair_game_path = str(parent_dir)
                    if repair_game_path == config["GAME_PATH"]:
                        messagebox.showerror("Error", "You selected the same folder as your main game folder. Please select a backup folder.")
                    else:
                        flag = False
                else :
                    messagebox.showerror("Error", "You did not select the correct file. Please select the BLEACH_Rebirth_of_Souls.exe file of your backup folder")


        messagebox.showinfo("Repair", "Repairing files. Please wait")
        repairPage.tkraise()
        window.update()

        repairWaitOstPath = os.path.join(BASE_DIR,"ressources","RepairWaitOst.wav")
        repairEndOstPath = os.path.join(BASE_DIR,"ressources","RepairEndOst.wav")


        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
            winsound.PlaySound(repairWaitOstPath, winsound.SND_ASYNC | winsound.SND_LOOP)
        except:
            pass

        try:
            subprocess.run([
                "robocopy", repair_game_path, game_path, "/E", "/XO"
            ], capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        except:
            shutil.copytree(repair_game_path, game_path, dirs_exist_ok=True)

        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
            winsound.PlaySound(repairEndOstPath, winsound.SND_ASYNC)
        except:
            pass
        messagebox.showinfo("Repair", "Files repaired successfully!")
        backToMainMenu()
        launcherOstPath = os.path.join(BASE_DIR,"ressources","LauncherOst.wav")

        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
            winsound.PlaySound(launcherOstPath, winsound.SND_ASYNC | winsound.SND_LOOP)
        except:
            pass

    def setup_matchmaking(target_path, gameVersion):
        """Install the in-game matchmaking loader (dinput8.dll) and stamp a
        match code so only players on the SAME patch version + build match.
        Vanilla players have no loader and are excluded automatically."""
        import zlib
        src = os.path.join(BASE_DIR, "Files", "Matchmaking", "dinput8.dll")
        # A game mode can ship its own loader instead of (or as well as) data.
        # Reawakening Battle is the first: its mechanic is an exe hook, not a
        # CharaStatus edit, so there is nothing to copy into Script/. Any mode
        # that drops a dinput8.dll in its folder gets it installed here, and
        # because setup_matchmaking runs LAST in launch() it wins over the
        # normal loader rather than racing it.
        # 4-5 is not one of them any more: its frozen loader had fallen 59
        # commits behind the master (rooms capped at two, no plugins). The
        # master carries the mode and launch_patched() asks for it with
        # BROS_GAME_MODE, so 4-5 is always the current build.
        # Universal Step Cancel never had a loader of its own: it is the master
        # plus the stepcancel.dll plugin, armed by the same BROS_GAME_MODE.
        # Strike Back Last Hit is the same shape (strikeback.dll).
        if gameMode not in ("DEFAULT", "4-5", "UniversalStepCancel", "StrikeBackLastHit", "RapideReverse"):
            modeDll = os.path.join(BASE_DIR, "GameModes", f"{gameMode}", "dinput8.dll")
            if os.path.exists(modeDll):
                src = modeDll
                print(f"[matchmaking] game mode {gameMode} ships its own loader")
        try:
            shutil.copy(src, os.path.join(target_path, "dinput8.dll"))
            # ---- _LOADER_INSTALL_VERIFIED (added 2026-08-28) ---------------------------
            # A silently stale loader is how the 08-06 Aizen hotfix became a desync
            # nobody could trace: Windows refuses to overwrite a DLL that is still
            # loaded, the copy above raised, the caller caught it, printed to a
            # console nobody reads, and the game launched anyway on the OLD build.
            # Two clients on two builds then computed flame costs differently.
            # SystemExit derives from BaseException, so the surrounding
            # "except Exception" cannot swallow this the way it swallowed the copy.
            _dst = os.path.join(target_path, "dinput8.dll")
            import hashlib as _hl
            _want = _hl.sha256(open(src, "rb").read()).hexdigest()
            _got  = _hl.sha256(open(_dst, "rb").read()).hexdigest() if os.path.exists(_dst) else ""
            if _want != _got:
                raise SystemExit(
                    "\n!! dinput8.dll did NOT install -- the game was NOT started.\n"
                    "   built  %s\n   on disk %s\n"
                    "   Windows locks a loaded DLL: close the game completely and run\n"
                    "   this again. Launching on a stale loader is what produces\n"
                    "   'the patch works for me but not for them' reports.\n"
                    % (_want[:16], _got[:16] or "MISSING"))
            # A master without the run-time mode would start a stock game the
            # player believes is 4-5. Read the capability out of the bytes.
            if gameMode == "4-5":
                with open(_dst, "rb") as _f:
                    if b"BROS_GAME_MODES=4-5" not in _f.read():
                        raise SystemExit(
                            "\n!! The installed dinput8.dll cannot run 4-5 -- the game\n"
                            "   was NOT started. The master was rebuilt from a source\n"
                            "   without the run-time mode; rebuild it from HEAD's\n"
                            "   Files/Matchmaking/dinput8_proxy.c.\n")
        except Exception as e:
            print(f"[matchmaking] could not install dinput8.dll: {e}")
            return

        # ---- PLUGINS (added 2026-09-06) -------------------------------------------
        # dinput8.dll is the MASTER now: character mods live in their own DLLs under
        # <game>/ReBalanceOfSouls/ and the master loads them from there. The reason is
        # 2026-09-05, when a BUILD_CRE=0 build was committed over the shared
        # Files/Matchmaking/dinput8.dll and Zangetsu simply stopped existing -- that
        # flag compiles his whole system out, so the moon gauge, the level counter and
        # the forced Reawakening were absent from the process for a full playtest with
        # nothing anywhere saying so. A plugin cannot be compiled out of somebody
        # else's binary.
        #
        # MIRRORED, not merged. A plugin left behind from an older install is exactly
        # the criss-crossing this replaces: it would keep patching the exe next to the
        # one that replaced it. Anything in the folder that we are not shipping goes.
        try:
            import hashlib as _hl2
            plug_src = os.path.join(BASE_DIR, "Files", "Matchmaking", "Plugins")
            plug_dst = os.path.join(target_path, "ReBalanceOfSouls")
            want = sorted(f for f in os.listdir(plug_src)
                          if f.lower().endswith(".dll")) if os.path.isdir(plug_src) else []

            # A master that cannot host plugins must not be given any. Read the
            # capability out of the DLL we just installed rather than matching its
            # bytes against a recipe -- a hash stops being true the moment anyone
            # rebuilds, which is how the developers' game-mode check (from Quick
            # Launch Training Mode.py, now launcher/quick_menu.py gate_game_mode)
            # goes wrong.
            with open(_dst, "rb") as _f:
                _master = _f.read()
            can_host = b"BROS_PLUGIN_HOST_ABI=" in _master
            if want and not can_host:
                raise SystemExit(
                    "\n!! The dinput8.dll being installed has no plugin loader, but\n"
                    "   %d plugin(s) are due to be installed beside it:\n"
                    "       %s\n"
                    "   They would sit in ReBalanceOfSouls/ with nothing to load them,\n"
                    "   which in game reads as 'that character just isn't there'.\n"
                    "   The game was NOT started. Rebuild the loader:\n"
                    "       Files/Matchmaking/build_dinput8.sh cre\n"
                    % (len(want), ", ".join(want)))

            # A VERSION'S OWN PLUGINS (2026-10-13). A version can ship a plugin in its
            # Overlay/ReBalanceOfSouls/ -- V1.7 carries dcreborn.dll and dcstory.dll
            # beside the rule files they read. install_overlay() has just put them
            # down, and the mirror below used to delete them again as "stale",
            # because they are not in Files/Matchmaking/Plugins: the Reborn
            # characters, costume paging and subtitles went with them before the
            # game ever started. They are part of what this version ships, so they
            # stay; a switch to a version whose chain does not ship them removes
            # them here like any other stale plugin.
            version_plugins = {}
            for _v in version_chain(gameVersion):
                _vp = os.path.join(BASE_DIR, "GameVersions", _v, "Overlay", "ReBalanceOfSouls")
                if os.path.isdir(_vp):
                    for _f in os.listdir(_vp):
                        if _f.lower().endswith(".dll"):
                            version_plugins[_f] = os.path.join(_vp, _f)
            if want or version_plugins:
                os.makedirs(plug_dst, exist_ok=True)
            if os.path.isdir(plug_dst):
                for stale in os.listdir(plug_dst):
                    if stale.lower().endswith(".dll") and stale not in want and stale not in version_plugins:
                        try:
                            os.remove(os.path.join(plug_dst, stale))
                            print(f"[plugins] removed stale {stale}")
                        except Exception as _e:
                            raise SystemExit(
                                "\n!! Could not remove the stale plugin %s: %s\n"
                                "   Leaving it would let two builds patch the exe at once.\n"
                                "   The game was NOT started. Close the game and retry.\n"
                                % (stale, _e))
            # The version's plugins first, so a shared plugin of the same name still wins.
            for f, s_p in sorted(version_plugins.items()):
                if f in want:
                    continue
                d_p = os.path.join(plug_dst, f)
                shutil.copy(s_p, d_p)
                if _hl2.sha256(open(s_p, "rb").read()).hexdigest() != \
                        (_hl2.sha256(open(d_p, "rb").read()).hexdigest() if os.path.exists(d_p) else ""):
                    raise SystemExit(
                        "\n!! %s (shipped by %s) did NOT install -- the game was NOT started.\n"
                        "   Windows locks a loaded DLL: close the game completely and run this again.\n"
                        % (f, gameVersion))
                print(f"[plugins] installed {f} (from the version)")
            for f in want:
                s_p = os.path.join(plug_src, f)
                d_p = os.path.join(plug_dst, f)
                shutil.copy(s_p, d_p)
                w = _hl2.sha256(open(s_p, "rb").read()).hexdigest()
                g = _hl2.sha256(open(d_p, "rb").read()).hexdigest() if os.path.exists(d_p) else ""
                if w != g:
                    raise SystemExit(
                        "\n!! %s did NOT install -- the game was NOT started.\n"
                        "   built  %s\n   on disk %s\n"
                        "   Windows locks a loaded DLL: close the game completely and\n"
                        "   run this again. Launching on a stale plugin is the same\n"
                        "   'works for me, not for them' bug the loader check catches.\n"
                        % (f, w[:16], g[:16] or "MISSING"))
                print(f"[plugins] installed {f}")
            if want:
                print(f"[plugins] {len(want)} plugin(s) in ReBalanceOfSouls/ -- the loader"
                      f" reports them in patch_ranked.log under BROS/plugins")
            if _room_modes is not None:
                _room_modes.install(BASE_DIR, target_path)
        except SystemExit:
            raise
        except Exception as e:
            print(f"[plugins] could not install plugins: {e}")
        # Universal Step Cancel and Strike Back Last Hit live in PLUGINS, not in
        # the master: every launch mirrors the plugin and it only arms under
        # BROS_GAME_MODE=<the mode>. Without it the player would sit in the
        # mode's pool believing a mechanic is on that is not in the process.
        # Read the capability out of the installed bytes.
        _plugin_mode = {
            "UniversalStepCancel": ("stepcancel", "Universal Step Cancel"),
            "StrikeBackLastHit":   ("strikeback", "Strike Back Last Hit"),
            "RapideReverse":       ("rapidreverse", "Rapide Reverse"),
        }.get(gameMode)
        if _plugin_mode:
            _pm_name, _pm_label = _plugin_mode
            _sc = os.path.join(target_path, "ReBalanceOfSouls", _pm_name + ".dll")
            _sc_ok = False
            if os.path.exists(_sc):
                with open(_sc, "rb") as _f:
                    _sc_ok = ("BROS_GAME_MODES=" + gameMode).encode() in _f.read()
            if not _sc_ok:
                raise SystemExit(
                    f"\n!! {_pm_label} cannot run -- the game was NOT started.\n"
                    f"   ReBalanceOfSouls/{_pm_name}.dll is missing or is not the mode's\n"
                    f"   plugin. It ships in Files/Matchmaking/Plugins/; pull, or rebuild\n"
                    f"   it with Files/Matchmaking/build_plugin.sh {_pm_name}.\n")
        # Match pool is derived AUTOMATICALLY from the current GitHub build
        # (the commit SHA from get_snapshot()) plus the selected game version.
        # crc32 turns the SHA (hex letters + digits) into a number. Every push
        # yields a new SHA -> a fresh pool, so players on a different build /
        # game version / vanilla won't match you. No manual bumping needed.
        build = get_snapshot() or "unknown"
        seed = f"{build}|{gameVersion}"
        # Universal Step Cancel simulates a different fight from a normal client
        # (a dash out of a step becomes the run loop), so it needs its own pool.
        # 4-5 gets its pool from the master; this mode is a plugin, so the pool
        # comes from here: the mode joins the seed, and only players with the
        # mode on, on the same build and version, can meet. Strike Back Last Hit
        # too: a Strike Back pays on a different hit than a normal client's. Rapide
        # Reverse too: Light+Heavy on a hit drops a fighter back to idle for a bar.
        if gameMode in ("UniversalStepCancel", "StrikeBackLastHit", "RapideReverse"):
            seed += "|" + gameMode
        code = 100000 + (zlib.crc32(seed.encode("utf-8")) % 800000)
        # A content pool (CONTENT_POOLS, above compute_match_code): launch() writes this version's code just before
        # the start, once every switch file is in place. Until then patch_ranked.txt holds this commit's own code, a
        # pool the beta never joins, so a launch stopped before that step cannot land in the beta's pool.
        if gameMode == "DEFAULT" and gameVersion in CONTENT_POOLS:
            print(f"[matchmaking] {gameVersion}: the content pool is made just before the start "
                  f"(launcher/content_pool.py)")
        try:
            with open(os.path.join(target_path, "patch_ranked.txt"), "w") as f:
                f.write(str(code) + "\n")
        except Exception as e:
            print(f"[matchmaking] could not write match code: {e}")

    def remove_matchmaking(target_path):
        """Revert online segregation: remove the loader so vanilla launches
        cleanly under EasyAntiCheat."""
        p = os.path.join(target_path, "dinput8.dll")
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception as e:
            print(f"[matchmaking] could not remove dinput8.dll: {e}")

        # The plugins too (as Quick Launch Bros Vanilla did, until 2026-11-06):
        # inert without the loader, but a vanilla game folder should not keep them.
        try:
            pdst = os.path.join(target_path, "ReBalanceOfSouls")
            if os.path.isdir(pdst):
                gone = []
                for f in os.listdir(pdst):
                    if f.lower().endswith(".dll"):
                        os.remove(os.path.join(pdst, f))
                        gone.append(f)
                if gone:
                    print(f"[plugins] removed {len(gone)} plugin(s) for a vanilla run: "
                          f"{', '.join(gone)}")
        except Exception as e:
            print(f"[plugins] could not clear plugins: {e}")

    def launch_patched(target_path, boot_mode=None, game_mode=None):
        """Launch the patched game. On Windows, start the .exe directly (required
        so EasyAntiCheat doesn't block the injected dinput8.dll -- crash otherwise).
        On Linux/macOS a Windows .exe can't be exec'd directly ([Errno 8] Exec
        format error) -- it only runs through Steam/Proton -- so launch it via
        Steam's app URL instead. Steam must be running for online play.

        boot_mode is the Quick Launch shortcut ("training" / "roommatch"): the
        screen the loader jumps to instead of the title screen. It travels in
        BROS_BOOT_MODE rather than as a separate dll, so the one activated
        dinput8.dll serves every shortcut -- the contract the standalone Quick
        Launch scripts at the repo root had too, until they were baked into this
        launcher (2026-11-06). Clearing it when there is no
        shortcut keeps a failed quick launch from leaking into the next normal
        launch.

        Returns True if the game was started.

        Error 740 (the exe set to "Run this program as an administrator"): the
        only way in is the UAC prompt, and a process elevated through it gets a
        FRESH environment -- it never sees BROS_BOOT_MODE or BROS_GAME_MODE. A
        plain launch loses nothing and goes on elevated. A Quick Launch is asked
        first; a game mode is refused outright, because a plugin mode's online
        pool is already in patch_ranked.txt and the game would play stock rules
        in it -- the desync the mode pools exist to prevent.

        game_mode: the rules this start plays -- None means the launcher's game
        mode (gameMode); a vanilla plus version passes "DEFAULT", so no mode
        reaches its loader whatever the launcher shows."""
        exe = os.path.join(target_path, "BLEACH_Rebirth_of_Souls.exe")
        if _QUICK is not None and _QUICK["cmd"] == "prepare":
            print("[prepare] %s in %s; the game was NOT started (--prepare)"
                  % ("installed, with the problem the install check showed (OK was chosen)" if _QUICK.get("problem")
                     else "everything is in place", target_path))
            _QUICK["done"] = True
            return True
        _mh = globals().get("_maint_hold")
        if _mh:
            print("[%s] everything is in place in %s; the game starts %s" % (
                ("open", target_path, "at the Launch click") if _mh[0] == "open"
                else ("maintenance", target_path, "at the end of the maintenance")))
            _mh.append("installed")
            return True
        if boot_mode:
            os.environ["BROS_BOOT_MODE"] = boot_mode
        else:
            os.environ.pop("BROS_BOOT_MODE", None)
        # 4-5 travels the same way, and is cleared the same way: this window
        # stays open, so a 4-5 launch must not leak into the next normal one.
        # Universal Step Cancel too -- stepcancel.dll arms only on this value --
        # and Strike Back Last Hit (strikeback.dll).
        _mode = gameMode if game_mode is None else game_mode
        if _mode in ("4-5", "UniversalStepCancel", "StrikeBackLastHit", "RapideReverse"):
            os.environ["BROS_GAME_MODE"] = _mode
        else:
            os.environ.pop("BROS_GAME_MODE", None)
        if platform.system() != "Windows":
            try:
                open_file("steam://rungameid/1689620")
                if _QUICK is not None:
                    _QUICK["done"] = True
            except Exception as e:
                print(f"Error launching patched game: {e}")
            return True
        # Smart App Control on blocks the loader and every plugin (launcher/sac_check.py): say so before starting.
        if _sac_check is not None and not _sac_check.ok_to_start(messagebox):
            return False
        # A graphics add-on beside the exe (ReShade as dxgi.dll ...) can close the patched game as it starts
        # (launcher/injector_check.py): ask first. Read through globals(): see launch_report below.
        _ic = globals().get("_injector_check")
        if _ic is not None and not _ic.ok_to_start(messagebox, target_path):
            return False
        # The launch report (launcher/launch_report.py): read through globals() so that the tests which run this
        # function alone, with only the names they know, keep working.
        _lr = globals().get("_launch_report")
        try:
            _proc = subprocess.Popen([exe], cwd=target_path)
            if _lr is not None:
                _lr.game_started(target_path, _proc, "direct")       # the watcher: returns at once, never raises
            if _QUICK is not None:
                _QUICK["done"] = True
            if os.environ.get("BROS_FOCUS") and _quick_menu:
                _quick_menu.focus_game_window(_proc.pid)
            return True
        except OSError as e:
            if getattr(e, "winerror", None) != 740:
                print(f"Error launching patched game: {e}")
                if _lr is not None:
                    _lr.not_started(target_path, e)
                return False
        except Exception as e:
            print(f"Error launching patched game: {e}")
            if _lr is not None:
                _lr.not_started(target_path, e)
            return False
        fix = ("To fix it: right-click\n%s\n> Properties > Compatibility, untick 'Run this program as an "
               "administrator' (and the same under 'Change settings for all users')." % exe)
        if os.environ.get("BROS_GAME_MODE"):
            messagebox.showerror(
                "Launch Error",
                f"The {os.environ['BROS_GAME_MODE']} game mode cannot start: Windows is set to run the game "
                "as administrator (error 740), and a game started through the administrator prompt does "
                "not receive the game mode. It would play normal rules in the mode's online pool.\n\n"
                "The game was NOT started.\n\n" + fix)
            return False
        if boot_mode and not messagebox.askyesno(
                "Quick Launch",
                "Quick Launch cannot jump straight to %s: Windows is set to run the game as administrator "
                "(error 740), and a game started through the administrator prompt does not receive the "
                "shortcut.\n\nStart the game normally instead (title screen)?\n\n%s"
                % ("the Room Match menu" if boot_mode == "roommatch" else "Training", fix)):
            return False
        # The exe asks for elevation -- Popen/CreateProcess cannot raise the UAC
        # prompt itself, ShellExecuteW with "runas" can.
        try:
            _ok = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, None, target_path, 1) > 32
            if _ok and _QUICK is not None:
                _QUICK["done"] = True
            if _lr is not None:
                if _ok:
                    _lr.game_started(target_path, None, "elevated (the administrator prompt)")
                else:
                    _lr.not_started(target_path, "the elevated start was refused or cancelled (error 740 first)")
            return _ok
        except Exception as e2:
            print(f"Error launching patched game (elevated): {e2}")
            if _lr is not None:
                _lr.not_started(target_path, e2)
            return False

    def _install_check_dialog(title, text, problem):
        """launcher/install_guard.finish()'s screen, and vanilla_revert's: True carries on (the game is started; under
        --prepare the install finishes), False stops."""
        if problem:
            if _QUICK is not None and _QUICK["cmd"] == "prepare":
                # --prepare starts nothing: OK lets the tool that asked carry on (as the Quick Launch scripts' console
                # did), Cancel stops it here (exit 1)
                _QUICK["problem"] = True
                return messagebox.askokcancel(title, text + "\n\nOK carries on (--prepare: the game is not "
                                              "started). Cancel stops here.", icon="warning")
            return messagebox.askokcancel(title, text + "\n\nOK starts the game anyway. Cancel does not.",
                                          icon="warning")
        messagebox.showinfo(title, text)
        return True

    # launch_game() under maintenance: launch()'s pass that installs and starts nothing -- "install" from the pull on,
    # "installed" once everything is in place (launch_patched, Vanilla's Steam start).
    _maint_hold = []

    # The opening's pass (warm_install; user, 2026-11-26: "rendre l'update plus longue au lancement du launcher, mais
    # plus court quand on lance le jeu"): launch() without its pull -- the update window has just pulled -- installing
    # everything and starting nothing ("open" in _maint_hold). It shows nothing: a message or a question waits for the
    # Launch click, which then runs the whole launch and shows it. A pass that ran through keeps what the install
    # depended on in _warm_ok: a click whose pull brought nothing and that changed no setting starts the game at once.
    _warm_ok, _warm_thread, _warm_told = [], [], []

    def _warm_key(gameVersion):
        """What an install depends on besides the checkout's files: the version, the commit, the game's exe (a Steam
        update), the launcher's settings and switches. None when it cannot be read."""
        try:
            head = subprocess.run(["git", "-C", BASE_DIR, "rev-parse", "HEAD"],
                                  check=True, capture_output=True, text=True).stdout.strip()
            st = os.stat(os.path.join(game_path, "BLEACH_Rebirth_of_Souls.exe"))
        except Exception:
            return None
        g = globals()
        return repr((gameVersion, head, st.st_size, st.st_mtime_ns,
                     json.dumps(g.get("config"), sort_keys=True, default=str),
                     json.dumps(g.get("admin_config"), sort_keys=True, default=str),
                     [g.get(n) for n in ("gameMode", "reworks", "netcodeOn", "diagnosticsOn", "fulldiagOn",
                                         "zangetsuManualOn", "rapidReverseOn", "komamuraOn", "devStudioOn",
                                         "devF9On")]))

    def _warm_wanted(gameVersion):
        """The opening installs gameVersion unless it is Vanilla or a vanilla plus version (their install asks the
        player first), the checkout is a developer's (its files change between the opening and the click: every click
        installs them), or the game is running."""
        if gameVersion not in gameVersionsList or gameVersion == "Bleach Rebirth of Souls" or _vanilla_revert is None:
            return False
        if os.path.isfile(os.path.join(BASE_DIR, "GameVersions", gameVersion, "vanilla_plus.json")) \
                or os.path.exists(os.path.join(BASE_DIR, "BalanceLeadTools", "DevToken.txt")):
            return False
        return os.path.isfile(os.path.join(game_path, "BLEACH_Rebirth_of_Souls.exe")) \
            and not _vanilla_revert.exe_locked(game_path)

    def _quiet_when_warm(f, answer):
        """messagebox's f, answered by `answer` (no, cancel) without a window on the opening's thread."""
        def g(*a, **k):
            if threading.current_thread() in _warm_thread:
                _warm_told.append(a[:1])
                print("[open] left for the Launch click: %s" % " -- ".join(map(str, a[:2])).replace("\n", " ")[:300])
                return answer
            return f(*a, **k)
        return g
    for _n, _a in (("showerror", "ok"), ("showwarning", "ok"), ("showinfo", "ok"), ("askokcancel", False),
                   ("askyesno", False), ("askyesnocancel", None), ("askretrycancel", False), ("askquestion", "no")):
        setattr(messagebox, _n, _quiet_when_warm(getattr(messagebox, _n), _a))

    def warm_install(gameVersion):
        """The opening's pass (above)."""
        _warm_ok.clear()
        _warm_told.clear()
        _maint_hold[:] = ["open"]
        _warm_thread[:] = [threading.current_thread()]
        try:
            launch(gameVersion, pull=False)
            if _maint_hold == ["open", "installed"] and not _warm_told:
                _warm_ok[:] = [_warm_key(gameVersion), time.time()]
        finally:
            _maint_hold.clear()
            _warm_thread.clear()

    def launch_game(gameVersion, boot_mode=None):
        """launch(); under maintenance (launcher/maintenance.py) the copy is done DURING it (user, 2026-11-24: 10 min of
        copy after a 5 min maintenance): a first pass installs everything and starts nothing, the maintenance window
        counts down, then the same launch runs again -- its pull and copy_if_changed bring only what changed meanwhile
        -- and starts the game. A maintenance moved later in the meantime holds that pass as well."""
        while True:
            _maint_hold.clear()
            try:
                launch(gameVersion, boot_mode)
                held = list(_maint_hold)
            finally:
                _maint_hold.clear()
            if held != ["install", "installed"] or not _maintenance.gate(BASE_DIR, game_path, parent=window):
                return

    def launch(gameVersion, boot_mode=None, pull=True):
        # read through globals(), like _launch_report: the tests run this function alone, with only the names they know
        _mh = globals().get("_maint_hold", [])
        if globals().get("_launch_report") is not None:
            globals()["_launch_report"].note_version(gameVersion, boot_mode)
        # boot_mode is set by the Quick Launch buttons and only forwarded to
        # launch_patched -- everything the game needs on disk is prepared the
        # exact same way as a normal launch.
        # A refused update used to end here with nothing on screen: the click
        # just did nothing, its traceback in the hidden console.
        try:
            _pull = pulling_from_git() if pull and (_QUICK is None or _QUICK["pull"]) else None
        except Exception as e:
            detail = (getattr(e, "stderr", "") or "").strip()
            messagebox.showerror(
                "Launch Error",
                f"The update before the launch failed, so the game was NOT started:\n\n{e}"
                + (f"\n\n{detail[-1500:]}" if detail else ""))
            return
        # The version's files that ship in parts (launcher/bigfiles.py; the pull above may have brought new ones). The
        # install walks the version's folders: without them it would quietly put the previous version's files, or the
        # game's own, back in their place. Not in place = nothing is installed and nothing starts.
        _bf = globals().get("_big_files")
        _why = _bf() if _bf and gameVersion != "Bleach Rebirth of Souls" else None
        if _why:
            messagebox.showerror(
                "Launch Error",
                "The update is not complete: some of the game's files could not be put together, so the game was "
                f"NOT started.\n\n{_why}\n\nCheck the free space on this disk, then start the launcher again.")
            return
        # Under maintenance: this pass installs and starts nothing; launch_game() waits for the end, then runs it again.
        # --prepare starts nothing anyway: it installs at once.
        _m = globals().get("_maintenance")
        if _m and not _mh and (_QUICK is None or _QUICK["cmd"] != "prepare") and _m.running(BASE_DIR, game_path):
            _mh.append("install")
        # The opening installed this version and nothing it depended on changed since (warm_install): the game starts.
        # One use: a start that fails runs the whole launch the next time.
        _wk = globals().get("_warm_ok")
        if _wk and not _mh:
            _k, _t = _wk
            _wk.clear()
            if _k is not None and time.time() - _t < 1800 and _k == globals()["_warm_key"](gameVersion):
                print("[open] %s was installed when the launcher opened, nothing changed since: the game starts"
                      % gameVersion)
                if launch_patched(game_path, boot_mode):
                    window.destroy()
                return
        # The record of this launch: the checkout as the pull left it -- before the syncs below, which delete
        # and write tracked files on purpose -- then every file put down (launcher/install_guard).
        if _install_guard:
            _install_guard.begin(BASE_DIR, game_path, gameVersion, _pull,
                                 os.path.exists(os.path.join(BASE_DIR, "BalanceLeadTools", "DevToken.txt")))
        if _leftovers:
            _leftovers.mark_start()            # what this launch writes from here on is its own
        # After the pull -- a parent may have just moved -- and before the
        # injection, so what lands in the game folder already has it: every
        # layer takes its parent's rows (launcher/version_inherit.py).
        if _version_inherit:
            _version_inherit.sync_quietly(BASE_DIR)
        try:
            # Vanilla means the game as Steam ships it: no game mode, no Team
            # Battle table, no patch data of any kind (the mode and Team Battle
            # copies below used to run for it too, putting a modded
            # CharaStatus.fsv into a Steam/EasyAntiCheat online game).
            vanilla = (gameVersion == "Bleach Rebirth of Souls")
            # A vanilla plus version (launcher/vanilla_plus.py): Vanilla's data, then its own loader and plugins.
            # Read before anything is installed, so a version that is not right stops here with nothing changed.
            _vplus = None
            if os.path.isfile(os.path.join(BASE_DIR, "GameVersions", gameVersion, "vanilla_plus.json")):
                if _vanilla_plus is None or _vanilla_revert is None:
                    messagebox.showerror(
                        "Launch Error",
                        f"'{gameVersion}' is the Steam game plus its own plugins: it needs launcher/vanilla_plus.py "
                        "and launcher/vanilla_revert.py, and this checkout is missing one.\n\nThe game was NOT started.")
                    return
                try:
                    _vplus = _vanilla_plus.read(BASE_DIR, gameVersion)
                except _vanilla_plus.VanillaPlusError as e:
                    messagebox.showerror("Launch Error",
                                         f"'{gameVersion}' cannot be installed:\n\n{e}\n\nThe game was NOT started.")
                    return
            vanilla_data = vanilla or _vplus is not None
            #folder injection
            # The chain's ROOT is mirrored (/MIR), which is what makes Script and Motion
            # revert cleanly between versions. Every version layered on top is merged, so
            # an add-on only has to ship the handful of files it actually changes.
            _chain = version_chain(gameVersion)
            _root = _chain[0]
            injectFolder(_root,"Script")
            injectFolder(_root,"Motion")
            injectFolder(_root,"00HIGH",False)
            injectFolder(_root,"01MIDDLE",False)
            for _child in _chain[1:]:
                for _sub in ("Script","Motion","00HIGH","01MIDDLE"):
                    if os.path.isdir(os.path.join(BASE_DIR,"GameVersions",_child,_sub)):
                        injectFolder(_child,_sub,False)
            # The Komamura rework's own files, before anything of it is installed (launcher/komamura_rework.py): a
            # missing or half-pulled file, or no pl023rework.dll in this checkout, stops the launch here.
            if _komamura_rework and _komamura_rework.wanted(BASE_DIR, gameVersion):
                try:
                    _komamura_rework.preflight(BASE_DIR, game_path)
                except _komamura_rework.KomamuraReworkError as e:
                    messagebox.showerror(
                        "Launch Error",
                        f"The Komamura rework cannot be installed:\n\n{e}\n\nThe game was NOT started. Switch the "
                        "rework OFF on the Advanced settings page, or fix the cause, and launch again.")
                    return
            install_overlay(gameVersion)
            # Every file of the install against its source; a mismatch is copied again once.
            if _install_guard:
                _install_guard.verify_and_repair()
            if not setup_exe(gameVersion):
                return
            # Vanilla: the game folder as Steam ships it -- every stock file proven against Steam's own list, every
            # file of ours removed, the logs moved out -- BEFORE the player's own choices below (the performance mods,
            # the reworks) are applied. Not proven on stock files only: the game starts, the report goes to the log
            # and Json\vanilla_report.txt (2026-11-28: the report window scared players). The patch itself still in
            # the folder: the player is asked. A running game is never started over (launcher/vanilla_revert.py, V1.5
            # delivery B.1). A vanilla plus version the same, before its own loader goes in (below).
            if vanilla_data and _vanilla_revert:
                # (2026-11-14) a vanilla plus version keeps its own plugins' state (its vanilla_plus.json "keep")
                _vr_kw = {} if vanilla else {"title": f"{gameVersion}: the Steam game's files", "label": gameVersion,
                                             "keep": _vplus.keep}
                if not _vanilla_revert.run(BASE_DIR, game_path, parent=window, ask=_install_check_dialog, **_vr_kw):
                    return
                # The online character a patched version left in the player's save (Zangetsu picked on V2.0): the
                # Steam game cannot go online with it, and the player was stuck until Ranked's character select. Only
                # a character the patch alone has is changed: to Ichigo (pl000), costume 0, with a backup first
                # (launcher/save_unlock.py; Berg 2026-11-28: "just switch you to pl000 selected online when you switch
                # to vanilla"). Never stops the start.
                if _save_unlock:
                    _ok, _text, _res = _save_unlock.vanilla_online(game_path)
                    if not _ok or any(_s != "kept" for _s, _l in _res):
                        print("[vanilla] " + _text.replace("\n", "\n[vanilla] "))



            #ost choice
            #ostFolder = ""
                #if config["OST_MOD"] == "ON":
                    #ostFolder = "Mod"
                #else :
                    #ostFolder = "Default"
                #ostPath = os.path.join(BASE_DIR,"Files","OST",f"{ostFolder}","bgm.bnk")
                #if os.path.exists(ostPath):
                    #shutil.copy(
                        #ostPath,
                        #os.path.join(game_path, "Sound")
                    #)


            #Performance Mode injection
            shutil.copytree(os.path.join(BASE_DIR,"Files","Spec Mod",'reverse_globe',f'{config["reverse_globe"]}',"high"),
                        os.path.join(game_path,"00HIGH","Effect","spfx","com"),dirs_exist_ok=True)

            shutil.copytree(os.path.join(BASE_DIR,"Files","Spec Mod",'reverse_globe',f'{config["reverse_globe"]}',"middle"),
                        os.path.join(game_path,"01MIDDLE","Effect","spfx","com"),dirs_exist_ok=True)

            for folder in os.listdir(os.path.join(BASE_DIR,"Files","Spec Mod")):
                if folder != "reverse_globe":
                    injectPerformanceFiles(folder,config[folder])

            reworkPath = os.path.join(BASE_DIR,"Reworks")
            for rework in reworks:
                if rework != "OFF":
                    scriptPath = os.path.join(reworkPath,rework,"Script")
                    motionPath = os.path.join(reworkPath,rework,"Motion")

                    if os.path.exists(scriptPath):
                        shutil.copytree(scriptPath,os.path.join(game_path,"Script"),dirs_exist_ok=True)
                    if os.path.exists(motionPath):
                        shutil.copytree(motionPath,os.path.join(game_path,"Motion"),dirs_exist_ok=True)


            #gamemode injection
            if gameMode != "DEFAULT" and not vanilla_data:
                # Script/ and Motion/ both: a mode that needs its own animations
                # carries a .tactpkg, and those live under Motion/.
                for sub in ("Script","Motion"):
                    srcPath = os.path.join(BASE_DIR,"GameModes",f"{gameMode}",sub)
                    dstPath = os.path.join(game_path,sub)

                    # Not every mode is a data mode -- Reawakening Battle ships a
                    # loader and no Script/ at all, and copytree raises on a source
                    # that is not there.
                    if os.path.exists(srcPath):
                        shutil.copytree(srcPath, dstPath, dirs_exist_ok=True)

            # The Komamura rework's data (launcher/komamura_rework.py), on a patched version. Switch ON: pl023's acts,
            # combo tables and motion from Reworks/Komamura over the version's, his rows of CharaStatus / WepVisible /
            # CharaAttackHitColl and his CPU tables -- after the version, the reworks and the game mode's files,
            # before the game mode's CharaStatus cells (still the last word). OFF: the version's mirror and the
            # overlay revert have just put their own files back; the rework's files at paths the Steam game does not
            # have are removed. If it cannot be applied, the game is not started: a half-reworked Komamura is broken.
            if _komamura_rework and not vanilla_data:
                try:
                    _komamura_rework.install_data(BASE_DIR, game_path,
                                                  _komamura_rework.wanted(BASE_DIR, gameVersion))
                except _komamura_rework.KomamuraReworkError as e:
                    messagebox.showerror(
                        "Launch Error",
                        f"The Komamura rework could not be installed:\n\n{e}\n\nThe game was NOT started. Switch "
                        "the rework OFF on the Advanced settings page, or fix the cause, and launch again.")
                    return
            # The retired Starrk rework switch (launcher/starrk_rework.py, retired 2026-11-22: the rework is the reborn
            # Starrk, 54, in the version), on a patched version, right after the Komamura rework's: the files a launch
            # with the switch ON left at paths the Steam game does not have are removed -- never a path this version
            # installs itself (the reborn shares 42 of them). It does not raise; if it ever does, the game is not
            # started.
            if _starrk_rework and not vanilla_data:
                try:
                    _starrk_rework.install_data(BASE_DIR, game_path, False, gameVersion)
                except _starrk_rework.StarrkReworkError as e:
                    messagebox.showerror(
                        "Launch Error",
                        f"The old Starrk rework's files could not be cleared:\n\n{e}\n\nThe game was NOT started. "
                        "Fix the cause and launch again.")
                    return


            # The game mode's own CharaStatus cells (GameModes/<mode>/CharaStatus.json)
            # over whatever the version just installed, so they are the last word.
            # Called on EVERY launch: it also refuses a table that still holds a
            # mode's values from an earlier launch. Vanilla goes through
            # Steam with no loader, so no mode is armed there and none is applied; a vanilla plus version plays the
            # Steam game's rules too.
            from launcher import mode_status as _mode_status
            _mode_status.apply(BASE_DIR, game_path, "DEFAULT" if vanilla_data else gameMode)


            forlater = """
            else:
                src = Path(os.path.join(BASE_DIR,"Files",choice))
                dst = Path(game_path)

                dst.mkdir(parents=True,exist_ok=True)

                for item in src.rglob("*"):
                    if item.is_file:
                        relative_path = item.relative_to(src)
                        target_file = dst / relative_path

                        target_file.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copy2(item,target_file)
                """

            # --- matchmaking segregation + EAC-aware launch --------------------
            # Only true Vanilla launches via Steam (EAC on, no loader). Every
            # other version - Community Patch AND any other custom version
            # (e.g. a future variant) - launches the exe directly (EAC off,
            # required for the loader). Each one still gets its OWN matchmaking
            # pool automatically: setup_matchmaking's seed includes gameVersion,
            # so a Community Patch player and an "other version" player will
            # never be given the same match code even though both skip Steam.
            # After every copy of the launch: stray effect backups out of the effect folders, then the report
            # (launcher_install_report.txt in the game folder). A problem is shown before the game starts, and
            # the player decides; an information note (backups moved, files re-copied) is just shown.
            if _install_guard:
                _install_guard.sweep_effect_strays(game_path)
                if not _install_guard.finish(_install_check_dialog):
                    return
            VANILLA_VERSION = "Bleach Rebirth of Souls"
            if gameVersion != VANILLA_VERSION and _vplus is None:
                setup_matchmaking(game_path, gameVersion)
                # The New netcode switch, once the loader is in: it rewrites the
                # bros_net.txt the Overlay may just have put down. If it cannot,
                # the game is not started -- a game on a netcode the switch does
                # not show is the "works for me, not for them" bug again.
                if _netcode_mode:
                    try:
                        _netcode_mode.launch_step(BASE_DIR, game_path, version_chain(gameVersion),
                                                  os.path.join(game_path, "dinput8.dll"))
                    except _netcode_mode.NetcodeError as e:
                        messagebox.showerror(
                            "Launch Error",
                            f"The New netcode switch could not be applied:\n\n{e}\n\n"
                            "The game was NOT started. Fix the cause and launch again.")
                        return
                else:
                    print("[netcode] launcher/netcode_mode.py is missing: bros_net.txt is left as the version put it")
                # The Developer tools switches, once the plugins are in. Same rule
                # as the netcode: if they cannot be applied, the game is not
                # started -- a tool running that the switch shows off (or the
                # reverse) is the same "works for me" bug.
                if _devtools_mode:
                    try:
                        _devtools_mode.launch_step(BASE_DIR, game_path)
                    except _devtools_mode.DevtoolsError as e:
                        messagebox.showerror(
                            "Launch Error",
                            f"The Developer tools switches could not be applied:\n\n{e}\n\n"
                            "The game was NOT started. Fix the cause and launch again.")
                        return
                else:
                    print("[devtools] launcher/devtools_mode.py is missing: bros_tools.txt is left as it is")
                # The Zangetsu switch (manual Reawakening), once the plugins are
                # in. Same rule: if it cannot be applied, the game is not started
                # -- a match on a setting the switch does not show is the same bug.
                if _zangetsu_mode:
                    try:
                        _zangetsu_mode.launch_step(BASE_DIR, game_path)
                    except _zangetsu_mode.ZangetsuModeError as e:
                        messagebox.showerror(
                            "Launch Error",
                            f"The Zangetsu switch could not be applied:\n\n{e}\n\n"
                            "The game was NOT started. Fix the cause and launch again.")
                        return
                else:
                    print("[zangetsu] launcher/zangetsu_mode.py is missing: bros_zangetsu.txt is left as it is")
                # The Rapid Reverse switch, once the plugins are in. Same rule: if it cannot be applied, the game is
                # not started -- a match with Rapid Reverse while the switch shows OFF (or the reverse) is the same bug.
                if _rapidreverse_mode:
                    try:
                        _rapidreverse_mode.launch_step(BASE_DIR, game_path, gameMode)
                    except _rapidreverse_mode.RapidReverseModeError as e:
                        messagebox.showerror(
                            "Launch Error",
                            f"The Rapid Reverse switch could not be applied:\n\n{e}\n\n"
                            "The game was NOT started. Fix the cause and launch again.")
                        return
                else:
                    print("[rapidreverse] launcher/rapidreverse_mode.py is missing: "
                          "ReBalanceOfSouls\\rapidreverse.txt is left as it is")
                # The Komamura rework switch, once the plugins are in: ReBalanceOfSouls\komamura_rework.txt
                # (pl023rework.dll's switch) written while ON, removed while OFF -- the data went in above. ON with no
                # pl023rework.dll installed is refused. Same rule: if it cannot be applied, the game is not started.
                if _komamura_rework:
                    try:
                        _komamura_rework.launch_step(BASE_DIR, game_path)
                    except _komamura_rework.KomamuraReworkError as e:
                        messagebox.showerror(
                            "Launch Error",
                            f"The Komamura rework switch could not be applied:\n\n{e}\n\n"
                            "The game was NOT started. Fix the cause and launch again.")
                        return
                else:
                    print("[komamura] launcher/komamura_rework.py is missing: the Komamura rework is not installed")
                # The retired Starrk rework switch's plugin, once the plugins are in: a ReBalanceOfSouls\pl033rw.dll a
                # launch with the switch ON left is removed (the reborn's pl054rw.dll came with the plugins above).
                # Same rule: if it cannot be applied, the game is not started.
                if _starrk_rework:
                    try:
                        _starrk_rework.launch_step(BASE_DIR, game_path, gameVersion)
                    except _starrk_rework.StarrkReworkError as e:
                        messagebox.showerror(
                            "Launch Error",
                            f"The old Starrk rework's plugin could not be removed:\n\n{e}\n\n"
                            "The game was NOT started. Fix the cause and launch again.")
                        return
                else:
                    print("[starrk] launcher/starrk_rework.py is missing: a pl033rw.dll from the retired Starrk "
                          "rework switch is not checked")
                # The Advanced diagnostics switch (launcher/fulldiag.py), once the plugins are in. Same rule as the
                # switches above: if it cannot be applied, the game is not started -- a game that records while the
                # switch shows OFF (or the reverse) is the same "works for me" bug, and recording while OFF would go
                # against the player's choice. While ON it also leaves the launcher's snapshot beside the recordings.
                if _fulldiag:
                    try:
                        _fulldiag.launch_step(BASE_DIR, game_path, gameVersion, gameMode)
                    except _fulldiag.FulldiagError as e:
                        messagebox.showerror(
                            "Launch Error",
                            f"The Advanced diagnostics switch could not be applied:\n\n{e}\n\n"
                            "The game was NOT started. Fix the cause and launch again.")
                        return
                else:
                    print("[fulldiag] launcher/fulldiag.py is missing: bros_fulldiag.txt is left as it is")
                # The tournament recorder's switch (launcher/diagnostics.py): never stops a launch.
                if _diagnostics:
                    print("[diagnostics] " + _diagnostics.sync_switch_safe(BASE_DIR, game_path))
                # Leftovers of other builds (launcher/leftovers.py, pass rt 2026-11-09; Berg: "how do we just make it
                # so that it launches the same exact version that I have right now for other people"): a plugin rule
                # file this version does not ship, and another version's marker beside the exe, go to
                # _launcher_quarantine/leftovers/ -- each one gave a tester an online pool of his own. Never stops a
                # launch.
                _left, _snd = [], []
                if _leftovers:
                    try:
                        _keep_txt, _keep_root, _others = set(), set(), set()
                        for _s, _rel in _overlay_pairs(gameVersion):
                            _l = _rel.lower()
                            if _l.startswith("rebalanceofsouls/") and _l.count("/") == 1:
                                _keep_txt.add(_l.split("/", 1)[1])
                            elif "/" not in _l:
                                _keep_root.add(_l)
                        # the Rapid Reverse switch's file is this launcher's own (launcher/rapidreverse_mode.py): kept
                        # here; the public launcher's leftovers step moves it, so a beta game never has Rapid Reverse off
                        if _rapidreverse_mode:
                            _keep_txt.add(_rapidreverse_mode.NAME)
                        # the Komamura rework switch's file is this launcher's own too (launcher/komamura_rework.py);
                        # the public launcher's leftovers step moves it, so a beta game never runs the rework
                        if _komamura_rework:
                            _keep_txt.add(_komamura_rework.NAME)
                        _gv = os.path.join(BASE_DIR, "GameVersions")
                        for _v in (os.listdir(_gv) if os.path.isdir(_gv) else []):
                            _ov = os.path.join(_gv, _v, "Overlay")
                            if os.path.isdir(_ov):
                                _others |= {f.lower() for f in os.listdir(_ov) if os.path.isfile(os.path.join(_ov, f))}
                        _leftovers.clean(game_path, _keep_txt, _keep_root, _others - _keep_root, print)
                        # Another version's cutscene over the game's own (leftovers.py, CUTSCENES): put back from a
                        # copy proven against Steam's list (vanilla_revert's sources), else only Steam's verify can.
                        # This repo has no other version's Overlay (V1.7's Yumichika cutscenes are not here): the
                        # built-in tables name them too (2026-11-27, Petrichor alone on his pool with V1.7's
                        # Demo/pl015_evo_ct_sp_break01_2.tdemopkg, which V2.0's registry still lists).
                        _od = _leftovers.other_demos(_gv, version_chain(gameVersion))
                        for _r, _c in _leftovers.known_other_demos().items():
                            _od.setdefault(_r, []).extend(_c)
                        # A Steam cutscene not Steam's size at a path this version does not write: another build's
                        # too (a Dev build's Byakuya evolve, 2026-11-28), put back from the copy install_overlay kept
                        # (leftovers.py, STEAM'S CUTSCENES KEPT).
                        if _vanilla_revert:
                            _ship = set(_r.lower() for _s, _r in _overlay_pairs(gameVersion))
                            for _r, _c in _leftovers.over_steam_demos(
                                    game_path, _vanilla_revert.steam_list(BASE_DIR, game_path).files, _ship).items():
                                _od.setdefault(_r, []).extend(_c)
                        _left = _leftovers.fix_demo(
                            game_path, _od,
                            (lambda: _vanilla_revert.steam_list(BASE_DIR, game_path)) if _vanilla_revert else None,
                            (lambda _r: _vanilla_revert._stock_sources(BASE_DIR, game_path, _r)
                             + _leftovers.stock_copy(game_path, _r))
                            if _vanilla_revert else None, print)
                        # A cutscene that neither Steam nor any version ships (an older build's): to the quarantine
                        # too (leftovers.py, UNKNOWN CUTSCENES; 2026-11-27).
                        _leftovers.fix_unknown_demos(
                            game_path, _gv,
                            (lambda: _vanilla_revert.steam_list(BASE_DIR, game_path)) if _vanilla_revert else None,
                            print)
                        # A sound mod's files where the game's own should be (leftovers.py, CHANGED SOUNDS; 2026-11-28,
                        # a player's music mod left 80 Sound/Media/*.wem: Zangetsu's SP2 froze the game, awakenings
                        # crashed). Listed only: the mod is kept, and the version's banks follow its files
                        # (launcher/sound_merge.py, the same day; Berg: "not overwrite their already installed music
                        # mod"), so Steam's verify is no longer asked for.
                        if _vanilla_revert:
                            _snd = _leftovers.changed_sounds(
                                game_path, _vanilla_revert.steam_list(BASE_DIR, game_path).files, BASE_DIR)
                            if _snd:
                                print(f"[leftovers] {len(_snd)} sound file(s) are not Steam's (a sound mod's?): "
                                      + ", ".join(_snd[:5]))
                    except Exception as e:
                        print(f"[leftovers] not checked: {e}")
                if _left and messagebox.askyesno(
                        "Cutscenes from another version",
                        f"{len(_left)} cutscene file(s) in your game folder belong to another ReBalance version, "
                        f"where the game's own should be (for example {_left[0]}). The launcher has no copy of the "
                        f"game's own to put back, so only Steam can.\n\nUntil then you cannot meet the other players "
                        f"of {gameVersion} in Room Match.\n\nYes: open Steam's \"Verify integrity of game files\" now "
                        f"and stop here -- launch again when Steam has finished.\nNo: launch anyway.",
                        icon="warning"):
                    print("[leftovers] Steam's verify opened (steam://validate/1689620); the game was NOT started -- "
                          "launch again when Steam has finished")
                    try:
                        open_file(_leftovers.VERIFY_URL)
                    except Exception as e:
                        print(f"[leftovers] could not open Steam's verify: {e}")
                    return
                if _snd and not _sound_merge and _leftovers.sound_warning(BASE_DIR, _snd):
                    # Only a launcher without sound_merge.py still asks for Steam's verify (it would install banks
                    # that do not follow the mod's files).
                    if messagebox.askyesno(
                            "Game sound files changed",
                            f"{len(_snd)} of the game's sound files are not the ones Steam installed (for example "
                            f"{_snd[0]}): a sound or music mod changed them. With them the game can freeze or crash "
                            f"(a special move, an awakening), and the launcher has no copy of the originals to put "
                            f"back.\n\nYes: open Steam's \"Verify integrity of game files\" now and stop here -- "
                            f"launch again when Steam has finished.\nNo: launch anyway (you will not be asked again "
                            f"for these files).",
                            icon="warning"):
                        print("[leftovers] Steam's verify opened for the changed sound files; the game was NOT "
                              "started -- launch again when Steam has finished")
                        try:
                            open_file(_leftovers.VERIFY_URL)
                        except Exception as e:
                            print(f"[leftovers] could not open Steam's verify: {e}")
                        return
                    _leftovers.sound_ack(BASE_DIR, _snd)
                # The content pool, last: everything that decides a match is in place now -- the version, the loader,
                # the plugins, the Zangetsu, Rapid Reverse and developer-tools switches. Every version and every game
                # mode (FORMAT 2,
                # MATCHFIND 2026-11-06; a game mode other than DEFAULT is part of the code): the same build gives the
                # same code here -- a right-click Quick Launch runs this same launch() -- and in the public beta. Same
                # rule as the switches: if it cannot be made, the game is not started.
                if _content_pool:
                    try:
                        _cp_code, _cp_n, _cp_digest = _content_pool.write_code(
                            game_path, plan=_launch_plan(), version=gameVersion, mode=gameMode, built=_head_time())
                    except _content_pool.PoolError as e:
                        messagebox.showerror(
                            "Launch Error",
                            f"The online pool could not be made from the installed game:\n\n{e}\n\n"
                            "The game was NOT started. Fix the cause and launch again.")
                        return
                    print(f"[matchmaking] {gameVersion} ({gameMode}): content pool {_cp_code} ({_cp_n} files, "
                          f"{_cp_digest[:12]}) -- players meet exactly when they run the same build")
                else:
                    print("[matchmaking] launcher/content_pool.py is missing: this commit's own pool, "
                          "which no other launcher's player shares")
                if not launch_patched(game_path, boot_mode):
                    return
            elif _vplus is not None:
                # A vanilla plus version (launcher/vanilla_plus.py): the Steam game, proven above, plus its own loader
                # and plugins -- nothing of the master's, no switch, no game mode. Its pool is its own: the content
                # pool counts its loader and plugins, and its loader tags its lobbies outside every other pool.
                if gameMode != "DEFAULT":
                    print(f"[vanilla+] {gameVersion}: the game mode {gameMode} is not applied -- this version plays "
                          "the Steam game's rules")
                if not _content_pool:
                    messagebox.showerror(
                        "Launch Error",
                        f"'{gameVersion}' needs launcher/content_pool.py for its online pool, and this checkout is "
                        "missing it.\n\nThe game was NOT started.")
                    return
                try:
                    _vanilla_plus.install(BASE_DIR, game_path, _vplus)
                except _vanilla_plus.VanillaPlusError as e:
                    messagebox.showerror("Launch Error",
                                         f"'{gameVersion}' could not be installed:\n\n{e}\n\nThe game was NOT started.")
                    return
                try:
                    _cp_code, _cp_n, _cp_digest = _content_pool.write_code(
                        game_path, plan=_launch_plan(), version=gameVersion, mode="DEFAULT", built=_head_time())
                except _content_pool.PoolError as e:
                    messagebox.showerror(
                        "Launch Error",
                        f"The online pool could not be made from the installed game:\n\n{e}\n\n"
                        "The game was NOT started. Fix the cause and launch again.")
                    return
                print(f"[matchmaking] {gameVersion}: content pool {_cp_code} ({_cp_n} files, {_cp_digest[:12]}); "
                      f"the loader tags its lobbies {_cp_code + 1000000} -- only this build of this version meets it")
                if not launch_patched(game_path, boot_mode, game_mode="DEFAULT"):
                    return
            else:
                # the launcher's own files out of the game folder (its report goes to Json\), then the loader
                if _vanilla_revert:
                    _vanilla_revert.finalize(BASE_DIR, game_path)
                remove_matchmaking(game_path)
                if _QUICK is not None and _QUICK["cmd"] == "prepare":
                    print("[prepare] Vanilla is in place%s; Steam was NOT started (--prepare)"
                          % (", with the problem the revert showed (OK was chosen)" if _QUICK.get("problem") else ""))
                    _QUICK["done"] = True
                elif _mh:
                    _mh.append("installed")     # under maintenance: Steam opens at its end (launch_game())
                else:
                    try:
                        open_file("steam://rungameid/1689620")
                        if _QUICK is not None:
                            _QUICK["done"] = True
                    except:
                        print("Error launching game")
        except SystemExit as e:
            # setup_matchmaking refuses with SystemExit so that no "except
            # Exception" can swallow it. In this window that closed the whole
            # launcher, its reason printed to the hidden console: a player saw the
            # launcher vanish (a game mode whose old loader cannot host plugins, a
            # DLL locked by a running game...). Same refusal, now on screen, and
            # the launcher stays open.
            messagebox.showerror("Launch Error", str(e).strip() or "The game was NOT started.")
            return
        except Exception as e:
            messagebox.showerror(
                "Launch Error",
                f"Something went wrong while preparing '{gameVersion}' for launch:\n\n{e}\n\n"
                "The game was not launched. Please check that this version's folder "
                "under GameVersions has all required subfolders (Script, Motion, 00High, 01MIDDLE)."
            )
            return

        if not _mh:             # the install pass of a maintenance keeps the window for its countdown
            window.destroy()



    def readBalanceChanges():
        webbrowser.open("https://rebalance-of-souls.github.io/reBalanceOfSouls.github.io/")
        latestChangesPath = os.path.join(BASE_DIR,"BalanceChanges","LatestChanges.txt")

        try:
            open_file(latestChangesPath)
        except:
            print("Error opening LatestChanges.txt")

    def readCredits():
        creditsFile = os.path.join(BASE_DIR,"Credits","credits.txt")
        if os.path.exists(creditsFile):
            try:
                open_file(creditsFile)
            except:
                print("Error opening credits.txt")


        saveJson()

    def changeGamePath():
        flag = True
        firstTime = True
        while(flag):
            game_path = filedialog.askopenfilename(title="Select Bleach rebirth of souls",filetypes=[("Executable files", "*.exe")])
            if"BLEACH_Rebirth_of_Souls.exe" in game_path:
                flag = False
            elif firstTime:
                firstTime = False
                messagebox.showerror("Error","BLEACH_Rebirth_of_Souls.exe not found")


        parent_dir = os.path.dirname(game_path)
        game_path = str(parent_dir)
        config["GAME_PATH"] = game_path

        with open(config_path, "w") as f:
            json.dump(config, f)

        labelGamePath.config(text=f'📁  Current game path : {game_path}')


    def advancedMenu():
        advancedPage.tkraise()



    #box
    # Scrollable viewport: a screen shorter than the tallest page used to cut
    # the bottom buttons off with no way to reach them, so every page now lives
    # inside a canvas that scrolls vertically. The scrollbar only shows up when
    # the content really is taller than the window.
    viewport = Frame(window, bg=bgcolor)
    viewport.pack(expand=YES, fill=BOTH)
    scrollCanvas = Canvas(viewport, bg=bgcolor, highlightthickness=0, bd=0,
                          takefocus=0)
    scrollBar = ttk.Scrollbar(viewport, orient=VERTICAL,
                              command=scrollCanvas.yview,
                              style="Bros.Vertical.TScrollbar")
    scrollCanvas.configure(yscrollcommand=scrollBar.set)
    scrollCanvas.pack(side=LEFT, expand=YES, fill=BOTH)

    # padx/pady on the Frame itself, because the old pack() padding cannot be
    # used once the frame is an item inside the canvas.
    container = Frame(scrollCanvas, bg=bgcolor, padx=26, pady=5)
    _containerItem = scrollCanvas.create_window((0, 0), window=container, anchor="nw")

    def _sync_scroll(_event=None):
        # Keep the scrollregion and the item width in step with the canvas, and
        # add or drop the scrollbar depending on whether it is needed.
        scrollCanvas.itemconfigure(_containerItem, width=scrollCanvas.winfo_width())
        scrollCanvas.configure(scrollregion=scrollCanvas.bbox("all"))
        needed = container.winfo_reqheight() > scrollCanvas.winfo_height()
        mapped = bool(scrollBar.winfo_ismapped())
        if needed and not mapped:
            scrollBar.pack(side=RIGHT, fill=Y, before=scrollCanvas)
        elif mapped and not needed:
            scrollBar.pack_forget()
            scrollCanvas.yview_moveto(0)

    container.bind("<Configure>", _sync_scroll)
    scrollCanvas.bind("<Configure>", _sync_scroll)

    def _on_mousewheel(event):
        # bind_all, so the wheel works wherever the cursor is -- except over a
        # combobox, which uses the wheel to change its own value.
        if isinstance(event.widget, ttk.Combobox):
            return
        if not scrollBar.winfo_ismapped():
            return
        scrollCanvas.yview_scroll(int(-event.delta / 120), "units")

    window.bind_all("<MouseWheel>", _on_mousewheel)
    mainPage = Frame(container,bg=bgcolor)
    settingsPage = Frame(container,bg=bgcolor)
    advancedPage = Frame(container,bg=bgcolor)
    repairPage = Frame(container,bg=bgcolor)
    loadingPage = Frame(container,bg=bgcolor)
    reworksPage = Frame(container,bg=bgcolor)
    diagnosticsPage = Frame(container,bg=bgcolor)



    titleText = "Bleach Rebirth of Souls community patch launcher"
    subTitleText = "made by Nilsix :3"

    #headers (title / subtitle / fading divider), shared component per page
    build_header(mainPage, titleText, subTitleText).pack()
    build_header(settingsPage, titleText, subTitleText, icon="⚙").pack()
    build_header(advancedPage, titleText, subTitleText, icon="🔧").pack()
    build_header(repairPage, titleText, subTitleText, icon="🛠").pack()
    build_header(reworksPage, titleText, subTitleText, icon="✨").pack()
    build_header(diagnosticsPage, titleText, subTitleText, icon="📡").pack()

    labelWarning = Label(mainPage, text="Warning : Please only use the non vanilla features in room matches online, not in casual or ranked matches",font=FONT_SMALL,bg=bgcolor,fg=TEXT_MUTED)

    # Version panel. Each pill shows a short explanation on hover (reuses the
    # Tooltip class) so the numbers are not confusing.
    COMMUNITY_VERSION = "ReBalance of Souls V2.0"
    LATEST_STRING = get_latest() if _QUICK is None else "unknown"     # no window shown: no fetch for its pill
    _have_latest  = LATEST_STRING not in ("", "unknown")
    _up_to_date   = _have_latest and (VERSION_STRING == LATEST_STRING)

    _status1 = "(up to date)" if _up_to_date else ("(update available - relaunch)" if _have_latest else "(offline)")
    _status_dot = GREEN_OK if _up_to_date else (GOLD if _have_latest else GRAY_OFFLINE)

    statusOuter, statusInner = make_card(mainPage, "Status")
    statusRow1 = Frame(statusInner, bg=PANEL); statusRow1.pack(fill=X)
    make_pill(statusRow1, GOLD, f"Current : {VERSION_STRING}",
              "The patch build you have installed right now (short git commit hash).")\
        .pack(side=LEFT, padx=(0,8))
    make_pill(statusRow1, _status_dot, f"Latest : {LATEST_STRING}  {_status1}",
              "The newest patch build published on GitHub. If it differs from Current, an update is available - relaunch to get it.")\
        .pack(side=LEFT)
    statusOuter.pack(fill=X, pady=(0,5))

    brosVersion = StringVar()
    gameVersionsPath = os.path.join(BASE_DIR,"GameVersions")
    # Folders only: GameVersions also holds INHERITANCE.md, which is no version.
    gameVersionsList = sorted(f for f in os.listdir(gameVersionsPath)
                              if os.path.isdir(os.path.join(gameVersionsPath, f)))
    # COMMUNITY_VERSION is the build everyone plays (ReBalance of Souls V2.0
    # since the V1.5 rework, 2026-11; V1.7 from 2026-10-14, V1.3 on 2026-10-13,
    # the Community Patch before): list it first and preselect it, instead of
    # vanilla.
    if COMMUNITY_VERSION in gameVersionsList:
        gameVersionsList.remove(COMMUNITY_VERSION)
        gameVersionsList.insert(0, COMMUNITY_VERSION)

    # Themed combobox (dark, matches the rest of the UI) -- 'clam' is the only
    # built-in ttk theme that lets us restyle field/background colours on Windows.
    _style = ttk.Style()
    try:
        _style.theme_use("clam")
    except Exception:
        pass
    _style.configure("Bros.TCombobox",
                      fieldbackground=PANEL_SOFT, background=PANEL_SOFT,
                      foreground=labelcolor, arrowcolor=GOLD,
                      bordercolor=BORDER, lightcolor=PANEL_SOFT, darkcolor=PANEL_SOFT,
                      padding=8)
    _style.map("Bros.TCombobox",
               fieldbackground=[("readonly", PANEL_SOFT)],
               foreground=[("readonly", labelcolor)],
               background=[("readonly", PANEL_SOFT)])
    window.option_add("*TCombobox*Listbox.background", PANEL_SOFT)
    window.option_add("*TCombobox*Listbox.foreground", labelcolor)
    window.option_add("*TCombobox*Listbox.selectBackground", BTN_BG_HOVER)
    window.option_add("*TCombobox*Listbox.font", FONT_BODY)

    # Same dark treatment for the viewport scrollbar created above.
    _style.configure("Bros.Vertical.TScrollbar",
                      background=BTN_BG, troughcolor=PANEL, bordercolor=BORDER,
                      arrowcolor=GOLD, lightcolor=BTN_BG, darkcolor=BTN_BG,
                      relief="flat", width=12)
    _style.map("Bros.Vertical.TScrollbar",
               background=[("active", BTN_BG_HOVER), ("pressed", GOLD_DARK)],
               arrowcolor=[("active", GOLD_HOVER)])

    _launch_running = []

    def launch_with_screen(gameVersion, boot_mode=None, warm=False):
        """launch() on a thread, this window on its "Preparing the game" page meanwhile. On the window's own thread a
        launch held the window for minutes on a slow disk, and Windows greyed it out as "Not responding": it looked
        crashed (2026-11-19). launch()'s message boxes and dialogs still run on this thread -- tkinter hands another
        thread's Tk call to the thread in mainloop, and wait_variable keeps that loop turning. Closing the window, or a
        second click, waits for the launch: a half-copied install is a broken game. warm: the opening's pass
        (warm_install), which starts nothing."""
        if _launch_running:
            return
        _launch_running.append(1)
        done, failed = IntVar(window, 0), []

        def work():
            try:
                if warm:
                    warm_install(gameVersion)
                else:
                    launch_game(gameVersion, boot_mode)
            except BaseException as e:
                failed.append(e)
            finally:
                done.set(1)

        close = window.protocol("WM_DELETE_WINDOW")
        window.protocol("WM_DELETE_WINDOW", window.bell)
        loadingText.config(text=LOADING_TEXT[warm])
        loadingPage.tkraise()
        scrollCanvas.yview_moveto(0)        # a Quick Launch button is clicked scrolled down: the message is at the top
        loadingBar.start(12)
        threading.Thread(target=work, daemon=True).start()
        try:
            window.wait_variable(done)
        finally:
            try:
                loadingBar.stop()
                mainPage.tkraise()
                window.protocol("WM_DELETE_WINDOW", close)
            except TclError:
                pass                        # the game started: launch() closed the window (a traceback every start)
            _launch_running.clear()
        if failed:
            raise failed[0]

    def preLauncher():
        if brosVersionList.get() != "Choose a game version":
            launch_with_screen(brosVersionList.get())

    # Quick Launch: the normal Community Patch launch plus a boot shortcut, so
    # the game opens on the screen you actually wanted instead of the title
    # screen and the menu walk. The version is forced to COMMUNITY_VERSION
    # (as the standalone Quick Launch scripts did, until 2026-11-06): vanilla
    # goes through Steam with no loader, and with no loader there is nothing to
    # read BROS_BOOT_MODE, so the shortcut would silently do nothing.
    def quickLaunchTraining():
        launch_with_screen(COMMUNITY_VERSION, boot_mode="training")

    def quickLaunchRoomMatch():
        launch_with_screen(COMMUNITY_VERSION, boot_mode="roommatch")

    def performanceSettingsMenu():
        settingsPage.tkraise()

    def adjustAwakeningAuraSettings():
        if config["awakeningaura"] == "original":
            config["awakeningaura"] = "lowspec"
        else:
            config["awakeningaura"] = "original"
        _on = config["awakeningaura"] != "original"
        awakeningAuraButton.config(text=f'remove awakening aura : currently {"OFF" if config["awakeningaura"] == "original" else "ON"}')
        set_toggle_visual(awakeningAuraButton, _on)


    def adjustBreakerGrabSettings():
        if config["breaker_grab"] == "original":
            config["breaker_grab"] = "lowspec"
        else:
            config["breaker_grab"] = "original"

        _on = config["breaker_grab"] != "original"
        breakerGrabButton.config(
            text=f'remove breaker grab effect : currently {"OFF" if config["breaker_grab"] == "original" else "ON"}'
        )
        set_toggle_visual(breakerGrabButton, _on)


    def adjustHakugekiSettings():
        if config["hakugeki"] == "original":
            config["hakugeki"] = "lowspec"
        else:
            config["hakugeki"] = "original"
        _on = config["hakugeki"] != "original"
        hakugekiButton.config(text=f'remove hakugeki effect : currently {"OFF" if config["hakugeki"] == "original" else "ON"}')
        set_toggle_visual(hakugekiButton, _on)


    def adjustHitEffectSettings():
        if config["hit"] == "original":
            config["hit"] = "lowspec"
        else:
            config["hit"] = "original"
        _on = config["hit"] != "original"
        hitEffectButton.config(text=f'remove hit effect : currently {"OFF" if config["hit"] == "original" else "ON"}')
        set_toggle_visual(hitEffectButton, _on)


    def adjustReverseGlobeSettings():
        if config["reverse_globe"] == "original":
            config["reverse_globe"] = "lowspec"
        else:
            config["reverse_globe"] = "original"
        _on = config["reverse_globe"] != "original"
        reverseGlobeButton.config(text=f'remove reverse globe effect : currently {"OFF" if config["reverse_globe"] == "original" else "ON"}')
        set_toggle_visual(reverseGlobeButton, _on)


    def adjustSkillActivationSettings():
        if config["skill_activation"] == "original":
            config["skill_activation"] = "lowspec"
        else:
            config["skill_activation"] = "original"
        _on = config["skill_activation"] != "original"
        skillActivationButton.config(text=f'remove skill activation effect : currently {"OFF" if config["skill_activation"] == "original" else "ON"}')
        set_toggle_visual(skillActivationButton, _on)


    def backToMainMenu():
        saveJson()
        mainPage.tkraise()

    def unlockDangaiIchigo():
        # V1.5 delivery B.2 (2026-11-02): the unlock is set in the player's OWN save -- the one story flag Dangai
        # Ichigo's row names (nd_04_000_0350_end), nothing else, a backup first (launcher/save_unlock.py). It used to
        # copy ressources\savedata.bin -- another player's whole save: settings, items, ranked record and that
        # player's online identity -- over every save.
        if not _save_unlock:
            messagebox.showerror("Unlock Dangai Ichigo",
                                 "launcher/save_unlock.py is missing from this launcher: update it, then try again.")
            return
        if not messagebox.askyesno("Unlock Dangai Ichigo",
                                   "This unlocks Dangai Ichigo in your own save and changes nothing else.\n\n"
                                   "It sets the story flag that unlocks him (chapter 4, node 0350 finished), so that "
                                   "story node may show as cleared. A backup of your save is kept.\n\n"
                                   "Close the game first. Continue?"):
            return
        try:
            ok, text, _results = _save_unlock.unlock(BASE_DIR, game_path)
        except Exception as e:
            messagebox.showerror("Unlock Dangai Ichigo", "The unlock stopped: %r\n\nIf a save was changed, its backup "
                                 "is in %%LOCALAPPDATA%%\\BROS Launcher\\save_backups." % (e,))
            return
        (messagebox.showinfo if ok else messagebox.showerror)("Unlock Dangai Ichigo", text)

    def refreshLauncher():
        result = pulling_from_git()
        if result.returncode == 0:
            messagebox.showinfo("Refresh", "Launcher refreshed successfully!")
        else:
            messagebox.showerror("Refresh", f"Error refreshing launcher: {result.stderr}")

    def reworksMenu():
        reworksPage.tkraise()

    def byakuyaReworkToggle():
        global reworks
        if reworks[0] == "OFF":
            reworks[0] = "Byakuya"
        else:
            reworks[0] = "OFF"
        reworksByakuyaButton.config(text=f'Byakuya Rework : {"ON" if reworks[0] == "Byakuya" else "OFF"}')
        set_toggle_visual(reworksByakuyaButton, reworks[0] == "Byakuya")

    paddingYvalue = 2

    # ── Main page ────────────────────────────────────────────────────────────
    #labelWarning.pack(fill=X)
    labelGamePathOuter, labelGamePathInner = make_card(mainPage)
    labelGamePath = Label(labelGamePathInner, text=f'📁  Current game path : {game_path}',font=FONT_SMALL,bg=PANEL,fg=TEXT_MUTED, wraplength=430, justify="left")
    labelGamePath.pack(anchor="w")
    labelGamePathOuter.pack(fill=X, pady=(0,5))

    playOuter, playInner = make_card(mainPage, "Play")
    brosVersionList = ttk.Combobox(
        playInner,
        textvariable=brosVersion,
        values=gameVersionsList,
        state="readonly",
        font=FONT_COMBO,
        style="Bros.TCombobox"
    )
    brosVersionList.set(COMMUNITY_VERSION if COMMUNITY_VERSION in gameVersionsList
                        else "Choose a game version")
    launchButton = mkbutton(playInner, "Launch the game", preLauncher, kind="primary", icon="▶",
                             tooltip="Launch the game using the version selected in the dropdown above.")
    brosVersionList.pack(pady=(0,paddingYvalue+3), fill=X)
    launchButton.pack(fill=X)
    # The Room Match check (pass rt, 2026-11-09; Berg: "an actual tool that can tell why we're not finding one another
    # with a single look"): a window over this one, filled by online.dll while the game runs.
    if _room_check is not None:
        def openRoomCheck():
            try:
                _room_check.open_window(window, game_path, {
                    "bg": bgcolor, "panel": PANEL, "fg": labelcolor, "muted": TEXT_MUTED, "gold": GOLD,
                    "font": FONT_BODY, "small": FONT_SMALL, "title": ("Segoe UI", 13, "bold"), "mono": FONT_MONO})
            except Exception as e:
                messagebox.showerror("Room Match check", "The Room Match check could not open:\n\n%s" % e)
        roomCheckButton = mkbutton(playInner, "Room Match check", openRoomCheck, icon="🔍",
                                   tooltip="Who can find your rooms in Room Match right now, and why the others "
                                           "can't. Keep it open while the game runs.")
        roomCheckButton.pack(fill=X, pady=(paddingYvalue+2, 0))
    playOuter.pack(fill=X, pady=(0,5))

    # Diagnostics (2026-10-31, pass fd): everything that records and sends diagnostics has its own page, reached from
    # this card the way Game Modes is -- the tournament recorder (launcher/diagnostics.py: its switch moved there from
    # Game Modes, its Send button from this page) and the advanced recorder (launcher/fulldiag.py). This card keeps a
    # status line for each; a line turns gold while recordings wait to be sent.
    diagOuter, diagInner = make_card(mainPage, "Diagnostics")
    diagStatus = Label(diagInner, text="", font=FONT_SMALL, bg=PANEL, fg=TEXT_MUTED, wraplength=430,
                       justify="left")
    diagStatus.pack(anchor="w")
    fulldiagMainStatus = Label(diagInner, text="", font=FONT_SMALL, bg=PANEL, fg=TEXT_MUTED, wraplength=430,
                               justify="left")
    fulldiagMainStatus.pack(anchor="w", pady=(2,4))

    def diagnosticsMenu():
        refreshDiagnosticsStatus()
        refreshFulldiagStatus()
        diagnosticsPage.tkraise()

    diagnosticsPageButton = mkbutton(diagInner, "Diagnostics", diagnosticsMenu, icon="📡",
                                      tooltip="Tournament diagnostics and Advanced diagnostics: their switches, what "
                                              "they have recorded on this PC, and sending it to the patch developers.")
    diagnosticsPageButton.pack(fill=X)
    diagOuter.pack(fill=X, pady=(0,5))

    # ── Diagnostics page ─────────────────────────────────────────────────────
    _diagTheme = {"bg": bgcolor, "panel": PANEL, "fg": labelcolor, "muted": TEXT_MUTED, "gold": GOLD,
                  "button_bg": BTN_BG, "font": FONT_BODY, "small": FONT_SMALL}

    # Tournament diagnostics -- the player's own switch for the tournament recorder (launcher/diagnostics.py,
    # 2026-10-16), the status and Send. ON unless the player switched it OFF. OFF means nothing runs on this PC:
    # bros_diag.txt is removed at once and at every launch, so the loader never arms. Kept in Json/diagnostics.json.
    # Moved here from the Game Modes page and the main page on 2026-10-31; its behaviour is unchanged.
    tourOuter, tourInner = make_card(diagnosticsPage, "Tournament diagnostics")
    tourStatus = Label(tourInner, text="", font=FONT_SMALL, bg=PANEL, fg=TEXT_MUTED, wraplength=430, justify="left")
    tourStatus.pack(anchor="w", pady=(0,4))
    diagnosticsOn = _diagnostics.load_choice(BASE_DIR) if _diagnostics else False

    def refreshDiagnosticsStatus():
        if not _diagnostics:
            for w in (diagStatus, tourStatus):
                w.config(text="launcher/diagnostics.py is missing -- refresh the launcher.", fg=TEXT_MUTED)
            return
        text, waiting = _diagnostics.status_text(BASE_DIR, game_path)
        diagStatus.config(text="Tournament: " + text, fg=GOLD if waiting else TEXT_MUTED)
        tourStatus.config(text=text, fg=GOLD if waiting else TEXT_MUTED)
        set_toggle_visual(sendDiagnosticsButton, waiting)

    def actualiseDiagnosticsButton():
        diagnosticsButton.config(text=f'Tournament diagnostics : (Currently {"ON" if diagnosticsOn else "OFF"})')
        set_toggle_visual(diagnosticsButton, diagnosticsOn)

    def diagnosticsFunc():
        global diagnosticsOn
        if not _diagnostics:
            return
        try:
            print("[diagnostics] " + _diagnostics.set_choice(BASE_DIR, game_path, not diagnosticsOn))
        except _diagnostics.DiagnosticsError as e:
            messagebox.showerror("Tournament diagnostics", f"The switch could not be saved:\n\n{e}")
            return
        diagnosticsOn = not diagnosticsOn
        actualiseDiagnosticsButton()
        try:
            refreshDiagnosticsStatus()
        except Exception:
            pass

    def openSendDiagnostics():
        if not _diagnostics:
            messagebox.showerror("Send diagnostics",
                                 "launcher/diagnostics.py is missing. Refresh the launcher, then try again.")
            return
        _diagnostics.open_send_dialog(window, BASE_DIR, game_path, theme=_diagTheme, on_done=refreshDiagnosticsStatus)

    diagnosticsButton = mkbutton(
        tourInner,
        text=f'Tournament diagnostics : (Currently {"ON" if diagnosticsOn else "OFF"})',
        command=diagnosticsFunc,
        tooltip="ON (the default): while a tournament is switched on, the patch records how your online matches run -- freezes, network timing, your PC's load -- so the tournament lag can be found and fixed. Nothing leaves your PC until you click Send diagnostics below. OFF: nothing is recorded on this PC."
    )
    sendDiagnosticsButton = mkbutton(tourInner, "Send diagnostics", openSendDiagnostics, icon="📡",
                                      tooltip="After a tournament: send the recorded match diagnostics to the patch "
                                              "developers. You see what is sent, and nothing leaves your PC until "
                                              "you click Send.")
    diagnosticsButton.pack(pady=(0,paddingYvalue), fill=X)
    sendDiagnosticsButton.pack(fill=X)
    if not _diagnostics:
        diagnosticsButton.config(state=DISABLED)
    tourOuter.pack(fill=X, pady=(0,5))
    set_toggle_visual(diagnosticsButton, diagnosticsOn)

    # Advanced diagnostics -- the player's switch for fulldiag.dll (launcher/fulldiag.py, 2026-10-31), OFF unless
    # switched on; kept in Json/fulldiag.json and written into bros_fulldiag.txt now and at every launch. Its
    # recordings stay in <game>\BROS_FullDiag\ until the player sends or deletes them (nothing is deleted on its own).
    fdOuter, fdInner = make_card(diagnosticsPage, "Advanced diagnostics")
    Label(fdInner, text="Records everything a game session does, to find why the game plays differently on one PC: "
                        "every battle frame of both fighters and the commands each executed, your pad and keyboard, "
                        "the timing of every frame and where slow frames spent their time, this PC's load, and every "
                        "module in the game. Recordings stay on this PC (about half a GB per hour of battles) until you "
                        "send or delete them. Takes effect at the next game start.",
          font=FONT_SMALL, bg=PANEL, fg=labelcolor, wraplength=430, justify="left").pack(anchor="w", pady=(0,4))
    fulldiagStatus = Label(fdInner, text="", font=FONT_SMALL, bg=PANEL, fg=TEXT_MUTED, wraplength=430, justify="left")
    fulldiagStatus.pack(anchor="w", pady=(0,4))
    fulldiagOn = _fulldiag.load_choice(BASE_DIR) if _fulldiag else False

    def refreshFulldiagStatus():
        if not _fulldiag:
            for w in (fulldiagStatus, fulldiagMainStatus):
                w.config(text="launcher/fulldiag.py is missing -- refresh the launcher.", fg=TEXT_MUTED)
            return
        text, waiting = _fulldiag.status_text(BASE_DIR, game_path)
        fulldiagStatus.config(text=text, fg=GOLD if waiting else TEXT_MUTED)
        fulldiagMainStatus.config(text="Advanced: " + text, fg=GOLD if waiting else TEXT_MUTED)
        set_toggle_visual(fulldiagSendButton, waiting)

    def actualiseFulldiagButton():
        fulldiagButton.config(text=f'Advanced diagnostics : (Currently {"ON" if fulldiagOn else "OFF"})')
        set_toggle_visual(fulldiagButton, fulldiagOn)

    def fulldiagFunc():
        global fulldiagOn
        if not _fulldiag:
            return
        try:
            print("[fulldiag] " + _fulldiag.set_choice(BASE_DIR, game_path, not fulldiagOn))
        except _fulldiag.FulldiagError as e:
            messagebox.showerror("Advanced diagnostics", f"The switch could not be saved:\n\n{e}")
            return
        fulldiagOn = not fulldiagOn
        actualiseFulldiagButton()
        refreshFulldiagStatus()

    def openFulldiagSend():
        if not _fulldiag:
            return
        _fulldiag.open_send_dialog(window, BASE_DIR, game_path, theme=_diagTheme, on_done=refreshFulldiagStatus)

    def openFulldiagDelete():
        if not _fulldiag:
            return
        _fulldiag.open_delete_dialog(window, BASE_DIR, game_path, theme=_diagTheme, on_done=refreshFulldiagStatus)

    def openFulldiagFolder():
        if not _fulldiag:
            return
        try:
            _fulldiag.open_folder(game_path)
        except Exception as e:
            messagebox.showerror("Advanced diagnostics", f"The recordings folder could not be opened:\n\n{e}")

    fulldiagButton = mkbutton(
        fdInner,
        text=f'Advanced diagnostics : (Currently {"ON" if fulldiagOn else "OFF"})',
        command=fulldiagFunc,
        tooltip="ON: every game start records everything into BROS_FullDiag in the game folder, offline and online, until you switch it OFF. OFF (the default): nothing is recorded. Turn it on when you are asked to record a problem: it writes about half a GB per hour of battles and stops by itself when the disk has less than 2 GB free."
    )
    fulldiagSendButton = mkbutton(fdInner, "Send recordings...", openFulldiagSend, icon="📤",
                                   tooltip="Choose recordings and send them to the patch developers, or save them as "
                                           "zips on your Desktop. You see what is included first, and nothing leaves "
                                           "your PC until you click Send.")
    fulldiagDeleteButton = mkbutton(fdInner, "Delete older recordings...", openFulldiagDelete, icon="🗑",
                                     tooltip="Keep the newest recordings and delete the older ones, after a "
                                             "confirmation. Nothing is ever deleted on its own.")
    fulldiagFolderButton = mkbutton(fdInner, "Open the recordings folder", openFulldiagFolder, icon="📁",
                                     tooltip="Open BROS_FullDiag in the game folder.")
    fulldiagButton.pack(pady=(0,paddingYvalue), fill=X)
    fulldiagSendButton.pack(pady=paddingYvalue, fill=X)
    fulldiagDeleteButton.pack(pady=paddingYvalue, fill=X)
    fulldiagFolderButton.pack(pady=(paddingYvalue,0), fill=X)
    if not _fulldiag:
        for _b in (fulldiagButton, fulldiagSendButton, fulldiagDeleteButton, fulldiagFolderButton):
            _b.config(state=DISABLED)
    fdOuter.pack(fill=X, pady=(0,5))
    set_toggle_visual(fulldiagButton, fulldiagOn)

    diagnosticsMenuButton = mkbutton(diagnosticsPage, "Main Menu", backToMainMenu, kind="ghost", icon="←",
                                      tooltip="Return to the main menu.")
    diagnosticsMenuButton.pack(pady=paddingYvalue, fill=X)
    refreshDiagnosticsStatus()
    refreshFulldiagStatus()

    quickLaunchOuter, quickLaunchInner = make_card(mainPage, "Quick Launch")
    quickLaunchTrainingButton = mkbutton(quickLaunchInner, "Quick Launch Training Mode", quickLaunchTraining, icon="🥋",
                                          tooltip="Launch the Community Patch straight into the training character select, skipping the title screen.")
    quickLaunchRoomMatchButton = mkbutton(quickLaunchInner, "Quick Launch Room Match", quickLaunchRoomMatch, icon="🌐",
                                           tooltip="Launch the Community Patch straight into the online room match menu (create / find room), skipping the title screen.")
    quickLaunchTrainingButton.pack(pady=(0,paddingYvalue), fill=X)
    quickLaunchRoomMatchButton.pack(fill=X)
    quickLaunchOuter.pack(fill=X, pady=(0,5))

    customizeOuter, customizeInner = make_card(mainPage, "Customize")
    advancedButton = mkbutton(customizeInner, "Advanced settings", advancedMenu, icon="🔧",
                               tooltip="Zangetsu's manual Reawakening, the New netcode switch and the developer tools. "
                                       "The game modes are in Room Match now: the Create room dialog's Game Mode row.")
    lowSpecButton = mkbutton(customizeInner, "FPS Booster settings", performanceSettingsMenu, icon="⚡",
                              tooltip="Toggle per-effect FPS booster settings to improve performance on lower-end PCs.")
    unlockDangaiIchigoButton = mkbutton(customizeInner, "Unlock Dangai Ichigo", unlockDangaiIchigo, icon="🔓",
                                         tooltip="Unlocks Dangai Ichigo in your own save (one flag, with a backup)")
    advancedButton.pack(pady=paddingYvalue, fill=X)
    lowSpecButton.pack(pady=paddingYvalue, fill=X)
    unlockDangaiIchigoButton.pack(pady=(paddingYvalue,0), fill=X)
    customizeOuter.pack(fill=X, pady=(0,5))

    toolsOuter, toolsInner = make_card(mainPage, "Tools & Community")
    changeGamePathButton = mkbutton(toolsInner, "Change your game path", changeGamePath, icon="🗂",
                                     tooltip="Change the folder path where your copy of Bleach Rebirth of Souls is installed.")
    readBalanceChangesButton = mkbutton(toolsInner, "Read balance changes", readBalanceChanges, icon="📜",
                                         tooltip="Open the latest balance-changes notes")
    repairButton = mkbutton(toolsInner, "Repair files", repair, icon="🛠",
                             tooltip="Restore your game files from a clean backup copy of the game.")
    refreshLauncherButton = mkbutton(toolsInner, "Refresh launcher", refreshLauncher, icon="🔄",
                                      tooltip="Refresh the launcher to get the latest updates.")
    CreditsButton = mkbutton(toolsInner, "Credits", readCredits, icon="🎬",
                              tooltip="View the credits for the mods used in this patch.")
    joinDiscordButton = mkbutton(toolsInner, "Join our discord :) ", lambda: webbrowser.open("https://discord.gg/fSbsZE3qSZ"), icon="💬",
                                  tooltip="Open the community Discord server in your browser.")
    reworksPageButton = mkbutton(toolsInner, "Reworks", reworksMenu, icon="✨")
    changeGamePathButton.pack(pady=paddingYvalue, fill=X)
    readBalanceChangesButton.pack(pady=paddingYvalue, fill=X)
    repairButton.pack(pady=paddingYvalue, fill=X)
    refreshLauncherButton.pack(pady=paddingYvalue, fill=X)
    #reworksPageButton.pack(pady=paddingYvalue,fill=X)
    CreditsButton.pack(pady=paddingYvalue, fill=X)
    joinDiscordButton.pack(pady=(paddingYvalue,0), fill=X)
    toolsOuter.pack(fill=X)


    # ── Settings page (FPS booster effect toggles) ──────────────────────────
    settingsOuter, settingsInner = make_card(settingsPage, "FPS Booster effects")

    awakeningAuraButton = mkbutton(
        settingsInner,
        text=f'remove awakening aura : currently {"OFF" if config["awakeningaura"] == "original" else "ON"}',
        command=adjustAwakeningAuraSettings,
        tooltip="Toggle the awakening aura visual effect on/off to save GPU performance."
    )
    awakeningAuraButton.pack(pady=paddingYvalue, fill=X)
    set_toggle_visual(awakeningAuraButton, config["awakeningaura"] != "original")


    breakerGrabButton = mkbutton(
        settingsInner,
        text=f'remove breaker grab effect : currently {"OFF" if config["breaker_grab"] == "original" else "ON"}',
        command=adjustBreakerGrabSettings,
        tooltip="Toggle the breaker grab screen effect on/off."
    )
    breakerGrabButton.pack(pady=paddingYvalue, fill=X)
    set_toggle_visual(breakerGrabButton, config["breaker_grab"] != "original")


    hakugekiButton = mkbutton(
        settingsInner,
        text=f'remove hakugeki effect : currently {"OFF" if config["hakugeki"] == "original" else "ON"}',
        command=adjustHakugekiSettings,
        tooltip="Toggle the Hakugeki flash effect on/off."
    )
    hakugekiButton.pack(pady=paddingYvalue, fill=X)
    set_toggle_visual(hakugekiButton, config["hakugeki"] != "original")


    hitEffectButton = mkbutton(
        settingsInner,
        text=f'remove hit effect : currently {"OFF" if config["hit"] == "original" else "ON"}',
        command=adjustHitEffectSettings,
        tooltip="Toggle hit impact visual effects on/off."
    )
    hitEffectButton.pack(pady=paddingYvalue, fill=X)
    set_toggle_visual(hitEffectButton, config["hit"] != "original")


    reverseGlobeButton = mkbutton(
        settingsInner,
        text=f'remove reverse globe effect : currently {"OFF" if config["reverse_globe"] == "original" else "ON"}',
        command=adjustReverseGlobeSettings,
        tooltip="Toggle the reverse globe screen effect on/off."
    )
    reverseGlobeButton.pack(pady=paddingYvalue, fill=X)
    set_toggle_visual(reverseGlobeButton, config["reverse_globe"] != "original")


    skillActivationButton = mkbutton(
        settingsInner,
        text=f'remove skill activation effect : currently {"OFF" if config["skill_activation"] == "original" else "ON"}',
        command=adjustSkillActivationSettings,
        tooltip="Toggle the skill activation flash effect on/off."
    )
    skillActivationButton.pack(pady=paddingYvalue, fill=X)
    set_toggle_visual(skillActivationButton, config["skill_activation"] != "original")

    settingsOuter.pack(fill=X, pady=(0,5))

    mainMenuButton = mkbutton(settingsPage, "Main Menu", backToMainMenu, kind="ghost", icon="←",
                               tooltip="Return to the main menu.")
    mainMenuButton.pack(pady=paddingYvalue, fill=X)

    # Advanced settings page (the Game Modes page until 2026-11-02, when its game
    # mode toggles left the launcher for the Create room's Game Mode row).
    # Zangetsu -- manual Reawakening (launcher/zangetsu_mode.py, Berg 2026-10-18):
    # a switch of the dev build, ON unless switched off. Kept in
    # Json/zangetsu.json (not config.json, for the netcode switch's reason) and
    # written into bros_zangetsu.txt now and at every launch.
    zangetsuOuter, zangetsuInner = make_card(advancedPage, "Zangetsu")
    zangetsuManualOn = _zangetsu_mode.load_choice(BASE_DIR) if _zangetsu_mode else True

    def actualiseZangetsuButton():
        zangetsuButton.config(text=f'Manual Reawakening : (Currently {"ON" if zangetsuManualOn else "OFF"})')
        set_toggle_visual(zangetsuButton, zangetsuManualOn)

    def zangetsuFunc():
        global zangetsuManualOn
        if not _zangetsu_mode:
            return
        try:
            _zangetsu_mode.save_choice(BASE_DIR, not zangetsuManualOn)
        except _zangetsu_mode.ZangetsuModeError as e:
            messagebox.showerror("Zangetsu", f"The switch could not be saved:\n\n{e}")
            return
        zangetsuManualOn = not zangetsuManualOn
        actualiseZangetsuButton()
        # Written into the game folder now, so a game started from the exe
        # follows it too. Every launch writes it again.
        try:
            print("[zangetsu] " + _zangetsu_mode.apply(game_path, zangetsuManualOn))
        except _zangetsu_mode.ZangetsuModeError as e:
            messagebox.showwarning(
                "Zangetsu",
                f"The switch is saved, but bros_zangetsu.txt could not be written now:\n\n{e}\n\n"
                "The next launch writes it again, and does not start the game if it still cannot.")

    zangetsuButton = mkbutton(
        zangetsuInner,
        text=f'Manual Reawakening : (Currently {"ON" if zangetsuManualOn else "OFF"})',
        command=zangetsuFunc,
        tooltip="ON (the default): Zangetsu's 4th moon stack fills his Awakened fighting-spirit bar and its sublimation bar (training mode's Kikon channel), and he enters his Reawakening himself, with the full bar, when he wants to. OFF: the 4th moon stack starts the Reawakening by itself, as before. Takes effect at the next game start. Online, both players need the same setting."
    )
    zangetsuButton.pack(pady=(paddingYvalue,0), fill=X)
    if not _zangetsu_mode:
        zangetsuButton.config(state=DISABLED)
    zangetsuOuter.pack(fill=X, pady=(0,5))
    set_toggle_visual(zangetsuButton, zangetsuManualOn)

    # Rapid Reverse (launcher/rapidreverse_mode.py, Berg 2026-11-13: "Add a new option in the launcher that would
    # disable Rapid Reverse and its UI and everything about it as if it was never added without breaking anything").
    # ON unless switched off. Kept in Json/rapidreverse.json and applied to the game folder now and at every launch:
    # OFF writes ReBalanceOfSouls\rapidreverse.txt, ON removes it.
    rapidReverseOuter, rapidReverseInner = make_card(advancedPage, "Rapid Reverse")
    rapidReverseOn = _rapidreverse_mode.load_choice(BASE_DIR) if _rapidreverse_mode else True

    def actualiseRapidReverseButton():
        rapidReverseButton.config(text=f'Rapid Reverse : (Currently {"ON" if rapidReverseOn else "OFF"})')
        set_toggle_visual(rapidReverseButton, rapidReverseOn)

    def rapidReverseFunc():
        global rapidReverseOn
        if not _rapidreverse_mode:
            return
        try:
            _rapidreverse_mode.save_choice(BASE_DIR, not rapidReverseOn)
        except _rapidreverse_mode.RapidReverseModeError as e:
            messagebox.showerror("Rapid Reverse", f"The switch could not be saved:\n\n{e}")
            return
        rapidReverseOn = not rapidReverseOn
        actualiseRapidReverseButton()
        # Applied to the game folder now, so a game started from the exe follows it too. Every launch applies it
        # again.
        try:
            print("[rapidreverse] " + _rapidreverse_mode.apply(game_path, rapidReverseOn))
        except _rapidreverse_mode.RapidReverseModeError as e:
            messagebox.showwarning(
                "Rapid Reverse",
                f"The switch is saved, but the game folder could not follow it now:\n\n{e}\n\n"
                "The next launch applies it again, and does not start the game if it still cannot.")

    rapidReverseButton = mkbutton(
        rapidReverseInner,
        text=f'Rapid Reverse : (Currently {"ON" if rapidReverseOn else "OFF"})',
        command=rapidReverseFunc,
        tooltip="ON (the default): Rapid Reverse as it is -- two of Light, Heavy and Signature together (or its button) once a move has hit, for 1.5 Reverse bars; its Input Settings row, the 1.5-bar marker, the gauge's look, the pop and the sound. OFF: Rapid Reverse is gone, as if it had never been added; Diminishing Returns stays. Online you only meet players with the same setting. It takes effect at the next game start."
    )
    rapidReverseButton.pack(pady=(paddingYvalue,0), fill=X)
    if not _rapidreverse_mode:
        rapidReverseButton.config(state=DISABLED)
    if not _rapidreverse_mode or _rapidreverse_mode.IN_GAME:   # hidden while Rapid Reverse is out of the release (2026-11-17)
        rapidReverseOuter.pack(fill=X, pady=(0,5))
    set_toggle_visual(rapidReverseButton, rapidReverseOn)

    # The Komamura rework (launcher/komamura_rework.py, pass kr 2026-11-14; Berg: "removing the giant form/current evo
    # from komamura, changing his base form's moveset and everything to that of his rev form, and his evo form gets the
    # base form moveset and everything ... Turn this new rework off by default in the launcher's advanced settings, so
    # it can be toggled on"). OFF unless switched on; kept in Json/komamura_rework.json. A click only keeps the choice:
    # his files, his tables and pl023rework.dll's switch change together at the next launch, never apart.
    komamuraOuter, komamuraInner = make_card(advancedPage, "Komamura rework")
    komamuraOn = _komamura_rework.load_choice(BASE_DIR) if _komamura_rework else False

    def actualiseKomamuraButton():
        komamuraButton.config(text=f'Komamura rework : (Currently {"ON" if komamuraOn else "OFF"})')
        set_toggle_visual(komamuraButton, komamuraOn)

    def komamuraFunc():
        global komamuraOn
        if not _komamura_rework:
            return
        try:
            _komamura_rework.save_choice(BASE_DIR, not komamuraOn)
        except _komamura_rework.KomamuraReworkError as e:
            messagebox.showerror("Komamura rework", f"The switch could not be saved:\n\n{e}")
            return
        komamuraOn = not komamuraOn
        actualiseKomamuraButton()
        print("[komamura] the switch is saved %s: it takes effect at the next launch"
              % ("ON" if komamuraOn else "OFF"))

    komamuraButton = mkbutton(
        komamuraInner,
        text=f'Komamura rework : (Currently {"ON" if komamuraOn else "OFF"})',
        command=komamuraFunc,
        tooltip="OFF (the default): Komamura as this version ships him. ON: Komamura has two forms -- his base "
                "form is the vanilla game's Reawakened Komamura (its moves, combos, stats and CPU) and his Awakened "
                "form is the vanilla game's base Komamura, with the giant as a stand behind him that copies his "
                "moves (it vanishes while he is hit, thrown or knocked down). He awakens with the vanilla cutscene, "
                "has spirit drive like the characters without a Reawakened form, and his sublimation kikon is the "
                "vanilla giant's. Base 10000 HP, Awakened 11500. Online you only meet players with the same "
                "setting. It takes effect at the next launch from this launcher."
    )
    komamuraButton.pack(pady=(paddingYvalue,0), fill=X)
    if not _komamura_rework:
        komamuraButton.config(state=DISABLED)
    komamuraOuter.pack(fill=X, pady=(0,5))
    set_toggle_visual(komamuraButton, komamuraOn)

    # (The "Starrk rework (beta)" card stood here, 2026-11-15 .. 2026-11-22. The switch is retired: the rework is the
    # reborn Coyote Starrk (Primera), 54, in the version for everyone -- launcher/starrk_rework.py.)

    # Netcode -- the New netcode switch (launcher/netcode_mode.py). Kept in
    # Json/netcode.json, not config.json: a new config key would reset every
    # player's settings (the template check near the top of this file).
    netcodeOuter, netcodeInner = make_card(advancedPage, "Netcode")
    netcodeOn = _netcode_mode.load_choice(BASE_DIR) if _netcode_mode else False

    def actualiseNetcodeButton():
        netcodeButton.config(text=f'New netcode : (Currently {"ON" if netcodeOn else "OFF"})')
        set_toggle_visual(netcodeButton, netcodeOn)

    def netcodeFunc():
        global netcodeOn
        if not _netcode_mode:
            return
        try:
            _netcode_mode.save_choice(BASE_DIR, not netcodeOn)
        except _netcode_mode.NetcodeError as e:
            messagebox.showerror("New netcode", f"The switch could not be saved:\n\n{e}")
            return
        netcodeOn = not netcodeOn
        actualiseNetcodeButton()
        # Written into the game folder now, for the version installed there, so a
        # game started from the exe or from BalanceLaunch runs it too. Every launch
        # writes it again for the version it installs.
        try:
            installed = read_patch_state().get("version")
            shipped = (_netcode_mode.shipped_file(BASE_DIR, version_chain(installed))
                       if netcodeOn and installed else None)
            print("[netcode] " + _netcode_mode.apply(game_path, netcodeOn, shipped, BASE_DIR))
        except _netcode_mode.NetcodeError as e:
            messagebox.showwarning(
                "New netcode",
                f"The switch is saved, but bros_net.txt could not be written now:\n\n{e}\n\n"
                "The next launch writes it again, and does not start the game if it still cannot.")

    netcodeButton = mkbutton(
        netcodeInner,
        text=f'New netcode : (Currently {"ON" if netcodeOn else "OFF"})',
        command=netcodeFunc,
        tooltip="ON: the Rebalance netcode -- a lock around the send queues, the network thread every 1 ms and 8 inputs per packet, plus the test settings of the version you launch (V1.2's bros_net.txt). OFF: the game's own netcode. Takes effect at the next game start. When testing, both players should use the same setting; a match between ON and OFF is safe."
    )
    netcodeButton.pack(pady=(paddingYvalue,0), fill=X)
    if not _netcode_mode:
        netcodeButton.config(state=DISABLED)
    netcodeOuter.pack(fill=X, pady=(0,5))
    set_toggle_visual(netcodeButton, netcodeOn)

    # (The Tournament diagnostics switch was here until 2026-10-31; it is on the Diagnostics page now.)

    # Developer tools -- BRoS Studio and F9 (launcher/devtools_mode.py). Both OFF
    # unless switched on; kept in Json/devtools.json (not config.json, for the
    # netcode switch's reason) and written into bros_tools.txt now and at every
    # launch.
    devtoolsOuter, devtoolsInner = make_card(advancedPage, "Developer tools")
    devStudioOn, devF9On = _devtools_mode.load_choice(BASE_DIR) if _devtools_mode else (False, False)

    def actualiseDevtoolsButtons():
        devStudioButton.config(text=f'BRoS Studio : (Currently {"ON" if devStudioOn else "OFF"})')
        set_toggle_visual(devStudioButton, devStudioOn)
        devF9Button.config(text=f'F9 hides the HUD : (Currently {"ON" if devF9On else "OFF"})')
        set_toggle_visual(devF9Button, devF9On)

    def devtoolsFunc(which):
        global devStudioOn, devF9On
        if not _devtools_mode:
            return
        studio = (not devStudioOn) if which == "studio" else devStudioOn
        f9 = (not devF9On) if which == "f9" else devF9On
        try:
            _devtools_mode.save_choice(BASE_DIR, studio, f9)
        except _devtools_mode.DevtoolsError as e:
            messagebox.showerror("Developer tools", f"The switch could not be saved:\n\n{e}")
            return
        devStudioOn, devF9On = studio, f9
        actualiseDevtoolsButtons()
        # Written into the game folder now, so a game started from the exe
        # follows it too. Every launch writes it again.
        try:
            print("[devtools] " + _devtools_mode.apply(game_path, studio, f9))
        except _devtools_mode.DevtoolsError as e:
            messagebox.showwarning(
                "Developer tools",
                f"The switch is saved, but bros_tools.txt could not be written now:\n\n{e}\n\n"
                "The next launch writes it again, and does not start the game if it still cannot.")

    devStudioButton = mkbutton(
        devtoolsInner,
        text=f'BRoS Studio : (Currently {"ON" if devStudioOn else "OFF"})',
        command=lambda: devtoolsFunc("studio"),
        tooltip="ON: studio.dll arms at the next game start -- its hooks, its hotkeys and studio.txt, for BRoS Studio (the cutscene tool). OFF: studio.dll writes one line to patch_ranked.log and does nothing else. A development tool; leave it OFF to play."
    )
    devF9Button = mkbutton(
        devtoolsInner,
        text=f'F9 hides the HUD : (Currently {"ON" if devF9On else "OFF"})',
        command=lambda: devtoolsFunc("f9"),
        tooltip="ON: F9 hides and shows the HUD in battle (for screenshots and footage). OFF: F9 does nothing. Works with BRoS Studio OFF. Takes effect at the next game start."
    )
    devStudioButton.pack(pady=(paddingYvalue,0), fill=X)
    devF9Button.pack(pady=(paddingYvalue,0), fill=X)
    if not _devtools_mode:
        devStudioButton.config(state=DISABLED)
        devF9Button.config(state=DISABLED)
    devtoolsOuter.pack(fill=X, pady=(0,5))
    set_toggle_visual(devStudioButton, devStudioOn)
    set_toggle_visual(devF9Button, devF9On)

    # Quick Launch -- the right-click menu on this launcher's file (launcher/quick_menu.py, MATCHFIND 2026-11-06):
    # Quick Launch > a version > Title screen / Room Match / Training (Vanilla: the title screen). ON unless switched
    # off (Berg's choice); kept in Json/quick_menu.json (not config.json, for the netcode switch's reason). Put in place
    # or taken away at once, and brought up to date at every start of this window.
    def _quick_menu_apply():
        """The right-click menu as the switch says: brought up to date (ON) or removed (OFF). A line for the log."""
        if not _quick_menu:
            return "[quick menu] launcher/quick_menu.py is missing"
        me = os.path.abspath(__file__)
        if _quick_menu.load_choice(BASE_DIR):
            return _quick_menu.install(me, gameVersionsList, first=COMMUNITY_VERSION, label="Quick Launch",
                                       app_name="Bleach Community Patch",
                                       icon=os.path.join(BASE_DIR, "ressources", "pimplin.ico"))
        return _quick_menu.remove(me)

    def _run_quick():
        """--quick / --prepare / --quick-menu (launcher/quick_menu.py). This window is never shown; what goes wrong is
        said in a dialog, as from the window."""
        global gameMode
        q = _QUICK
        if q["cmd"] == "menu":
            me = os.path.abspath(__file__)
            if q["action"] == "status":
                line = _quick_menu.status(me)
            elif q["action"] == "remove":
                line = _quick_menu.remove(me)
            else:
                line = _quick_menu.install(me, gameVersionsList, first=COMMUNITY_VERSION, label="Quick Launch",
                                           app_name="Bleach Community Patch",
                                           icon=os.path.join(BASE_DIR, "ressources", "pimplin.ico"),
                                           flat=q["flat"], match=q["match"])
            print(line)
            q["done"] = not any(w in line for w in ("not made", "not removed", "unknown"))
            messagebox.showinfo("Quick Launch", line.replace("[quick menu] ", "Right-click menu: "))
            return
        v = q["version"]
        if v not in gameVersionsList:
            messagebox.showerror("Quick Launch", f"'{v}' is not a version of this launcher (there is no "
                                 f"GameVersions/{v}). Nothing was started.\n\nThe right-click menu is brought up "
                                 "to date whenever the launcher's window opens.")
            return
        if q["cmd"] == "prepare":
            mode = q["mode"] or "DEFAULT"
            # a mode of its own folder, or one the loader arms at run time (setup_matchmaking's / launch_patched's list)
            if mode != "DEFAULT" and not os.path.isdir(os.path.join(BASE_DIR, "GameModes", mode)) \
                    and mode not in ("4-5", "UniversalStepCancel", "StrikeBackLastHit", "RapideReverse"):
                messagebox.showerror("Prepare", f"There is no GameModes/{mode}. Nothing was installed.")
                return
            gameMode = mode
            launch_game(v)
            return
        boot = q["boot"]
        if v == "Bleach Rebirth of Souls" and boot != "title":
            messagebox.showerror("Quick Launch", "Vanilla is the game as Steam ships it: with no loader there is "
                                 "nothing to open Room Match or Training. Nothing was started.")
            return
        gameMode = _quick_menu.quick_game_mode(BASE_DIR, boot) or "DEFAULT"
        if boot == "guides":   # replay.dll: Title > Tutorial > GUIDES by keys (as Quick Boot Guides.bat)
            os.environ["BROS_QUICKBOOT"] = "guides"
        launch_game(v, boot_mode=_quick_menu.BOOT_ENV[boot])

    quickMenuOuter, quickMenuInner = make_card(advancedPage, "Quick Launch")
    quickMenuOn = _quick_menu.load_choice(BASE_DIR) if _quick_menu else False

    def actualiseQuickMenuButton():
        quickMenuButton.config(text=f'Right-click Quick Launch menu : (Currently {"ON" if quickMenuOn else "OFF"})')
        set_toggle_visual(quickMenuButton, quickMenuOn)

    def quickMenuFunc():
        global quickMenuOn
        if not _quick_menu:
            return
        try:
            _quick_menu.save_choice(BASE_DIR, not quickMenuOn)
        except _quick_menu.QuickError as e:
            messagebox.showerror("Quick Launch", f"The switch could not be saved:\n\n{e}")
            return
        quickMenuOn = not quickMenuOn
        actualiseQuickMenuButton()
        line = _quick_menu_apply()
        print(line)
        if any(w in line for w in ("not made", "not removed")):
            messagebox.showwarning("Quick Launch", line.replace("[quick menu] ", "The right-click menu was "))

    quickMenuButton = mkbutton(
        quickMenuInner,
        text=f'Right-click Quick Launch menu : (Currently {"ON" if quickMenuOn else "OFF"})',
        command=quickMenuFunc,
        tooltip="ON: right-click this launcher's file > Quick Launch > a version > Title screen, Room Match or Training starts the game on that screen at once -- updated and installed exactly like the Launch button, with default rules. On Windows 11 the menu is under 'Show more options'. OFF: the menu is removed."
    )
    quickMenuButton.pack(pady=(paddingYvalue,0), fill=X)
    if not _quick_menu:
        quickMenuButton.config(state=DISABLED)
    quickMenuOuter.pack(fill=X, pady=(0,5))
    set_toggle_visual(quickMenuButton, quickMenuOn)

    advancedMenuButton = mkbutton(advancedPage, "Main Menu", backToMainMenu, kind="ghost", icon="←",
                                   tooltip="Return to the main menu.")
    advancedMenuButton.pack(pady=paddingYvalue, fill=X)

    #repairPage
    labelRepairText = Label(
        repairPage,
        text="🛠  Repairing files. Please wait",
        font=("Segoe UI", 22, "bold"),
        bg=bgcolor,
        fg=ACCENT
    )
    labelRepairText.pack(pady=(30,10))

    labelSubtitleRepairText = Label(
        repairPage,
        text="Do not close this window, this may take a moment.",
        font=FONT_BODY,
        bg=bgcolor,
        fg=TEXT_MUTED
    )
    labelSubtitleRepairText.pack()

    #loadingPage (launch_with_screen): the launch copies the game files, the bar keeps moving
    Label(loadingPage, text="⏳  Preparing the game", font=("Segoe UI", 22, "bold"),
          bg=bgcolor, fg=ACCENT).pack(pady=(30,10))
    LOADING_TEXT = {False: "The launcher is copying the game files. This can take a few minutes after an update. "
                           "It has not crashed: the game starts by itself. Do not close this window.",
                    True: "The launcher is installing the game files now, so that Launch starts the game at once. "
                          "This can take a few minutes after an update. It has not crashed. Do not close this window."}
    loadingText = Label(loadingPage, text=LOADING_TEXT[False], font=FONT_BODY, bg=bgcolor, fg=TEXT_MUTED,
                        justify="center", wraplength=400)
    loadingText.pack()
    _style.configure("Bros.Horizontal.TProgressbar", background=GOLD, troughcolor=PANEL, bordercolor=BORDER,
                     lightcolor=GOLD, darkcolor=GOLD)
    loadingBar = ttk.Progressbar(loadingPage, mode="indeterminate", style="Bros.Horizontal.TProgressbar")
    loadingBar.pack(fill=X, padx=40, pady=20)

    reworksOuter, reworksInner = make_card(reworksPage, "Reworks")
    reworksByakuyaButton = mkbutton(reworksInner, "Byakuya Rework", byakuyaReworkToggle)
    reworksByakuyaButton.pack(pady=paddingYvalue, fill=X)
    reworksOuter.pack(fill=X, pady=(0,5))
    reworksBackToMenuButton = mkbutton(reworksPage, "Back to menu", lambda: mainPage.tkraise(), kind="ghost", icon="←")
    reworksBackToMenuButton.pack(pady=paddingYvalue, fill=X)

    # Let the stacked pages fill the whole container (so buttons stretch to width).
    container.grid_rowconfigure(0, weight=1)
    container.grid_columnconfigure(0, weight=1)
    for page in(mainPage,settingsPage,advancedPage,repairPage,loadingPage,reworksPage,diagnosticsPage):
        page.grid(row=0,column=0,sticky="nsew")
    mainPage.tkraise()

    def fit_window():
        # Size the window to exactly fit its content (the tallest stacked page,
        # since they all share row0/col0), capped to the screen, then centre it.
        # Crisp at native DPI + never clipped, whatever the monitor/scaling.
        # Measured on the container, not the window: the canvas around it has no
        # size of its own, so asking the window would give back 1x1.
        window.update_idletasks()
        sw = window.winfo_screenwidth(); sh = window.winfo_screenheight()
        cw = container.winfo_reqwidth(); ch = container.winfo_reqheight()
        h = min(ch, sh - 80)
        # A capped height means the scrollbar will show, so reserve its width.
        w = min(max(cw + (14 if h < ch else 0), 500), sw - 40)
        x = max(0, (sw - w) // 2); y = max(0, (sh - h) // 2 - 20)
        window.geometry(f"{w}x{h}+{x}+{y}")
        window.update_idletasks()
        _sync_scroll()
    if _QUICK is not None:
        # A Quick Launch, --prepare or --quick-menu: inside this window's event loop (the update window, the dialogs
        # and the install check need it), the window itself never shown. Exit 0 when it did what was asked.
        def _quick_start():
            # What this start tells the player is counted -- an error or a warning, a question answered no -- so that
            # a Quick Launch which ends with nothing started and nothing said (a start that failed with only a line in
            # its log) still says so, with the end of its log: the Quick Launch scripts' failure screen.
            told = []

            def _counted(f, declined_only):
                def g(*a, **k):
                    r = f(*a, **k)
                    if not declined_only or not r:
                        told.append(1)
                    return r
                return g
            for _n, _d in (("showerror", False), ("showwarning", False), ("askokcancel", True), ("askyesno", True)):
                setattr(messagebox, _n, _counted(getattr(messagebox, _n), _d))
            try:
                _run_quick()
            except Exception as e:
                messagebox.showerror("Quick Launch", f"Something went wrong:\n\n{e}\n\nNothing more was done.")
            finally:
                try:
                    if _QUICK["cmd"] == "quick" and not _QUICK.get("done") and not told:
                        messagebox.showerror("Quick Launch", _update_window.failure_text("The game was not started.")
                                             if _update_window else "The game was not started.")
                except Exception:
                    pass
                try:
                    window.destroy()
                except Exception:
                    pass
        window.after(0, _quick_start)
        window.mainloop()
        sys.exit(0 if _QUICK.get("done") else 1)
    fit_window()
    window.deiconify()
    # Under maintenance the selected version is installed at once, while the maintenance runs, and the game opens at
    # its end (launch_game()).
    if _maint_at_start and brosVersionList.get() in gameVersionsList:
        window.after(300, lambda: launch_with_screen(brosVersionList.get()))
    # Otherwise the opening installs it (warm_install): the Launch click finds everything in place.
    elif _warm_wanted(brosVersionList.get()):
        window.after(300, lambda: launch_with_screen(brosVersionList.get(), warm=True))
    # The right-click Quick Launch menu, brought up to date (or removed) on a thread: a registry or a file manager's
    # folder must never hold the window.
    import threading as _threading
    _threading.Thread(target=lambda: print(_quick_menu_apply()), daemon=True).start()
    window.mainloop()
except Exception as e:
    try :
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 1)
    except:
        pass
    print(f'Error : {e}')
    input("Please ping the error to Nilsix")
