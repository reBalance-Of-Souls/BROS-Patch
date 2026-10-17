"""diagnostics.py -- the launcher side of the online match recorder, "Online Match Diagnostics" in the launcher
(PART 43 "NETDIAG" of Files/Matchmaking/dinput8.dll). Version 1 2026-10-12; version 2 2026-10-16; version 3
2026-10-17: the player's switch is OFF unless the player turns it on, and the launcher calls it "Online Match
Diagnostics" (Berg, 2026-10-17; it was "Tournament diagnostics", ON by default). The internal names stay:
Diagnostics/tournament.txt, bros_diag.txt, the `tournament` key, the upload format.

WHY. Players report more connection trouble in the tournaments Berg hosts than in normal play. The loader records
how each battle ran (freezes, network timing, the PC's load and traffic, which kinds of program were open), and the
players send it in with one button.

TWO SWITCHES. The loader records only when both are on:
  1. Berg's, for everyone: Diagnostics/tournament.txt in the repository. A `key value` per line:
         on 1
         tournament 2026-10-16                      (letters, digits, - and _)
         salt <any text, new for each event>        (mixed into the match key the two seats share)
         upload https://<relay>/upload              (where "Send diagnostics" posts the zip)
     It has no time window: recording runs while it says `on 1`, and stops when Berg pushes `on 0` or removes the
     file (version 1 also had `from`/`until`; they are no longer passed to the loader).
  2. The player's own, on the Game Modes page ("Online Match Diagnostics"): kept in Json/diagnostics.json
     ({"DIAGNOSTICS": "ON"} or "OFF"), OFF when the file is missing (version 3; versions 1-2 read a missing file as
     ON). Only the player's own click writes the file, so a player who never touched the switch is OFF, and one who
     turned it ON stays ON. OFF means nothing runs on this PC: the launcher removes bros_diag.txt at once, as it
     opens (remove_if_off, version 3) and at every launch, and the loader never arms.
At every launch that installs the loader, sync_switch() writes <game>/bros_diag.txt from Berg's switch (everything
but `upload`, plus `commit <HEAD>`), or removes it when either switch is off. The loader reads bros_diag.txt once,
at game start, so a game started before a change keeps what it read.

THE DATA. The loader writes <game>/BROS_Diagnostics/diag_<UTC>_<pid>.jsonl, outside the repository, so the
launcher's `git clean` never touches it. There is no limit on the number or the length of the sessions it records
(version 1 stopped a session file at 64 MB). Nothing leaves the PC by itself.

SENDING. The main launcher's "Send diagnostics" button opens open_send_dialog(). It:
  - says what is included;
  - takes an optional pseudonym and comment;
  - zips the unsent sessions together with a scrubbed extract of patch_ranked.log's netcode lines;
  - POSTs the zip to the `upload` address, a relay that files it in a private repository.
The relay takes at most 20 MB per upload, so build_bundles() splits a larger send into parts of at most PART_LIMIT
each, all with the same `batch` id in meta.json; a single session too large for one part is cut, at line ends,
into chunks with their offsets and checksums. Sessions count as sent only when every part got through. A session
the game is still writing is sent as far as it was read, and offered again once it has grown. If the upload fails,
or no address is set, the parts can be saved to the Desktop instead, for sending by hand.

PRIVACY (Berg, 2026-10-12: fully anonymous, a pseudonym only if the player wants one). Neither the loader's
files nor this bundle carry:
  - a Steam ID, a name, an IP address;
  - the machine's name, a path, a list of programs.
The log extract keeps only the netcode lines. Every long number in it becomes <id>, every IPv4 address <ip>,
and every drive path <path>. Its clock times are converted to UTC, and the zip's entries carry a fixed date, so an
upload does not tell the sender's time zone (the Dev test run of 2026-10-12 showed that it did).

Standard library only; never raises into a launch: sync_switch_safe() returns a message instead.
"""
import datetime
import hashlib
import io
import json
import os
import platform
import re
import subprocess
import threading
import time
import uuid
import zipfile
import zlib

