"""Regression tests for untrusted YouTube URL handling."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "yt-design-extractor"
    / "yt-design-extractor.py"
)
SPEC = importlib.util.spec_from_file_location("yt_design_extractor", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load yt-design-extractor module")
EXTRACTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXTRACTOR)


class ExtractorInputSecurityTests(unittest.TestCase):
    def test_metadata_and_download_receive_only_canonical_video_url(self):
        video_id = "abcDEF12345"
        untrusted_url = (
            f"https://www.youtube.com/watch?v={video_id}&--exec=/tmp/marker"
        )
        canonical_url = f"https://www.youtube.com/watch?v={video_id}"

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "out"
            unused_video = output_dir / "video.mp4"
            with (
                patch.object(EXTRACTOR.shutil, "which", return_value="/bin/tool"),
                patch.object(
                    EXTRACTOR,
                    "get_video_metadata",
                    return_value={"title": "test", "channel": "test", "duration": 0},
                ) as metadata,
                patch.object(EXTRACTOR, "get_transcript", return_value=None),
                patch.object(
                    EXTRACTOR, "download_video", return_value=unused_video
                ) as download,
                patch.object(EXTRACTOR, "extract_frames_interval", return_value=[]),
                patch.object(
                    EXTRACTOR, "build_markdown", return_value=output_dir / "result.md"
                ),
                patch.object(
                    sys,
                    "argv",
                    [str(SCRIPT), untrusted_url, "--output-dir", str(output_dir)],
                ),
            ):
                EXTRACTOR.main()

        self.assertEqual(metadata.call_args.args[0], canonical_url)
        self.assertEqual(download.call_args.args[0], canonical_url)


if __name__ == "__main__":
    unittest.main()
