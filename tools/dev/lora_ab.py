"""A/B a LoRA on the LTX-2.5 effect pass: same first frame, same prompt, same seed.

    python tools/lora_ab.py walk-of-fire FRAME.png OUT_DIR --lora none --lora LTX_2.3_Crisp_Enhance_Style.safetensors:0.7

Each --lora is NAME[:STRENGTH] ("none" is the baseline). The LoRA goes on the model only,
between the transformer loader and both guiders, so it acts on the half-res pass and on the
upscaled refine pass alike.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from comfy_sdk import Comfy  # noqa: E402

from vfx4all.config import ASPECTS, EFFECT_WORKFLOW, QUALITY_MEGAPIXELS, api_key, load_dotenv  # noqa: E402
from vfx4all.presets import get_preset, render  # noqa: E402

UNET = "398:384"


def with_lora(graph: dict, name: str, strength: float, node_id: str = "900") -> dict:
    graph[node_id] = {"class_type": "LoraLoaderModelOnly",
                      "inputs": {"model": [UNET, 0], "lora_name": name, "strength_model": strength}}
    for nid, node in graph.items():
        if nid != node_id and node["inputs"].get("model") == [UNET, 0]:
            node["inputs"]["model"] = [node_id, 0]
    return graph


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("preset")
    parser.add_argument("frame", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--lora", action="append", default=[])
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument("--subject", default="person")
    args = parser.parse_args()

    load_dotenv()
    client = Comfy(api_key=api_key())
    preset = get_preset(args.preset)
    prompt = render(preset["effect_prompt"], subject=args.subject)
    # set_input writes into the dict it was given, so every variant starts from a fresh parse.
    base_text = EFFECT_WORKFLOW.read_text(encoding="utf-8")
    frame = client.assets.from_file(args.frame)
    args.out.mkdir(parents=True, exist_ok=True)

    jobs = []
    for spec in args.lora or ["none"]:
        name, _, strength = spec.partition(":")
        base = json.loads(base_text)
        graph = base if name == "none" else with_lora(base, name, float(strength or 1.0))
        wf = client.workflows.from_json(graph)
        wf.set_input("395", "image", frame)
        wf.set_input("398:376", "value", prompt)
        wf.set_input("403", "aspect_ratio", ASPECTS["16:9"]["selector"])
        wf.set_input("403", "megapixels", QUALITY_MEGAPIXELS["draft"])
        wf.set_input("398:362", "value", int(preset.get("duration", 6)))
        wf.set_input("398:339", "noise_seed", args.seed)
        tag = "base" if name == "none" else f"{Path(name).stem}_{strength or '1.0'}"
        jobs.append((tag, client.submit(wf), time.time()))
        print("queued", tag, flush=True)

    for tag, job, started in jobs:
        try:
            job.result()
            out = job.get_outputs("75")
            path = args.out / f"{args.preset}_{tag}.mp4"
            out[0].to_file(path)
            print("done", tag, round(time.time() - started, 1), "s", path.name, flush=True)
        except Exception as exc:  # report and keep going with the other variants
            print("failed", tag, repr(exc)[:400], flush=True)


if __name__ == "__main__":
    main()
