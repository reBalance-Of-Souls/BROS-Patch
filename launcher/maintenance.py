"""The update's maintenance: the files download, the game stays shut until one instant, the same for every player.

Asked 2026-11-24: during the maintenance a player still gets the whole update (the launcher's pull), is told it is
downloaded and that the window may be closed, and cannot start the game before the end; the end is one instant
whatever the player's timezone.

HOW
---
The end is one number, UTC seconds since 1970, stamped inside Files/Matchmaking/Plugins/maintenance.dll
("BROS_MAINT_END=" + 10 digits, 0 = no maintenance). It has two readers:
  * every launch, after its update (running() below): the launch installs everything and starts nothing, then a
    window (gate()) says the update is installed, when the game opens in the player's own time, and counts down. At
    the end it closes itself and the same launch runs again -- only what changed meanwhile is copied -- and starts the
    game; closing it = no start. A launcher opened during the maintenance launches by itself, so the copy is done
    during the maintenance, not after it (user, 2026-11-24: 10 min of copy after a 5 min maintenance on a USB disk).
  * the game itself (Files/Matchmaking/maintenance_plugin.c): every launcher installs Plugins/*.dll, a launcher whose
    code is older than the update too (one left open across the release push runs its old launch() on the new
    files: no new launcher code runs at all). It shows the same end and closes the game. gate() also copies it into
    the game folder at once, so starting the exe by hand on the previous install is closed as well.
Now = github.com's Date header (the server every update comes from), not the PC's clock: a wrong or changed clock
neither ends nor extends it.

SET IT (the release step, committed with the update; run it from the checkout that ships):
    python launcher/maintenance.py staging      ends MAINTENANCE_MINUTES["staging"] from now (30)
    python launcher/maintenance.py dev          ends MAINTENANCE_MINUTES["dev"] from now (120)
    python launcher/maintenance.py 45           ends in 45 minutes
    python launcher/maintenance.py 2026-11-27T17:00+01:00    ends at that instant (no offset = this PC's time)
    python launcher/maintenance.py off          no maintenance
    python launcher/maintenance.py show         what is stamped
Never rebuild maintenance.dll after stamping it: a build writes 0 back.
"""

from __future__ import annotations

import datetime
import email.utils
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

# Minutes from the moment the stamp is written, per release target (user, 2026-11-24).
MAINTENANCE_MINUTES = {"test": 1, "staging": 30, "dev": 120}

# the update window's colours (launcher/update_window.py)
BG, TEXT, MUTED, GOLD, BTN_BG, BTN_HOVER = "#1c0e23", "#efe1f4", "#b79bc4", "#e3b34f", "#3a2144", "#4c2c59"

DLL = os.path.join("Files", "Matchmaking", "Plugins", "maintenance.dll")
MARK = b"BROS_MAINT_END="


def end_utc(base):
    """The stamped end (UTC seconds), 0 when none or no plugin."""
    try:
        with open(os.path.join(base, DLL), "rb") as f:
            b = f.read()
    except OSError:
        return 0
    i = b.find(MARK)
    digits = b[i + len(MARK): i + len(MARK) + 10] if i >= 0 else b""
    return int(digits) if digits.isdigit() else 0


def server_now():
    """github.com's clock (its Date header), or the PC's when it does not answer."""
    req = urllib.request.Request("https://github.com", method="HEAD",
                                 headers={"User-Agent": "BrosCommunityPatchLauncher"})
    try:
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                date = r.headers.get("Date")
        except urllib.error.HTTPError as e:
            date = e.headers.get("Date")
        if date:
            return email.utils.parsedate_to_datetime(date).timestamp()
    except Exception:
        pass
    # shortcut: no answer = the PC's clock (offline, a clock set forward passes); a player needs the server to update
    return time.time()


def local_text(end):
    return datetime.datetime.fromtimestamp(end).strftime("%A %d %B %Y at %H:%M")


