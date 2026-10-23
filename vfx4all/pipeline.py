"""The three things a user can ask for: build a scene, animate an effect, or
splice an effect into an existing video."""

from __future__ import annotations

import random
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from comfy_sdk.exceptions import JobFailed

from . import media
from .config import (ASPECTS, BLACK_LUMA_THRESHOLD, MAX_RETRIES, QUALITY_MEGAPIXELS,
                     closest_selector)
from .engine import Engine
from .jobs import Job
from .presets import get_preset, render, wardrobe_for

SPLICE_DURATION = 5
_SERVER_ENGINE: Engine | None = None
_ENGINE_LOCK = threading.Lock()


@contextmanager
def engine_for(key: str | None) -> Iterator[Engine]:
    """The server key's engine (shared), or a one-off engine for a key the user brought. A
    user's key is never kept: its engine is closed when the job ends."""
    global _SERVER_ENGINE
    user_key = (key or "").strip()
    if user_key:
        engine = Engine(user_key)
        try:
            yield engine
        finally:
            engine.close()
        return
    with _ENGINE_LOCK:
        if _SERVER_ENGINE is None:
            _SERVER_ENGINE = Engine()
    yield _SERVER_ENGINE


def supports(preset: dict, mode: str) -> bool:
    """Whether a preset runs in a mode: "scene" (photo scene), "own_image" or "video"."""
    if mode not in preset["modes"]:
        return False
    return mode == "scene" or bool(preset.get("generic_prompt"))


def _seed(seed: int | None) -> int:
    return int(seed) if seed not in (None, "") else random.randint(1, 2**31 - 1)


def _effect_with_retry(job: Job, engine: Engine, image: Path, prompt: str, selector: str,
                       quality: str, duration: int, seed: int, name: str,
                       lora: dict | None = None) -> Path:
    """Render the effect; a failed take (it happens on some seeds) is retried
    with the next seed before the user ever sees it. A failed take shows up two
    ways: a black video, or NaNs that make the audio encoder in SaveVideo fail."""
    megapixels = QUALITY_MEGAPIXELS.get(quality, QUALITY_MEGAPIXELS["draft"])
    for attempt in range(MAX_RETRIES + 1):
        label = "Animating the effect" if attempt == 0 else f"Failed take, retrying ({attempt}/{MAX_RETRIES})"
        # The DFR graph fails on some inputs whatever the seed (round 5); the classic graph has not
        # failed on them, so the last attempt goes through it.
        graph = "classic" if attempt == MAX_RETRIES else None
        job.set(0.05, label)
        try:
            out = engine.effect(image, prompt, selector, megapixels, duration, seed + attempt,
                                job.dir / name, lambda p, m: job.set(p, f"{label}: {m}"), lora, graph)
        except JobFailed as exc:
            if "nan" not in str(getattr(exc, "error", "") or exc).lower():
                raise
            continue
        if media.mean_luma(out) >= BLACK_LUMA_THRESHOLD:
            job.params["seed_used"] = seed + attempt
            job.params["graph_used"] = graph or "default"
            return out
        out.rename(out.with_name(f"{out.stem}_black_{attempt}{out.suffix}"))
    raise RuntimeError("Every attempt failed (black or NaN take). Try another seed or preset.")


def _flf_with_retry(job: Job, engine: Engine, first: Path, last: Path, mids: list, prompt: str,
                    selector: str, quality: str, duration: int, seed: int, lora: dict | None,
                    strengths: list | None = None) -> Path:
    """First and last frame effect, with the same failed-take check as `_effect_with_retry`."""
    for attempt in range(MAX_RETRIES + 1):
        label = "Animating between the key frames" if attempt == 0 else f"Failed take, retrying ({attempt}/{MAX_RETRIES})"
        job.set(0.1, label)
        try:
            out = engine.effect_flf(first, last, prompt, flf_size(selector, quality), duration, seed + attempt,
                                    job.dir / "effect", lambda p, m: job.set(p, f"{label}: {m}"), mids, lora,
                                    tuple(strengths or (0.7, 0.7)))
        except JobFailed as exc:
            if "nan" not in str(getattr(exc, "error", "") or exc).lower():
                raise
            continue
        if media.mean_luma(out) >= BLACK_LUMA_THRESHOLD:
            job.params["seed_used"] = seed + attempt
            job.params["graph_used"] = "flf"
            return out
        out.rename(out.with_name(f"{out.stem}_black_{attempt}{out.suffix}"))
    raise RuntimeError("Every attempt failed (black or NaN take). Try another seed or preset.")


def run_scene(job: Job, *, key: str | None, preset_id: str, refs: list[Path], subject: str,
              notes: str, aspect: str, seed: int | None) -> None:
    preset = get_preset(preset_id)
    fmt = ASPECTS[aspect]
    prompt = render(preset["scene_prompt"], subject=subject, aspect_words=fmt["words"],
                    identity_notes=notes, wardrobe=wardrobe_for(preset, subject), references=len(refs))
    seed = _seed(seed)
    job.params.update(prompt=prompt, seed_used=seed)
    with engine_for(key) as engine:
        out = engine.scene(refs, prompt, fmt["scene"], seed, job.dir / "scene",
                           lambda p, m: job.set(p, f"Building the scene: {m}"))
    job.add_output("scene", out)


