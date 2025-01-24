#!/usr/bin/env bash
#
# merge_chapters.sh
#
# Merges audiobook MP3 segments into a single file per chapter,
# ignoring pre-existing Merged_Chapters directory and leading track numbers.
#
# Usage:
#    ./merge_chapters.sh /path/to/audiobook/folder
#
# Requirements:
#    - bash 4+ (for associative arrays and mapfile)
#    - ffmpeg
#
# Behavior:
#    - Recursively scans for *.mp3 under the given folder, excluding Merged_Chapters
#    - Groups them by chapter (e.g., "Chapter 1", "Chapter 2", etc.)
#    - Merges each group into a single MP3 using ffmpeg with re-encoding to fix DTS issues

set -euo pipefail

# --- Check usage ---
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 /path/to/audiobook/folder"
  exit 1
fi

TARGET_DIR="$1"

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Error: '$TARGET_DIR' is not a directory."
  exit 1
fi

# --- Define output directory ---
MERGED_DIR="$TARGET_DIR/Merged_Chapters"

# --- Skip scanning the Merged_Chapters directory ---
echo "Ensuring Merged_Chapters directory is ignored during crawling."
mapfile -t all_mp3s < <(find "$TARGET_DIR" -type f -iname '*.mp3' ! -path "$MERGED_DIR/*" | sort)

# --- Process files ---
declare -A chapter_map

# Updated regex to ignore leading numbers and spaces
# This regex matches filenames like "09 Chapter 2a.mp3", "03 Chapter 10b.mp3", etc.
# It captures the chapter number and optional letter suffix
chapter_regex='^[0-9]+[[:space:]]+Chapter[[:space:]]+([0-9]+)([a-z])?$'

for filepath in "${all_mp3s[@]}"; do
    filename="$(basename "$filepath")"
    name_no_ext="${filename%.mp3}"

    if [[ $name_no_ext =~ $chapter_regex ]]; then
        chapter_number="${BASH_REMATCH[1]}"      # e.g., "2" or "10"
        chapter_letter="${BASH_REMATCH[2]}"      # e.g., "a" or empty if none
        group="Chapter $chapter_number"           # e.g., "Chapter 2"

        # Append the file to the corresponding chapter group
        chapter_map["$group"]+="$filepath|"
    fi
done

# Create output directory if it doesn't exist
mkdir -p "$MERGED_DIR"

# --- Merge each chapter ---
echo "Merging chapters..."
for chapter in "${!chapter_map[@]}"; do
    file_list="${chapter_map[$chapter]}"
    file_list="${file_list%|}"  # Remove trailing '|'

    tmp_list="$(mktemp)"
    IFS='|' read -r -a parts <<< "$file_list"
    for f in "${parts[@]}"; do
        # Escape single quotes in filenames
        esc_f="${f//\'/\'\\\'\'}"
        echo "file '$esc_f'" >> "$tmp_list"
    done

    # Output filename: e.g., "Chapter 2.mp3"
    out_filename="${chapter}.mp3"
    out_filepath="$MERGED_DIR/$out_filename"

    echo "  -> Creating: $out_filename"

    # Use ffmpeg with re-encoding to fix DTS issues
    ffmpeg -hide_banner -loglevel error \
        -fflags +genpts \
        -f concat -safe 0 -i "$tmp_list" \
        -c:a libmp3lame -b:a 192k \
        -af aresample=async=1 \
        -y "$out_filepath"

    rm -f "$tmp_list"
done

echo "All done! Merged chapters are in: $MERGED_DIR"
