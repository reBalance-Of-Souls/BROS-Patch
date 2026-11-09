"""room_check.py -- the launchers' Room Match check window (pass rt, 2026-11-09).

THE SAME FILE SITS IN BOTH REPOSITORIES (Dev Environment and BROS-Patch, launcher/room_check.py), byte for byte.

WHY (Berg, 2026-11-09: "can you make sure to fix people not finding each other on room matches? We created the in game
UI to help, but an actual tool that can tell why we're not finding one another with a single look is what I truly
want"; the form he chose: online.dll's list shown live in the launcher, and in game later; players named by their
Steam ID, Steam friends by name)
  Two players see each other's rooms only when their game folders make the same pool code (content_pool.py FORMAT 2).
  While the game runs, online.dll (build mf-online3g and later) searches Steam for every ReBalance player online (any
  pool), compares what each one's code is made of with this player's, and writes the answer to
  <game>/ReBalanceOfSouls/online_room_check.json: every 60 s, every 15 s while this window is open. This window shows
  it: who can meet this player and, for everyone else, why not and who has to do what. Steam friends are named;
  nobody else is, and online.dll never writes a Steam ID.

HOW IT KNOWS IT IS OPEN
  It rewrites <game>/ReBalanceOfSouls/online_room_check.want every 5 s; online.dll counts the window as open while that
  file is younger than 20 s. Neither file is part of the pool code (content_pool.py counts only .dll and .txt there).

THE REPORT (format 1, written by online.dll presence.c pc_end)
  {"format", "written" (seconds since 1970), "build",
   "me": {"code", "line", "mode", "built", "fp": "ok" | "stale" | "nocheck", "folder_code", "state", "on_patch", "newer"},
   "players": [{"name" ("" unless a Steam friend), "friend", "state" ("o" online, "f"/"r" searching Free/Ranked),
                "code", "line", "mode", "built", "verdict", "reason", "details", "exe", "mode_differs", "loader",
                "plugins", "plugin_files", "options" (names; each with a *_count), "data" (trees: "Script,Demo")}],
   "census": {"seen", "listed", "partial", "searches", "unreadable", "names"}}
  verdict: same | older | newer | files | options | exe | mode | line | stale.
"""

import json
import os
import time

REPORT = ("ReBalanceOfSouls", "online_room_check.json")
WANT = ("ReBalanceOfSouls", "online_room_check.want")
STALE_S = 150            # older than this: the game is not running, or is not online
REFRESH_MS = 2000
WANT_EVERY_S = 5

VERDICT = {
    "same": ("Can meet", "ok"),
    "older": ("Older build", "bad"),
    "newer": ("Newer build", "bad"),
    "files": ("Different files", "bad"),
    "options": ("Different options", "bad"),
    "exe": ("Game version", "bad"),
    "mode": ("Game mode", "bad"),
    "line": ("Other version", "bad"),
    "stale": ("Old code", "bad"),
}
STATE = {"o": "Online", "f": "Searching Free Match", "r": "Searching Ranked Match"}
ORDER = {"same": 0, "older": 1, "newer": 2, "files": 3, "options": 4, "stale": 5, "mode": 6, "line": 7, "exe": 8}


def report_path(game):
    return os.path.join(game, *REPORT)


def want_path(game):
    return os.path.join(game, *WANT)


def load_report(game, now=None):
    """-> (report dict or None, age in seconds or None, a reason when there is no usable report)."""
    p = report_path(game)
    try:
        with open(p, "r", encoding="utf-8") as f:
            rep = json.load(f)
    except FileNotFoundError:
        return None, None, "none"
    except (OSError, ValueError):
        return None, None, "unreadable"
    if not isinstance(rep, dict) or rep.get("format") != 1 or not isinstance(rep.get("players"), list):
        return None, None, "format"
    now = time.time() if now is None else now
    age = max(0, now - (rep.get("written") or 0))
    return rep, age, ("stale" if age > STALE_S else "")


def touch_want(game):
    """Tell online.dll the window is open (it reads the file's time). Errors are harmless: a missing plugin folder
    means there is no online.dll to tell."""
    try:
        with open(want_path(game), "w", encoding="ascii") as f:
            f.write("%d\n" % int(time.time()))
        return True
    except OSError:
        return False


def when(sec):
    if not sec:
        return "unknown"
    try:
        return time.strftime("%d %b %H:%M", time.localtime(sec)).lstrip("0")
    except (OverflowError, OSError, ValueError):
        return "unknown"


def mode_name(m):
    return "normal game" if m in ("", "DEFAULT", None) else "game mode " + str(m)


