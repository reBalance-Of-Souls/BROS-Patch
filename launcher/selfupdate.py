"""Re-run the launcher when the pull it just did brought an update.

The launcher pulls, then keeps going -- but Python compiled the script at
startup, so the code still executing is the code from *before* the pull. Fix a
launcher bug and a tester still runs the old one for that launch; they only get
the fix on the launch after, which is the launch where they no longer need it.
Same shape as a stale loader sitting in the game folder: the repo current, the
execution behind.

The public launcher does not need this. It resolves patch content through a
manifest at prepare() time, so new content applies to the launch that fetched it.
The launcher carries its own logic (as the standalone Quick Launch scripts did,
until 2026-11-06), so its code IS the thing that goes stale.

Usage, two lines around the existing pull:

    before = selfupdate.digest(__file__)
    pulling_from_git()
    selfupdate.relaunch_if_changed(__file__, before)

Two things this deliberately does NOT do:

* It never re-runs more than once. A guard env var is set before handing over, so
  a script that somehow always looks changed stops after one hop instead of
  spawning launchers forever. That failure mode is far worse than a stale launch.
* It does not use os.execv. On Windows execv goes through the CRT's own
  re-quoting, which mangles paths with spaces -- and every path here has one
  ("Bleach Rebirth of Souls Community Patch.py"). Running a child and exiting
  with its code keeps the argument list intact.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys

#: set on the child so it cannot relaunch in turn
GUARD = "BROS_LAUNCHER_RELAUNCHED"


def _head(script: str) -> str:
    """The commit the checkout holding `script` is on, or "" without git."""
    try:
        r = subprocess.run(["git", "-C", os.path.dirname(os.path.abspath(script)),
                            "rev-parse", "HEAD"], capture_output=True, text=True,
                           timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def digest(script: str) -> str:
    """Content hash of a script PLUS the commit it is checked out at, or "" if
    the script cannot be read.

    Hashing the bytes rather than reading a version or an mtime: a pull can
    rewrite a file to the same length, and mtime says when git touched it, not
    whether the code differs.

    The commit is in it because the script is not the only code that goes
    stale. Everything it imports from launcher/ (zangetsu_sync, this module) was
    compiled before the pull too, so until 2026-09-19 an update that fixed
    launcher/zangetsu_sync.py and left the Quick Launch file alone ran the OLD
    sync on the launch that fetched it. Any pull that moves HEAD now restarts
    the launcher; one that brings nothing costs nothing."""
    try:
        with open(script, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""
    return h + ":" + _head(script)


def relaunch_if_changed(script: str, before: str) -> None:
    """Hand over to the updated script. Returns only if nothing changed."""
    if os.environ.get(GUARD):
        return                                   # already the second run
    after = digest(script)
    if not before or not after or before == after:
        return
    b_head, a_head = before.partition(":")[2][:7], after.partition(":")[2][:7]
    print("Update pulled (%s -> %s) -- restarting the launcher so this launch "
          "runs the new code." % (b_head or "?", a_head or "?"))
    env = dict(os.environ)
    env[GUARD] = "1"
    try:
        rc = subprocess.call([sys.executable, os.path.abspath(script)] + sys.argv[1:],
                             env=env)
    except Exception as e:
        # Carrying on with the old code is still a launch; failing here is not.
        print("Could not restart the launcher (%s) -- continuing with the "
              "version that is already running." % e)
        return
    sys.exit(rc)
