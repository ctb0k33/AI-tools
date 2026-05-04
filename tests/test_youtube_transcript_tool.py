import unittest

from tools.youtube.youtube_transcript_tool import (
    build_transcript_text,
    extract_video_id,
    normalize_video_url,
)


class ExtractVideoIdTests(unittest.TestCase):
    def test_accepts_direct_video_id(self):
        self.assertEqual(extract_video_id("dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_extracts_watch_url(self):
        self.assertEqual(
            extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_extracts_short_url(self):
        self.assertEqual(
            extract_video_id("https://youtu.be/dQw4w9WgXcQ?t=42"),
            "dQw4w9WgXcQ",
        )

    def test_extracts_shorts_url(self):
        self.assertEqual(
            extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )


class UrlNormalizationTests(unittest.TestCase):
    def test_normalizes_to_watch_url(self):
        self.assertEqual(
            normalize_video_url("https://youtu.be/dQw4w9WgXcQ"),
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )


class TranscriptFormattingTests(unittest.TestCase):
    def test_builds_timestamped_text(self):
        transcript = build_transcript_text(
            [
                {"timestamp": "00:01", "text": "Hello world"},
                {"timestamp": "", "text": "No timestamp line"},
            ]
        )

        self.assertEqual(transcript, "[00:01] Hello world\nNo timestamp line")


if __name__ == "__main__":
    unittest.main()
