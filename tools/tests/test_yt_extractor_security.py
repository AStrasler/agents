"""Regression tests for yt-dlp URL normalization and option injection."""

import importlib.util
import subprocess  # nosec B404
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "yt-design-extractor" / "yt-design-extractor.py"
spec = importlib.util.spec_from_file_location("yt_design_extractor_security", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("could not load yt-design-extractor module")
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)

VIDEO_ID = "dQw4w9WgXcQ"
CANONICAL = "https://www.youtube.com/watch?v=" + VIDEO_ID


class YoutubeSubprocessTests(unittest.TestCase):
    def test_supported_input_forms_return_exact_id(self):
        for source in (
            VIDEO_ID,
            "https://www.youtube.com/watch?v=" + VIDEO_ID + "&t=5",
            "https://youtu.be/" + VIDEO_ID,
            "https://m.youtube.com/shorts/" + VIDEO_ID,
            "https://www.youtube-nocookie.com/embed/" + VIDEO_ID,
            "youtube.com/v/" + VIDEO_ID,
        ):
            with self.subTest(source=source):
                self.assertEqual(extractor.extract_video_id(source), VIDEO_ID)
                self.assertEqual(extractor.canonical_watch_url(source), CANONICAL)

    def test_rejects_non_youtube_and_malformed_inputs(self):
        for source in (
            "--config-locations",
            "not a video",
            "https://evil.example/watch?v=" + VIDEO_ID,
            "https://youtube.com.evil.example/watch?v=" + VIDEO_ID,
            "https://youtube.com@evil.example/watch?v=" + VIDEO_ID,
            "file:///tmp/video",
            "https://www.youtube.com/watch?v=" + VIDEO_ID + ";--exec",
            "https://youtube.com/watch?v=" + VIDEO_ID + "&v=aaaaaaaaaaa",
            "https://youtu.be/" + VIDEO_ID + "/evil",
            "http://[bad",
            "https://[::1/watch?v=" + VIDEO_ID,  # urlsplit raises ValueError
        ):
            with self.subTest(source=source), self.assertRaises(SystemExit):
                extractor.extract_video_id(source)

    def test_metadata_uses_only_canonical_url_after_terminator(self):
        completed = subprocess.CompletedProcess([], 0, '{"id":"ok"}', "")
        with patch.object(extractor.subprocess, "run", return_value=completed) as run:
            self.assertEqual(
                extractor.get_video_metadata("https://youtu.be/" + VIDEO_ID),
                {"id": "ok"},
            )
        command = run.call_args.args[0]
        self.assertEqual(command[-2:], ["--", CANONICAL])
        self.assertIs(run.call_args.kwargs["shell"], False)

    def test_download_uses_canonical_url_after_terminator(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            expected_file = directory / "video.mp4"
            expected_file.write_bytes(b"test")
            completed = subprocess.CompletedProcess([], 0, "", "")
            with patch.object(extractor.subprocess, "run", return_value=completed) as run:
                self.assertEqual(extractor.download_video(VIDEO_ID, directory), expected_file)
            self.assertEqual(run.call_args.args[0][-2:], ["--", CANONICAL])
            self.assertIs(run.call_args.kwargs["shell"], False)

    def test_invalid_input_fails_before_subprocess(self):
        with patch.object(extractor.subprocess, "run") as run:
            with self.assertRaises(SystemExit):
                extractor.get_video_metadata("--exec")
            with (
                tempfile.TemporaryDirectory() as folder,
                self.assertRaises(SystemExit),
            ):
                extractor.download_video("https://evil.example/watch?v=" + VIDEO_ID, Path(folder))
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