SWITCH_REPO = os.path.join("Diagnostics", "tournament.txt")
SWITCH_GAME = "bros_diag.txt"
DATA_DIR = "BROS_Diagnostics"
SENT_DIR = "sent"
BUNDLE_FORMAT = "bros-diag-bundle 1"   # the relay checks this header; meta.json's "bundle" says 2 for parted sends
MAX_UPLOAD = 20 * 1024 * 1024          # the relay refuses more
PART_LIMIT = 18 * 1024 * 1024          # what build_bundles() aims a part at: 2 MB under the relay's limit
CHUNK_LIMIT = 16 * 1024 * 1024         # the compressed size of one cut piece of a session
SWITCH_KEYS = ("tournament", "salt")   # version 1 also passed from/until; there is no time window any more
LOG_KEEP = ("] NET/", "] NET:", "] PACING:", "] NETDIAG:", "] PATCHSTAMP")
CHOICE_NAME = "diagnostics.json"       # Json/diagnostics.json: {"DIAGNOSTICS": "ON"} or {"DIAGNOSTICS": "OFF"}
DIALOG_WIDTH = 600                     # the Send window's fixed size (version 3); its page scrolls
DIALOG_HEIGHT = 640                    # at most this tall, or the screen's height less 140 px
DIALOG_MIN_HEIGHT = 420
DEFAULT_ON = False                     # version 3 (2026-10-17): OFF unless the player turns it on


class DiagnosticsError(Exception):
    """Something the player should read: shown as it is in the dialog."""


# ---------------------------------------------------------------- the player's switch (Game Modes)
def choice_path(base_dir):
    return os.path.join(base_dir, "Json", CHOICE_NAME)


def load_choice(base_dir):
    """True = the player's switch is ON. A missing, unreadable or unexpected Json/diagnostics.json reads as
    DEFAULT_ON."""
    try:
        with open(choice_path(base_dir), "r", encoding="utf-8") as f:
            v = json.load(f).get("DIAGNOSTICS")
    except Exception:
        return DEFAULT_ON
    if v == "ON":
        return True
    if v == "OFF":
        return False
    return DEFAULT_ON


def save_choice(base_dir, on):
    """Keep the player's switch in Json/diagnostics.json (through a temporary file). Raises DiagnosticsError if it
    does not read back."""
    path = choice_path(base_dir)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"DIAGNOSTICS": "ON" if on else "OFF"}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise DiagnosticsError("could not save the diagnostics switch in %s (%s)" % (path, e))
    if load_choice(base_dir) != bool(on):
        raise DiagnosticsError("the diagnostics switch did not read back from %s" % path)


# ---------------------------------------------------------------- Berg's switch
def read_switch(base_dir):
    """Diagnostics/tournament.txt as a dict of lower-case keys, or None when the repository has none."""
    path = os.path.join(base_dir, SWITCH_REPO)
    if not os.path.isfile(path):
        return None
    out = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            out[parts[0].lower()] = parts[1].strip() if len(parts) > 1 else ""
    return out


def switch_is_on(sw):
    return bool(sw) and sw.get("on", "0").strip() == "1"


def _git_head(base_dir):
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        r = subprocess.run(["git", "-C", base_dir, "rev-parse", "HEAD"], capture_output=True, text=True,
                           timeout=15, **kw)
        head = r.stdout.strip()
        return head if re.fullmatch(r"[0-9a-f]{40}", head) else ""
    except Exception:
        return ""


def _write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    with open(path, encoding="utf-8") as f:
        if f.read() != text:
            raise DiagnosticsError("%s did not read back as written" % path)


def _remove_game_switch(target, why):
    if os.path.exists(target):
        os.remove(target)
        return "recording off -- %s (bros_diag.txt removed)" % why
    return "recording off -- %s" % why


def sync_switch(base_dir, game_path):
    """Put Berg's switch beside the game exe, or take it away when either switch is off. Returns what it did."""
    target = os.path.join(game_path, SWITCH_GAME)
    if not load_choice(base_dir):
        return _remove_game_switch(target, "Online Match Diagnostics is off on this PC (Game Modes)")
    sw = read_switch(base_dir)
    if not switch_is_on(sw):
        return _remove_game_switch(target, "no tournament is on")
    lines = ["# bros_diag.txt -- written by the launcher from Diagnostics/tournament.txt at every launch;",
             "# the loader (PART 43) reads it once, at game start. Do not edit: the next launch rewrites it.",
             "on 1"]
    for k in SWITCH_KEYS:
        v = sw.get(k, "").replace("\r", " ").replace("\n", " ").strip()
        if v:
            lines.append("%s %s" % (k, v))
    head = _git_head(base_dir)
    if head:
        lines.append("commit " + head)
    _write_atomic(target, "\n".join(lines) + "\n")
    return "recording ON for tournament '%s'" % sw.get("tournament", "?")


def sync_switch_safe(base_dir, game_path):
    """sync_switch() that never raises: a diagnostics problem must never stop a launch."""
    try:
        return sync_switch(base_dir, game_path)
    except Exception as e:
        return "the switch could not be synced (%s); this game records nothing" % e


