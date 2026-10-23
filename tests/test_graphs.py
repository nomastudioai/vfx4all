"""The ComfyUI graphs are wired correctly and the node ids the engine sets still exist."""

import json
import sys
import unittest
from pathlib import Path

from vfx4all import engine
from vfx4all.config import DFR_WORKFLOW, EDIT_WORKFLOW, EFFECT_WORKFLOW, FLF_WORKFLOW, ROOT, SCENE_WORKFLOW, WORKFLOWS_DIR
from vfx4all.presets import load_presets

sys.path.insert(0, str(ROOT / "tools"))
import build_app_graph  # noqa: E402


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dangling(graph: dict) -> list:
    """Links that point at a node the graph does not have."""
    bad = []
    for node_id, node in graph.items():
        for name, value in node["inputs"].items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
                if value[0] not in graph:
                    bad.append((node_id, name, value[0]))
    return bad


def expect(test, graph: dict, node_id: str, class_type: str):
    test.assertIn(node_id, graph)
    test.assertEqual(graph[node_id]["class_type"], class_type)


class WorkflowFileTests(unittest.TestCase):
    def test_every_graph_is_well_formed(self):
        files = sorted(WORKFLOWS_DIR.glob("*.json")) + sorted((WORKFLOWS_DIR / "apps").glob("*.json"))
        self.assertGreater(len(files), 5)
        for path in files:
            with self.subTest(graph=path.name):
                graph = load(path)
                for node in graph.values():
                    self.assertIn("class_type", node)
                    self.assertIsInstance(node["inputs"], dict)
                self.assertEqual(dangling(graph), [])

    def test_node_ids_the_engine_sets(self):
        scene = load(SCENE_WORKFLOW)
        expect(self, scene, engine.SCENE_REF_1, "LoadImage")
        expect(self, scene, engine.SCENE_REF_2, "LoadImage")
        expect(self, scene, engine.SCENE_TEXT, "TextEncodeQwenImageEditPlus")
        expect(self, scene, engine.SCENE_NEGATIVE, "TextEncodeQwenImageEditPlus")
        expect(self, scene, engine.SCENE_LATENT, "EmptySD3LatentImage")
        expect(self, scene, engine.SCENE_SAMPLER, "KSampler")
        expect(self, scene, engine.SCENE_SAVE, "SaveImage")

        classic = load(EFFECT_WORKFLOW)
        expect(self, classic, engine.EFFECT_IMAGE, "LoadImage")
        expect(self, classic, engine.EFFECT_SIZE, "ResolutionSelector")
        expect(self, classic, engine.EFFECT_SEED, "RandomNoise")
        expect(self, classic, engine.EFFECT_SAVE, "SaveVideo")
        expect(self, classic, engine.CLASSIC_TRANSFORMER, "UNETLoader")

        dfr = load(DFR_WORKFLOW)
        expect(self, dfr, engine.DFR_IMAGE, "LoadImage")
        expect(self, dfr, engine.DFR_PROMPT, "PrimitiveStringMultiline")
        expect(self, dfr, engine.DFR_SIZE, "ResolutionSelector")
        expect(self, dfr, engine.DFR_DURATION, "PrimitiveFloat")
        expect(self, dfr, engine.DFR_SAVE, "SaveVideo")
        expect(self, dfr, engine.DFR_TRANSFORMER, "UNETLoader")
        for node_id in engine.DFR_SEEDS:
            expect(self, dfr, node_id, "RandomNoise")

        flf = load(FLF_WORKFLOW)
        for node_id in ("31", "39"):
            expect(self, flf, node_id, "LoadImage")
        for node_id in ("251:206", "251:204"):
            expect(self, flf, node_id, "LTXVAddGuide")
        expect(self, flf, "251:252", "PrimitiveStringMultiline")
        expect(self, flf, "251:196", "RandomNoise")
        expect(self, flf, "68", "SaveVideo")
        expect(self, flf, engine.FLF_TRANSFORMER, "UNETLoader")

        edit = load(EDIT_WORKFLOW)
        expect(self, edit, "1", "LoadImage")
        expect(self, edit, "8", "TextEncodeQwenImageEditPlus")
        expect(self, edit, "13", "KSampler")
        expect(self, edit, "15", "SaveImage")

    def test_scenes_use_a_model_licensed_for_commercial_use(self):
        # Qwen Image 2.1 is non-commercial only; scenes moved to Qwen Image Edit 2511 (Apache 2.0).
        text = SCENE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("qwen_image_edit_2511", text)
        self.assertNotIn("qwen_image_2.1", text)

    def test_effect_graphs_use_the_int8_builds(self):
        # bf16 transformer and encoder inside DFR came back black on every seed (round 5).
        for path in (DFR_WORKFLOW, FLF_WORKFLOW):
            text = path.read_text(encoding="utf-8")
            with self.subTest(graph=path.name):
                self.assertIn("ltx-2.5-22b-distilled-transformer-comfy-int8-convrot", text)
                self.assertIn("gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot", text)