def me_lines(rep):
    """The header: this player's own pool, and anything wrong on his side."""
    me = rep.get("me") or {}
    head = "You: pool %s  ·  %s  ·  %s  ·  build from %s" % (me.get("code", "?"), me.get("line", "?"),
                                                             mode_name(me.get("mode")), when(me.get("built")))
    notes = []
    if me.get("fp") == "stale":
        notes.append("Your game plays under an old code: the folder now makes %s. Start the game from the launcher."
                     % me.get("folder_code", "?"))
    elif me.get("fp") == "nocheck":
        notes.append("online.dll could not check your game folder, so the list below cannot say which files differ.")
    same = sum(1 for p in rep.get("players", []) if isinstance(p, dict) and p.get("verdict") == "same")
    notes.append("On your pool right now: you%s." % ("" if not same else " and %d other%s" % (same, "" if same == 1 else "s")))
    return head, notes


def explain(p):
    """A row's full reason, for the detail line under the list."""
    bits = [p.get("reason") or ""]
    if p.get("details"):
        for key, label in (("plugins", "Plugins"), ("plugin_files", "Plugin settings files"), ("options", "Launcher options")):
            names = p.get(key) or []
            total = p.get(key + "_count", len(names))
            if total:
                more = " and %d more" % (total - len(names)) if total > len(names) else ""
                bits.append("%s that differ: %s%s." % (label, ", ".join(names), more))
        if p.get("data"):
            bits.append("Game data that differs: %s." % p["data"].replace(",", ", "))
        if p.get("loader"):
            bits.append("The loader (dinput8.dll) differs.")
    bits.append("Their build is from %s (%s, %s)." % (when(p.get("built")), p.get("line", "?"), mode_name(p.get("mode"))))
    return " ".join(b for b in bits if b)


def rows(rep):
    """[(who, status, pool, verdict label, kind, short reason, player dict)], can-meet first, then friends."""
    out = []
    for p in rep.get("players", []):
        if not isinstance(p, dict):
            continue
        label, kind = VERDICT.get(p.get("verdict"), ("Unknown", "bad"))
        who = p.get("name") if p.get("friend") and p.get("name") else "A player"
        out.append((who, STATE.get(p.get("state"), "Online"), str(p.get("code", "?")), label, kind,
                    p.get("reason") or "", p))
    out.sort(key=lambda r: (ORDER.get(r[6].get("verdict"), 9), 0 if r[6].get("friend") else 1, r[0].lower()))
    return out


def summary(rep):
    """One line over the list."""
    rs = rows(rep)
    meet = sum(1 for r in rs if r[4] == "ok")
    cen = rep.get("census") or {}
    seen = cen.get("seen", len(rs))
    if not seen:
        return "No other ReBalance player is online right now, on any build."
    s = "%d other ReBalance player%s online%s: %d can meet you in Room Match, %d cannot." % (
        seen, "" if seen == 1 else "s", " (at least)" if cen.get("partial") else "", meet, seen - meet)
    if seen > len(rs):
        s += " The list shows the first %d." % len(rs)
    return s


def text_report(rep):
    """The list as plain text (the Copy button): for a message to the other players."""
    head, notes = me_lines(rep)
    lines = ["Room Match check, " + when(rep.get("written")), head] + notes + [summary(rep)]
    for who, status, pool, label, kind, reason, p in rows(rep):
        lines.append("- %s (%s, pool %s): %s. %s" % (who, status, pool, label, reason))
    return "\n".join(lines)


