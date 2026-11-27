"""Getting the newest patch build, and reporting which one is installed.

Players used to receive the patch as a git clone that re-pointed itself at
origin/main on every launch. That meant carrying 2.4 GB of history and
5.5 GB of working tree to play one game version, and it meant the launcher
had to `git reset --hard` -- destroying any local file, which is a blunt
instrument to hand someone who just wants to play.

Players now install from GitHub Releases, and update against a content
manifest: hash what is on disk, download only the files that differ. See
launcher/release.py for the mechanism.

Contributors are unaffected. A checkout with BalanceLeadTools/DevToken.txt
is a working copy, not an install, so it keeps using git and this module
stays out of its way.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import channels
from . import release as rel

# Where releases are published. Overridable so a fork or a staging repo can
# be pointed at without editing code.
DEFAULT_REPO = "Nilsix/Bleach-Rebirth-of-Souls-Community-Patch"

CORE_ASSET = "core.zip"


# ---------------------------------------------------------------------
#  which mode is this checkout in
# ---------------------------------------------------------------------
def is_dev_checkout(base_dir) -> bool:
    """True for a contributor's clone, which updates itself with git."""
    return (Path(base_dir) / "BalanceLeadTools" / "DevToken.txt").exists()


def runtime_dir(base_dir) -> Path:
    return Path(base_dir) / "Runtime"


def repo_slug(base_dir, config=None) -> str:
    """owner/name to fetch releases from.

    Runtime/repo.txt wins when present -- that is how a staging install or
    tools/verify_release.py retargets without touching config. Otherwise the
    active channel decides; see launcher/channels.py.
    """
    p = runtime_dir(base_dir) / "repo.txt"
    try:
        s = p.read_text(encoding="utf-8").strip()
        if s and "/" in s:
            return s
    except OSError:
        pass
    if config is not None:
        ch = channels.current(base_dir, config)
        if ch.configured:
            return ch.repo
    return DEFAULT_REPO


# ---------------------------------------------------------------------
#  version reporting
# ---------------------------------------------------------------------
def current_build(base_dir) -> str:
    """What is installed right now.

    A release tag for players. For a dev checkout, the short commit hash,
    because that is what actually identifies their build.
    """
    if is_dev_checkout(base_dir):
        return _git_short_head(base_dir)
    return rel.read_stamp(runtime_dir(base_dir)).get("release") or "not installed"


def latest_build(base_dir, timeout=20) -> str:
    """Newest published release tag, or 'unknown' when offline."""
    try:
        return rel.latest_release(repo_slug(base_dir), timeout=timeout).tag or "unknown"
    except Exception:
        return "unknown"


def _git_short_head(base_dir) -> str:
    try:
        r = subprocess.run(["git", "-C", str(base_dir), "rev-parse", "--short", "HEAD"],
                           check=True, capture_output=True, text=True)
        return r.stdout.strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------
#  checking for work
# ---------------------------------------------------------------------
@dataclass
class UpdateCheck:
    """The result of comparing this install against the newest release."""

    release: rel.Release = None
    manifest: rel.Manifest = None
    plan: rel.UpdatePlan = field(default_factory=rel.UpdatePlan)
    up_to_date: bool = True
    offline: bool = False
    no_releases: bool = False    # reachable, but nothing published yet
    unconfigured: bool = False   # channel named but has no repo set
    no_access: bool = False      # private channel, token missing or rejected
    no_manifest: bool = False    # release exists but predates this pipeline
    channel: object = None
    error: str = ""

    def describe(self) -> str:
        if self.unconfigured:
            return f"Channel not configured: {self.error}."
        if self.no_access:
            # Distinguished from no_releases on purpose: a private repo
            # answers 404 to both, and telling someone with a bad token that
            # the channel is simply empty sends them looking the wrong way.
            return (f"No access to the {self.channel.label if self.channel else ''} "
                    f"channel -- its token is missing, expired or rejected.")
        # Distinguished from offline deliberately: this is what every
        # install sees until the first release is tagged, and telling
        # someone to check their connection would be wrong.
        if self.no_manifest:
            # A release built before this pipeline, or by hand. Saying
            # "could not reach GitHub" here would be nonsense -- we reached
            # it and read a release that simply is not in this format.
            return (f"The {self.channel.label if self.channel else ''} channel's "
                    f"newest release carries no content manifest, so this "
                    f"launcher cannot install from it ({self.error}).")
        if self.no_releases:
            return f"No releases published yet ({self.error})."
        # Offline is checked before the generic error: it always carries one
        # (the reason it failed), and "could not reach GitHub" is the useful
        # half of that for a player who is simply not connected.
        if self.offline:
            reason = f" ({self.error})" if self.error else ""
            return f"Could not reach GitHub{reason} -- running the build you already have."
        if self.error:
            return f"Update check failed: {self.error}"
        if self.up_to_date:
            return f"Up to date ({self.release.title})."
        return f"Update available ({self.release.title}):\n  {self.plan.describe()}"


