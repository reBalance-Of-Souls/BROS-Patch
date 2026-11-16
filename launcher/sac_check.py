"""Windows Smart App Control, checked before the patched game starts (pass sa, 2026-11-16; the same file in the Dev
launcher and the public one).

When Smart App Control is ON, Windows refuses to load a DLL that is neither code-signed by a publisher it trusts nor
already known to Microsoft's cloud. None of the patch's DLLs is signed (the loader dinput8.dll, every plugin in
ReBalanceOfSouls\\, studio.dll, the patched SPFXEngine.dll), and every build is a file the cloud has never seen. The game
then stops as it starts with "Bad Image ... DINPUT8.dll ... 0xc0e90002" ("Imagen incorrecta" on a Spanish Windows).
Windows has no per-file exception: the player's only fix is to turn Smart App Control off, once, in Windows Security.

This module only READS the setting, and on the player's request opens the Windows Security page where it is changed.
It never changes the setting itself: Microsoft documents changing it outside Windows Security as for testing only.

The state (Microsoft Learn, "Test your app with Smart App Control"):
HKLM\\SYSTEM\\CurrentControlSet\\Control\\CI\\Policy, VerifiedAndReputablePolicyState (REG_DWORD):
0 off, 1 on (enforced), 2 evaluation.
- Only 1 blocks anything. In evaluation nothing is blocked yet; if it ever switches itself on, the next start finds 1.
- No value (Windows 10, an older Windows 11) means there is no Smart App Control: nothing to say.

The message is laid out line by line: every line is at most WIDTH characters, so the Windows message box never wraps
a line on its own (it did with long lines: a phrase broken in two, a word left alone on its line).

BROS_SAC_STATE=0, 1 or 2 in the environment stands in for the registry, to see the message on a PC where it is off.
"""
from __future__ import annotations

import os

OFF, ON, EVALUATION = 0, 1, 2
KEY = r"SYSTEM\CurrentControlSet\Control\CI\Policy"
VALUE = "VerifiedAndReputablePolicyState"
PAGE = "windowsdefender://smartapp/"          # Windows Security, Smart App Control (Windows 11)
OVERRIDE = "BROS_SAC_STATE"
WIDTH = 48                                    # the longest line the message may have

TITLE = "Smart App Control is on"
TEXT = "\n".join([
    "Windows Smart App Control is turned on.",
    "",
    "It blocks the patch's files: the game will",
    "not start, and Windows shows a \"Bad Image\"",
    "error about DINPUT8.dll (0xc0e90002).",
    "",
    "Turn it off once and it stays off:",
    "1. Press Yes to open Smart App Control.",
    "2. Select Off (not Evaluation).",
    "3. Then start the game again.",
    "",
    "Yes: open Smart App Control",
    "No: start the game anyway",
    "Cancel: do nothing",
])
MANUAL = "\n".join([
    "Windows Security could not be opened from here.",
    "",
    "Open Windows Security from the Start menu, then:",
    "App & browser control",
    "> Smart App Control settings",
    "> Off",
])


def state():
    """0 off, 1 on, 2 evaluation; None when there is no Smart App Control to read (not Windows, no value)."""
    forced = os.environ.get(OVERRIDE, "").strip()
    if forced in ("0", "1", "2"):
        return int(forced)
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY) as k:
            value, kind = winreg.QueryValueEx(k, VALUE)
    except OSError:
        return None
    if kind != winreg.REG_DWORD or value not in (OFF, ON, EVALUATION):
        return None
    return value


def open_page():
    """Windows Security on its Smart App Control page. True when Windows took the request."""
    try:
        os.startfile(PAGE)
        return True
    except Exception as e:        # no Windows Security app, or not Windows
        print(f"[sac] could not open {PAGE}: {e}")
        return False


def ok_to_start(messagebox):
    """Asked by launch_patched before the game starts: True starts it, False does not start it now.

    messagebox is tkinter.messagebox (askyesnocancel, showinfo). Nothing is asked unless Smart App Control is on."""
    if state() != ON:
        return True
    print("[sac] Smart App Control is on: it blocks the patch's DLLs -- asking the player")
    answer = messagebox.askyesnocancel(TITLE, TEXT, icon="warning")
    if answer is True:
        if not open_page():
            messagebox.showinfo(TITLE, MANUAL)
        print("[sac] the Smart App Control page was offered; the game was NOT started")
        return False
    if answer is False:
        print("[sac] the player starts the game anyway")
        return True
    print("[sac] cancelled; the game was NOT started")
    return False
