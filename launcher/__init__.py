"""Patch installation for BLEACH: Rebirth of Souls, without installing anything.

The entry point is prepare(): give it the same selections the UI already
tracks and it produces everything the game process needs, touching only
the loader DLL in the game folder.

    result = launcher.prepare(BASE_DIR, game_path, config,
                              game_version="ReBalance of Souls V2.0",
                              game_mode="EightKonpakus",
                              reworks=["OFF"])
    subprocess.Popen([exe], cwd=game_path, env=result.env)

Replacing the old copy-based install means a few properties come for free:

  * Switching game version, game mode or a performance toggle is writing a
    text file, not copying gigabytes. It is effectively instant.
  * Nothing needs uninstalling. Launch vanilla, or delete two files.
  * An update that changes patch content takes effect on the next launch
    with no re-copy, because the manifest points at the installed files
    wherever they live.
  * The game folder stays byte-identical to what Steam shipped, so Steam's
    own integrity check stops being a recovery step players need.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import channels, cleanup, config, game, layers, release, updater, vfs

__all__ = [
    "prepare", "prepare_vanilla", "PrepareResult", "VANILLA_VERSION",
    "channels", "cleanup", "config", "game", "layers", "release", "updater", "vfs",
]

# The one version that means "do not patch anything".
VANILLA_VERSION = "Bleach Rebirth of Souls"


@dataclass
class PrepareResult:
    """Everything the caller needs to start the game."""

    env: dict = field(default_factory=dict)
    manifest: Path = None
    file_count: int = 0
    new_count: int = 0
    layer_count: int = 0
    conflicts: list = field(default_factory=list)
    loader_updated: bool = False

    def describe(self) -> str:
        return (
            f"{self.file_count} file(s) overlaid from {self.layer_count} layer(s)"
            f"{f', {self.new_count} new' if self.new_count else ''}"
        )


def prepare(
    base_dir,
    game_root,
    config: dict,
    game_version: str,
    game_mode: str = "DEFAULT",
    reworks=(),
    *,
    enum_merge: bool = True,
    log_level: int = 1,
) -> PrepareResult:
    """Build the overlay for these selections and stage it for launch.

    Does not launch anything and does not write game content anywhere. The
    only thing that lands in the game folder is the loader DLL, and only
    when its bytes differ from the copy in the repo.
    """
    base_dir, game_root = Path(base_dir), Path(game_root)

    stack = layers.build_stack(base_dir, config, game_version, game_mode, reworks)
    overlay = layers.resolve(stack)

    manifest = vfs.manifest_path(base_dir)
    note = (
        f"version={game_version} mode={game_mode} "
        f"reworks={','.join(r for r in reworks if r and r != 'OFF') or 'none'}\n"
        + "\n".join(f"layer {i + 1}: {lyr.label} -> {lyr.dest or '<root>'}"
                    for i, lyr in enumerate(stack))
    )
    count, new_count = vfs.write_manifest(
        manifest, game_root, overlay,
        enum_merge=enum_merge, log_level=log_level, header_note=note,
    )
    loader_updated = vfs.deploy_loader(base_dir, game_root)

    return PrepareResult(
        env=vfs.launch_env(base_dir),
        manifest=manifest,
        file_count=count,
        new_count=new_count,
        layer_count=len(stack),
        conflicts=overlay.conflicts,
        loader_updated=loader_updated,
    )


def prepare_vanilla(game_root) -> None:
    """Strip the patch for a genuine vanilla launch.

    The loader has to go: a vanilla launch runs through Steam with
    EasyAntiCheat active, and EAC refuses a process carrying an injected
    dinput8.dll. With the loader gone the VFS cannot run either, which is
    correct -- vanilla means the files on disk, unmediated. It also means a
    vanilla launch is only truly vanilla if the game folder itself is
    clean; see cleanup.scan().
    """
    vfs.remove_loader(game_root)
