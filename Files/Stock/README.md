# Stock manifest

`stock_manifest_sha256.txt` is what a clean Steam install of BLEACH Rebirth of
Souls contains. One row per file:

```
<sha256 | ->	<size in bytes>	<game-relative path>
```

Built 2026-09-21 from a fresh download of build **21095206** (appid 1689620),
verified byte-for-byte against Steam's own `SizeOnDisk` of 78,596,422,367 across
71,277 files.

## Why the hash column is often `-`

Only the 1,298 paths that some `GameVersions/<v>/` folder can actually write are
hashed. Hashing the whole tree reads 73.6 GB, which this drive serves at about
10 MB/s -- two hours, for rows nothing reads. A `-` means **no hash recorded**.
It never means "mismatch".

## What it is for

It is the only authority that can tell three things apart in a game folder:

| | how it is recognised | what a revert may do |
|---|---|---|
| a stock file | listed here | restore it, never delete it |
| a patch file | not listed, but shipped by some `GameVersions/<v>/` | delete it |
| the player's own file | listed nowhere | **never touch it** |

Without it the second and third are indistinguishable, and a revert has to
guess. That guess deleted `Fnames/filename.bin` on 2026-09-09 and left every
launcher faulting at `exe+0x1C8187` with no crashlog.

`launcher/vanilla_revert.py` reads this file (`stock_manifest()`) when there is
neither Steam's own list nor the repo's copy of it below: a vanilla start then
proves stock by size only, and its report says so. Until 2026-11-06 `Quick Launch
Bros Vanilla.py` read it too, in `restore_stock()`, its fallback when
`launcher/vanilla_revert.py` was missing (with the manifest missing it deleted
nothing at all, by design).

## Steam's own list (2026-11-02, V1.5 delivery B.1)

`steam_1689621_21095206_4654145826755142404.tsv.gz` is Steam's own file list for
the same build: depot 1689621, manifest 4654145826755142404, read from Steam's
`depotcache` by `launcher/vanilla_revert.py` (`parse_depot_manifest`). One row per
file, gzip-compressed, no name or time in the gzip header:

```
<game-relative path, backslashes>	<size>	0	<SHA-1 of the content>	0
```

The same 71,277 paths and sizes as `stock_manifest_sha256.txt`, with a SHA-1 for
every one of them. A vanilla start (`launcher/vanilla_revert.py`) proves the game
folder against Steam's list: the player's own copy first (the app manifest's build
and manifest id, then Steam's depotcache file), then this copy when the build and
the manifest id are the same, else `stock_manifest_sha256.txt` by size only (and
its report says so). A new game build needs nothing here, since the player's own
Steam files are read first; to add the copy for a new build, `write_tsv()` in the
same module writes it from Steam's file.

## Rebuilding it

Only from a clean install -- a patched folder would record the patch as stock.
Uninstall through Steam, delete whatever Steam leaves behind (it only removes
files it shipped), reinstall, and run the builder before launching anything.