def check(base_dir, wanted_versions=(), include_prerelease=False,
          scan_progress=None, config=None) -> UpdateCheck:
    """Work out what this install needs to match the newest release.

    `wanted_versions` names the game versions the player actually wants.
    Nothing else is downloaded -- there is no reason to pull a 1.4 GB
    version folder someone never selects. The core asset always applies.

    `config` selects the release channel. Without it the stable channel is
    used, which is what every player-facing path wants.
    """
    base_dir = Path(base_dir)
    ch = channels.current(base_dir, config or {})
    if ch.requires_token and not ch.configured:
        return UpdateCheck(offline=True, unconfigured=True,
                           error=f"the {ch.label} channel has no repo set in "
                                 f"Json/channels.json")
    if ch.name != channels.STABLE:
        include_prerelease = include_prerelease or ch.prerelease

    # A private channel's token is stored per channel and injected for the
    # duration of the check; nothing else in the process should see it.
    rel.set_token(channels.load_token(base_dir, ch.name) if ch.requires_token else "")
    try:
        release = rel.latest_release(repo_slug(base_dir, config), include_prerelease)
        manifest = rel.fetch_manifest(release)
    except rel.NoReleases as e:
        # For a private channel, that 404 may mean "cannot see it" rather
        # than "nothing published". Ask the question that has one answer.
        if ch.requires_token:
            try:
                if not rel.repo_accessible(ch.repo):
                    return UpdateCheck(offline=True, no_access=True, channel=ch,
                                       error=f"no access to {ch.repo}")
            except Exception:
                pass    # network trouble; fall through and report it as such
        return UpdateCheck(offline=True, no_releases=True, error=str(e), channel=ch)
    except LookupError as e:
        # fetch_manifest could not find content-manifest.json on the release.
        return UpdateCheck(offline=True, no_manifest=True, error=str(e), channel=ch)
    except Exception as e:
        # A rejected credential is not an outage. Reporting 401/403 as
        # "could not reach GitHub" would send someone to check their wifi
        # over a token that simply expired.
        if ch.requires_token and getattr(e, "code", None) in (401, 403):
            return UpdateCheck(offline=True, no_access=True, channel=ch, error=str(e))
        # Otherwise offline is normal and must never block a launch: the
        # player has a working install already.
        return UpdateCheck(offline=True, error=str(e), channel=ch)

    assets = {a for v in wanted_versions
              for a in (asset_for_version(manifest, v),) if a}
    # core.zip is the launcher. Only the stable channel delivers it; see
    # Channel.delivers_launcher for why that is a safety property.
    if ch.delivers_launcher:
        assets.add(CORE_ASSET)
    # An asset already fully installed still gets scanned -- that is what
    # makes this double as a repair.
    cache = rel.HashCache(runtime_dir(base_dir) / "content-cache.json")
    try:
        stale = rel.diff_local(base_dir, manifest, cache,
                               only_assets=assets, progress=scan_progress)
    finally:
        cache.save()

    plan = rel.plan_update(manifest, stale)
    return UpdateCheck(release=release, manifest=manifest, plan=plan,
                       up_to_date=not plan, channel=ch)


