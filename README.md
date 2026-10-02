# Audiobook chapter merger

Merge MP3 fragments ripped from an audiobook CD into one MP3 per chapter. The script scans one book's directory recursively, prints the exact merge plan, and writes results under `Merged_Chapters`. Source audio is never modified.

## Quick start

Run these commands from the repository in Bash:

```bash
# Review chapter membership, fragment order, and skipped files first.
bash merge_chapters.sh --dry-run "/path/to/book"

# Create the planned chapter files.
bash merge_chapters.sh "/path/to/book"

# Explicitly replace existing chapter files after successful encoding.
bash merge_chapters.sh --overwrite "/path/to/book"
```

Relative directories work too. Options must precede the directory; use `--` before a directory name beginning with a dash. `--help` lists the options. A preview of an existing output set also requires `--overwrite` to acknowledge the conflicts.

Requirements:

- Bash 4 or newer; do not run the script with `sh`.
- GNU coreutils, including `sort -V`, `ln -T`, and `mv -T`, plus `find` and `grep`.
- FFmpeg with the `libmp3lame` encoder for merging. Previewing does not require FFmpeg.
- A writable output filesystem with hard-link support for the default no-overwrite mode. This is checked before encoding. FAT/exFAT cannot provide this behavior; use a suitable local filesystem. `--overwrite` uses replacement semantics and should only be used when that behavior is intended.

Linux with GNU tools and Windows Git Bash are the intended environments. On Windows, use a normal Git Bash terminal with its Unix tools on `PATH`; PowerShell's `find` and `sort` are different programs. Native Windows FFmpeg paths are converted explicitly. macOS needs a newer Bash and GNU coreutils on `PATH`; the system defaults are insufficient. macOS and older Bash versions have not been validated in this change.

## Input names and ordering

Accepted filenames have this form, without extra title text:

```text
TRACK Chapter NUMBER[LETTER].mp3
```

`TRACK` and `NUMBER` contain decimal digits. The optional suffix is one letter. Matching is case insensitive, including `.MP3`; chapter and track leading zeros are normalized. For example, `02 Chapter 01A.MP3` and `3 chapter 1b.mp3` belong to Chapter 1.

```text
Book/
  Disc 9/
    2 Chapter 1a.mp3
    10 Chapter 1b.mp3
  Disc 10/
    1 Chapter 1c.mp3
    2 Chapter 2a.mp3
```

This produces `Merged_Chapters/Chapter 1.mp3` from the first three files in that order, followed by `Chapter 2.mp3` from the fourth.

The order is numeric chapter, natural order of the relative parent folder, then numeric track within that folder. Use consistent disc names such as `Disc 1`, `Disc 2`, and `Disc 10`. The optional letter is informational; it does not override disc/track order. Mixed folder naming schemes and missing fragments cannot be inferred reliably, so inspect the preview. Files for multiple books must not be placed under one input root.

Two files claiming the same chapter, parent folder, and normalized track are rejected as ambiguous. `Chapter 01` and `Chapter 1` share an output. Opening titles, prologues, epilogues, and other unmatched names are listed as skipped; they are not silently included or assigned invented chapter numbers. A scan failure, invalid input, or zero matches stops the run.

Directories named `Merged_Chapters` are excluded recursively. File symlinks are not followed. Spaces and apostrophes are supported; pipes are supported on filesystems that allow them. Newlines, carriage returns, and tabs in input paths are explicitly rejected.

## Output safety and recovery

Existing outputs are refused unless `--overwrite` is supplied. Output symlinks and non-regular files are refused even in overwrite mode, and `Merged_Chapters` itself must not be a symlink.

Each chapter is encoded to a private staging directory on the destination filesystem. Only a successful FFmpeg exit with a nonempty output is published. Default publication refuses to replace a file that appeared after the initial checks. With `--overwrite`, the staged file replaces the old chapter only after encoding succeeds. A failed chapter preserves its previous output. Chapters already completed earlier in the run remain published; this is not an all-book transaction. Old chapter files outside the current plan are left alone.

A `.merge-lock` directory prevents overlapping runs from publishing simultaneously. Normal exit, encoding failure, and handled INT/TERM signals clean up the run's lock, temporary manifest, and partial output. A power loss or forced termination can leave `.merge-lock` or `.merge-stage.*` directories behind. Before removing those remnants manually, confirm that no merge process is still running and inspect their contents. Never remove another active run's lock.

## Audio behavior and current limits

The existing audio policy is retained: MP3 re-encoding with `libmp3lame` at 192 kb/s, generated timestamps, and asynchronous resampling. Only the first audio stream is selected; cover images/video streams are excluded. This is a lossy re-encode, not a lossless MP3 join.

FFmpeg's concat demuxer expects compatible input streams. Mixed codecs, sample rates, or channel layouts are not normalized by a separate preprocessing step. Use consistent rip settings. Re-encoding is not a guarantee that arbitrary mixed inputs will concatenate correctly. Chapter tags, metadata retention, audiobook-player behavior, quality presets, prologue grouping, and whole-book M4B output remain future product decisions.

## Tests

The regression suite uses Python 3.10 or newer and its standard library, temporary synthetic files, mocked failures, and optional real FFmpeg/ffprobe audio checks. It does not use personal audio or network services.

```bash
python -B -m unittest discover -s tests -v
bash -n merge_chapters.sh
```

On Windows the runner locates Git Bash automatically. Set `MERGER_TEST_BASH` to a Bash executable to override that selection.

Real-audio checks require FFmpeg and ffprobe. See the test output for any environment-specific skips; a skipped integration test does not establish audio compatibility. The checked-in `.gitattributes` keeps shell files in LF format when checking out on Windows.
