"""The local ffmpeg steps: probe, splice, reverse and the black take check."""

import tempfile
import unittest
from pathlib import Path

from vfx4all import media
from vfx4all.config import BLACK_LUMA_THRESHOLD

from .helpers import make_clip


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.source = make_clip(cls.dir / "source.mp4", 3, size="854x480", fps=30)
        cls.effect = make_clip(cls.dir / "effect.mp4", 2, size="896x512", fps=24)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_probe(self):
        info = media.probe(self.source)
        self.assertEqual((info["width"], info["height"]), (854, 480))
        self.assertAlmostEqual(info["duration"], 3, delta=0.1)
        self.assertEqual(info["fps"], 30)
        self.assertTrue(info["has_audio"])

    def test_splice_keeps_the_source_size_and_drops_the_repeated_frame(self):
        for mode in ("effect", "original"):
            with self.subTest(audio=mode):
                out = media.splice(self.source, self.effect, 1.5, self.dir / f"spliced_{mode}.mp4", audio_mode=mode)
                info = media.probe(out)
                self.assertEqual((info["width"], info["height"]), (854, 480))
                self.assertAlmostEqual(info["duration"], 1.5 + 2 - 1 / 24, delta=0.12)
                self.assertTrue(info["has_audio"])

    def test_reverse_keeps_length_and_sound(self):
        out = media.reverse(self.effect, self.dir / "reversed.mp4")
        info = media.probe(out)
        self.assertAlmostEqual(info["duration"], 2, delta=0.1)
        self.assertTrue(info["has_audio"])

    def test_black_take_detection(self):
        black = make_clip(self.dir / "black.mp4", 1, source="color=c=black", audio=False)
        self.assertLess(media.mean_luma(black), BLACK_LUMA_THRESHOLD)
        self.assertGreater(media.mean_luma(self.source), BLACK_LUMA_THRESHOLD)


if __name__ == "__main__":
    unittest.main()
