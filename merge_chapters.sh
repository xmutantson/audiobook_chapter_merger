#!/usr/bin/env bash
# Merge MP3 chapter fragments in numeric folder/track order.
set -euo pipefail
export LC_ALL=C

usage() {
    cat <<'USAGE'
Usage: merge_chapters.sh [--dry-run] [--overwrite] [--] DIRECTORY

  --dry-run    Print the merge plan without creating outputs or running FFmpeg.
  --overwrite  Replace existing chapter files only after successful encoding.
  -h, --help   Show this help.

Names: TRACK Chapter NUMBER[LETTER].mp3 (case insensitive).
Ordering: chapter number, natural parent-folder order, then numeric track.
Use one audiobook per directory and consistent disc names such as Disc 1, Disc 2.
Output: DIRECTORY/Merged_Chapters/Chapter NUMBER.mp3
Requirements: Bash 4+, GNU coreutils, find; FFmpeg with libmp3lame for merging.
USAGE
}

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
warn() { printf 'Warning: %s\n' "$*" >&2; }

(( BASH_VERSINFO[0] >= 4 )) || die 'Bash 4 or newer is required.'
dry_run=0
overwrite=0
while (( $# )); do
    case "$1" in
        --dry-run) dry_run=1; shift ;;
        --overwrite) overwrite=1; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; break ;;
        -*) die "Unknown option: $1 (see --help)" ;;
        *) break ;;
    esac