def left_text(s):
    s = int(s)
    return "%d h %02d min %02d s" % (s // 3600, s // 60 % 60, s % 60)


def _put_in_game(base, game_path):
    """The stamped plugin into the game folder at once: the exe started by hand on the previous install closes too."""
    if game_path and os.path.isdir(os.path.join(game_path, "ReBalanceOfSouls")):
        try:
            shutil.copy2(os.path.join(base, DLL), os.path.join(game_path, "ReBalanceOfSouls", "maintenance.dll"))
        except OSError as e:            # the game is running: its own copy is the one it booted with
            print("[maintenance] could not put maintenance.dll in the game folder: %s" % e)


def running(base, game_path=None):
    """True while the stamped maintenance runs (github.com's clock); the stamped plugin then goes into the game folder.
    The launcher installs the update during it and starts the game at its end (gate)."""
    end = end_utc(base)
    if not end or end - server_now() <= 0:
        return False
    _put_in_game(base, game_path)
    return True


def gate(base, game_path=None, parent=None):
    """True: the game may start (no maintenance, or it just ended). False: the player closed the window."""
    end = end_utc(base)
    if not end:
        return True
    offset = server_now() - time.time()

    def left():
        return end - (time.time() + offset)

    if left() <= 0:
        return True
    print("[maintenance] until %s (%d s left): the game does not start before" % (local_text(end), left()))
    _put_in_game(base, game_path)
    return _window(end, left, parent)


def _window(end, left, parent):
    try:
        import tkinter as tk
        top = tk.Toplevel(parent) if parent is not None else tk.Tk()
    except Exception as e:              # no display: no start, said in the log
        print("[maintenance] no window (%s): the game is not started" % e)
        return False
    ended = []
    top.title("ReBalance of Souls: maintenance")
    top.configure(bg=BG)
    top.resizable(False, False)
    frame = tk.Frame(top, bg=BG, padx=24, pady=18)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text="The update is installed: the game opens by itself at the end.", font=("Segoe UI", 11, "bold"),
             bg=BG, fg=TEXT, anchor="w").pack(fill="x")
    tk.Label(frame, text="The game is under maintenance until %s (your time).\nYou can close this window: the game "
             "then does not start, and Launch the game after the end starts it at once." % local_text(end),
             font=("Segoe UI", 9), bg=BG, fg=MUTED, anchor="w", justify="left").pack(fill="x", pady=(8, 0))
    count = tk.Label(frame, text="", font=("Segoe UI", 16, "bold"), bg=BG, fg=GOLD)
    count.pack(pady=(12, 0))
    tk.Button(frame, text="Close", command=top.destroy, font=("Segoe UI", 9), bg=BTN_BG, fg=TEXT,
              activebackground=BTN_HOVER, activeforeground=TEXT, relief="flat", bd=0, padx=14, pady=4,
              cursor="hand2").pack(anchor="e", pady=(12, 0))

    def tick():
        s = left()
        if s <= 0:
            ended.append(1)
            count.config(text="Maintenance over: the game is open")
            top.after(2000, top.destroy)
            return
        count.config(text="Opens in " + left_text(s))
        top.after(500, tick)

    tick()
    top.update_idletasks()
    top.geometry("+%d+%d" % ((top.winfo_screenwidth() - top.winfo_reqwidth()) // 2,
                             (top.winfo_screenheight() - top.winfo_reqheight()) // 3))
    top.deiconify()
    top.lift()
    if parent is None:
        top.mainloop()
    else:
        parent.wait_window(top)
    print("[maintenance] %s" % ("over: the start goes on" if ended else "window closed: the game is not started"))
    return bool(ended)


def stamp(base, end):
    """Write end (UTC seconds, 0 = off) into the plugin's 10 digits, in place."""
    p = os.path.join(base, DLL)
    with open(p, "rb") as f:
        b = f.read()
    i = b.find(MARK)
    if i < 0 or b.count(MARK) != 1 or not 0 <= end < 10 ** 10:
        raise SystemExit("%s: no single %s stamp to write" % (p, MARK.decode()))
    j = i + len(MARK)
    with open(p, "wb") as f:
        f.write(b[:j] + b"%010d" % end + b[j + 10:])


def main(argv):
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    arg = argv[0] if argv else "show"
    if arg == "off":
        stamp(base, 0)
    elif arg != "show":
        if arg in MAINTENANCE_MINUTES or arg.isdigit():
            end = int(server_now()) + 60 * int(MAINTENANCE_MINUTES.get(arg, arg))
        else:
            end = int(datetime.datetime.fromisoformat(arg).timestamp())
        stamp(base, end)
    end = end_utc(base)
    print("maintenance: %s" % ("none" if not end else "until %s UTC = %s here (%d)" % (
        datetime.datetime.fromtimestamp(end, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        local_text(end), end)))


if __name__ == "__main__":
    main(sys.argv[1:])
