"""The layer stack, and how it collapses into one overlay.

The old launcher applied the patch by copying folders into the game
directory in a specific order, each copy overwriting the last. That order
*was* the priority system -- it just happened to be expressed as
destructive file operations against a 35 GB install.

This module keeps the exact same order and throws away the copying. Each
step becomes a Layer: a folder on disk plus where its contents belong
relative to the game root. Collapsing the stack gives one dict of
"game-relative path -> file that should be served for it", which the VFS
resolves at runtime. Nothing is written to the game folder.

Priority runs low to high, so a later layer wins:

    1. game version      GameVersions/<version>
    2. performance       Files/Spec Mod/<feature>/<setting>
    3. reworks           Reworks/<name>
    4. game mode         GameModes/<mode>
    5. team battle       GameModes/TeamBattle/CharaStatus.fsv

which is the same sequence the old launch() performed its copytrees in.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# The four top-level trees the patch overlays. Anything a version folder
# contains outside these is ignored rather than guessed at.
VERSION_SUBTREES = ("Script", "Motion", "00HIGH", "01MIDDLE")

# Effects live in two quality tiers and the perf toggles patch both.
SPFX_HIGH = "00HIGH/Effect/spfx/com"
SPFX_MID = "01MIDDLE/Effect/spfx/com"

# Dev leftovers that sit in the content folders and are not game assets.
# The old installer copied every one of these into players' game folders.
# Matching is on the file name only, never on the path, so a real asset
# like "COM_tm_HitSlash_00.desktop.vfxt" is untouched by the desktop.ini
# rule.
_EXCLUDE_EXACT = {"thumbs.db", "desktop.ini", ".gitkeep", ".gitignore", ".ds_store"}
_EXCLUDE_PATTERNS = (
    re.compile(r"\.bak$", re.I),          # pl038.tadjpkg.bak
    re.compile(r"_bak$", re.I),           # pl022.tadjpkg.prepetal_bak
    re.compile(r"\s\(\d+\)\.", re.I),     # "pl022 (3).tadjpkg" -- Explorer copy
    # The balance-editing toolchain lives inside Script/ next to the files
    # it edits: ConvertToCSV.bat, InjectBoth.bat, fsv2csv.py, and the two
    # zero-byte "fsv2csv.py to_csv" artifacts. Scripts, not game assets --
    # the old installer copied every one of them into players' game folders.
    # The trailing (\s|$) is what catches those two odd names.
    re.compile(r"\.(bat|py)(\s|$)", re.I),
)
# Note there is no .csv rule: the game genuinely loads .csv assets
# (Script\ObjectConfig\pl027_menu_minion00.csv is referenced by the exe).


def is_excluded(name: str) -> bool:
    """True for dev leftovers that should never reach the game."""
    if name.lower() in _EXCLUDE_EXACT:
        return True
    return any(p.search(name) for p in _EXCLUDE_PATTERNS)


@dataclass(frozen=True)
class Layer:
    """One folder of content and where it lands relative to the game root."""

    label: str            # shown in conflict reports and the manifest header
    source: Path          # folder on disk
    dest: str = ""        # game-relative prefix; "" means the game root
    only: tuple = ()      # if set, only these file names are taken

    def entries(self):
        """Yield (game_relative_path, absolute_source_path) for this layer.

        Paths are yielded with forward slashes and no normalisation of case;
        the caller lowercases when building lookup keys so that the file's
        real casing is still available for directory listings.
        """
        if not self.source.is_dir():
            return
        prefix = self.dest.strip("/")
        for dirpath, dirnames, filenames in os.walk(self.source):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if is_excluded(name):
                    continue
                if self.only and name not in self.only:
                    continue
                abs_path = Path(dirpath) / name
                rel = abs_path.relative_to(self.source).as_posix()
                yield (f"{prefix}/{rel}" if prefix else rel), abs_path


@dataclass
class Overlay:
    """The collapsed stack: one winning source file per game-relative path."""

    files: dict = field(default_factory=dict)      # relpath -> (abs source, layer label)
    conflicts: list = field(default_factory=list)  # (relpath, loser label, winner label)
    excluded: int = 0

    def add_layer(self, layer: Layer) -> int:
        n = 0
        for rel, src in layer.entries():
            prev = self.files.get(rel)
            if prev is not None and prev[1] != layer.label:
                self.conflicts.append((rel, prev[1], layer.label))
            self.files[rel] = (src, layer.label)
            n += 1
        return n

    def __len__(self):
        return len(self.files)


def build_stack(
    base_dir: Path,
    config: dict,
    game_version: str,
    game_mode: str = "DEFAULT",
    reworks=(),
) -> list[Layer]:
    """Assemble the layer list, lowest priority first.

    Mirrors the order the old launch() copied in, so a build produced here
    is byte-for-byte the same set of winning files that the copy-based
    installer would have left in the game folder -- minus the leftovers it
    also left behind.
    """
    layers: list[Layer] = []

    # 1. the selected game version
    version_root = base_dir / "GameVersions" / game_version
    for sub in VERSION_SUBTREES:
        src = version_root / sub
        if src.is_dir():
            layers.append(Layer(f"version:{game_version}", src, sub))

    # 2. performance toggles.
    #    reverse_globe goes first because it splits into high/ and middle/
    #    subfolders, and the remaining features are applied over it -- the
    #    same order the old loop produced.
    spec_root = base_dir / "Files" / "Spec Mod"
    rg_setting = config.get("reverse_globe", "original")
    rg = spec_root / "reverse_globe" / rg_setting
    if (rg / "high").is_dir():
        layers.append(Layer(f"perf:reverse_globe={rg_setting}", rg / "high", SPFX_HIGH))
    if (rg / "middle").is_dir():
        layers.append(Layer(f"perf:reverse_globe={rg_setting}", rg / "middle", SPFX_MID))

    if spec_root.is_dir():
        for feature in sorted(os.listdir(spec_root)):
            if feature == "reverse_globe":
                continue
            setting = config.get(feature, "original")
            src = spec_root / feature / setting
            if not src.is_dir():
                continue
            label = f"perf:{feature}={setting}"
            # One source, two destinations: both quality tiers get it.
            layers.append(Layer(label, src, SPFX_HIGH))
            layers.append(Layer(label, src, SPFX_MID))

    # 3. reworks
    rework_root = base_dir / "Reworks"
    for rework in reworks:
        if not rework or rework == "OFF":
            continue
        for sub in ("Script", "Motion"):
            src = rework_root / rework / sub
            if src.is_dir():
                layers.append(Layer(f"rework:{rework}", src, sub))

    # 4. game mode
    #    Script/ and Motion/ both, like the rework layer above: a mode that
    #    needs its own animations carries a .tactpkg, and those live under
    #    Motion/, not Script/.
    if game_mode and game_mode != "DEFAULT":
        for sub in ("Script", "Motion"):
            src = base_dir / "GameModes" / game_mode / sub
            if src.is_dir():
                layers.append(Layer(f"mode:{game_mode}", src, sub))

    # 5. team battle -- a single file, and the highest-priority layer.
    #    The folder around it holds .bat/.py tooling that must not ship, so
    #    this layer names the one file it wants explicitly.
    if config.get("TEAM_BATTLE") == "ON":
        src = base_dir / "GameModes" / "TeamBattle"
        if (src / "CharaStatus.fsv").is_file():
            layers.append(Layer("mode:TeamBattle", src, "Script", only=("CharaStatus.fsv",)))

    return layers


def resolve(layers) -> Overlay:
    """Collapse the stack into one winning file per path."""
    overlay = Overlay()
    for layer in layers:
        overlay.add_layer(layer)
    return overlay
