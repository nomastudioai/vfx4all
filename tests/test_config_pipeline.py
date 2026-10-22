"""Upload limits, size matching and the keyframe step that needs no Comfy call."""

import tempfile
import unittest
from pathlib import Path

from vfx4all import media
from vfx4all.config import VIDEO_LIMITS, check_video, closest_selector
from vfx4all.pipeline import flf_size, keyframes
from vfx4all.presets import get_preset

from .helpers import make_image

MB = 1024 * 1024


class VideoLimitTests(unittest.TestCase):
    def test_a_clip_inside_the_limits_passes(self):
        self.assertIsNone(check_video(854, 480, 3.0, 5 * MB))
        self.assertIsNone(check_video(480, 854, VIDEO_LIMITS["min_seconds"], 5 * MB))
        self.assertIsNone(check_video(3840, 2160, VIDEO_LIMITS["max_seconds"], VIDEO_LIMITS["max_mb"] * MB))

    def test_each_limit_has_its_own_message(self):
        cases = {
            "MB": (1920, 1080, 10, (VIDEO_LIMITS["max_mb"] + 1) * MB),
            "at least": (1920, 1080, VIDEO_LIMITS["min_seconds"] - 0.5, MB),
            "or less around": (1920, 1080, VIDEO_LIMITS["max_seconds"] + 1, MB),
            "480p or more": (640, 360, 10, MB),
            "4K or less": (4097, 2160, 10, MB),
        }
        for phrase, args in cases.items():
            with self.subTest(limit=phrase):
                self.assertIn(phrase, check_video(*args) or "")


class SizeTests(unittest.TestCase):
    def test_closest_selector(self):
        self.assertEqual(closest_selector(1920, 1080), "16:9 (Widescreen)")
        self.assertEqual(closest_selector(1080, 1920), "9:16 (Portrait Widescreen)")
        self.assertEqual(closest_selector(1000, 1000), "1:1 (Square)")
        self.assertEqual(closest_selector(2560, 1080), "21:9 (Ultrawide)")

    def test_flf_renders_one_pass_at_the_output_size(self):
        self.assertEqual(flf_size("16:9 (Widescreen)", "draft"), (896, 512))
        self.assertEqual(flf_size("16:9 (Widescreen)", "hq"), (1280, 704))
        self.assertEqual(flf_size("9:16 (Portrait Widescreen)", "draft"), (512, 896))
        for size in (flf_size("16:9 (Widescreen)", q) for q in ("draft", "hq")):
            self.assertTrue(all(side % 64 == 0 for side in size))


class KeyframeTests(unittest.TestCase):
    def test_an_ordinary_preset_needs_no_keyframes(self):
        # engine=None: if keyframes() tried to call Comfy, this would raise.
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(keyframes(None, get_preset("shockwave"), Path(tmp) / "a_f0.png", "person",
                                       Path(tmp), seed=1), (None, []))

    def test_bullet_time_mirrors_the_first_frame_locally(self):
        preset = get_preset("bullet-time")
        self.assertEqual(preset.get("last_frame_mode"), "mirror")
        with tempfile.TemporaryDirectory() as tmp:
            first = make_image(Path(tmp) / "shot_f0.png")
            last, mids = keyframes(None, preset, first, "person", Path(tmp), seed=1)
            self.assertEqual(last.name, "shot_f1.png")
            self.assertEqual(mids, [])
            a, b = media.probe(first), media.probe(last)
            self.assertEqual((a["width"], a["height"]), (b["width"], b["height"]))
            self.assertNotEqual(first.read_bytes(), last.read_bytes())


if __name__ == "__main__":
    unittest.main()
