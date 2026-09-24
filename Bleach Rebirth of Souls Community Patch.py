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
import webbrowser
from pathlib import Path
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
    print("Checking for updates, please wait")

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

    def pulling_from_git():
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
        return subprocess.run(["git", "-C", BASE_DIR, "pull"], check=True, capture_output=True, text=True)


    try:
        result = pulling_from_git()
        output = result.stdout.strip()
        if "Already up to date." in output:
            pass

        # An update that lands new launcher code cannot take effect in THIS
        # process: Python already holds the old module in memory, so the player
        # would run the previous launch() against the new files -- which is how
        # a data-only feature can land while the code that installs it does not.
        #
        # This used to stop and ask the player to reopen the launcher. The
        # console is hidden (see the except branch below, which has to call
        # ShowWindow to make it visible), so that prompt was invisible: the
        # launcher looked frozen and whoever killed it never got the update
        # applied. So relaunch ourselves instead, and only ever once -- the
        # child carries a marker so a pull that keeps reporting changes cannot
        # bounce the launcher forever.
        else:
            if os.environ.get("BROS_LAUNCHER_RELAUNCHED") != "1":
                child_env = dict(os.environ)
                child_env["BROS_LAUNCHER_RELAUNCHED"] = "1"
                try:
                    if getattr(sys, "frozen", False):
                        cmd = [sys.executable]
                    else:
                        cmd = [sys.executable, os.path.abspath(__file__)]
                    subprocess.Popen(cmd, env=child_env, cwd=BASE_DIR)
                    exit()
                except Exception as relaunch_error:
                    try:
                        ctypes.windll.user32.ShowWindow(
                            ctypes.windll.kernel32.GetConsoleWindow(), 1)
                    except:
                        pass
                    print("Auto-relaunch failed :", relaunch_error)
                    input("A new update just dropped, press enter to close this "
                          "window then reopen your launcher")
                    exit()
            # Second pass: the code on disk is what is running now, so carry on.

    except Exception as e:
        try:
            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 1)
        except:
            pass
        print("Git update failed :", e)
        print("Please relaunch the installer script, while installing make sure to wait for the installer window to close itself, DO NOT close it yourself please")
        a = input("Press Enter to exit ")
        exit()

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
    gameMode = "DEFAULT"
    # The Quick Launch shortcut of the launch in progress, spelled the way the
    # loader reads it ("training", "roommatch"), or None. See launch().
    bootMode = None

    # ── Fonts ────────────────────────────────────────────────────────────────
    FONT_TITLE    = ("Segoe UI", 18, "bold")
    FONT_SUBTITLE = ("Segoe UI", 10, "italic")
    FONT_SECTION  = ("Segoe UI", 9, "bold")
    FONT_BODY     = ("Segoe UI", 10)
    FONT_SMALL    = ("Segoe UI", 9)
    FONT_MONO     = ("Consolas", 9)
    FONT_COMBO    = ("Segoe UI", 12, "bold")

    #minimum size of the window
    window.minsize(560,420)
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
            padx=12, pady=6, anchor=styles["anchor"],
            highlightthickness=1, highlightbackground=styles["border"], highlightcolor=styles["border"]
        )
        btn.bind("<Enter>", lambda e: btn.config(bg=styles["hover"]), add="+")
        btn.bind("<Leave>", lambda e: btn.config(bg=styles["bg"]),   add="+")
        if tooltip:
            Tooltip(btn, tooltip)
        return btn

    def build_header(parent, icon="⚔"):
        """Title + subtitle + a soft fading divider, shared by every page."""
        head = Frame(parent, bg=bgcolor)
        Label(head, text=f"{icon}  Bleach Rebirth of Souls community patch launcher",
              font=FONT_TITLE, bg=bgcolor, fg=ACCENT, wraplength=480, justify="center").pack(pady=(0,0))
        Label(head, text="made by Nilsix :3", font=FONT_SUBTITLE, bg=bgcolor, fg=TEXT_MUTED).pack(pady=(1,5))
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
        inner = Frame(outer, bg=PANEL, padx=11, pady=7)
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



    def injectFolder(files,folderName,fullFolder=True):
            folder_src = os.path.join(BASE_DIR,"GameVersions",f"{files}",f'{folderName}')
            folder_dst = os.path.join(game_path,f'{folderName}')

            if fullFolder:
                try:
                    subprocess.run(["robocopy",folder_src,folder_dst,"/MIR"],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                except Exception as e:
                    shutil.rmtree(folder_dst)
                    shutil.copytree(folder_src, folder_dst)
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
            shutil.copytree(os.path.join(BASE_DIR,"Files","Spec Mod",f'{folderName}',f'{lowspecmodornot}'),
                            os.path.join(game_path,"00HIGH","Effect","spfx","com"),dirs_exist_ok=True)
            shutil.copytree(os.path.join(BASE_DIR,"Files","Spec Mod",f'{folderName}',f'{lowspecmodornot}'),
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
        # A game mode may ship its OWN loader, for a mechanic that is an exe hook
        # rather than data. When the selected mode has one it wins; it is this
        # same source built with that mode's flag, so it carries every patch the
        # normal loader carries. See GameModes/<mode>/README.md.
        src = os.path.join(BASE_DIR, "Files", "Matchmaking", "dinput8.dll")
        if gameMode != "DEFAULT":
            modeLoader = os.path.join(BASE_DIR, "GameModes", gameMode, "dinput8.dll")
            if os.path.exists(modeLoader):
                src = modeLoader
                print(f"[matchmaking] game mode '{gameMode}' ships its own loader")
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
                    # The copy is not the file we shipped: an antivirus cleaned it
                    # mid-write, the disk filled, the write was cut short. Remove
                    # it -- the loader survives a half-written DLL (it logs that
                    # the file would not load and carries on), but a plugin we
                    # cannot vouch for is worth nothing -- and start without it.
                    # A plugin is an add-on; the game is fine.
                    # This used to 'raise SystemExit', which is NOT an Exception,
                    # so neither handler below caught it: tkinter re-raised it, the
                    # launcher window vanished, and the one line explaining why
                    # went to a console that is hidden at startup.
                    # Only claim it is gone if the remove actually worked -- the
                    # file can be held open by the same antivirus that broke it.
                    try:
                        os.remove(d_p)
                        binned = True
                    except Exception:
                        binned = False
                    if binned:
                        print(f"[plugins] {f} did NOT install -- removed, starting without it")
                        detail = (f"{f} did not install correctly, so it was removed and "
                                  "is NOT active.")
                    else:
                        print(f"[plugins] {f} did NOT install and the bad copy could not be removed")
                        detail = (f"{f} did not install correctly and the bad copy could not "
                                  "be removed, so please delete it yourself from the "
                                  "ReBalanceOfSouls folder next to the game.")
                    messagebox.showerror(
                        "Plugin not installed",
                        detail + "\n\nThe game still starts without it. An antivirus scanning "
                        "your game folder is the usual cause -- allow the folder, then "
                        "launch again."
                    )
                    continue
                print(f"[plugins] installed {f}")
            if want:
                print(f"[plugins] {len(want)} plugin(s) in ReBalanceOfSouls/")
        except Exception as e:
            # This branch, not the sha256 check above, is where an antivirus hit
            # usually lands: the copy itself raises because the source in the
            # launcher folder was quarantined or the write into the game folder
            # was denied. print() alone is invisible (the console is hidden at
            # startup), so say it out loud -- then fall through and launch, same
            # as before. A plugin is an add-on.
            print(f"[plugins] could not install plugins: {e}")
            messagebox.showerror(
                "Plugins not installed",
                f"The optional plugins could not be installed:\n\n{e}\n\n"
                "The game still starts, just without them. An antivirus scanning "
                "the launcher folder or your game folder is the usual cause -- "
                "allow both, then launch again."
            )
        # Match pool is derived AUTOMATICALLY from the current GitHub build
        # (the commit SHA from get_snapshot()) plus the selected game version.
        # crc32 turns the SHA (hex letters + digits) into a number. Every push
        # yields a new SHA -> a fresh pool, so players on a different build /
        # game version / vanilla won't match you. No manual bumping needed.
        build = get_snapshot() or "unknown"
        seed = f"{build}|{gameVersion}"
        code = 100000 + (zlib.crc32(seed.encode("utf-8")) % 800000)
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

    def launch_patched(target_path):
        """Launch the patched game. On Windows, start the .exe directly (required
        so EasyAntiCheat doesn't block the injected dinput8.dll -- crash otherwise).
        On Linux/macOS a Windows .exe can't be exec'd directly ([Errno 8] Exec
        format error) -- it only runs through Steam/Proton -- so launch it via
        Steam's app URL instead. Steam must be running for online play."""
        exe = os.path.join(target_path, "BLEACH_Rebirth_of_Souls.exe")
        # The Quick Launch shortcut rides in BROS_BOOT_MODE, set on THIS process's
        # environment rather than only on the Popen call: the elevated fallback
        # below goes through ShellExecuteW, which has no env parameter and hands
        # the child a copy of ours. Cleared when there is no shortcut, so a quick
        # launch can never leak into the next normal one. Same contract as the
        # development launcher.
        if bootMode:
            os.environ["BROS_BOOT_MODE"] = bootMode
        else:
            os.environ.pop("BROS_BOOT_MODE", None)
        if platform.system() != "Windows":
            try:
                open_file("steam://rungameid/1689620")
            except Exception as e:
                print(f"Error launching patched game: {e}")
            return
        try:
            subprocess.Popen([exe], cwd=target_path)
        except OSError as e:
            if getattr(e, "winerror", None) == 740:
                # exe's manifest requires elevation — Popen/CreateProcess can't
                # trigger the UAC prompt itself, ShellExecuteW with "runas" can.
                try:
                    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, None, target_path, 1)
                except Exception as e2:
                    print(f"Error launching patched game (elevated): {e2}")
            else:
                print(f"Error launching patched game: {e}")
        except Exception as e:
            print(f"Error launching patched game: {e}")

    def launch(gameVersion, boot_mode=None):
        """boot_mode is a Quick Launch shortcut: "TrainingBoot" or "RoomMatchBoot".

        A Quick Launch must install EXACTLY what a normal launch installs -- the
        same version, game mode, reworks, Team Battle table, plugins and loader --
        and only open on another screen. So the shortcut is no longer turned into
        a game mode. It used to be, and setup_matchmaking() then installed
        GameModes/<mode>/dinput8.dll: a loader frozen before the 2026-09-22
        update, with no plugin host, no three-player room, no room-match crash
        guards, and a matchmaking pool 4003 away from the normal loader's, so a
        player who used these buttons could never find one who launched
        normally (measured 2026-09-24: code 805088 -> pool 805088 on the frozen
        loader, code 407699 -> pool 411702 on the normal one).

        It now travels as BROS_BOOT_MODE, which the normal loader reads at
        startup -- the way the standalone Quick Launch scripts at the repo root
        have sent it since they were fixed for the same reason."""
        global bootMode
        bootMode = {"TrainingBoot": "training", "RoomMatchBoot": "roommatch"}.get(boot_mode)
        try:
            _launch_impl(gameVersion)
        finally:
            bootMode = None

    def _launch_impl(gameVersion):
        pulling_from_git()
        if not os.path.exists(os.path.join(BASE_DIR,"GameModes","TeamBattle","TokenOpen.txt")):
            config["TEAM_BATTLE"] = "OFF"
        try:
            #folder injection
            revert_foreign_overlay(game_path, gameVersion)
            injectFolder(gameVersion,"Script")
            injectFolder(gameVersion,"Motion")
            injectFolder(gameVersion,"00HIGH",False)
            injectFolder(gameVersion,"01MIDDLE",False)
            # Demo/ carries the shortened match intros and stage opening cameras.
            # MERGE only (fullFolder=False): the game's Demo folder holds ~1000
            # packages and a /MIR would delete every one this version does not
            # ship. Guarded on the folder existing, because the versions that do
            # not carry it must still launch.
            if os.path.isdir(os.path.join(BASE_DIR,"GameVersions",gameVersion,"Demo")):
                injectFolder(gameVersion,"Demo",False)



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
            if gameMode != "DEFAULT":
                srcPath = os.path.join(BASE_DIR,"GameModes",f"{gameMode}","Script")
                dstPath = os.path.join(game_path,"Script")

                # A boot shortcut is a loader and has no Script/ at all, and
                # copytree raises on a source that is not there.
                if os.path.exists(srcPath):
                    shutil.copytree(srcPath, dstPath, dirs_exist_ok=True)


            #team battle injection
            if config["TEAM_BATTLE"] == "ON":
                srcPath = os.path.join(BASE_DIR,"GameModes","TeamBattle")
                dstPath = os.path.join(game_path,"Script")
                shutil.copy(
                    os.path.join(srcPath,"CharaStatus.fsv"),
                    os.path.join(dstPath,"CharaStatus.fsv"))


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
            VANILLA_VERSION = "Bleach Rebirth of Souls"
            if gameVersion != VANILLA_VERSION:
                setup_matchmaking(game_path, gameVersion)
                launch_patched(game_path)
            else:
                remove_matchmaking(game_path)
                try:
                    open_file("steam://rungameid/1689620")
                except:
                    print("Error launching game")
        except Exception as e:
            messagebox.showerror(
                "Launch Error",
                f"Something went wrong while preparing '{gameVersion}' for launch:\n\n{e}\n\n"
                "The game was not launched. Please check that this version's folder "
                "under GameVersions has all required subfolders (Script, Motion, 00High, 01MIDDLE)."
            )
            return

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


    def gameModesMenu():
        gameModesPage.tkraise()



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
    container = Frame(scrollCanvas, bg=bgcolor, padx=34, pady=6)
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
    gameModesPage = Frame(container,bg=bgcolor)
    repairPage = Frame(container,bg=bgcolor)
    reworksPage = Frame(container,bg=bgcolor)



    #headers (title / subtitle / fading divider), shared component per page
    build_header(mainPage).pack()
    build_header(settingsPage, icon="⚙").pack()
    build_header(gameModesPage, icon="🎮").pack()
    build_header(repairPage, icon="🛠").pack()
    build_header(reworksPage, icon="✨").pack()

    labelWarning = Label(mainPage, text="Warning : Please only use the non vanilla features in room matches online, not in casual or ranked matches",font=FONT_SMALL,bg=bgcolor,fg=TEXT_MUTED)

    # Version panel: two small status pills. Each shows a short explanation on
    # hover (reuses the Tooltip class) so the numbers aren't confusing.
    # The GameVersions/ folder the Quick Launch buttons force, so a shortcut
    # never runs vanilla (which has no loader and would ignore it).
    COMMUNITY_VERSION = "Bleach Rebirth of Souls Community Patch"
    LATEST_STRING = get_latest()
    _have_latest  = LATEST_STRING not in ("", "unknown")
    _up_to_date   = _have_latest and (VERSION_STRING == LATEST_STRING)

    versionPanel = Frame(mainPage, bg=bgcolor)

    _status1 = "(up to date)" if _up_to_date else ("(update available - relaunch)" if _have_latest else "(offline)")
    _status_dot = GREEN_OK if _up_to_date else (GOLD if _have_latest else GRAY_OFFLINE)

    make_pill(versionPanel, GOLD if True else GOLD, f"Current : {VERSION_STRING}",
              "The patch build you have installed right now (short git commit hash).")\
        .pack(side=LEFT, padx=(0,10))
    make_pill(versionPanel, _status_dot, f"Latest : {LATEST_STRING}  {_status1}",
              "The newest patch build published on GitHub. If it differs from Current, an update is available - relaunch to get it.")\
        .pack(side=LEFT)

    brosVersion = StringVar()
    gameVersionsList = []
    gameVersionsPath = os.path.join(BASE_DIR,"GameVersions")
    for folder in os.listdir(gameVersionsPath):
        gameVersionsList.append(folder)

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

    def preLauncher():
        if brosVersionList.get() != "Choose a game version":
            launch(brosVersionList.get())

    # Quick Launch: the normal Community Patch launch plus a boot shortcut, so
    # the game opens on the screen you actually wanted instead of the title
    # screen and the menu walk. The version is forced to the Community Patch
    # (same as the standalone Quick Launch scripts at the repo root): vanilla
    # goes through Steam with no loader, and with no loader there is nothing to
    # act on the shortcut, so it would silently do nothing.
    def quickLaunchTraining():
        launch(COMMUNITY_VERSION, boot_mode="TrainingBoot")

    def quickLaunchRoomMatch():
        launch(COMMUNITY_VERSION, boot_mode="RoomMatchBoot")

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

    def baseOnlyFunc():
        global gameMode
        if gameMode == "BaseOnly":
            gameMode = "DEFAULT"
        else:
            gameMode = "BaseOnly"
        actualiseGameModeButtons()

    def teamBattleFunc():
        if not os.path.exists(os.path.join(BASE_DIR,"GameModes","TeamBattle","TokenOpen.txt")):
            config["TEAM_BATTLE"] = "OFF"
            saveJson()
            messagebox.showinfo("Team Battle", "You need to contact a Team Battle host to be able to join a team battle, for that, ping one on the discord using @Team Battle Host")
            return
        config["TEAM_BATTLE"] = "ON" if config["TEAM_BATTLE"] == "OFF" else "OFF"
        saveJson()
        teamBattleButton.config(text=f'Team Battle : (Currently {"ON" if config["TEAM_BATTLE"] == "ON" else "OFF"})')
        set_toggle_visual(teamBattleButton, config["TEAM_BATTLE"] == "ON")

    def instantEvoAndSublimationFunc():
        global gameMode
        if gameMode == "InstantEvoAndSublimation":
            gameMode = "DEFAULT"
        else:
            gameMode = "InstantEvoAndSublimation"
        actualiseGameModeButtons()

    def eightKonpakusFunc():
        global gameMode
        if gameMode == "EightKonpakus":
            gameMode = "DEFAULT"
        else:
            gameMode = "EightKonpakus"
        actualiseGameModeButtons()

    def extraKonpakuFunc():
        global gameMode
        if gameMode == "ExtraKonpaku":
            gameMode = "DEFAULT"
        else:
            gameMode = "ExtraKonpaku"
        actualiseGameModeButtons()

    def suddenDeathFunc():
        global gameMode
        if gameMode == "SuddenDeath":
            gameMode = "DEFAULT"
        else:
            gameMode = "SuddenDeath"
        actualiseGameModeButtons()

    def reawakeningBattleFunc():
        global gameMode
        if gameMode == "ReawakeningBattle":
            gameMode = "DEFAULT"
        else:
            gameMode = "ReawakeningBattle"
        actualiseGameModeButtons()

    def actualiseGameModeButtons():
        baseOnlyButton.config(text=f'Base Only : (Currently {"ON" if gameMode == "BaseOnly" else "OFF"})')
        instantEvoAndSublimation.config(text=f'Instant Evo and Sublimation : (Currently {"ON" if gameMode == "InstantEvoAndSublimation" else "OFF"})')
        eightKonpakus.config(text=f'8 Konpakus : (Currently {"ON" if gameMode == "EightKonpakus" else "OFF"})')
        extraKonpaku.config(text=f'Extra Konpaku : (Currently {"ON" if gameMode == "ExtraKonpaku" else "OFF"})')
        suddenDeath.config(text=f'Sudden Death : (Currently {"ON" if gameMode == "SuddenDeath" else "OFF"})')
        reawakeningBattle.config(text=f'Reawakening Battle : (Currently {"ON" if gameMode == "ReawakeningBattle" else "OFF"})')
        set_toggle_visual(baseOnlyButton, gameMode == "BaseOnly")
        set_toggle_visual(instantEvoAndSublimation, gameMode == "InstantEvoAndSublimation")
        set_toggle_visual(eightKonpakus, gameMode == "EightKonpakus")
        set_toggle_visual(extraKonpaku, gameMode == "ExtraKonpaku")
        set_toggle_visual(suddenDeath, gameMode == "SuddenDeath")
        set_toggle_visual(reawakeningBattle, gameMode == "ReawakeningBattle")

    def unlockDangaiIchigo():
        result = messagebox.askyesno("Unlock Dangai Ichigo", "Unlocking Dangai Ichigo this way will reset your settings and ranked progress , are you sure you want to continue?")
        theDangaiFiles = os.path.join(BASE_DIR,"ressources","savedata.bin")
        if result:
            appdataPath = os.getenv("APPDATA")
            try:
                saveDataPath = os.path.join(appdataPath,"BLEACH Rebirth of Souls","Savedata")
                for folder in os.listdir(saveDataPath):
                    shutil.copy(theDangaiFiles, os.path.join(saveDataPath, folder))
            except Exception as e:
                messagebox.showerror("Error", f"Error: {e}")
                return
            # Copy the dangai files to the save data path
            #shutil.copy2(theDangaiFiles, saveDataPath)
            messagebox.showinfo("Dangai Ichigo unlocked", "Dangai Ichigo unlocked successfully!")

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

    paddingYvalue = 3

    # ── Main page ────────────────────────────────────────────────────────────
    versionPanel.pack(pady=(0,6))
    #labelWarning.pack(fill=X)
    labelGamePathOuter, labelGamePathInner = make_card(mainPage)
    labelGamePath = Label(labelGamePathInner, text=f'📁  Current game path : {game_path}',font=FONT_SMALL,bg=PANEL,fg=TEXT_MUTED, wraplength=480, justify="left")
    labelGamePath.pack(anchor="w")
    labelGamePathOuter.pack(fill=X, pady=(0,7))

    playOuter, playInner = make_card(mainPage, "Play")
    brosVersionList = ttk.Combobox(
        playInner,
        textvariable=brosVersion,
        values=gameVersionsList,
        state="readonly",
        font=FONT_COMBO,
        style="Bros.TCombobox"
    )
    brosVersionList.set("Choose a game version")
    launchButton = mkbutton(playInner, "Launch the game", preLauncher, kind="primary", icon="▶",
                             tooltip="Launch the game using the version selected in the dropdown above.")
    brosVersionList.pack(pady=(0,paddingYvalue+3), fill=X)
    launchButton.pack(fill=X)
    playOuter.pack(fill=X, pady=(0,7))

    quickLaunchOuter, quickLaunchInner = make_card(mainPage, "Quick Launch")
    quickLaunchTrainingButton = mkbutton(quickLaunchInner, "Quick Launch Training Mode", quickLaunchTraining, icon="🥋",
                                          tooltip="Launch the Community Patch straight into the training character select, skipping the title screen.")
    quickLaunchRoomMatchButton = mkbutton(quickLaunchInner, "Quick Launch Room Match", quickLaunchRoomMatch, icon="🌐",
                                           tooltip="Launch the Community Patch straight into the online room match menu (create / find room), skipping the title screen.")
    quickLaunchTrainingButton.pack(pady=(0,paddingYvalue), fill=X)
    quickLaunchRoomMatchButton.pack(fill=X)
    quickLaunchOuter.pack(fill=X, pady=(0,7))

    customizeOuter, customizeInner = make_card(mainPage, "Customize")
    gameModesButton = mkbutton(customizeInner, "Game Modes", gameModesMenu, icon="🎮",
                                tooltip="Switch between different game modes (Base only, 8 konpaku, etc...)")
    lowSpecButton = mkbutton(customizeInner, "FPS Booster settings", performanceSettingsMenu, icon="⚡",
                              tooltip="Toggle per-effect FPS booster settings to improve performance on lower-end PCs.")
    unlockDangaiIchigoButton = mkbutton(customizeInner, "Unlock Dangai Ichigo", unlockDangaiIchigo, icon="🔓",
                                         tooltip="Unlocks Dangai Ichigo")
    gameModesButton.pack(pady=paddingYvalue, fill=X)
    lowSpecButton.pack(pady=paddingYvalue, fill=X)
    unlockDangaiIchigoButton.pack(pady=(paddingYvalue,0), fill=X)
    customizeOuter.pack(fill=X, pady=(0,7))

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

    settingsOuter.pack(fill=X, pady=(0,7))

    mainMenuButton = mkbutton(settingsPage, "Main Menu", backToMainMenu, kind="ghost", icon="←",
                               tooltip="Return to the main menu.")
    mainMenuButton.pack(pady=paddingYvalue, fill=X)

    #game modes page
    gameModesOuter, gameModesInner = make_card(gameModesPage, "Game Modes")

    teamBattleButton = mkbutton(
        gameModesInner,
        text=f'Team Battle : (Currently {"ON" if config["TEAM_BATTLE"] == "ON" else "OFF"})',
        command=teamBattleFunc,
        tooltip="Toggle Team Battle mode: allows team fights."
    )
    instantEvoAndSublimation = mkbutton(
        gameModesInner,
        text=f'Instant Evo and Sublimation : (Currently {"ON" if gameMode == "InstantEvoAndSublimation" else "OFF"})',
        command=instantEvoAndSublimationFunc,
        tooltip="Toggle Instant Evolution & Sublimation: evolution and sublimation happen immediately."
    )
    baseOnlyButton = mkbutton(
        gameModesInner,
        text=f'Base Only : (Currently {"ON" if gameMode == "BaseOnly" else "OFF"})',
        command=baseOnlyFunc,
        tooltip="Toggle Base Only mode: disables evolutions and sublimations entirely. Every character starts with 6 konpaku stocks"
    )
    eightKonpakus = mkbutton(
        gameModesInner,
        text=f'8 Konpakus : (Currently {"ON" if gameMode == "EightKonpakus" else "OFF"})',
        command=eightKonpakusFunc,
        tooltip="Toggle 8 Konpakus mode: each player starts with 8 Konpaku stocks (revive characters start with 7)."
    )
    extraKonpaku = mkbutton(
        gameModesInner,
        text=f'Extra Konpaku : (Currently {"ON" if gameMode == "ExtraKonpaku" else "OFF"})',
        command=extraKonpakuFunc,
        tooltip="Toggle Extra Konpaku mode: gives every player extra Konpaku stocks."
    )
    suddenDeath = mkbutton(
        gameModesInner,
        text=f'Sudden Death : (Currently {"ON" if gameMode == "SuddenDeath" else "OFF"})',
        command=suddenDeathFunc,
        tooltip="Toggle Sudden Death mode."
    )
    reawakeningBattle = mkbutton(
        gameModesInner,
        text=f'Reawakening Battle : (Currently {"ON" if gameMode == "ReawakeningBattle" else "OFF"})',
        command=reawakeningBattleFunc,
        tooltip="Every character who owns a Reawakening starts the match already in it, on 10 Konpaku. Ships its own loader and its own online pool."
    )
    teamBattleButton.pack(pady=paddingYvalue, fill=X)
    instantEvoAndSublimation.pack(pady=paddingYvalue, fill=X)
    baseOnlyButton.pack(pady=paddingYvalue, fill=X)
    eightKonpakus.pack(pady=paddingYvalue, fill=X)
    extraKonpaku.pack(pady=paddingYvalue, fill=X)
    suddenDeath.pack(pady=paddingYvalue, fill=X)
    reawakeningBattle.pack(pady=(paddingYvalue,0), fill=X)
    gameModesOuter.pack(fill=X, pady=(0,7))
    set_toggle_visual(teamBattleButton, config["TEAM_BATTLE"] == "ON")

    gameModesMenuButton = mkbutton(gameModesPage, "Main Menu", backToMainMenu, kind="ghost", icon="←",
                                    tooltip="Return to the main menu.")
    gameModesMenuButton.pack(pady=paddingYvalue, fill=X)

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

    reworksOuter, reworksInner = make_card(reworksPage, "Reworks")
    reworksByakuyaButton = mkbutton(reworksInner, "Byakuya Rework", byakuyaReworkToggle)
    reworksByakuyaButton.pack(pady=paddingYvalue, fill=X)
    reworksOuter.pack(fill=X, pady=(0,7))
    reworksBackToMenuButton = mkbutton(reworksPage, "Back to menu", lambda: mainPage.tkraise(), kind="ghost", icon="←")
    reworksBackToMenuButton.pack(pady=paddingYvalue, fill=X)

    # Let the stacked pages fill the whole container (so buttons stretch to width).
    container.grid_rowconfigure(0, weight=1)
    container.grid_columnconfigure(0, weight=1)
    for page in(mainPage,settingsPage,gameModesPage,repairPage,reworksPage):
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
        w = min(max(cw + (14 if h < ch else 0), 560), sw - 40)
        x = max(0, (sw - w) // 2); y = max(0, (sh - h) // 2 - 20)
        window.geometry(f"{w}x{h}+{x}+{y}")
        window.update_idletasks()
        _sync_scroll()
    fit_window()
    window.deiconify()
    window.mainloop()
except Exception as e:
    try :
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 1)
    except:
        pass
    print(f'Error : {e}')
    input("Please ping the error to Nilsix")
