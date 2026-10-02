"""Offline regression tests; only synthetic files in temporary directories are used."""
import array
import hashlib
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "merge_chapters.sh"
BASH = os.environ.get("MERGER_TEST_BASH")
if not BASH and os.name == "nt":
    candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
    BASH = str(candidate) if candidate.is_file() else None
if not BASH:
    BASH = shutil.which("bash")

MOCK_FFMPEG = r'''#!/usr/bin/env bash
set -eu
if [[ " $* " == *" -encoders "* ]]; then
    if [[ ${TEST_MODE:-success} == no_encoder ]]; then
        echo ' A..... some_other_encoder'
    else
        echo ' A..... libmp3lame MP3 encoder'
    fi
    exit 0
fi
echo encode >> "$TEST_CALLS"
manifest=''
previous=''
for argument in "$@"; do
    if [[ $previous == -i ]]; then manifest=$argument; fi
    previous=$argument
done
cat -- "$manifest" >> "$TEST_MANIFEST"
output=${!#}
case "${TEST_MODE:-success}" in
    fail) printf partial > "$output"; exit 7 ;;
    empty) : > "$output" ;;
    terminate) printf partial > "$output"; kill -TERM "$PPID"; sleep 1; exit 8 ;;
    race) printf concurrent > "$TEST_RACE_DEST"; printf complete > "$output" ;;
    *) printf complete > "$output" ;;
esac
'''


