"""Release channels, and the credential a private channel needs.

One launcher, more than one source of builds. A channel is just a repo, a
prerelease policy, and whether it needs a token:

    stable   the public patch repo, released builds only, no credential
    dev      a private repo, needs a token with read access to it

Channels are data, not code -- see Json/channels.json -- so adding one is a
config change rather than a release.

## What the credential does and does not do

The token gates *downloading* the dev build. It does not stop a developer
who already has it from passing it on; nothing client-side can. What it
buys is that access is granted per person and can be revoked, and that the
assets are not sitting somewhere a stranger can enumerate.

This is why the gate is a real credential rather than a passkey compared
against a constant in this file. The launcher ships as readable Python: any
check written here can be read and removed in a text editor, so a passkey
would keep out exactly the people who were never going to look. Requiring a
token that GitHub itself validates moves the decision to the one place the
player does not control.

## Storage

On Windows the token is encrypted with DPAPI before it touches disk, so the
file is bound to that user on that machine. Copying a patch folder to a
friend -- or zipping it up for a bug report, which is how this actually
leaks -- carries a blob that will not decrypt for them.

Elsewhere it is written with owner-only permissions and no encryption,
which is stated plainly rather than pretended otherwise.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

STABLE = "stable"

# Used when Json/channels.json is missing or unreadable, so a damaged
# install still updates itself from the public channel instead of failing.
BUILTIN = {
    STABLE: {
        "label": "Stable",
        "repo": "Nilsix/Bleach-Rebirth-of-Souls-Community-Patch",
        "prerelease": False,
        "requires_token": False,
        "description": "The public patch. What players run.",
    },
}


@dataclass(frozen=True)
class Channel:
    name: str
    label: str
    repo: str
    prerelease: bool = False
    requires_token: bool = False
    content_only: bool = False
    description: str = ""

    @property
    def is_private(self) -> bool:
        return self.requires_token

    @property
    def delivers_launcher(self) -> bool:
        """Whether this channel supplies core.zip -- the launcher itself.

        False for every content channel, and that is a safety property, not
        a preference. core.zip carries the launcher, so a channel that
        delivered it would replace the running launcher with whatever copy
        that repo happens to hold. If that copy is older -- which for a
        content repo it invariably is -- the player lands on a launcher with
        no channel control and no way back. A one-way door.

        Content channels therefore ship game versions only. The launcher
        comes from stable, always, so the control that got you here is
        still there to get you back.
        """
        return not self.content_only

    @property
    def configured(self) -> bool:
        """False when channels.json names the channel but not its repo.

        The dev channel ships with an empty repo on purpose -- guessing one
        would point testers at the wrong build. Callers report it as
        unconfigured rather than failing with a 404 from nowhere.
        """
        return bool(self.repo and "/" in self.repo)


def _definitions(base_dir) -> dict:
    p = Path(base_dir) / "Json" / "channels.json"
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data:
            return data
    except Exception:
        pass
    return BUILTIN


def all_channels(base_dir) -> dict:
    """name -> Channel, stable first."""
    out = {}
    for name, d in _definitions(base_dir).items():
        # JSON has no comments, so documentation lives in _-prefixed keys.
        if name.startswith("_") or not isinstance(d, dict):
            continue
        out[name] = Channel(
            name=name,
            label=d.get("label", name.title()),
            repo=d.get("repo", ""),
            prerelease=bool(d.get("prerelease", False)),
            requires_token=bool(d.get("requires_token", False)),
            content_only=bool(d.get("content_only", False)),
            description=d.get("description", ""),
        )
    if STABLE in out:
        return {STABLE: out[STABLE], **{k: v for k, v in out.items() if k != STABLE}}
    return out


def get(base_dir, name: str) -> Channel:
    """A channel by name, falling back to stable for anything unknown.

    Falling back rather than raising matters: a config naming a channel that
    a later release removed must not stop the launcher from starting.
    """
    chans = all_channels(base_dir)
    if name in chans:
        return chans[name]
    return chans.get(STABLE) or Channel(STABLE, "Stable", BUILTIN[STABLE]["repo"])


def current(base_dir, config: dict) -> Channel:
    return get(base_dir, config.get("CHANNEL", STABLE))


# ---------------------------------------------------------------------
#  token storage
# ---------------------------------------------------------------------
def _token_path(base_dir, channel_name: str) -> Path:
    # Runtime/ is gitignored and is where generated state already lives.
    return Path(base_dir) / "Runtime" / f"token-{channel_name}.bin"


def _dpapi(data: bytes, unprotect: bool) -> bytes:
    """Encrypt or decrypt with the current Windows user's DPAPI key."""
    import ctypes
    import ctypes.wintypes as w

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", w.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def to_blob(b):
        buf = ctypes.create_string_buffer(b, len(b))
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    src, _keep = to_blob(data)
    out = BLOB()
    # Both take (in, descr, entropy, reserved, prompt, flags, out) -- the
    # second parameter differs in direction but not in arity, and NULL is
    # correct for both.
    fn = (ctypes.windll.crypt32.CryptUnprotectData if unprotect
          else ctypes.windll.crypt32.CryptProtectData)
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def save_token(base_dir, channel_name: str, token: str) -> None:
    p = _token_path(base_dir, channel_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    raw = token.strip().encode("utf-8")
    if sys.platform == "win32":
        try:
            blob = _dpapi(raw, unprotect=False)
            p.write_bytes(b"DPAPI1\n" + base64.b64encode(blob))
            return
        except Exception:
            pass    # fall through to plaintext rather than losing the token
    p.write_bytes(b"PLAIN1\n" + base64.b64encode(raw))
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def load_token(base_dir, channel_name: str) -> str:
    """The stored token, or "" if there is none / it will not decrypt.

    A DPAPI blob copied from another machine or user fails to decrypt, and
    that is the intended outcome -- treated as "no token", so the launcher
    asks for one rather than reporting something cryptic.
    """
    p = _token_path(base_dir, channel_name)
    try:
        data = p.read_bytes()
    except OSError:
        return ""
    head, _, body = data.partition(b"\n")
    try:
        blob = base64.b64decode(body)
        if head == b"DPAPI1":
            return _dpapi(blob, unprotect=True).decode("utf-8")
        return blob.decode("utf-8")
    except Exception:
        return ""


def clear_token(base_dir, channel_name: str) -> None:
    try:
        _token_path(base_dir, channel_name).unlink()
    except OSError:
        pass


def token_is_stored(base_dir, channel_name: str) -> bool:
    return bool(load_token(base_dir, channel_name))
