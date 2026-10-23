"""Every model the graphs or presets load is listed in THIRD_PARTY_NOTICES.md."""

import json
import unittest

from vfx4all.config import ROOT, WORKFLOWS_DIR
from vfx4all.presets import load_presets

# File name prefix in the Comfy Cloud catalog -> text its row in the notices must contain.
FAMILIES = {
    "ltx-2.5-22b-ic-lora-refine-details": "Lightricks/LTX-2.5-22b-IC-LoRA-Refine-Details",
    "ltx-2.5-": "Lightricks/LTX-2.5",
    "gemma4-12b": "Gemma 4 12B",
    "qwen_image_edit_2511": "Qwen/Qwen-Image-Edit-2511",
    "qwen_image_vae": "Qwen/Qwen-Image)",
    "qwen_2.5_vl_7b": "Qwen/Qwen2.5-VL-7B-Instruct",
}
LORAS = {
    "LTX2.3_Cozy_Felt_Style.safetensors": "Cozy Felt",
    "LTX_2.3_Clay_Mation_Style.safetensors": "Clay Mation",
    "LTX_2.3_Fantasy_Painterly_Style.safetensors": "Fantasy Painterly",
    "LTX_2.3_Fantasy_Anime_Style.safetensors": "Fantasy Anime",
    "LTX_2.3_Cinematic_Sci-fi-Cyberpunk_Style.safetensors": "Cyberpunk",
}


def model_files() -> set:
    names = set()
    for path in WORKFLOWS_DIR.glob("*.json"):
        for node in json.loads(path.read_text(encoding="utf-8")).values():
            for value in node["inputs"].values():
                if isinstance(value, str) and value.endswith(".safetensors"):
                    names.add(value)
    return names


class NoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    def test_every_model_file_has_a_row(self):
        for name in sorted(model_files()):
            with self.subTest(model=name):
                family = next((text for prefix, text in FAMILIES.items() if name.startswith(prefix)), None)
                self.assertIsNotNone(family, "new model: add it to THIRD_PARTY_NOTICES.md and to FAMILIES")
                self.assertIn(family, self.notices)

    def test_every_preset_lora_has_a_row(self):
        for preset in load_presets():
            lora = (preset.get("effect_lora") or {}).get("name")
            if lora:
                with self.subTest(preset=preset["id"]):
                    self.assertIn(lora, LORAS, "new LoRA: add it to THIRD_PARTY_NOTICES.md and to LORAS")
                    self.assertIn(LORAS[lora], self.notices)
                    self.assertIn(preset["name"], self.notices)


if __name__ == "__main__":
    unittest.main()
