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

`Quick Launch Bros Vanilla.py` reads this file in `restore_stock()`. With the
manifest missing it deletes nothing at all, by design.

## Rebuilding it

Only from a clean install -- a patched folder would record the patch as stock.
Uninstall through Steam, delete whatever Steam leaves behind (it only removes
files it shipped), reinstall, and run the builder before launching anything.