def run_effect(job: Job, *, key: str | None, preset_id: str, image: Path, source: str,
               subject: str, aspect: str, quality: str, seed: int | None) -> None:
    preset = get_preset(preset_id)
    if source == "scene":
        template, selector = preset["effect_prompt"], ASPECTS[aspect]["selector"]
    else:
        if not supports(preset, "own_image"):
            raise ValueError(f"{preset['name']} needs its own scene, so it only runs from a photo")
        template = preset["generic_prompt"]
        info = media.probe(image)
        selector = closest_selector(info["width"], info["height"])
    prompt = render(template, subject=subject)
    seed = _seed(seed)
    job.params.update(prompt=prompt, selector=selector)
    with engine_for(key) as engine:
        last, mids = (None, [])
        if source == "scene":
            job.set(0.03, "Building the key frames")
            last, mids = keyframes(engine, preset, image, subject, job.dir, seed,
                                   progress=lambda p, m: job.set(0.03, f"Building the key frames: {m}"))
        if last:
            job.add_output("last_frame", last)
            out = _flf_with_retry(job, engine, image, last, mids, prompt, selector, quality,
                                  preset.get("duration", 6), seed, preset.get("effect_lora"),
                                  preset.get("flf_strengths"))
        else:
            out = _effect_with_retry(job, engine, image, prompt, selector, quality,
                                     preset.get("duration", 6), seed, "effect", preset.get("effect_lora"))
    if preset.get("post") == "reverse":
        out = media.reverse(out, job.dir / "effect_reversed.mp4")
    job.add_output("video", out)
    job.add_output("poster", media.poster(out, job.dir / "poster.jpg", 1.0))


def run_splice(job: Job, *, key: str | None, preset_id: str, video: Path, seconds: float,
               subject: str, quality: str, audio_mode: str, seed: int | None) -> None:
    preset = get_preset(preset_id)
    if not supports(preset, "video"):
        raise ValueError(f"{preset['name']} cannot be spliced into a video yet")
    template = preset["generic_prompt"]
    info = media.probe(video)
    seconds = max(0.0, min(float(seconds), max(info["duration"] - 0.1, 0.0)))
    job.set(0.02, f"Grabbing the frame at {seconds:.2f} s")
    frame = media.extract_frame(video, seconds, job.dir / "cut_frame.png")
    job.add_output("frame", frame)
    prompt = render(template, subject=subject)
    selector = closest_selector(info["width"], info["height"])
    job.params.update(prompt=prompt, selector=selector, cut=seconds)
    with engine_for(key) as engine:
        effect = _effect_with_retry(job, engine, frame, prompt, selector, quality,
                                    SPLICE_DURATION, _seed(seed), "effect", preset.get("effect_lora"))
    job.add_output("effect", effect)
    job.set(0.97, "Splicing the effect into your video")
    final = media.splice(video, effect, seconds, job.dir / "final.mp4", audio_mode=audio_mode)
    job.add_output("video", final)
    job.add_output("poster", media.poster(final, job.dir / "poster.jpg", seconds + 1.0))


def keyframes(engine: Engine, preset: dict, first: Path, subject: str, out_dir: Path, seed: int,
              face: Path | None = None, reuse: bool = False, progress=lambda p, m: None
              ) -> tuple[Path | None, list[tuple[Path, int]]]:
    """Last frame (and optional middle guides) for a first-and-last-frame preset, edited from the
    first frame with Qwen Image Edit 2511. Returns (None, []) for an ordinary preset."""
    mode = preset.get("last_frame_mode")
    if not (mode or preset.get("last_frame_prompt")):
        return None, []
    frames = int(preset.get("duration", 6) * 24) + 1

    def edit(template: str, dest: Path) -> Path:
        if reuse and dest.exists():
            return dest
        prompt = render(template, subject=subject)
        use_face = face if "image 2" in prompt else None
        made = engine.edit_frame(first, prompt, seed, dest.with_suffix(""), progress, use_face)
        if made != dest:
            made.replace(dest)
        return dest

    last = out_dir / f"{first.stem.removesuffix('_f0')}_f1.png"
    if mode == "mirror":
        if not (reuse and last.exists()):
            media.mirror(first, last)
    else:
        edit(preset["last_frame_prompt"], last)
    mids = []
    for i, mid in enumerate(preset.get("mid_frames") or []):
        image = edit(mid["prompt"], out_dir / f"{first.stem.removesuffix('_f0')}_m{i}.png")
        mids.append((image, int(round(mid["at"] * (frames - 1)))))
    return last, mids


def flf_size(selector: str, quality: str) -> tuple[int, int]:
    """One pass at the output size (the FLF graph has no x2 stage): 512p for Draft, 704p for HQ."""
    short, long = (704, 1280) if quality == "hq" else (512, 896)
    return (short, long) if selector.startswith("9:16") else (long, short)
