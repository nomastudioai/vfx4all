"""Upload limits, size matching and the keyframe step that needs no Comfy call."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vfx4all import media
from vfx4all.config import (HOSTED_VIDEO_LIMITS, IMAGE_LIMITS, VIDEO_LIMITS, check_image, check_video,
                            closest_selector, comfy_target, video_limits)
from vfx4all.engine import Engine, MissingApiKey
from vfx4all.jobs import Job
from vfx4all.pipeline import flf_size, keyframes, run_scene, run_splice, supports
from vfx4all.presets import MAX_DIRECTION, get_preset, with_direction

from .helpers import make_clip, make_image

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

    def test_a_hosted_server_takes_shorter_lighter_clips(self):
        with mock.patch.dict(os.environ, {"VFX4ALL_MODE": "hosted"}):
            self.assertEqual(video_limits(), HOSTED_VIDEO_LIMITS)
            self.assertIn("MB", check_video(1920, 1080, 10, (HOSTED_VIDEO_LIMITS["max_mb"] + 1) * MB) or "")
        self.assertEqual(video_limits(), VIDEO_LIMITS)

    def test_photo_limits(self):
        self.assertIsNone(check_image(4032, 3024, 4 * MB))
        self.assertIn("MB", check_image(4032, 3024, (IMAGE_LIMITS["max_mb"] + 1) * MB) or "")
        self.assertIn("px", check_image(IMAGE_LIMITS["max_side"] + 1, 1000, MB) or "")


class ModeTests(unittest.TestCase):
    def test_presets_run_only_in_their_modes(self):
        self.assertTrue(supports(get_preset("shockwave"), "video"))
        self.assertTrue(supports(get_preset("colossus"), "scene"))
        self.assertFalse(supports(get_preset("colossus"), "own_image"))
        # Ant Size has a generic prompt but is listed for its own scene only.
        self.assertFalse(supports(get_preset("ant-size"), "own_image"))
        self.assertFalse(supports(get_preset("rewind"), "video"))


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
        self.assertEqual(flf_size("16:9 (Widescreen)", "unknown"), (896, 512))  # like the DFR graph: Draft
        for size in (flf_size("16:9 (Widescreen)", q) for q in ("draft", "hq")):
            self.assertTrue(all(side % 64 == 0 for side in size))


class SceneTests(unittest.TestCase):
    def test_the_scene_prompt_counts_the_photos_it_gets(self):
        sent = {}

        def fake_scene(engine, refs, prompt, size, seed, dest, progress):
            sent[len(refs)] = prompt
            out = dest.with_suffix(".png")
            out.write_bytes(b"png")
            return out

        with mock.patch.object(Engine, "scene", fake_scene), tempfile.TemporaryDirectory() as tmp:
            photos = [make_image(Path(tmp) / "front.png"), make_image(Path(tmp) / "side.png")]
            for count in (1, 2):
                job = Job(id=f"scene-test{count}", kind="scene")
                job.dir.mkdir(parents=True, exist_ok=True)
                run_scene(job, key=None, preset_id="walk-of-fire", refs=photos[:count], subject="man",
                          notes="", aspect="16:9", seed=1)
                self.assertIn("scene", job.outputs)
        self.assertIn("Image 1 is a photo of the man.", sent[1])
        self.assertIn("Image 1 and image 2 are two photos of the same man.", sent[2])


class TargetTests(unittest.TestCase):
    def test_the_base_url_says_where_the_graphs_run(self):
        cases = {"": "cloud", "https://cloud.comfy.org": "cloud", "https://my-app.run.comfy.app": "deployment",
                 "http://127.0.0.1:8189": "local", "http://localhost:8189": "local",
                 "https://gpu.example.com": "custom"}
        for url, kind in cases.items():
            with self.subTest(url=url), mock.patch.dict(os.environ, {"COMFY_BASE_URL": url}):
                self.assertEqual(comfy_target()["kind"], kind)

    def test_your_own_comfyui_runs_without_a_key(self):
        with mock.patch.dict(os.environ, {"COMFY_BASE_URL": "http://127.0.0.1:8189", "COMFY_API_KEY": ""}), \
                mock.patch("vfx4all.engine.Comfy") as comfy:
            Engine().client
            comfy.assert_called_once_with(api_key=None)
        with mock.patch.dict(os.environ, {"COMFY_BASE_URL": "", "COMFY_API_KEY": ""}):
            with self.assertRaises(MissingApiKey):
                Engine().client


class DirectionTests(unittest.TestCase):
    def test_the_direction_ends_the_effect_prompt(self):
        self.assertEqual(with_direction("A burst of fire.", "  "), "A burst of fire.")
        self.assertEqual(with_direction("A burst of fire.", "  the camera  pushes in "),
                         "A burst of fire. the camera pushes in.")
        self.assertEqual(with_direction("Fire.", "Slow motion!"), "Fire. Slow motion!")
        self.assertEqual(len(with_direction("Fire.", "a" * 900)), len("Fire. ") + MAX_DIRECTION + 1)

    def test_a_splice_sends_the_direction_to_ltx(self):
        sent = {}

        def fake_effect(engine, image, prompt, selector, megapixels, duration, seed, dest, progress,
                        lora=None, pipeline=None):
            sent["prompt"] = prompt
            return make_clip(dest.with_suffix(".mp4"), 3.0)   # long enough for the poster 1 s after the cut

        with mock.patch.object(Engine, "effect", fake_effect), tempfile.TemporaryDirectory() as tmp:
            clip = make_clip(Path(tmp) / "walk.mp4", 2.0)
            job = Job(id="splice-direction", kind="splice")
            job.dir.mkdir(parents=True, exist_ok=True)
            run_splice(job, key=None, preset_id="disintegrate", video=clip, seconds=1.0, subject="man",
                       quality="draft", audio_mode="effect", seed=7, direction="the wind blows from the left")
        self.assertTrue(sent["prompt"].endswith(" the wind blows from the left."))
        self.assertEqual(job.params["prompt"], sent["prompt"])
        self.assertIn("video", job.outputs)


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