class GraphBuilderTests(unittest.TestCase):
    def test_style_lora_sits_between_transformer_and_every_consumer(self):
        lora = {"name": "LTX_2.3_Clay_Mation_Style.safetensors", "strength": 0.8}
        for path, transformer in ((DFR_WORKFLOW, engine.DFR_TRANSFORMER), (EFFECT_WORKFLOW, engine.CLASSIC_TRANSFORMER),
                                  (FLF_WORKFLOW, engine.FLF_TRANSFORMER)):
            with self.subTest(graph=path.name):
                plain = load(path)
                consumers = [k for k, v in plain.items() if v["inputs"].get("model") == [transformer, 0]]
                self.assertTrue(consumers)
                graph = engine.with_style_lora(load(path), lora, transformer)
                node = graph[engine.STYLE_LORA]
                self.assertEqual(node["inputs"]["model"], [transformer, 0])
                self.assertEqual(node["inputs"]["strength_model"], 0.8)
                for consumer in consumers:
                    self.assertEqual(graph[consumer]["inputs"]["model"], [engine.STYLE_LORA, 0])
                self.assertEqual(dangling(graph), [])

    def test_no_lora_leaves_the_graph_alone(self):
        self.assertEqual(engine.with_style_lora(load(DFR_WORKFLOW), None), load(DFR_WORKFLOW))

    def test_flf_middle_guides_are_chained_in_order(self):
        graph = engine.flf_graph([48, 96])
        self.assertEqual(dangling(graph), [])
        first, second = "9503", "9513"
        self.assertEqual(graph[first]["inputs"]["latent"], ["251:206", 2])
        self.assertEqual(graph[second]["inputs"]["latent"], [first, 2])
        self.assertEqual([graph[first]["inputs"]["frame_idx"], graph[second]["inputs"]["frame_idx"]], [48, 96])
        for key, slot in (("latent", 2), ("negative", 1), ("positive", 0)):
            self.assertEqual(graph["251:204"]["inputs"][key], [second, slot])
        self.assertEqual(engine.mid_node(1), "9510")

    def test_flf_without_middle_guides_matches_the_file(self):
        self.assertEqual(engine.flf_graph(), load(FLF_WORKFLOW))

    def test_scene_graph_with_one_photo_drops_the_second_slot(self):
        two, one = engine.scene_graph(), engine.scene_graph(two_refs=False)
        self.assertEqual(dangling(two), [])
        self.assertEqual(dangling(one), [])
        self.assertNotIn(engine.SCENE_REF_2, one)
        for node in (engine.SCENE_TEXT, engine.SCENE_NEGATIVE):
            self.assertNotIn("image2", one[node]["inputs"])
            self.assertEqual(two[node]["inputs"]["image2"], ["17", 0])

    def test_edit_graph_with_a_face_reference(self):
        graph = engine.edit_graph(with_face=True)
        self.assertEqual(dangling(graph), [])
        for node in ("8", "9"):
            self.assertEqual(graph[node]["inputs"]["image2"], ["17", 0])
        self.assertNotIn("16", engine.edit_graph())


class AppModeGraphTests(unittest.TestCase):
    def test_every_app_ready_preset_builds_one_graph(self):
        presets = load_presets()
        ready = [p for p in presets if build_app_graph.app_ready(p)]
        self.assertGreater(len(ready), 30)
        for preset in ready:
            with self.subTest(preset=preset["id"]):
                graph = build_app_graph.build(preset)
                self.assertEqual(dangling(graph), [])
                expect(self, graph, str(build_app_graph.PHOTO), "LoadImage")
                expect(self, graph, str(build_app_graph.RGB), "SplitImageWithAlpha")
                expect(self, graph, str(build_app_graph.EFFECT_SAVE), "SaveVideo")
                seed = [str(build_app_graph.EFFECT_SEED), 0]
                noises = [v for v in graph.values() if v["class_type"] == "RandomNoise"]
                self.assertEqual(len(noises), 3)
                self.assertTrue(all(n["inputs"]["noise_seed"] == seed for n in noises))
                self.assertEqual(len([v for v in graph.values() if v["class_type"] == "LoadImage"]), 1)

    def test_presets_that_need_more_than_one_graph_are_refused(self):
        for preset in load_presets():
            if not build_app_graph.app_ready(preset):
                with self.subTest(preset=preset["id"]), self.assertRaises(ValueError):
                    build_app_graph.build(preset)


if __name__ == "__main__":
    unittest.main()
