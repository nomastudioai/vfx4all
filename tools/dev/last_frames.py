"""Build the last frame of a first-and-last-frame preset: Qwen Image Edit 2511 over the first frame.

    python tools/last_frames.py ant-size bullet-time comic-panel --out .../pruebas_ltx --tag v05 --cast-file cast.json

image 1 is the preset's first frame (inputs_<tag>/<id>_f0.png), image 2 the face reference of the
subject, so the edit keeps the scene and the person. Writes inputs_<tag>/<id>_f1.png.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vfx4all import media  # noqa: E402
from vfx4all.config import ASPECTS, load_dotenv  # noqa: E402
from vfx4all.engine import Engine  # noqa: E402
from vfx4all.presets import get_preset, render, wardrobe_for  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("presets", nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tag", default="v05")
    parser.add_argument("--cast-file", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261016)
    args = parser.parse_args()
    load_dotenv()
    cast = json.loads(args.cast_file.read_text(encoding="utf-8"))
    engine = Engine()
    _ = engine.client

    def one(pid: str) -> str:
        preset = get_preset(pid)
        subject = cast["preset_subject"][pid]
        actor = cast["actors"][subject]
        first = args.out / f"inputs_{args.tag}" / f"{pid}_f0.png"
        last = first.with_name(f"{pid}_f1.png")
        if preset.get("last_frame_mode") == "mirror":
            media.mirror(first, last)
            return f"{pid}: {last.name} (mirrored)"
        prompt = render(preset["last_frame_prompt"], subject=subject, aspect_words=ASPECTS["16:9"]["words"],
                        identity_notes=actor["notes"], wardrobe=wardrobe_for(preset, subject))
        face = Path(actor["refs"][0]) if "image 2" in prompt else None
        made = engine.edit_frame(first, prompt, args.seed, last.with_suffix(""), lambda p, m: None, face)
        if made != last:
            made.replace(last)
        return f"{pid}: {last.name}"

    with ThreadPoolExecutor(max_workers=3) as pool:
        for line in pool.map(one, args.presets):
            print(line, flush=True)


if __name__ == "__main__":
    main()
