"""bigfiles.py : the version's files above GitHub's 100 MB limit, shipped in parts and put together here.

GitHub refuses a blob over 100 MB. Git LFS was the way around it until 2026-11-27, and it had two costs on a public
repository: every player's download is charged to the owner's LFS quota (quota spent = the update is refused for
everyone), and a player without git-lfs gets 1 KB placeholders instead of the files. So the release tree holds no LFS
file: each file over the limit is cut into parts, plain blobs under BigFiles/, and BigFiles/manifest.json names them:

    {"version": 1, "files": [{"path": "GameVersions/.../ui_Title_mdl.cat", "size": 223177728, "sha256": "ae1f...",
                              "mtime": 1234567890, "parts": ["ae1f2dbe8a4a19a9.00", "ae1f2dbe8a4a19a9.01", ...]}]}

ensure() writes every file that is not in place: its parts, in order, into a temporary file under BigFiles/, the size
and the sha256 checked against the manifest, then moved to the path in one step (os.replace) with the manifest's time.
Nothing half-written is ever at the path. "In place" = the file is there with the manifest's size and time: `mtime` is
a stamp made from the file's sha256, so other bytes of the same size carry another time and are written again, and no
record has to be kept beside the manifest. The assembled paths are untracked and named in .gitignore: `git reset
--hard` and `git clean -fd` leave them alone and `git status` stays clean.

A checkout without BigFiles/manifest.json (the dev repository, where those files are LFS files) has nothing to do.

The launcher calls it at its start, behind the update window when there is something to write (ensure_shown: after an
update that is about 1 GB), and again at every launch before anything is installed (ensure). The install walks the
version's folders: a file that is not there is silently not installed, and the previous version's -- or the game's
own -- stays in the game folder. So both callers stop on BigFilesError.

    python launcher/bigfiles.py [<checkout>]        assemble what is not in place, and say what was done
"""
import hashlib
import json
import os
import sys

DIR = "BigFiles"
MANIFEST = "manifest.json"


class BigFilesError(Exception):
    pass


def _path(base, rel):
    return os.path.join(base, *rel.split("/"))


def manifest(base):
    """The manifest's files; [] when the checkout ships none."""
    p = os.path.join(base, DIR, MANIFEST)
    if not os.path.isfile(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            files = json.load(f)["files"]
        return [{"path": str(e["path"]), "size": int(e["size"]), "sha256": str(e["sha256"]), "mtime": int(e["mtime"]),
                 "parts": [str(x) for x in e["parts"]]} for e in files]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise BigFilesError("%s cannot be read: %s" % (p, e))


def in_place(base, e):
    try:
        st = os.stat(_path(base, e["path"]))
    except OSError:
        return False
    return st.st_size == e["size"] and abs(st.st_mtime - e["mtime"]) < 2      # FAT and exFAT keep a time to 2 s


def pending(base):
    """The manifest's files that are not in place."""
    return [e for e in manifest(base) if not in_place(base, e)]


def ensure(base, progress=None):
    """Write every file that is not in place; progress(bytes written so far). Returns how many were written.
    BigFilesError when one cannot be: its path then holds what it held before, or nothing."""
    todo = pending(base)
    done = 0
    for e in todo:
        tmp = os.path.join(base, DIR, e["sha256"][:16] + ".tmp")
        h, n = hashlib.sha256(), 0
        try:
            with open(tmp, "wb") as out:
                for part in e["parts"]:
                    with open(os.path.join(base, DIR, part), "rb") as f:
                        for chunk in iter(lambda: f.read(1 << 20), b""):
                            out.write(chunk)
                            h.update(chunk)
                            n += len(chunk)
                            if progress:
                                progress(done + n)
            if n != e["size"] or h.hexdigest() != e["sha256"]:
                raise BigFilesError("%s: the parts in %s do not give the file the update names (%d bytes read, %d "
                                    "expected)" % (e["path"], DIR, n, e["size"]))
            os.utime(tmp, (e["mtime"], e["mtime"]))
            dst = _path(base, e["path"])
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(tmp, dst)
        except OSError as x:
            raise BigFilesError("%s could not be written: %s" % (e["path"], x))
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        done += n
    return len(todo)


def ensure_shown(base, title="Bleach Rebirth of Souls: update"):
    """ensure(), behind the update window (launcher/update_window.py) when there is something to write. The window
    says "Updating files", as it does for the checkout's own files, with the measure of what is written."""
    todo = pending(base)
    if not todo:
        return 0
    try:
        try:
            from launcher import update_window as uw
        except ImportError:
            import update_window as uw
        prog = uw.Progress()
        prog.set(phase="Updating files", detail="", done=0, total=sum(e["size"] for e in todo), cancellable=False)
        win = uw._Window(None, title, prog)
    except Exception:
        win = None
    if win is None or not win.ok:
        return ensure(base)
    win.show_now()
    box = {}

    def work():
        try:
            box["n"] = ensure(base, lambda done: prog.set(done=done))
        except BaseException as e:      # handed to the caller on the main thread, unchanged
            box["e"] = e

    win.run(work)
    if "e" in box:
        raise box["e"]
    return box["n"]


if __name__ == "__main__":
    _base = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        print("%d of %d file(s) written in %s" % (ensure(_base), len(manifest(_base)), _base))
    except BigFilesError as _e:
        sys.exit("not assembled: %s" % _e)