done
(( $# == 1 )) || { usage >&2; exit 1; }
[[ $1 != *$'\n'* && $1 != *$'\r'* && $1 != *$'\t'* ]] || die 'Input directory contains a newline, carriage return or tab.'
[[ -d $1 ]] || die "Not a directory: $1"
target_capture=$(CDPATH= cd -P -- "$1" && printf '%s/.' "$PWD") || die 'Cannot resolve the input directory.'
target_dir=${target_capture%/.}
[[ $target_dir != *$'\n'* && $target_dir != *$'\r'* && $target_dir != *$'\t'* ]] || die 'Resolved directory contains a newline, carriage return or tab.'
merged_dir="$target_dir/Merged_Chapters"

for dependency in find sort mktemp; do
    command -v "$dependency" >/dev/null || die "Missing dependency: $dependency"
done
sort -V </dev/null >/dev/null 2>&1 || die 'GNU sort with -V support is required (use a Unix/Git Bash PATH).'

work_dir=''
stage_dir=''
lock_dir=''
child_pid=''
cleanup() {
    local status=$?
    trap - EXIT
    if [[ -n $child_pid ]]; then
        kill "$child_pid" 2>/dev/null || true
        wait "$child_pid" 2>/dev/null || true
    fi
    # Remove only known files in directories created by this invocation.
    if [[ -n $stage_dir ]]; then
        rm -f -- "$stage_dir/chapter.mp3" "$stage_dir/link-source" "$stage_dir/link-check" || true
        rmdir -- "$stage_dir" 2>/dev/null || true
    fi
    if [[ -n $lock_dir ]]; then rmdir -- "$lock_dir" 2>/dev/null || true; fi
    if [[ -n $work_dir ]]; then
        rm -f -- "$work_dir/discovered" "$work_dir/records" "$work_dir/ordered" "$work_dir/concat" "$work_dir/encoders" || true
        rmdir -- "$work_dir" 2>/dev/null || true
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/chapter-merger.XXXXXXXX") || die 'Cannot create temporary directory.'

# Check the producer directly: process substitution would hide find failures.
if ! find "$target_dir" -type d -name Merged_Chapters -prune -o \
    -type f -iname '*.mp3' -print0 >"$work_dir/discovered"; then
    die 'File discovery failed; no chapters were written.'
fi

# Avoid arithmetic conversion: leading zeros and very large chapter numbers are valid.
normalize_number() {
    local number=$1
    while [[ ${#number} -gt 1 && $number == 0* ]]; do number=${number#0}; done
    printf '%s' "$number"
}

declare -a paths=()
declare -A positions=()
discovered=0
matched=0
skipped=0
invalid=0
chapter_regex='^([0-9]+)[[:space:]]+chapter[[:space:]]+([0-9]+)([a-z])?$'
: >"$work_dir/records"
while IFS= read -r -d '' filepath; do
    discovered=$((discovered + 1))
    # FFconcat is line based; tabs are reserved for the sortable plan records.
    if [[ $filepath == *$'\n'* || $filepath == *$'\r'* || $filepath == *$'\t'* ]]; then
        printf 'Error: Unsupported newline, carriage return or tab in path: %q\n' "$filepath" >&2
        invalid=$((invalid + 1))
        continue
    fi
    filename=${filepath##*/}
    stem=${filename%.*}
    if [[ ${stem,,} =~ $chapter_regex ]]; then
        track=$(normalize_number "${BASH_REMATCH[1]}")
        chapter=$(normalize_number "${BASH_REMATCH[2]}")
        relative=${filepath#"$target_dir"/}
        parent=${relative%/*}
        [[ $parent != "$relative" ]] || parent='.'
        position="$chapter"$'\t'"$parent"$'\t'"$track"
        if [[ -n ${positions[$position]+present} ]]; then
            printf 'Error: Duplicate track %s for Chapter %s in %s:\n  %s\n  %s\n' \
                "$track" "$chapter" "$parent" "${positions[$position]}" "$filepath" >&2
            invalid=$((invalid + 1))
            continue
        fi
        positions["$position"]=$filepath
        paths+=("$filepath")
        printf '%s\t%s\t%s\t%s\n' "$chapter" "$parent" "$track" "$matched" >>"$work_dir/records"
        matched=$((matched + 1))
    else
        printf 'Skipped (name does not match): %s\n' "$filepath"
        skipped=$((skipped + 1))
    fi
done <"$work_dir/discovered"
printf 'Found %s MP3 files: %s matched, %s skipped, %s invalid.\n' "$discovered" "$matched" "$skipped" "$invalid"
(( invalid == 0 )) || die 'Resolve invalid or ambiguous inputs before merging.'
(( matched > 0 )) || die 'No matching chapter fragments found; no chapters were written.'
(( skipped == 0 )) || warn 'Skipped files will not appear in the output; review the list above.'

sort -t $'\t' -k1,1n -k2,2V -k2,2 -k3,3n -k4,4n "$work_dir/records" >"$work_dir/ordered" || die 'Cannot sort merge plan.'
declare -a chapters=() ordered_paths=() chapter_starts=()
last_chapter=''
ordered_count=0
while IFS=$'\t' read -r chapter parent track index; do
    if [[ $chapter != "$last_chapter" ]]; then
        chapters+=("$chapter")
        chapter_starts+=("$ordered_count")
        printf '\nChapter %s -> %s/Chapter %s.mp3\n' "$chapter" "$merged_dir" "$chapter"
        last_chapter=$chapter
    fi
    ordered_paths+=("${paths[$index]}")
    ordered_count=$((ordered_count + 1))
    printf '  %s\n' "${paths[$index]}"
done <"$work_dir/ordered"
chapter_starts+=("$ordered_count")

conflicts=0
for chapter in "${chapters[@]}"; do
    destination="$merged_dir/Chapter $chapter.mp3"
    if [[ -e $destination || -L $destination ]]; then
        if (( overwrite )) && [[ -f $destination && ! -L $destination ]]; then
            printf 'Will replace: %s\n' "$destination"
        else
            warn "Output already exists: $destination (regular files require --overwrite)."
            conflicts=$((conflicts + 1))
        fi
    fi
done
(( conflicts == 0 )) || die 'Output conflicts found; no chapters were written.'
if (( dry_run )); then
    printf '\nDry run: %s chapters planned; no outputs written.\n' "${#chapters[@]}"
    exit 0
fi

command -v ffmpeg >/dev/null || die 'Missing dependency: ffmpeg (preview is available with --dry-run).'
ffmpeg -hide_banner -encoders >"$work_dir/encoders" 2>&1 || die 'Cannot query FFmpeg encoders.'
if ! grep -Eq '(^|[[:space:]])libmp3lame([[:space:]]|$)' "$work_dir/encoders"; then
    die 'FFmpeg must include the libmp3lame encoder.'
fi

[[ ! -L $merged_dir ]] || die 'Merged_Chapters must not be a symbolic link.'
mkdir -p -- "$merged_dir" || die 'Cannot create output directory.'
if mkdir -- "$merged_dir/.merge-lock" 2>/dev/null; then
    lock_dir="$merged_dir/.merge-lock"
else
    die 'Another merge may be running (.merge-lock exists); see README for recovery.'
fi
stage_dir=$(mktemp -d "$merged_dir/.merge-stage.XXXXXXXX") || die 'Cannot create staged output directory.'
if (( ! overwrite )); then
    : >"$stage_dir/link-source"
    ln -T -- "$stage_dir/link-source" "$stage_dir/link-check" || die 'Output filesystem must support hard links for safe no-overwrite publishing.'
    rm -f -- "$stage_dir/link-source" "$stage_dir/link-check"
fi

# Native Windows FFmpeg cannot resolve /c/... paths inside a concat manifest.
media_path() {
    case "$OSTYPE" in
        msys*|cygwin*) cygpath -am -- "$1" ;;
        *) printf '%s' "$1" ;;
    esac
}

for (( chapter_index=0; chapter_index<${#chapters[@]}; chapter_index++ )); do
    chapter=${chapters[$chapter_index]}
    destination="$merged_dir/Chapter $chapter.mp3"
    : >"$work_dir/concat"
    for (( index=chapter_starts[chapter_index]; index<chapter_starts[chapter_index+1]; index++ )); do
        input_path=$(media_path "${ordered_paths[$index]}") || die 'Cannot convert input path for FFmpeg.'
        escaped=${input_path//\'/\'\\\'\'}
        printf "file 'file:%s'\n" "$escaped" >>"$work_dir/concat"
    done
    printf '\nMerging Chapter %s (%s fragments)...\n' "$chapter" "$((chapter_starts[chapter_index+1] - chapter_starts[chapter_index]))"
    manifest_path=$(media_path "$work_dir/concat") || die 'Cannot convert manifest path for FFmpeg.'
    staged_path=$(media_path "$stage_dir/chapter.mp3") || die 'Cannot convert output path for FFmpeg.'
    ffmpeg -nostdin -hide_banner -loglevel error -xerror \
        -fflags +genpts -f concat -safe 0 -i "$manifest_path" \
        -map 0:a:0 -vn -c:a libmp3lame -b:a 192k -af aresample=async=1 \
        -y "$staged_path" &
    child_pid=$!
    if wait "$child_pid"; then
        child_pid=''
    else
        child_pid=''
        die "FFmpeg failed for Chapter $chapter; its previous output was preserved."
    fi
    [[ -s $stage_dir/chapter.mp3 ]] || die "FFmpeg produced no audio for Chapter $chapter."
    if [[ -L $destination || ( -e $destination && ! -f $destination ) ]]; then
        die "Output became an unsupported file type: $destination"
    fi
    if (( overwrite )); then
        mv -fT -- "$stage_dir/chapter.mp3" "$destination" || die "Cannot publish Chapter $chapter."
    else
        # A hard link publishes the complete file without replacing an existing path.
        ln -T -- "$stage_dir/chapter.mp3" "$destination" || die "Cannot publish Chapter $chapter; destination may now exist."
        rm -f -- "$stage_dir/chapter.mp3"
    fi
    printf 'Created: %s\n' "$destination"
done
printf '\nDone: %s chapters merged from %s fragments; %s files skipped.\n' "${#chapters[@]}" "$matched" "$skipped"