def open_window(parent, game, theme=None):
    """The window. theme: the launcher's colours and fonts (bg, panel, fg, muted, gold, ok, bad, font, small, mono)."""
    import tkinter as tk
    from tkinter import ttk

    t = {"bg": "#1b1022", "panel": "#26172f", "fg": "#f2e9f6", "muted": "#a993b4", "gold": "#e5b73b",
         "ok": "#5fd38d", "bad": "#ff7b72", "font": ("Segoe UI", 10), "small": ("Segoe UI", 9),
         "title": ("Segoe UI Semibold", 13), "mono": ("Consolas", 10)}
    t.update(theme or {})

    win = tk.Toplevel(parent)
    win.title("Room Match check")
    win.configure(bg=t["bg"])
    win.geometry("900x540")
    win.minsize(600, 400)

    tk.Label(win, text="Room Match check", font=t["title"], bg=t["bg"], fg=t["gold"]).pack(anchor="w", padx=14, pady=(12, 0))
    tk.Label(win, text="Who can find your rooms, and why the others can't. Players are found through Steam every "
                       "15 seconds while this window is open.", font=t["small"], bg=t["bg"], fg=t["muted"],
             wraplength=860, justify="left").pack(anchor="w", padx=14, pady=(2, 8))
    me_var, notes_var, sum_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
    tk.Label(win, textvariable=me_var, font=t["font"], bg=t["bg"], fg=t["fg"], justify="left",
             wraplength=860).pack(anchor="w", padx=14)
    notes = tk.Label(win, textvariable=notes_var, font=t["small"], bg=t["bg"], fg=t["gold"], justify="left", wraplength=860)
    notes.pack(anchor="w", padx=14)
    tk.Label(win, textvariable=sum_var, font=t["font"], bg=t["bg"], fg=t["fg"], justify="left",
             wraplength=860).pack(anchor="w", padx=14, pady=(6, 6))

    style = ttk.Style(win)
    try:
        style.configure("RoomCheck.Treeview", background=t["panel"], fieldbackground=t["panel"], foreground=t["fg"],
                        rowheight=24, font=t["small"])
        style.configure("RoomCheck.Treeview.Heading", font=t["small"])
    except tk.TclError:
        pass
    cols = ("who", "status", "pool", "verdict", "reason")
    frame = tk.Frame(win, bg=t["bg"])
    frame.pack(fill="both", expand=True, padx=14)
    tree = ttk.Treeview(frame, columns=cols, show="headings", style="RoomCheck.Treeview", selectmode="browse")
    for c, label, w, st in (("who", "Player", 130, False), ("status", "Status", 150, False), ("pool", "Pool", 70, False),
                            ("verdict", "Room Match", 120, False), ("reason", "Why", 280, True)):
        tree.heading(c, text=label, anchor="w")
        tree.column(c, width=w, anchor="w", stretch=st)
    tree.tag_configure("ok", foreground=t["ok"])
    tree.tag_configure("bad", foreground=t["bad"])
    sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    detail_var = tk.StringVar(value="Pick a player to see everything that differs.")
    tk.Label(win, textvariable=detail_var, font=t["small"], bg=t["bg"], fg=t["fg"], justify="left", wraplength=860,
             anchor="w").pack(fill="x", padx=14, pady=(6, 2))
    bottom = tk.Frame(win, bg=t["bg"])
    bottom.pack(fill="x", padx=14, pady=(2, 10))
    age_var = tk.StringVar()
    tk.Label(bottom, textvariable=age_var, font=t["small"], bg=t["bg"], fg=t["muted"]).pack(side="left")

    state = {"rep": None, "rows": [], "written": None, "why": None, "last_want": 0.0, "alive": True}

    def copy():
        if state["rep"] is None:
            return
        win.clipboard_clear()
        win.clipboard_append(text_report(state["rep"]))
        age_var.set("Copied the list.")

    tk.Button(bottom, text="Copy the list", command=copy, font=t["small"], relief="flat", bg=t["panel"], fg=t["fg"],
              activebackground=t["panel"], activeforeground=t["gold"], cursor="hand2").pack(side="right")

    def on_select(_e=None):
        sel = tree.selection()
        if not sel:
            return
        i = int(sel[0])
        if 0 <= i < len(state["rows"]):
            detail_var.set(state["rows"][i][0] + ": " + explain(state["rows"][i][6]))

    tree.bind("<<TreeviewSelect>>", on_select)

    def show(rep, age, why):
        keep = None
        sel = tree.selection()
        if sel and 0 <= int(sel[0]) < len(state["rows"]):
            p = state["rows"][int(sel[0])][6]
            keep = (p.get("name"), p.get("code"))
        tree.delete(*tree.get_children())
        state["rows"] = []
        if rep is None or why == "stale":
            me_var.set("")
            notes_var.set("")
            if why == "stale":
                sum_var.set("The game is not running, or is not online. The last list is from %s." % when(rep.get("written")))
            elif why == "none":
                sum_var.set("No list yet. Start the game from the launcher: the list appears about 15 seconds after the "
                            "game reaches its title screen, with this window open.")
            else:
                sum_var.set("The list could not be read (%s). It is written again within a minute while the game runs."
                            % why)
            age_var.set("")
            return
        head, notes_lines = me_lines(rep)
        me_var.set(head)
        notes_var.set("\n".join(notes_lines))
        sum_var.set(summary(rep))
        state["rows"] = rows(rep)
        for i, (who, status, pool, label, kind, reason, p) in enumerate(state["rows"]):
            tree.insert("", "end", iid=str(i), values=(who, status, pool, ("✓ " if kind == "ok" else "✕ ") + label, reason),
                        tags=(kind,))
            if keep and (p.get("name"), p.get("code")) == keep:
                tree.selection_set(str(i))
        age_var.set("Updated %d s ago." % int(age))

    def tick():
        if not state["alive"]:
            return
        now = time.time()
        if now - state["last_want"] >= WANT_EVERY_S:
            touch_want(game)
            state["last_want"] = now
        rep, age, why = load_report(game, now)
        written = rep.get("written") if rep else None
        if written != state["written"] or why != state["why"]:          # a new list (or none): redraw
            state["written"], state["why"], state["rep"] = written, why, rep
            show(rep, age if age is not None else 0, why)
        elif rep is not None and why == "":
            age_var.set("Updated %d s ago." % int(age))
        win.after(REFRESH_MS, tick)

    def close():
        state["alive"] = False
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", close)
    tick()
    return win


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--text":
        r, a, w = load_report(sys.argv[2])
        print(text_report(r) if r else "no report (%s)" % w)
    elif len(sys.argv) > 1:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        open_window(root, sys.argv[1]).protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()
    else:
        print(__doc__)