def remove_if_off(base_dir, game_path):
    """Version 3: when the player's switch reads OFF, take away a bros_diag.txt left beside the game. A PC updated
    from version 2, which read a missing choice as ON, still holds the file of its last launch, and the loader
    would arm from it in a game started straight from the exe. The main page calls this as the launcher opens, so
    its "nothing is recorded" holds from then on, not only from the next launch. It only removes, never writes,
    and never raises."""
    try:
        if load_choice(base_dir):
            return "Online Match Diagnostics is on: bros_diag.txt is left to the next launch"
        if not game_path or not os.path.isdir(game_path):
            return "no game folder: nothing to remove"
        return _remove_game_switch(os.path.join(game_path, SWITCH_GAME),
                                   "Online Match Diagnostics is off on this PC (Game Modes)")
    except Exception as e:
        return "bros_diag.txt could not be checked (%s)" % e


def set_choice(base_dir, game_path, on):
    """The Game Modes button: keep the player's choice and apply it to the game folder now (OFF removes
    bros_diag.txt at once, so even a game started from the exe records nothing). Raises DiagnosticsError only when
    the choice itself could not be saved; returns what was done to the game folder."""
    save_choice(base_dir, on)
    return sync_switch_safe(base_dir, game_path)


# ---------------------------------------------------------------- the data
def data_dir(game_path):
    return os.path.join(game_path, DATA_DIR)


def _sent_marker(path):
    return path + ".sent"


def pending_sessions(game_path):
    """[(path, bytes)] of the session files not sent yet, oldest first."""
    d = data_dir(game_path)
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if not (name.startswith("diag_") and name.endswith(".jsonl") and os.path.isfile(p)):
            continue
        size = os.path.getsize(p)
        if size == 0:
            continue
        mk = _sent_marker(p)
        if os.path.isfile(mk):
            try:
                with open(mk, encoding="utf-8") as f:
                    if int(f.read().strip() or "-1") == size:
                        continue           # sent, and not grown since
            except Exception:
                pass
        out.append((p, size))
    return out


def summarize(path):
    """What the dialog lists for one session: start (UTC), battles, tournament."""
    info = {"name": os.path.basename(path), "bytes": os.path.getsize(path), "battles": 0, "tournament": "",
            "start": ""}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"t":"b1"' in line:
                    info["battles"] += 1
                elif line.startswith('{"t":"h"'):
                    try:
                        h = json.loads(line)
                        info["tournament"] = h.get("tour", "")
                        utc = h.get("utc", 0)
                        if utc:
                            info["start"] = datetime.datetime.fromtimestamp(
                                utc / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                    except Exception:
                        pass
    except OSError:
        pass
    return info


_RE_LONGNUM = re.compile(r"\b\d{15,20}\b")
_RE_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# A drive path, spaces included ("C:\Users\John Smith\...\diag_x.jsonl"): up to the first file extension of the kinds
# the loader names, or to the end of the line when there is none. (Fixed 2026-10-12: the first version stopped at the
# first space and left the rest of such a path -- a user name included -- in the extract.)
_RE_PATH = re.compile(r"[A-Za-z]:[\\/][^\r\n]*?\.(?:jsonl|json|txt|log|dll|exe|dmp|ini|cfg)\b|[A-Za-z]:[\\/][^\r\n]*")


def scrub(line):
    line = _RE_PATH.sub("<path>", line)
    line = _RE_LONGNUM.sub("<id>", line)
    return _RE_IPV4.sub("<ip>", line)


_RE_STAMP = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]")


def _utc_offset_s():
    """This PC's offset from UTC right now, in seconds (local time = UTC + offset); 0 if unknown."""
    try:
        return int(time.localtime().tm_gmtoff or 0)
    except Exception:
        return 0


def to_utc(line, offset_s):
    """A log line's leading "[HH:MM:SS.mmm]" (the PC's local clock) as UTC. The log has no dates, so the offset in
    force now is used for every line: lines written before a daylight-saving change are an hour off. Lines without
    a time are returned unchanged."""
    m = _RE_STAMP.match(line)
    if not m:
        return line
    h, mi, s, ms = (int(x) for x in m.groups())
    t = (h * 3600 + mi * 60 + s - offset_s) % 86400
    return "[%02d:%02d:%02d.%03d]" % (t // 3600, t % 3600 // 60, t % 60, ms) + line[m.end():]


def log_extract(game_path, limit=8 * 1024 * 1024):
    """The netcode lines of patch_ranked.log(.1), scrubbed and with their clock times in UTC; '' when there is no
    log."""
    out = []
    offset = _utc_offset_s()
    for name in ("patch_ranked.log.1", "patch_ranked.log"):
        p = os.path.join(game_path, name)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "rb") as f:
                size = os.path.getsize(p)
                if size > limit:
                    f.seek(size - limit)
                data = f.read().decode("utf-8", "replace")
        except OSError:
            continue
        out.append("===== %s (last %d bytes at most; clock times in UTC) =====" % (name, limit))
        for line in data.splitlines():
            if any(k in line for k in LOG_KEEP) and "ROOM3" not in line:
                out.append(scrub(to_utc(line, offset)))
    return "\n".join(out) + ("\n" if out else "")


