"""Paths, settings and the small tables the pipeline shares."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = ROOT / "workflows"
PRESETS_DIR = ROOT / "presets"
WEB_DIR = ROOT / "web"
RUNS_DIR = Path(os.environ.get("VFX4ALL_RUNS_DIR", str(ROOT / "runs")))
UPLOADS_DIR = RUNS_DIR / "uploads"

# Scenes from a photo run on Qwen Image Edit 2511 (Apache 2.0). Qwen Image 2.1, used until
# 22/10/2026, is licensed for non-commercial research only.
SCENE_WORKFLOW = WORKFLOWS_DIR / "scene_qwen_image_edit_2511.json"
EFFECT_WORKFLOW = WORKFLOWS_DIR / "effect_ltx_2_5_i2v.json"
# LTX-2.5 DFR (Diffusion Fidelity Rendering): detailing keyframes plus a spatial x2 pass with the
# Refine-Details IC-LoRA. Sharper faces and textures than the classic two pass i2v (round 4 A/B,
# 16/10/2026). VFX4ALL_EFFECT_PIPELINE=classic goes back to the old graph.
DFR_WORKFLOW = WORKFLOWS_DIR / "effect_ltx_2_5_dfr_i2v.json"
# Last frames of first-and-last-frame presets: Qwen Image Edit 2511 changes scale and style far more
# than Qwen Image 2.1, which keeps re-drawing the first frame (round 6, 17/10/2026).
EDIT_WORKFLOW = WORKFLOWS_DIR / "edit_qwen_image_edit_2511.json"
FLF_WORKFLOW = WORKFLOWS_DIR / "effect_ltx_2_5_flf2v.json"


def effect_pipeline() -> str:
    """Read at call time, so a value set in .env (loaded after import) still counts."""
    return os.environ.get("VFX4ALL_EFFECT_PIPELINE", "dfr").strip().lower()


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Read KEY=VALUE lines from .env without overriding the real environment."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def api_key() -> str:
    return os.environ.get("COMFY_API_KEY", "").strip()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


# "local" (the default: one person on their own machine) or "hosted" (a server other people
# open). Hosted mode ties jobs and files to a session cookie, lowers the video limits, caps the
# jobs a session runs at once and deletes old runs. All of it is read at call time, like
# effect_pipeline(), so a value set in .env counts.
def mode() -> str:
    return "hosted" if os.environ.get("VFX4ALL_MODE", "").strip().lower() == "hosted" else "local"


def hosted() -> bool:
    return mode() == "hosted"


def access_code() -> str:
    """When set, every POST needs it in the X-Access-Code header (for example a demo for judges)."""
    return os.environ.get("VFX4ALL_ACCESS_CODE", "").strip()


def daily_runs() -> int:
    """Generations (scene, effect or splice jobs) the server accepts per UTC day; 0 is no cap."""
    return _int_env("VFX4ALL_DAILY_RUNS", 0)


def session_jobs() -> int:
    """Jobs one browser session may have queued or running at once (hosted mode)."""
    return _int_env("VFX4ALL_SESSION_JOBS", 2)


def ip_jobs() -> int:
    """Jobs one IP address may have queued or running at once (hosted mode). Higher than the
    session cap, because people behind one office or venue network share an address."""
    return _int_env("VFX4ALL_IP_JOBS", 6)


def retention_hours() -> int:
    """Runs and uploads older than this are deleted; 0 keeps them. Hosted mode defaults to 48."""
    return _int_env("VFX4ALL_RETENTION_HOURS", 48 if hosted() else 0)


# Output formats the user can pick for the image mode. "selector" is the
# ResolutionSelector option the LTX workflow understands; "scene" is the size of
# the first frame built by Qwen Image 2.1 Edit.
ASPECTS = {
    "16:9": {"selector": "16:9 (Widescreen)", "scene": (1344, 768), "words": "16:9 landscape"},
    "9:16": {"selector": "9:16 (Portrait Widescreen)", "scene": (768, 1344), "words": "9:16 vertical"},
}

# Every ResolutionSelector ratio, used to match an uploaded image or video.
SELECTOR_RATIOS = {
    "1:1 (Square)": 1 / 1,
    "2:3 (Portrait Photo)": 2 / 3,
    "3:2 (Photo)": 3 / 2,
    "3:4 (Portrait Standard)": 3 / 4,
    "4:3 (Standard)": 4 / 3,
    "9:16 (Portrait Widescreen)": 9 / 16,
    "16:9 (Widescreen)": 16 / 9,
    "21:9 (Ultrawide)": 21 / 9,
}

# LTX-2.5 renders in two passes (half size, then a x2 latent upscale), so the
# output size is kept on a multiple of 64. Draft is the 480p class (896x512 in
# 16:9) and HQ the 720p class (1280x704).
QUALITY_MEGAPIXELS = {"draft": 0.45, "hq": 0.9}
SIZE_MULTIPLE = 64

# A render whose average luma stays under this is treated as a failed (black)
# take and retried with a new seed.
BLACK_LUMA_THRESHOLD = 20.0
MAX_RETRIES = 2

SUBJECTS = ("man", "woman", "person")

# Clips the video mode accepts. The effect only replaces the part after the cut, so a long clip
# buys nothing; and since LTX renders at 512p (Draft) or 704p (HQ) and is scaled to the clip,
# anything under 480p or over 4K makes the seam visible.
VIDEO_LIMITS = {
    "min_seconds": 2,
    "max_seconds": 60,
    "min_short_side": 480,
    "max_long_side": 4096,
    "max_mb": 500,
}
# A hosted server keeps the same quality limits but takes shorter, lighter clips.
HOSTED_VIDEO_LIMITS = {**VIDEO_LIMITS, "max_seconds": 30, "max_mb": 100}

# Photos: a phone photo is a few MB; anything over this is a scan or a mistake.
IMAGE_LIMITS = {"max_mb": 20, "max_side": 8192}


def video_limits() -> dict:
    return HOSTED_VIDEO_LIMITS if hosted() else VIDEO_LIMITS


def check_video(width: int, height: int, seconds: float, size_bytes: int, limits: dict | None = None) -> str | None:
    """Why a clip is outside the video limits, or None when it is fine."""
    lim = limits or video_limits()
    if size_bytes > lim["max_mb"] * 1024 * 1024:
        return f"That clip is over {lim['max_mb']} MB. Trim or compress it first."
    if seconds < lim["min_seconds"]:
        return f"That clip is {seconds:.1f} s. Use one of at least {lim['min_seconds']} s."
    if seconds > lim["max_seconds"]:
        return f"That clip is {seconds:.0f} s. Trim it to {lim['max_seconds']} s or less around the moment you want."
    if min(width, height) < lim["min_short_side"]:
        return f"That clip is {width}x{height}. Use 480p or more (short side of at least {lim['min_short_side']} px)."
    if max(width, height) > lim["max_long_side"]:
        return f"That clip is {width}x{height}. Use 4K or less (long side of up to {lim['max_long_side']} px)."
    return None


def check_image(width: int, height: int, size_bytes: int) -> str | None:
    """Why a photo is outside IMAGE_LIMITS, or None when it is fine."""
    lim = IMAGE_LIMITS
    if size_bytes > lim["max_mb"] * 1024 * 1024:
        return f"That photo is over {lim['max_mb']} MB. Export a smaller JPG first."
    if max(width, height) > lim["max_side"]:
        return f"That photo is {width}x{height}. Use one of up to {lim['max_side']} px on the long side."
    return None


def closest_selector(width: int, height: int) -> str:
    ratio = width / max(height, 1)
    return min(SELECTOR_RATIOS, key=lambda name: abs(SELECTOR_RATIOS[name] - ratio))