def apply(base_dir, chk: UpdateCheck, progress=None, log=print) -> int:
    """Download and write everything the check found missing."""
    if chk.offline or chk.up_to_date or not chk.manifest:
        return 0

    # Re-assert the credential from the check that produced this plan. The
    # token is global to the release module, so any stable-channel call
    # landing between check() and apply() would have cleared it, and every
    # download here would 404 against a private channel.
    ch = chk.channel
    rel.set_token(channels.load_token(base_dir, ch.name)
                  if (ch is not None and ch.requires_token) else "")

    need = chk.plan.wire_bytes
    free = rel.free_space(base_dir)
    # Whole-asset fetches stage a zip before extracting, so the peak is
    # roughly twice the download. Checking up front turns "disk full
    # halfway through an update" into a message before anything starts.
    if free >= 0 and free < need * 2:
        raise OSError(f"not enough free disk space: need about "
                      f"{need * 2 / 1e9:.1f} GB, {free / 1e9:.1f} GB available")

    written = rel.apply_plan(
        base_dir, chk.manifest, chk.plan,
        asset_url=lambda name: chk.release.url_for(name),
        progress=progress, log=log,
    )

    installed = set(rel.read_stamp(runtime_dir(base_dir)).get("assets", []))
    installed |= {a.asset for a in chk.plan.assets}
    rel.write_stamp(runtime_dir(base_dir), chk.release.tag, installed)
    return written


# ---------------------------------------------------------------------
#  game versions available in a release
# ---------------------------------------------------------------------
def available_versions(manifest: rel.Manifest) -> dict:
    """Game version name -> {asset, bytes}, derived from the manifest.

    The launcher's version list used to come from listing GameVersions/ on
    disk, which cannot work before anything is downloaded. Reading it from
    the manifest instead means a player sees every version a release offers
    and picks one, and only then is 1.4 GB fetched.
    """
    out = {}
    for path, e in manifest.files.items():
        parts = path.split("/")
        if len(parts) < 3 or parts[0] != "GameVersions":
            continue
        v = out.setdefault(parts[1], {"asset": e.asset, "bytes": 0})
        v["bytes"] += e.size
    return out


def validate_channel(base_dir, channel_name: str) -> tuple:
    """Can this install actually read that channel? Returns (ok, message).

    Just one API call -- deliberately not check(), which hashes the whole
    install and would take seconds for a question that is really "is this
    token any good". Used the moment a token is pasted, so a typo is caught
    while the person still has it on their clipboard rather than at the next
    launch.
    """
    ch = channels.get(base_dir, channel_name)
    if not ch.configured:
        return False, f"the {ch.label} channel has no repo set in Json/channels.json"

    rel.set_token(channels.load_token(base_dir, ch.name) if ch.requires_token else "")
    try:
        # Read access is checked on its own first. /releases/latest answers
        # 404 both for "you cannot see this repo" and "it has no releases",
        # so without this a missing or expired token reports itself as a
        # successful connection to an empty channel.
        if ch.requires_token and not rel.repo_accessible(ch.repo):
            return False, ("no access to that repository -- check the token is "
                           "correct, unexpired, and has Contents: Read on it")
        r = rel.latest_release(ch.repo, include_prerelease=ch.prerelease)
        # Access is not the whole question. A release that predates this
        # pipeline carries no manifest, and the launcher cannot install from
        # it -- better to say so while someone is still setting the channel
        # up than to accept the token and fail at the next launch.
        try:
            rel.fetch_manifest(r)
        except LookupError:
            return False, (f"reached {ch.label} ({r.title}), but that release has no "
                           f"content manifest -- the repo needs the release pipeline "
                           f"(see RELEASING.md)")
        return True, f"{ch.label}: {r.title}"
    except rel.NoReleases:
        # Access already confirmed above, so this really is an empty channel.
        return True, f"{ch.label}: reachable, no releases published yet"
    except Exception as e:
        code = getattr(e, "code", None)
        if code in (401, 403):
            return False, "that token was rejected (check it has not expired)"
        if code == 404:
            return False, ("no access to that repository -- the token needs "
                           "Contents: Read on it, or it may be the wrong repo")
        return False, str(e)
    finally:
        rel.set_token("")


