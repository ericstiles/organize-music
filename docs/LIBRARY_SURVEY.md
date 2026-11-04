# Library Survey

Read-only snapshot of the music library taken 2026-11-03 over SSH. Nothing was
modified. Re-run the commands at the bottom to refresh.

## Host

| Item | Value |
|------|-------|
| Pi | `256GB-P5` — `ssh ets04uga@192.168.1.222` (see `../talk-to-pi/PI_INVENTORY.md`) |
| Board | Raspberry Pi 5, 4 cores, 15 GiB RAM, Debian 13 `aarch64` |
| Python | 3.13.5 (system) |
| Library root | `/media/ets04uga/Extreme/PlaceHereToKeepFromWork/Music` |
| Disk | `/dev/sda1` 932 G, 578 G used (library is the 578 G), 355 G free |
| Tools present | `ffprobe`, `md5sum` |
| Tools missing | `mutagen` (Python), `fpcalc` (Chromaprint) |

## Contents

102,681 files total, 578 G.

| Extension | Count | Notes |
|-----------|------:|-------|
| mp3 | 58,333 | main format |
| m4a | 41,695 | main format (AAC / ALAC) |
| jpg | 1,137 | cover art |
| txt / nfo / m3u / xml / md5 | 517 | sidecar files |
| wma | 118 | |
| m4p | 38 | DRM-protected iTunes; tags readable, audio not playable |
| ogg / wav / shn / ac3 | 158 | |
| flv / m4v / mp4 | 201 | video, out of scope |
| exe / pdf / itc2 | 69 | junk, out of scope |

## Layout

There is no consistent layout. The folder structure is several old
collections merged together:

- **1,286 loose files at the root**, many with the info only in the filename,
  e.g. `(Old School Rap) De La Soul - Me Myself And I(1).mp3`,
  `01 Billie Jean.mp3`.
- **1,504 top-level folders**, mixing artist folders (`Jay-Z`, `Carbon Leaf`),
  release-group names (`[Indie Folk] Mumford & Sons - Discography 2008-2015 (...)`),
  and older collections whose names suggest they are copies.
- Audio sits anywhere from depth 0 to depth 6 (most at depth 3).

Largest top-level folders by audio count:

| Folder | Audio files | Likely meaning |
|--------|------------:|----------------|
| `OrganizesByGenre` | 17,960 | an earlier genre re-org — probably copies |
| `ipod_favs` | 9,832 | iPod export — probably copies |
| `torrent` | 2,717 | |
| `Carbon Leaf` | 2,707 | |
| `No genre info` | 1,563 | |
| `Jay-Z` | 1,533 | |

## Duplicate signal

Of the ~100k mp3/m4a files, **93,889 share an exact byte size with at least
one other file** (29,479 size groups). Same size is only a hint, not proof.
But it strongly suggests heavy byte-identical duplication, likely from
`OrganizesByGenre`, `ipod_favs` and similar copies. The real number comes
from the hash pass (see [PLAN.md](PLAN.md)).

## Implications for the design

1. **Tags can't be fully trusted, and filenames are messy.** Metadata
   extraction must report *where* each field came from (tag vs. filename vs.
   folder). It must not guess silently.
2. **Hashing must be resumable.** Reading 578 G from a USB SSD takes a long
   time. The index must survive interruption and skip files that haven't
   changed.
3. **Duplicate copies pick a winner by path.** When two files are
   byte-identical, the only difference is where they live. Path preference
   rules (e.g. "lose the copy under `ipod_favs`") matter more than quality
   rules.
4. **Only audio files are in scope.** Video, executables and other junk get
   reported, not touched.

## Commands used

```bash
M=/media/ets04uga/Extreme/PlaceHereToKeepFromWork/Music
find "$M" -type f | sed 's/.*\.//' | tr A-Z a-z | sort | uniq -c | sort -rn
find "$M" -type f \( -iname '*.mp3' -o -iname '*.m4a' \) | awk -F/ '{print NF-7}' | sort -n | uniq -c
find "$M" -mindepth 2 -type f \( -iname '*.mp3' -o -iname '*.m4a' \) | cut -d/ -f8 | sort | uniq -c | sort -rn | head
find "$M" -type f \( -iname '*.mp3' -o -iname '*.m4a' \) -printf '%s\n' | sort | uniq -c | awk '$1>1{f+=$1;g++} END{print f, g}'
```