ZIP_DATE = (1980, 1, 1, 0, 0, 0)   # every entry's date: a zip stores local clock time, which tells the time zone


def _zput(z, name, data):
    zi = zipfile.ZipInfo(name, date_time=ZIP_DATE)
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o600 << 16
    z.writestr(zi, data)


def _deflated_size(data):
    """What `data` costs inside a zip, about: zipfile deflates at zlib's default level."""
    c = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
    return len(c.compress(data)) + len(c.flush())


def _cut(data, limit):
    """Cut a session's bytes at line ends into pieces each deflating to at most `limit`. Returns [(offset, bytes)]."""
    pieces = []
    pos = 0
    n = len(data)
    while pos < n:
        size = _deflated_size(data[pos:])
        if size <= limit:
            pieces.append((pos, data[pos:]))
            break
        span = max(1, int((n - pos) * (limit / float(size)) * 0.9))
        while True:
            end = data.rfind(b"\n", pos, pos + span)
            end = (end + 1) if end >= pos else min(n, pos + span)   # a line longer than the span is cut inside it
            if _deflated_size(data[pos:end]) <= limit or end - pos <= 1:
                break
            span = max(1, span // 2)
        pieces.append((pos, data[pos:end]))
        pos = end
    return pieces


def read_sessions(files):
    """Each session's bytes as they are now: {path: bytes}. A session the game is still writing is taken as far
    as it has been written."""
    out = {}
    for p in files:
        with open(p, "rb") as f:
            out[p] = f.read()
    return out


def build_bundles(base_dir, game_path, snapshot, pseudonym="", comment="", part_limit=None, chunk_limit=None):
    """The zips that are sent: [bytes, ...], each at most part_limit (PART_LIMIT) and so under the relay's
    MAX_UPLOAD. snapshot: {path: bytes} from read_sessions(). Every part carries meta.json with the same `batch`
    id, its `part` number and the number of `parts`; part 1 also carries the log extract. A session that fits
    goes whole into one part (sessions/<name>); one that does not is cut at line ends into chunks
    (sessions/<name>.chunk<k>of<m>), each listed with its offset and checksum and the whole session's checksum."""
    part_limit = part_limit or PART_LIMIT
    chunk_limit = chunk_limit or min(CHUNK_LIMIT, part_limit - 512 * 1024)
    batch = uuid.uuid4().hex
    created = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commit = _git_head(base_dir)
    common = {"format": BUNDLE_FORMAT, "bundle": 2, "batch": batch, "created_utc": created,
              "launcher_commit": commit, "pseudonym": (pseudonym or "").strip()[:40],
              "comment": (comment or "").strip()[:4000], "python": platform.python_version()}
    extract = log_extract(game_path).encode("utf-8")
    # the items to pack: (zip name, bytes, entry for meta.json, deflated size)
    items = []
    for p in sorted(snapshot):
        data = snapshot[p]
        name = os.path.basename(p)
        whole = {"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        s = summarize_bytes(data)
        whole.update({"battles": s["battles"], "tournament": s["tournament"]})
        size = _deflated_size(data)
        if size <= chunk_limit:
            items.append(("sessions/" + name, data, dict(whole), size))
            continue
        pieces = _cut(data, chunk_limit)
        for k, (off, piece) in enumerate(pieces, 1):
            e = dict(whole)
            e.update({"chunk": k, "chunks": len(pieces), "offset": off, "chunk_bytes": len(piece),
                      "chunk_sha256": hashlib.sha256(piece).hexdigest()})
            items.append(("sessions/%s.chunk%dof%d" % (name, k, len(pieces)), piece, e, _deflated_size(piece)))
    # pack in order; part 1 starts with the log extract
    overhead = 64 * 1024                 # meta.json, headers and the central directory, with room to spare
    parts = [[]]
    used = _deflated_size(extract) + overhead
    for it in items:
        cost = it[3] + 512
        if parts[-1] and used + cost > part_limit:
            parts.append([])
            used = overhead
        parts[-1].append(it)
        used += cost
    out = []
    for i, part in enumerate(parts, 1):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for zname, data, entry, _ in part:
                _zput(z, zname, data)
            if i == 1:
                _zput(z, "log_extract.txt", extract)
            meta = dict(common)
            meta.update({"part": i, "parts": len(parts), "files": [e for _, _, e, _ in part]})
            _zput(z, "meta.json", json.dumps(meta, indent=1, sort_keys=True))
        b = buf.getvalue()
        if len(b) > MAX_UPLOAD:
            raise DiagnosticsError("A part of the diagnostics came out too large to upload (%.1f MB). Save the zip "
                                   "instead." % (len(b) / 1048576.0))
        out.append(b)
    return out


def summarize_bytes(data):
    """summarize() for bytes already read: battles and tournament."""
    info = {"battles": 0, "tournament": ""}
    for line in data.split(b"\n"):
        if b'"t":"b1"' in line:
            info["battles"] += 1
        elif line.startswith(b'{"t":"h"') and not info["tournament"]:
            try:
                info["tournament"] = json.loads(line.decode("utf-8", "replace")).get("tour", "")
            except Exception:
                pass
    return info


def build_bundle(base_dir, game_path, files, pseudonym="", comment=""):
    """Version 1's single zip, for a send that fits in one part: the zip's bytes. Raises DiagnosticsError when the
    sessions need more than one part (use build_bundles)."""
    parts = build_bundles(base_dir, game_path, read_sessions(files), pseudonym, comment)
    if len(parts) != 1:
        raise DiagnosticsError("The diagnostics need %d uploads; use build_bundles()." % len(parts))
    return parts[0]


def upload(bundle, url, tournament=""):
    """POST the zip to the relay. Returns its receipt; raises DiagnosticsError with a readable reason."""
    import urllib.error
    import urllib.request
    if not url or not url.lower().startswith("https://"):
        raise DiagnosticsError("No upload address is set.")
    if len(bundle) > MAX_UPLOAD:
        raise DiagnosticsError("The diagnostics are too large to upload (%.1f MB). Save the zip instead."
                               % (len(bundle) / 1048576.0))
    tour = re.sub(r"[^A-Za-z0-9_.-]", "", tournament or "")[:40] or "none"
    req = urllib.request.Request(url, data=bundle, method="POST", headers={
        "Content-Type": "application/zip",
        "X-BROS-Format": BUNDLE_FORMAT,
        "X-BROS-Tournament": tour,
        "User-Agent": "BROS-Launcher-Diagnostics/2",
    })
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read(8192)
    except urllib.error.HTTPError as e:
        raise DiagnosticsError("The upload was refused (HTTP %d). Save the zip instead." % e.code)
    except Exception as e:
        raise DiagnosticsError("The upload did not get through (%s). Save the zip instead." % e)
    try:
        answer = json.loads(body.decode("utf-8"))
    except Exception:
        raise DiagnosticsError("The upload server gave an unreadable answer. Save the zip instead.")
    if not answer.get("ok"):
        raise DiagnosticsError("The upload server said no (%s). Save the zip instead." % answer.get("error", "?"))
    return str(answer.get("receipt", ""))


def upload_all(bundles, url, tournament="", progress=None):
    """Upload every part, in order. Returns the receipts. If a part fails, raises DiagnosticsError saying how many
    got through; nothing is marked sent then, and the next Send sends everything again."""
    receipts = []
    for i, b in enumerate(bundles, 1):
        if progress:
            progress(i, len(bundles))
        try:
            receipts.append(upload(b, url, tournament))
        except DiagnosticsError as e:
            if len(bundles) == 1:
                raise
            raise DiagnosticsError("Part %d of %d did not get through: %s" % (i, len(bundles), e))
    return receipts


def desktop_dir():
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and os.path.isdir(buf.value):
                return buf.value                   # CSIDL_DESKTOPDIRECTORY: follows a OneDrive redirection
        except Exception:
            pass
    d = os.path.join(os.path.expanduser("~"), "Desktop")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def save_bundle(bundle, folder=None, part=1, parts=1):
    folder = folder or desktop_dir()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    name = ("BROS_diagnostics_%s.zip" % stamp) if parts == 1 else ("BROS_diagnostics_%s_part%dof%d.zip"
                                                                    % (stamp, part, parts))
    path = os.path.join(folder, name)
    with open(path + ".tmp", "wb") as f:
        f.write(bundle)
    os.replace(path + ".tmp", path)
    return path


def save_bundles(bundles, folder=None):
    """Every part to the Desktop (or `folder`); returns the paths."""
    return [save_bundle(b, folder, i, len(bundles)) for i, b in enumerate(bundles, 1)]


def mark_sent(game_path, sent):
    """sent: {path: bytes sent} (a list of paths means "as they are now", as in version 1). A session that has not
    grown since it was read moves to sent/; one the game still holds open, or that grew, gets a .sent marker with
    the size that was sent, so it is offered again once it grows."""
    if not isinstance(sent, dict):
        sent = {p: os.path.getsize(p) for p in sent if os.path.isfile(p)}
    folder = os.path.join(data_dir(game_path), SENT_DIR)
    os.makedirs(folder, exist_ok=True)
    for p, size in sent.items():
        try:
            if os.path.getsize(p) != size:
                raise OSError("grown since it was read")
            os.replace(p, os.path.join(folder, os.path.basename(p)))
            mk = _sent_marker(p)
            if os.path.exists(mk):
                os.remove(mk)
        except OSError:
            try:
                _write_atomic(_sent_marker(p), "%d\n" % size)
            except Exception:
                pass


def status_text(base_dir, game_path):
    """One line for the launcher's main page."""
    try:
        pend = pending_sessions(game_path)
        sw = read_switch(base_dir)
        mine = load_choice(base_dir)
    except Exception:
        return "", False
    if pend:
        n = len(pend)
        return ("%d recorded session%s waiting to be sent -- thank you for helping!" % (n, "" if n == 1 else "s"),
                True)
    if not mine:
        return "Online Match Diagnostics are OFF on this PC: nothing is recorded. You can turn them on in " \
               "Game Modes.", False
    if switch_is_on(sw):
        return "Recording is ON ('%s'). Nothing leaves your PC until you click Send." \
               % sw.get("tournament", "?"), False
    return "Nothing is being recorded: recording is switched off for now.", False


# ---------------------------------------------------------------- the dialog
CONSENT = (
    "While Online Match Diagnostics is on (Game Modes page; it is off unless you turn it on), the patch records "
    "how your online matches run, so we can find and fix lag, freezes and disconnects. You can turn it off again "
    "at any time.\n\n"
    "What is included: per second of each battle, freezes, frame timing, network timing and packet counts; "
    "your PC's CPU load and total network traffic; your hardware (CPU, GPU, RAM, Windows version, Wi-Fi or "
    "cable and its signal); yes/no flags for kinds of programs that were open (streaming, Discord, browsers, "
    "downloads...); the netcode lines of the patch's log.\n\n"
    "What is NOT included: your name, Steam ID, IP address, chat, files, or the names of your programs. "
    "Matches are matched up through an anonymous room key.\n\n"
    "Sending is optional. The data is stored privately for the patch developers and deleted after the "
    "analysis.")


def open_send_dialog(parent, base_dir, game_path, theme=None, on_done=None):
    """The "Send diagnostics" window (modal). theme: optional colours and fonts of the launcher."""
    import tkinter as tk
    th = {"bg": "#241129", "panel": "#2e1736", "fg": "#f1e4f5", "muted": "#b9a3c4", "gold": "#e6b450",
          "button_bg": "#3a2144", "font": ("Segoe UI", 10), "small": ("Segoe UI", 9),
          "title": ("Segoe UI", 13, "bold")}
    th.update(theme or {})
    sw = read_switch(base_dir) or {}
    url = sw.get("upload", "")
    pend = pending_sessions(game_path)
    infos = [summarize(p) for p, _ in pend]

    win = tk.Toplevel(parent)
    win.title("Send diagnostics")
    win.configure(bg=th["bg"])
    win.transient(parent)
    win.resizable(False, False)
    pad = {"padx": 14}
    # A fixed size (version 3): the window no longer grows with the number of sessions. Its page scrolls; the
    # status line and the buttons below it stay in view.
    win_w = DIALOG_WIDTH                 # widened at the end if the page asks for more (large fonts, high DPI)
    try:
        win_h = max(DIALOG_MIN_HEIGHT, min(DIALOG_HEIGHT, win.winfo_screenheight() - 140))
    except Exception:
        win_h = DIALOG_HEIGHT

    tk.Label(win, text="Send diagnostics", font=th["title"], bg=th["bg"], fg=th["gold"]).pack(anchor="w", pady=(12, 4), **pad)

    body = tk.Frame(win, bg=th["bg"])
    page_canvas = tk.Canvas(body, bg=th["bg"], highlightthickness=0, borderwidth=0, yscrollincrement=20)
    page_bar = tk.Scrollbar(body, orient="vertical", command=page_canvas.yview)
    page_canvas.configure(yscrollcommand=page_bar.set)
    page = tk.Frame(page_canvas, bg=th["bg"])
    page_item = page_canvas.create_window((0, 0), window=page, anchor="nw")
    page_canvas.pack(side="left", fill="both", expand=True)
    page_state = {"bar": False}

    def page_layout(_event=None):
        page_canvas.itemconfigure(page_item, width=page_canvas.winfo_width())
        page_canvas.configure(scrollregion=(0, 0, page.winfo_reqwidth(), page.winfo_reqheight()))
        need = page.winfo_reqheight() > page_canvas.winfo_height() + 1
        if need and not page_state["bar"]:
            page_bar.pack(side="right", fill="y")
            page_state["bar"] = True
        elif not need and page_state["bar"]:
            page_bar.pack_forget()
            page_state["bar"] = False
            page_canvas.yview_moveto(0)

    page.bind("<Configure>", page_layout)
    page_canvas.bind("<Configure>", page_layout)

    def wheel_units(event):
        # Tk's own step for a scroll bar (scrlbar.tcl): -delta/30 units, rounded away from zero, so a notch (delta
        # 120) is 4 units of 20 px. X11 sends buttons 4 and 5 instead.
        num = getattr(event, "num", None)
        if num == 4:
            return -4
        if num == 5:
            return 4
        d = int(getattr(event, "delta", 0) or 0)
        return (-d) // 30 if d >= 0 else (29 - d) // 30

    wheel_box = {"y": None}

    def wheel_mark(event):
        wheel_box["y"] = event.widget.yview()    # the comment box before its own class binding scrolls it
        return None

    def page_wheel(event):
        # Always "break": nothing behind the dialog may scroll (the launcher's main window binds the wheel for all
        # widgets with bind_all). The comment box scrolls itself while it can; then the page takes over.
        if isinstance(event.widget, tk.Text) and event.widget.yview() != wheel_box["y"]:
            return "break"
        if page_state["bar"]:
            page_canvas.yview_scroll(wheel_units(event), "units")
        return "break"

    # Bound on the window itself: every widget of the dialog carries the window in its bind tags, so the wheel
    # scrolls the page wherever the pointer is in the dialog, and the binding goes with the window (no global
    # binding to undo). The bar gets it as its own binding, which replaces its class binding's step (no double
    # scroll); the comment box notes where it stood (wheel_mark, below), so page_wheel can tell whether it moved.
    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        win.bind(seq, page_wheel)
        page_bar.bind(seq, page_wheel)

    tk.Label(page, text=CONSENT, font=th["small"], bg=th["bg"], fg=th["fg"], wraplength=520,
             justify="left").pack(anchor="w", **pad)

    box = tk.Frame(page, bg=th["panel"], padx=10, pady=6)
    box.pack(fill="x", pady=(10, 6), **pad)
    if infos:
        tk.Label(box, text="Sessions to send (%d):" % len(infos), font=th["small"], bg=th["panel"],
                 fg=th["gold"]).pack(anchor="w")
        for i in infos:                      # every session: the page scrolls (version 2 listed 12)
            line = "  %s   %d battle%s   %d KB%s" % (i["start"] or i["name"], i["battles"],
                                                    "" if i["battles"] == 1 else "s", max(1, i["bytes"] // 1024),
                                                    ("   (" + i["tournament"] + ")") if i["tournament"] else "")
            tk.Label(box, text=line, font=th["small"], bg=th["panel"], fg=th["fg"]).pack(anchor="w")
    else:
        tk.Label(box, text="No recorded sessions are waiting to be sent.", font=th["small"], bg=th["panel"],
                 fg=th["muted"]).pack(anchor="w")

    form = tk.Frame(page, bg=th["bg"])
    form.pack(fill="x", pady=(0, 6), **pad)
    tk.Label(form, text="Pseudonym (optional -- leave empty to stay anonymous):", font=th["small"], bg=th["bg"],
             fg=th["muted"]).pack(anchor="w")
    name_var = tk.StringVar()
    tk.Entry(form, textvariable=name_var, font=th["font"], width=40).pack(anchor="w", pady=(0, 6))
    tk.Label(form, text="Anything you noticed? Which matches felt laggy? (optional)", font=th["small"],
             bg=th["bg"], fg=th["muted"]).pack(anchor="w")
    comment = tk.Text(form, height=4, width=64, font=th["small"], wrap="word")
    comment.pack(anchor="w")
    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        comment.bind(seq, wheel_mark)         # runs before the box's class binding; page_wheel runs after it

    # The buttons and the status line are packed from the bottom first, so the scrolling page takes only the
    # height left over and the buttons are never pushed out of the window.
    buttons = tk.Frame(win, bg=th["bg"])
    buttons.pack(side="bottom", fill="x", pady=(4, 12), **pad)
    status = tk.Label(win, text="" if url else "No upload address is set: you can save the zip and send it by hand.",
                      font=th["small"], bg=th["bg"], fg=th["muted"], wraplength=520, justify="left")
    status.pack(side="bottom", anchor="w", pady=(8, 2), **pad)
    body.pack(side="top", fill="both", expand=True)
    state = {"busy": False, "result": None, "progress": ""}

    def files():
        return [p for p, _ in pend]

    def set_busy(b):
        state["busy"] = b
        for w in (send_btn, save_btn, close_btn):
            w.config(state="disabled" if b else "normal")
        if not infos:
            send_btn.config(state="disabled")
            save_btn.config(state="disabled")
        if not url:
            send_btn.config(state="disabled")

    def poll():
        r = state["result"]
        if r is None:
            if state["progress"]:
                status.config(text=state["progress"], fg=th["muted"])
            win.after(150, poll)
            return
        state["result"] = None
        kind, value, sent = r
        set_busy(False)
        if kind == "sent":
            mark_sent(game_path, sent)
            status.config(text="Sent -- thank you! Receipt%s: %s" % ("" if len(value) == 1 else "s",
                                                                     ", ".join(value)), fg=th["gold"])
            send_btn.config(state="disabled")
            save_btn.config(state="disabled")
        elif kind == "saved":
            mark_sent(game_path, sent)
            where = value[0] if len(value) == 1 else "%d files on your Desktop (%s ...)" % (
                len(value), os.path.basename(value[0]))
            status.config(text="Saved to %s -- please send %s to Berg on Discord."
                          % (where, "that file" if len(value) == 1 else "them all"), fg=th["gold"])
            send_btn.config(state="disabled")
            save_btn.config(state="disabled")
        else:
            status.config(text=value, fg="#ff8a80")

    def work(action, pseudonym, note):
        # A worker thread: it must not touch any tkinter object (Tk is single-threaded); the form's values
        # are read on the main thread in start() and passed in, and progress goes through state.
        try:
            snap = read_sessions(files())
            bundles = build_bundles(base_dir, game_path, snap, pseudonym, note)
            sent = {p: len(b) for p, b in snap.items()}
            if action == "send":
                def prog(i, n):
                    if n > 1:
                        state["progress"] = "Sending part %d of %d..." % (i, n)
                state["result"] = ("sent", upload_all(bundles, url, sw.get("tournament", ""), prog), sent)
            else:
                state["result"] = ("saved", save_bundles(bundles), sent)
        except DiagnosticsError as e:
            state["result"] = ("error", str(e), None)
        except Exception as e:
            state["result"] = ("error", "Something went wrong (%s). Save the zip instead." % e, None)

    def start(action):
        if state["busy"]:
            return
        set_busy(True)
        state["progress"] = ""
        status.config(text="Sending..." if action == "send" else "Saving...", fg=th["muted"])
        threading.Thread(target=work, args=(action, name_var.get(), comment.get("1.0", "end")),
                         daemon=True).start()
        win.after(150, poll)

    def close():
        if state["busy"]:
            return
        win.grab_release()
        win.destroy()
        if on_done:
            try:
                on_done()
            except Exception:
                pass

    send_btn = tk.Button(buttons, text="Send", font=th["font"], bg=th["gold"], fg="#241129", relief="flat",
                         padx=16, pady=4, command=lambda: start("send"))
    save_btn = tk.Button(buttons, text="Save zip to Desktop", font=th["font"], bg=th["button_bg"], fg=th["fg"],
                         relief="flat", padx=12, pady=4, command=lambda: start("save"))
    close_btn = tk.Button(buttons, text="Close", font=th["font"], bg=th["button_bg"], fg=th["fg"], relief="flat",
                          padx=12, pady=4, command=close)
    send_btn.pack(side="left")
    save_btn.pack(side="left", padx=8)
    close_btn.pack(side="right")
    set_busy(False)
    win.protocol("WM_DELETE_WINDOW", close)
    win.update_idletasks()
    win_w = max(win_w, page.winfo_reqwidth() + page_bar.winfo_reqwidth() + 4)
    try:
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - win_w) // 2)
        y = max(0, min(parent.winfo_rooty() + 30, win.winfo_screenheight() - win_h - 60))
        win.geometry("%dx%d+%d+%d" % (win_w, win_h, x, y))
    except Exception:
        win.geometry("%dx%d" % (win_w, win_h))
    win.update_idletasks()
    page_layout()
    win.grab_set()
    return win