@unittest.skipUnless(BASH, "Bash is required (set MERGER_TEST_BASH to its executable)")
class MergeTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="chapter-merger-tests-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.book = self.root / "Reader's book [test]"
        self.book.mkdir()
        self.shims = self.root / "bin"
        self.shims.mkdir()
        self.temporary = self.root / "temporary"
        self.temporary.mkdir()
        self.calls = self.root / "calls"
        self.manifest = self.root / "manifest"
        self.write_shim("ffmpeg", MOCK_FFMPEG)

    def write_shim(self, name, contents):
        path = self.shims / name
        path.write_text(contents, encoding="utf-8", newline="\n")
        path.chmod(0o755)
        return path

    def fragment(self, name="Disc 1/1 Chapter 1a.mp3", content=b"source"):
        path = self.book / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def output(self, chapter=1, content=b"previous"):
        path = self.book / "Merged_Chapters" / f"Chapter {chapter}.mp3"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
        return path

    def invoke(self, *options, target=None, expected=0, mode="success", extra_env=None):
        env = os.environ.copy()
        env.update(TMPDIR=self.temporary.as_posix(), TEST_MODE=mode,
                   TEST_CALLS=self.calls.as_posix(), TEST_MANIFEST=self.manifest.as_posix())
        if extra_env:
            env.update(extra_env)
        # Git Bash launched from PowerShell may inherit Windows find/sort first.
        launcher = ('export PATH="/usr/bin:/bin:$PATH"; shim=$1; '
                    'case "$OSTYPE" in msys*|cygwin*) shim=$(cygpath -u "$shim");; esac; '
                    'export PATH="$shim:$PATH"; shift; exec "$BASH" --noprofile --norc "$@"')
        args = [BASH, "--noprofile", "--norc", "-c", launcher, "merger-test",
                self.shims.as_posix(), SCRIPT.as_posix(),
                *options, str(target if target is not None else self.book)]
        result = subprocess.run(args, cwd=self.root, env=env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=30)
        message = result.stdout + result.stderr
        if expected == 0:
            self.assertEqual(result.returncode, 0, message)
        elif expected is not None:
            self.assertNotEqual(result.returncode, 0, message)
        return result

    def assert_clean(self):
        self.assertEqual(list(self.temporary.iterdir()), [], "Leaked temporary manifest")
        output = self.book / "Merged_Chapters"
        if output.exists():
            self.assertEqual(list(output.glob(".merge*")), [], "Leaked stage or lock")

    def test_relative_absolute_preview_and_numeric_order(self):
        late = self.fragment("Disc 10/1 Chapter 01c.MP3")
        middle = self.fragment("Disc 9/10 chapter 1B.mp3")
        first = self.fragment("Disc 9/2 Chapter 1a.mp3")
        self.fragment("Disc 9/3 Chapter 10a.mp3")
        self.fragment("Disc 9/4 Chapter 2a.mp3")
        absolute = self.invoke("--dry-run")
        relative = self.invoke("--dry-run", target=self.book.name)
        self.assertEqual(absolute.stdout, relative.stdout)
        text = absolute.stdout
        self.assertLess(text.index(first.name), text.index(middle.name))
        self.assertLess(text.index(middle.name), text.index(late.name))
        self.assertLess(text.index("Chapter 2 ->"), text.index("Chapter 10 ->"))
        self.assertIn("3 chapters planned", text)
        self.assertFalse((self.book / "Merged_Chapters").exists())
        self.assertFalse(self.calls.exists())
        self.assert_clean()

    def test_cdpath_does_not_change_relative_target(self):
        self.fragment()
        other = self.root / "other"
        (other / self.book.name).mkdir(parents=True)
        result = self.invoke("--dry-run", target=self.book.name, extra_env={"CDPATH": other.as_posix()})
        self.assertIn("1 matched", result.stdout)

    def test_skips_and_existing_output_tree_are_accounted_for(self):
        self.fragment()
        self.fragment("Disc 1/0 Prologue.mp3")
        self.fragment("Merged_Chapters/99 Chapter 99.mp3")
        result = self.invoke("--dry-run")
        self.assertIn("2 MP3 files: 1 matched, 1 skipped, 0 invalid", result.stdout)
        self.assertIn("Skipped (name does not match)", result.stdout)
        self.assertIn("Skipped files will not appear", result.stderr)

    def test_zero_matches_is_an_error(self):
        self.fragment("1 Prologue.mp3")
        result = self.invoke("--dry-run", expected=1)
        self.assertIn("No matching chapter fragments", result.stderr)
        self.assertFalse((self.book / "Merged_Chapters").exists())
        self.assert_clean()

    def test_duplicate_normalized_track_is_rejected(self):
        self.fragment("Disc 1/2 Chapter 01a.mp3")
        self.fragment("Disc 1/02 Chapter 1b.mp3")
        result = self.invoke(expected=1)
        self.assertIn("Duplicate track 2 for Chapter 1", result.stderr)
        self.assertFalse(self.calls.exists())
        self.assert_clean()

    def test_discovery_failure_does_not_encode_partial_scan(self):
        source = self.fragment()
        self.write_shim("find", '#!/usr/bin/env bash\nprintf "%s\\0" "$TEST_SOURCE"\nexit 3\n')
        result = self.invoke(expected=1, extra_env={"TEST_SOURCE": source.as_posix()})
        self.assertIn("File discovery failed", result.stderr)
        self.assertFalse((self.book / "Merged_Chapters").exists())
        self.assertFalse(self.calls.exists())
        self.assert_clean()

    def test_control_character_discovery_is_rejected(self):
        self.write_shim("find", '#!/usr/bin/env bash\nprintf "/book/bad\\nname/1 Chapter 1.mp3\\0"\n')
        result = self.invoke(expected=1)
        self.assertIn("Unsupported newline", result.stderr)
        self.assertFalse(self.calls.exists())
        self.assert_clean()

    def test_control_character_argument_is_rejected(self):
        result = self.invoke(target=str(self.book) + "\n", expected=1)
        self.assertIn("Input directory contains", result.stderr)

    @unittest.skipIf(os.name == "nt", "Windows filenames cannot contain pipes")
    def test_pipe_directory_is_not_split(self):
        self.fragment("Disc 1|notes/1 Chapter 1.mp3")
        self.invoke()
        self.assertIn("Disc 1|notes", self.manifest.read_text())
        self.assert_clean()

    def test_all_conflicts_are_checked_before_encoding(self):
        self.fragment("1 Chapter 1.mp3")
        self.fragment("2 Chapter 2.mp3")
        existing = self.output(2)
        self.invoke(expected=1)
        self.assertEqual(existing.read_bytes(), b"previous")
        self.assertFalse((existing.parent / "Chapter 1.mp3").exists())
        self.assertFalse(self.calls.exists())
        self.assert_clean()

    def test_failed_encode_preserves_previous_output_and_source(self):
        source = self.fragment()
        existing = self.output()
        result = self.invoke("--overwrite", mode="fail", expected=1)
        self.assertIn("FFmpeg failed", result.stderr)
        self.assertEqual(existing.read_bytes(), b"previous")
        self.assertEqual(source.read_bytes(), b"source")
        self.assert_clean()

    def test_empty_encode_preserves_previous_output(self):
        self.fragment()
        existing = self.output()
        result = self.invoke("--overwrite", mode="empty", expected=1)
        self.assertIn("produced no audio", result.stderr)
        self.assertEqual(existing.read_bytes(), b"previous")
        self.assert_clean()

    def test_termination_preserves_previous_output_and_cleans(self):
        self.fragment()
        existing = self.output()
        result = self.invoke("--overwrite", mode="terminate", expected=1)
        self.assertEqual(result.returncode, 143, result.stdout + result.stderr)
        self.assertEqual(existing.read_bytes(), b"previous")
        self.assert_clean()

    def test_successful_overwrite_and_apostrophe_manifest(self):
        self.fragment()
        existing = self.output()
        self.invoke("--overwrite")
        self.assertEqual(existing.read_bytes(), b"complete")
        self.assertIn("Reader'\\''s book", self.manifest.read_text())
        self.assert_clean()

    def test_concurrent_destination_is_not_overwritten(self):
        self.fragment()
        destination = self.book / "Merged_Chapters/Chapter 1.mp3"
        self.invoke(mode="race", expected=1, extra_env={"TEST_RACE_DEST": destination.as_posix()})
        self.assertEqual(destination.read_bytes(), b"concurrent")
        self.assert_clean()

    def test_missing_encoder_fails_before_output_creation(self):
        self.fragment()
        result = self.invoke(mode="no_encoder", expected=1)
        self.assertIn("libmp3lame encoder", result.stderr)
        self.assertFalse((self.book / "Merged_Chapters").exists())
        self.assertFalse(self.calls.exists())
        self.assert_clean()

    def test_existing_lock_is_preserved(self):
        self.fragment()
        existing = self.output()
        lock = existing.parent / ".merge-lock"
        lock.mkdir()
        result = self.invoke("--overwrite", expected=1)
        self.assertIn("Another merge may be running", result.stderr)
        self.assertTrue(lock.is_dir())
        self.assertEqual(existing.read_bytes(), b"previous")
        self.assertFalse(self.calls.exists())

    def test_unsupported_hard_links_fail_before_encode(self):
        self.fragment()
        self.write_shim("ln", "#!/usr/bin/env bash\nexit 1\n")
        result = self.invoke(expected=1)
        self.assertIn("filesystem must support hard links", result.stderr)
        self.assertFalse(self.calls.exists())
        self.assert_clean()

    def test_large_and_zero_chapter_numbers(self):
        self.fragment("01 Chapter 000.mp3")
        self.fragment("02 Chapter 999999999999999999999999a.mp3")
        result = self.invoke("--dry-run")
        self.assertIn("Chapter 0 ->", result.stdout)
        self.assertIn("Chapter 999999999999999999999999 ->", result.stdout)

    def test_real_corrupt_later_fragment_preserves_previous_chapter(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("FFmpeg required for real corrupt-fragment check")
        (self.shims / "ffmpeg").unlink()
        for track in (1, 3):
            source = self.fragment(f"{track} Chapter 1.mp3")
            subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                            "sine=frequency=440:duration=0.5", "-c:a", "libmp3lame",
                            "-y", str(source)], check=True, capture_output=True, timeout=30)
        bad = self.fragment("2 Chapter 1.mp3", b"synthetic unreadable fragment")
        output = self.output()
        result = self.invoke("--overwrite", expected=1)
        self.assertIn("FFmpeg failed", result.stderr)
        self.assertEqual(output.read_bytes(), b"previous")
        self.assertEqual(bad.read_bytes(), b"synthetic unreadable fragment")
        self.assert_clean()
        bad.write_bytes((self.book / "1 Chapter 1.mp3").read_bytes())
        self.invoke("--overwrite")
        self.assertGreater(output.stat().st_size, len(b"previous"))
        self.assert_clean()

    def test_real_audio_order_duration_and_source_preservation(self):
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            self.skipTest("FFmpeg and ffprobe are required for the real audio test")
        encoders = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, check=True)
        if "libmp3lame" not in encoders.stdout:
            self.skipTest("FFmpeg libmp3lame encoder unavailable")
        (self.shims / "ffmpeg").unlink()
        sources = []
        for name, frequency in [("Disc 9/2 Chapter 01a.mp3", 440), ("Disc 10/1 chapter 1B.MP3", 880)]:
            source = self.fragment(name)
            subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                            "-i", f"sine=frequency={frequency}:sample_rate=44100:duration=0.5",
                            "-c:a", "libmp3lame", "-y", str(source)], check=True, capture_output=True)
            sources.append((source, hashlib.sha256(source.read_bytes()).digest()))
        self.invoke(target=self.book.name)
        output = self.book / "Merged_Chapters/Chapter 1.mp3"
        probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=noprint_wrappers=1:nokey=1", str(output)],
                               check=True, capture_output=True, text=True)
        self.assertAlmostEqual(float(probe.stdout), 1.0, delta=0.10)
        decoded = subprocess.run([ffmpeg, "-v", "error", "-i", str(output), "-f", "s16le",
                                  "-ac", "1", "-ar", "44100", "pipe:1"], check=True, capture_output=True)
        samples = array.array("h", decoded.stdout)
        if sys.byteorder != "little":
            samples.byteswap()
        # Distinguish the tones within each half, away from MP3 encoder boundaries.
        for start, expected, other in [(0.15, 440, 880), (0.65, 880, 440)]:
            section = samples[int(start * 44100):int((start + 0.2) * 44100)]
            def energy(frequency):
                return abs(sum(value * complex(math.cos(2 * math.pi * frequency * i / 44100),
                                               math.sin(2 * math.pi * frequency * i / 44100))
                               for i, value in enumerate(section)))
            self.assertGreater(energy(expected), 5 * energy(other))
        for source, digest in sources:
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), digest)
        digest = hashlib.sha256(output.read_bytes()).digest()
        self.invoke(expected=1)
        self.assertEqual(hashlib.sha256(output.read_bytes()).digest(), digest)
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
