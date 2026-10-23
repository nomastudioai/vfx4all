"""Run a preset through the LTX-2.5 DFR graph (workflows/effect_ltx_2_5_dfr_i2v.json) for A/B against
tools/lora_ab.py: same first frame, prompt and seed.

    python tools/dfr_ab.py walk-of-fire FRAME.png OUT_DIR --cond 0.25 --cond 1.0 [--temporal]

--cond is the scale of the conditioning image against the output size. The Comfy template ships
0.25; 1.0 keeps the first frame sharp, which the splice mode needs.
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

from vfx4all.config import ASPECTS, QUALITY_MEGAPIXELS, WORKFLOWS_DIR, api_key, load_dotenv  # noqa: E402
from vfx4all.presets import get_preset, render  # noqa: E402

GRAPH = WORKFLOWS_DIR / "effect_ltx_2_5_dfr_i2v.json"
NEGATIVE = "pc game, console game, video game, cartoon, childish, ugly"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("preset")
    parser.add_argument("frame", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--cond", type=float, action="append", default=[])
    parser.add_argument("--temporal", action="store_true")
    # The template's pixel-spatial IC-LoRA is not on Comfy Cloud yet; "none" skips the LoRA.
    parser.add_argument("--lora", default="ltx-2.5-22b-ic-lora-refine-details-1.0.safetensors")
    parser.add_argument("--quality", default="draft")
    parser.add_argument("--clip", default="", help="text encoder file, e.g. the int8 build")
    parser.add_argument("--no-tiled", action="store_true", help="plain VAE decode instead of tiled")
    parser.add_argument("--unet", default="", help="transformer file, e.g. the int8 build")
    parser.add_argument("--duration", type=float, default=0.0)
    parser.add_argument("--tag", default="")
    parser.add_argument("--seed", type=int, default=20261016)
    args = parser.parse_args()

    load_dotenv()
    client = Comfy(api_key=api_key())
    preset = get_preset(args.preset)
    prompt = render(preset["effect_prompt"], subject="person")
    text = GRAPH.read_text(encoding="utf-8")
    frame = client.assets.from_file(args.frame)
    args.out.mkdir(parents=True, exist_ok=True)

    jobs = []
    for cond in args.cond or [0.25]:
        graph = json.loads(text)
        if preset.get("effect_lora"):
            from vfx4all.engine import with_style_lora
            graph = with_style_lora(graph, preset["effect_lora"])
        if args.lora == "none":
            for nid in ("5953:5835", "5953:5877"):
                graph[nid]["inputs"]["model"] = ["5953:5742", 0]
            del graph["5953:5903"]
        else:
            graph["5953:5903"]["inputs"]["lora_name"] = args.lora
        if args.clip:
            graph["5953:5745"]["inputs"]["clip_name"] = args.clip
        if args.unet:
            graph["5953:5742"]["inputs"]["unet_name"] = args.unet
        if args.no_tiled:
            graph["5953:5915"]["inputs"]["value"] = False
        wf = client.workflows.from_json(graph)
        wf.set_input("2004", "image", frame)
        wf.set_input("5953:5508", "value", prompt)
        wf.set_input("5953:5509", "value", NEGATIVE)
        wf.set_input("5954", "aspect_ratio", ASPECTS["16:9"]["selector"])
        wf.set_input("5954", "megapixels", QUALITY_MEGAPIXELS[args.quality])
        wf.set_input("5953:5918", "value", float(args.duration or preset.get("duration", 6)))
        wf.set_input("5953:5729", "resize_type.multiplier", cond)
        wf.set_input("5953:5901", "value", args.temporal)
        for node in ("5953:5808", "5953:5843", "5953:5878"):
            wf.set_input(node, "noise_seed", args.seed)
        lora = "nolora" if args.lora == "none" else Path(args.lora).stem.split("-ic-lora-")[-1]
        tag = f"dfr_{lora}_c{cond}{'_t2x' if args.temporal else ''}_{args.quality}{args.tag}"
        jobs.append((tag, client.submit(wf), time.time()))
        print("queued", tag, flush=True)

    for tag, job, started in jobs:
        try:
            job.result()
            outs = job.get_outputs("4852")
            if not outs:
                print("no output", tag, job.id, flush=True)
                continue
            path = args.out / f"{args.preset}_{tag}.mp4"
            outs[0].to_file(path)
            print("done", tag, round(time.time() - started, 1), "s", path.name, flush=True)
        except Exception as exc:
            print("failed", tag, str(getattr(exc, "error", None) or exc)[:600], flush=True)


if __name__ == "__main__":
    main()
