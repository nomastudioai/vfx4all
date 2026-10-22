"""Render test versions of presets: scene (Qwen) -> effect (LTX-2.5 DFR) -> card thumbnail and preview.

    python tools/batch_presets.py --experimental --out D:/.../pruebas_ltx --tag v05 --workers 3
    python tools/batch_presets.py ice-age gold-touch --out ... --tag v05

Casting is a local test setting, not part of the presets: CAST maps a subject to its reference
photos and identity notes. Pass --cast-file with a JSON file to change it. A failed take (black or
NaN) is retried with the next seed, like the app does.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from comfy_sdk.exceptions import JobFailed  # noqa: E402

from vfx4all import media  # noqa: E402
from vfx4all.config import (ASPECTS, BLACK_LUMA_THRESHOLD, MAX_RETRIES, QUALITY_MEGAPIXELS,  # noqa: E402
                            WEB_DIR, load_dotenv)
from vfx4all.engine import Engine  # noqa: E402
from vfx4all.pipeline import flf_size, keyframes  # noqa: E402
from vfx4all.presets import get_preset, load_presets, render, wardrobe_for  # noqa: E402

LOCK = threading.Lock()


def log(msg: str) -> None:
    with LOCK:
        print(time.strftime("%H:%M:%S"), msg, flush=True)


def retry_io(fn, tries: int = 3):
    """Comfy Cloud asset calls time out now and then under load; a job failure is not retried here."""
    for attempt in range(tries):
        try:
            return fn()
        except JobFailed:
            raise
        except Exception as exc:  # network hiccups (httpx timeouts) only
            if attempt == tries - 1 or "timed out" not in str(exc).lower() and "timeout" not in type(exc).__name__.lower():
                raise
            log(f"  network retry after {type(exc).__name__}")
            time.sleep(5 * (attempt + 1))


def thumb_and_preview(video: Path, pid: str, at: float) -> None:
    ff = media.FFMPEG
    thumbs, previews = WEB_DIR / "thumbs", WEB_DIR / "previews"
    thumbs.mkdir(exist_ok=True)
    previews.mkdir(exist_ok=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1",
                    "-vf", "scale=640:-2", "-q:v", "3", str(thumbs / f"{pid}.jpg")], check=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(video), "-an", "-vf", "scale=640:-2",
                    "-c:v", "libx264", "-crf", "30", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(previews / f"{pid}.mp4")], check=True)


def run_one(engine: Engine, preset: dict, cast: dict, out: Path, tag: str, seed: int, quality: str,
            reuse_scene: bool) -> dict:
    pid = preset["id"]
    subject = cast["preset_subject"].get(pid) or cast["default_subject"]
    actor = cast["actors"][subject]
    fmt = ASPECTS["16:9"]
    t0 = time.time()
    scene_png = out / f"inputs_{tag}" / f"{pid}_f0.png"
    scene_png.parent.mkdir(parents=True, exist_ok=True)
    record = {"id": pid, "subject": subject, "seed": seed, "lora": preset.get("effect_lora")}
    if not (reuse_scene and scene_png.exists()):
        prompt = render(preset["scene_prompt"], subject=subject, aspect_words=fmt["words"],
                        identity_notes=actor["notes"], wardrobe=wardrobe_for(preset, subject))
        refs = [Path(r) for r in actor["refs"]]
        log(f"{pid}: scene ({subject})")
        made = retry_io(lambda: engine.scene(refs, prompt, fmt["scene"], seed, scene_png.with_suffix(""),
                                             lambda p, m: None))
        if made != scene_png:
            made.replace(scene_png)
    record["scene_s"] = round(time.time() - t0, 1)
    last, mids = retry_io(lambda: keyframes(engine, preset, scene_png, subject, scene_png.parent, seed,
                                            face=Path(actor["refs"][0]), reuse=reuse_scene))
    if last:
        record["keyframes"] = [last.name] + [m.name for m, _ in mids]

    prompt = render(preset["effect_prompt"], subject=subject)
    video = out / f"renders_{tag}" / f"{pid}.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    attempts = []
    for attempt in range(MAX_RETRIES + 1):
        s = seed + attempt
        t1 = time.time()
        log(f"{pid}: effect seed {s}")
        try:
            if last:
                graph = "flf"
                made = retry_io(lambda: engine.effect_flf(scene_png, last, prompt, flf_size(fmt["selector"], quality),
                                                          preset.get("duration", 6), s, video.with_suffix(""),
                                                          lambda p, m: None, mids, preset.get("effect_lora"),
                                                          tuple(preset.get("flf_strengths") or (0.7, 0.7))))
            else:
                graph = "classic" if attempt == MAX_RETRIES else None  # same fallback as the app
                made = retry_io(lambda: engine.effect(scene_png, prompt, fmt["selector"], QUALITY_MEGAPIXELS[quality],
                                                      preset.get("duration", 6), s, video.with_suffix(""),
                                                      lambda p, m: None, preset.get("effect_lora"), graph))
        except JobFailed as exc:
            text = str(getattr(exc, "error", "") or exc)
            attempts.append({"seed": s, "result": "nan" if "nan" in text.lower() else "failed", "s": round(time.time() - t1, 1)})
            if "nan" in text.lower():
                continue
            record.update(attempts=attempts, error=text[:300])
            return record
        if made != video:
            made.replace(video)
        luma = media.mean_luma(video)
        attempts.append({"seed": s, "graph": graph or "dfr", "result": "ok" if luma >= BLACK_LUMA_THRESHOLD else "black",
                         "luma": round(luma, 1), "s": round(time.time() - t1, 1)})
        if luma >= BLACK_LUMA_THRESHOLD:
            break
        video.replace(video.with_name(f"{pid}_black_{attempt}.mp4"))
    record["attempts"] = attempts
    if not video.exists():
        record["error"] = "every take failed"
        return record
    if preset.get("post") == "reverse":
        forward = video.with_name(f"{pid}_forward.mp4")
        video.replace(forward)
        media.reverse(forward, video)
    thumb_and_preview(video, pid, at=min(preset.get("duration", 6) * 0.7, 4.2))
    record["total_s"] = round(time.time() - t0, 1)
    log(f"{pid}: done in {record['total_s']} s, {len(attempts)} take(s)")
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("presets", nargs="*")
    parser.add_argument("--experimental", action="store_true", help="every preset marked experimental")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tag", default="v05")
    parser.add_argument("--cast-file", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument("--quality", default="draft")
    parser.add_argument("--reuse-scene", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    cast = json.loads(args.cast_file.read_text(encoding="utf-8"))
    presets = [p for p in load_presets() if p.get("experimental")] if args.experimental else []
    presets += [get_preset(pid) for pid in args.presets]
    engine = Engine()
    log(f"{len(presets)} presets, {args.workers} workers")
    logfile = args.out / f"renders_{args.tag}" / "log.jsonl"
    logfile.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, engine, p, cast, args.out, args.tag, args.seed, args.quality,
                               args.reuse_scene): p["id"] for p in presets}
        for fut in as_completed(futures):
            try:
                rec = fut.result()
            except Exception as exc:
                rec = {"id": futures[fut], "error": f"{type(exc).__name__}: {exc}"[:400]}
                log(f"{futures[fut]}: ERROR {rec['error']}")
            with LOCK, logfile.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
