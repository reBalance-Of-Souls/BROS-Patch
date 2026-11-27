"""Loading the player's settings without throwing them away.

The old loader compared the template against the saved config and, if the
key counts differed, copied the template over the top:

    if len(data1) != len(data2):
        shutil.copy(template_path, config_path)

Which means adding a single key to the template silently reset every
player's settings -- including GAME_PATH, the one thing they had to go and
find by hand. It also fired on a config that had merely *lost* a key, and
it could not notice a template that swapped one key for another, since the
count stayed the same.

This merges instead: values already saved are kept, keys the template has
gained are added at their defaults, and keys the template no longer defines
are dropped. Nothing the player set is lost to a release that adds a
setting.
"""

from __future__ import annotations

import json
from pathlib import Path


def paths(base_dir):
    d = Path(base_dir) / "Json"
    return d / "configTemplate.json", d / "config.json"


def _read(p) -> dict:
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def load(base_dir) -> dict:
    """The player's config, reconciled against the shipped template."""
    template_path, config_path = paths(base_dir)
    template = _read(template_path)
    saved = _read(config_path)

    merged = dict(template)
    for k, v in saved.items():
        if k in template:          # drop keys the template retired
            merged[k] = v

    if merged != saved:
        save(base_dir, merged)
    return merged


def save(base_dir, config: dict) -> None:
    _, config_path = paths(base_dir)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = config_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=1)
    tmp.replace(config_path)
