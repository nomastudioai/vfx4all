"""Build one Comfy Cloud App Mode graph per preset: photo -> film scene (Qwen Image Edit 2511) -> effect
(LTX-2.5 DFR).

App Mode runs a single graph with no code around it, so the preset text is baked in with the
neutral subject ("person") and the scene image feeds LTX directly. Visitors open the app with
their own Comfy account and spend their own credits, so the web app never needs their key.

    python tools/build_app_graph.py walk-of-fire            # writes workflows/apps/walk-of-fire.json
    python tools/build_app_graph.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vfx4all.config import ASPECTS, QUALITY_MEGAPIXELS, WORKFLOWS_DIR  # noqa: E402
from vfx4all.engine import (SCENE_REF_1, SCENE_SAMPLER, SCENE_SAVE, SCENE_TEXT,  # noqa: E402
                            scene_graph)
from vfx4all.presets import get_preset, load_presets, render, wardrobe_for  # noqa: E402

OUT_DIR = WORKFLOWS_DIR / "apps"
SUBJECT = "person"
ASPECT = "16:9"

# Node ids in the merged graph. Plain integers, because the API to save format conversion
# on Comfy Cloud emits a flat graph and does not rebuild subgraph ids like "459:451".
PHOTO, SCENE_SAVE_ID, SCENE_PROMPT, SCENE_SAMPLER_ID, RGB = 1, 2, 3, 4, 5
EFFECT_PROMPT, EFFECT_SEED, EFFECT_SAVE = 101, 102, 103
# LTX-2.5 DFR graph: one noise node per stage. App Mode exposes one seed that feeds all three.
DFR_SEEDS = ("5953:5808", "5953:5843", "5953:5878")


def _load(name: str) -> dict:
    return json.loads((WORKFLOWS_DIR / name).read_text(encoding="utf-8"))


def _remap(graph: dict, fixed: dict[str, int], start: int) -> tuple[dict, dict[str, str]]:
    ids, nxt = {}, start
    for old in graph:
        if old in fixed:
            ids[old] = str(fixed[old])
        else:
            while nxt in fixed.values():
                nxt += 1
            ids[old], nxt = str(nxt), nxt + 1
    out = {}
    for old, node in graph.items():
        inputs = {}
        for key, value in node["inputs"].items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] in ids:
                value = [ids[value[0]], value[1]]
            inputs[key] = value
        out[ids[old]] = {**node, "inputs": inputs}
    return out, ids


def app_ready(preset: dict) -> bool:
    """A single App Mode graph covers scene + one-frame effect. Presets that need a last frame or a
    step after rendering (play backward) still run only in the VFX 4 All server."""
    return ("scene" in preset["modes"] and not preset.get("last_frame_prompt")
            and not preset.get("last_frame_mode") and not preset.get("post"))


def build(preset: dict) -> dict:
    if not app_ready(preset):
        raise ValueError(f"{preset['id']} cannot be a single App Mode graph yet")
    fmt = ASPECTS[ASPECT]

    # One photo in App Mode, so the scene graph without the second reference slot.
    scene, _ = _remap(scene_graph(two_refs=False),
                      {SCENE_REF_1: PHOTO, SCENE_SAVE: SCENE_SAVE_ID, SCENE_TEXT: SCENE_PROMPT,
                       SCENE_SAMPLER: SCENE_SAMPLER_ID}, 10)
    scene[str(SCENE_PROMPT)]["inputs"]["prompt"] = render(preset["scene_prompt"], subject=SUBJECT,
                                                          aspect_words=fmt["words"],
                                                          wardrobe=wardrobe_for(preset, SUBJECT), references=1)
    latent = next(v for v in scene.values() if v["class_type"] == "EmptySD3LatentImage")
    latent["inputs"]["width"], latent["inputs"]["height"] = fmt["scene"]
    scene[str(SCENE_SAVE_ID)]["inputs"]["filename_prefix"] = f"vfx4all/{preset['id']}_scene"
    scene[str(PHOTO)]["inputs"]["image"] = "example.png"
    scene[str(PHOTO)]["_meta"] = {"title": "Your photo (front view)"}
    decode = next(k for k, v in scene.items() if v["class_type"] == "VAEDecode")
    # LTXVPreprocess only takes RGB. The Qwen Image VAE already decodes to RGB, but an RGBA image
    # breaks the whole app, so the split stays as a guard (it passes RGB through untouched). The two
    # step app never needs it: the scene goes through a PNG and LoadImage on the way.
    scene[str(RGB)] = {"class_type": "SplitImageWithAlpha", "inputs": {"image": [decode, 0]},
                       "_meta": {"title": "Scene to RGB"}}

    effect, ids = _remap(_load("effect_ltx_2_5_dfr_i2v.json"),
                         {"5953:5508": EFFECT_PROMPT, "4852": EFFECT_SAVE}, 200)
    # The scene frame replaces the LoadImage of the i2v graph.
    load = next(k for k, v in effect.items() if v["class_type"] == "LoadImage")
    for node in effect.values():
        for key, value in node["inputs"].items():
            if value == [load, 0]:
                node["inputs"][key] = [str(RGB), 0]
    del effect[load]
    effect[str(EFFECT_SEED)] = {"class_type": "PrimitiveInt", "inputs": {"value": 0}, "_meta": {"title": "Effect seed"}}
    for old in DFR_SEEDS:
        effect[ids[old]]["inputs"]["noise_seed"] = [str(EFFECT_SEED), 0]
    effect[str(EFFECT_PROMPT)]["inputs"]["value"] = render(preset["effect_prompt"], subject=SUBJECT)
    effect[str(EFFECT_PROMPT)]["_meta"] = {"title": "Effect prompt"}
    for node in effect.values():
        if node["class_type"] == "ResolutionSelector":
            node["inputs"].update(aspect_ratio=fmt["selector"], megapixels=QUALITY_MEGAPIXELS["draft"])
        if node["class_type"] == "PrimitiveFloat" and node.get("_meta", {}).get("title") == "Duration":
            node["inputs"]["value"] = float(preset.get("duration", 6))
    effect[str(EFFECT_SAVE)]["inputs"]["filename_prefix"] = f"vfx4all/{preset['id']}"

    return {**scene, **effect}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("presets", nargs="*")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    chosen = [p for p in load_presets() if app_ready(p)] if args.all else [get_preset(i) for i in args.presets]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for preset in chosen:
        path = OUT_DIR / f"{preset['id']}.json"
        path.write_text(json.dumps(build(preset), indent=2, ensure_ascii=False), encoding="utf-8")
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