def asset_for_version(manifest: rel.Manifest, version: str):
    for path, e in manifest.files.items():
        if path.startswith(f"GameVersions/{version}/"):
            return e.asset
    return None


def installed_versions(base_dir) -> list:
    """Game versions actually present on disk right now."""
    d = Path(base_dir) / "GameVersions"
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir())


# ---------------------------------------------------------------------
#  contributor path
# ---------------------------------------------------------------------
def pull(base_dir):
    """git update, for dev checkouts only.

    Deliberately gentler than the old player-facing path, which did
    `reset --hard` + `clean -fd` on every launch. A contributor's local
    work is not disposable, so this fetches and fast-forwards and stops if
    it cannot.
    """
    base_dir = Path(base_dir)

    def git(*args, check=False):
        return subprocess.run(["git", "-C", str(base_dir), *args],
                              check=check, capture_output=True, text=True)

    # The deep Effect/spfx/... paths clear the legacy 260-character limit;
    # core.longpaths makes git use \\?\ extended paths internally, with no
    # admin rights, registry change or reboot.
    git("config", "core.longpaths", "true")
    return git("pull", "--ff-only")


def update(base_dir, wanted_versions=(), progress=None, log=print) -> UpdateCheck:
    """One call for the common case: bring this install up to date.

    Routes to git for a contributor checkout and to releases otherwise, so
    callers do not have to know which kind of install they are running in.
    """
    if is_dev_checkout(base_dir):
        r = pull(base_dir)
        if r.returncode != 0:
            log(f"[update] git pull skipped: {r.stderr.strip() or 'not fast-forwardable'}")
        return UpdateCheck(up_to_date=True)

    chk = check(base_dir, wanted_versions)
    if chk.offline:
        log(f"[update] {chk.describe()}")
        return chk
    if not chk.up_to_date:
        log(f"[update] {chk.describe()}")
        apply(base_dir, chk, progress=progress, log=log)
    return chk


def console_progress(width=34):
    """A one-line progress bar for the console launchers.

    Rewrites a single line rather than scrolling, so a 1.4 GB download does
    not bury whatever the player is meant to read afterwards.
    """
    state = {"last": -1}

    def cb(done, total, label=""):
        pct = int(done * 100 / total) if total else 100
        if pct == state["last"]:
            return
        state["last"] = pct
        filled = int(width * pct / 100)
        bar = "#" * filled + "-" * (width - filled)
        name = (label or "")[-40:]
        print(f"\r  [{bar}] {pct:3d}%  {name:<40s}", end="", flush=True)
        if pct >= 100:
            print()

    return cb


def report_version_if_admin(base_dir, build: str) -> None:
    """Announce a new build to Discord, for whoever holds adminConfig.json.

    adminConfig.json is gitignored, so this is a no-op for every player.
    Kept as its own function because all three launcher entry points used
    to carry their own copy of it.
    """
    cfg_path = Path(base_dir) / "adminConfig.json"
    if not cfg_path.exists():
        return
    try:
        import hashlib
        import json

        import requests

        with open(cfg_path) as f:
            cfg = json.load(f)
        if cfg.get("VERSION") == build:
            return
        cfg["VERSION"] = build
        with open(cfg_path, "w") as f:
            json.dump(cfg, f)

        if cfg.get("ADMIN_ID") != hashlib.sha256(cfg["HASH_VALUE"].encode()).hexdigest():
            return
        webhook = cfg.get("WEBHOOK_URL")
        if not webhook:
            # The URL used to be hardcoded in all three launcher scripts, in
            # a public repository. Read it from the (gitignored) admin config
            # instead so rotating it does not mean another commit.
            return
        requests.post(webhook, json={"content": "Launcher latest version : " + build})
    except Exception:
        pass
