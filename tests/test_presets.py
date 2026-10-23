"""Every preset in presets/ loads, renders cleanly and has what the UI and the pipeline need."""

import re
import unittest

from vfx4all.config import ASPECTS, SUBJECTS, WEB_DIR
from vfx4all.presets import load_presets, public_view, render, wardrobe_for

CATALOG_SIZE = 45
MODES = {"scene", "own_image", "video"}
CATEGORIES = {"Elements", "Transformations", "Clones", "Worlds", "Scale", "Physics", "Time", "Style"}
PROMPTS = ("scene_prompt", "effect_prompt", "generic_prompt", "last_frame_prompt")


class PresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.presets = load_presets()
        cls.icons = set(re.findall(r'symbol id="i-([a-z-]+)"', (WEB_DIR / "index.html").read_text(encoding="utf-8")))

    def test_catalog_is_complete_and_unique(self):
        self.assertEqual(len(self.presets), CATALOG_SIZE)
        ids = [p["id"] for p in self.presets]
        self.assertEqual(len(ids), len(set(ids)))
        orders = [p["order"] for p in self.presets]
        self.assertEqual(len(orders), len(set(orders)))

    def test_fields_the_ui_needs(self):
        for p in self.presets:
            with self.subTest(preset=p["id"]):
                self.assertIn(p["category"], CATEGORIES)
                self.assertIn(p.get("icon", "sparkles"), self.icons)
                self.assertTrue(set(p["modes"]) <= MODES and p["modes"])
                self.assertGreater(p.get("duration", 6), 0)
                view = public_view(p)
                self.assertTrue((WEB_DIR / "thumbs" / f"{p['id']}.jpg").exists(), "missing thumbnail")
                self.assertTrue((WEB_DIR / "previews" / f"{p['id']}.mp4").exists(), "missing preview")
                self.assertEqual(view["id"], p["id"])

    def test_modes_have_their_prompts(self):
        for p in self.presets:
            with self.subTest(preset=p["id"]):
                if {"own_image", "video"} & set(p["modes"]):
                    self.assertTrue(p.get("generic_prompt"), "own image and video modes need generic_prompt")

    def test_every_template_renders_for_every_subject(self):
        for p in self.presets:
            for subject in SUBJECTS:
                for field in PROMPTS:
                    template = p.get(field) or ""
                    if not template:
                        continue
                    with self.subTest(preset=p["id"], subject=subject, field=field):
                        text = render(template, subject=subject, aspect_words=ASPECTS["16:9"]["words"],
                                      identity_notes="a short beard", wardrobe=wardrobe_for(p, subject))
                        self.assertNotRegex(text, r"\{\w+\}", "placeholder left unrendered")
                        self.assertNotIn("—", text)
                        self.assertNotIn("–", text)

    def test_scene_prompts_name_each_photo_for_qwen_image_edit_2511(self):
        # Round 7b (22/10/2026): naming the photos as image 1 and image 2 with their role fixed the
        # hair colour and earrings 2511 exaggerated with the old "from the reference images" block.
        for p in self.presets:
            if "scene" not in p["modes"]:
                continue
            with self.subTest(preset=p["id"]):
                template = p["scene_prompt"]
                self.assertIn("{references}", template)
                self.assertIn("hair colour{facial_hair}", template)
                self.assertNotIn("reference images", template)
                two = render(template, subject="man", references=2)
                one = render(template, subject="woman", references=1)
                self.assertIn("Image 1 and image 2 are two photos of the same man.", two)
                self.assertIn("hair colour, facial hair, skin tone", two)
                self.assertIn("Image 1 is a photo of the woman.", one)
                self.assertNotIn("image 2", one)
                self.assertNotIn("facial hair", one)

    def test_optional_fields(self):
        for p in self.presets:
            with self.subTest(preset=p["id"]):
                lora = p.get("effect_lora")
                if lora:
                    self.assertTrue(lora["name"].endswith(".safetensors"))
                    self.assertTrue(0 < float(lora.get("strength", 1.0)) <= 1.5)
                if p.get("last_frame_prompt") or p.get("last_frame_mode"):
                    self.assertIn(p.get("last_frame_mode", "edit"), {"edit", "mirror"})
                    strengths = p.get("flf_strengths", [0.7, 0.7])
                    self.assertEqual(len(strengths), 2)
                    self.assertTrue(all(0 < s <= 1 for s in strengths))
                    self.assertNotIn("video", p["modes"], "a last frame is built from the preset scene")
                self.assertIn(p.get("post"), {None, "reverse"})
                if p.get("post") == "reverse":
                    self.assertNotIn("video", p["modes"], "a reversed effect cannot continue a clip")


if __name__ == "__main__":
    unittest.main()
