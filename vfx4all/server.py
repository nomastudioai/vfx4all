"""HTTP API and static web app. Runs locally; the Comfy key never leaves the server."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, media, pipeline
from .config import (ASPECTS, RUNS_DIR, SUBJECTS, UPLOADS_DIR, VIDEO_LIMITS, WEB_DIR, api_key,
                     check_video, load_dotenv)
from .jobs import JobManager
from .presets import load_presets, public_view

load_dotenv()
RUNS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="VFX 4 All", version=__version__)
jobs = JobManager()

IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_TYPES = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def _upload_path(upload_id: str) -> Path:
    path = (UPLOADS_DIR / Path(upload_id).name).resolve()
    if not path.exists() or path.parent != UPLOADS_DIR.resolve():
        raise HTTPException(404, f"Upload not found: {upload_id}")
    return path


def _key(user_key: str | None) -> str | None:
    """The key a generation bills: the user's own if they sent one, else the server's."""
    key = (user_key or "").strip() or None
    if not key and not api_key():
        raise HTTPException(401, "No Comfy API key. Add yours in Settings or set COMFY_API_KEY in .env.")
    return key


def _check(subject: str, aspect: str | None = None) -> None:
    if subject not in SUBJECTS:
        raise HTTPException(400, f"subject must be one of {SUBJECTS}")
    if aspect is not None and aspect not in ASPECTS:
        raise HTTPException(400, f"aspect must be one of {tuple(ASPECTS)}")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__, "has_key": bool(api_key()), "video_limits": VIDEO_LIMITS}


@app.get("/api/presets")
def presets() -> list[dict]:
    return [public_view(p) for p in load_presets()]


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in IMAGE_TYPES | VIDEO_TYPES:
        raise HTTPException(400, "Upload a PNG, JPG or WEBP image, or an MP4, MOV, WEBM or MKV video")
    upload_id = f"{uuid.uuid4().hex}{suffix}"
    dest = UPLOADS_DIR / upload_id
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    try:
        info = media.probe(dest)
    except media.MediaError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc
    if suffix in VIDEO_TYPES:
        problem = check_video(info["width"], info["height"], info["duration"], dest.stat().st_size)
        if problem:
            dest.unlink(missing_ok=True)
            raise HTTPException(422, problem)
    return {"id": upload_id, "name": file.filename, "url": f"/files/uploads/{upload_id}", **info}


class SceneRequest(BaseModel):
    preset: str
    refs: list[str] = Field(min_length=1, max_length=2)
    subject: str = "person"
    notes: str = ""
    aspect: str = "16:9"
    seed: int | None = None


class EffectRequest(BaseModel):
    preset: str
    scene_job: str | None = None   # animate the frame a scene job built
    image: str | None = None       # or animate an uploaded image as it is
    subject: str = "person"
    aspect: str = "16:9"
    quality: str = "draft"
    seed: int | None = None


class SpliceRequest(BaseModel):
    preset: str
    video: str
    seconds: float = 0.0
    subject: str = "person"
    quality: str = "draft"
    audio: str = "effect"
    seed: int | None = None


@app.post("/api/jobs/scene")
def scene(req: SceneRequest, x_comfy_key: str | None = Header(default=None)) -> dict:
    key = _key(x_comfy_key)
    _check(req.subject, req.aspect)
    refs = [_upload_path(r) for r in req.refs]
    job = jobs.submit("scene", req.model_dump(), lambda j: pipeline.run_scene(
        j, key=key, preset_id=req.preset, refs=refs, subject=req.subject, notes=req.notes,
        aspect=req.aspect, seed=req.seed))
    return job.to_dict()


@app.post("/api/jobs/effect")
def effect(req: EffectRequest, x_comfy_key: str | None = Header(default=None)) -> dict:
    key = _key(x_comfy_key)
    _check(req.subject, req.aspect)
    if req.scene_job:
        source_job = jobs.get(req.scene_job)
        if not source_job or "scene" not in source_job.outputs:
            raise HTTPException(400, "That scene is not ready")
        image = RUNS_DIR / source_job.outputs["scene"].removeprefix("/files/")
        source = "scene"
    elif req.image:
        image, source = _upload_path(req.image), "own"
    else:
        raise HTTPException(400, "Send scene_job or image")
    job = jobs.submit("effect", req.model_dump(), lambda j: pipeline.run_effect(
        j, key=key, preset_id=req.preset, image=image, source=source, subject=req.subject,
        aspect=req.aspect, quality=req.quality, seed=req.seed))
    return job.to_dict()


@app.post("/api/jobs/splice")
def splice(req: SpliceRequest, x_comfy_key: str | None = Header(default=None)) -> dict:
    key = _key(x_comfy_key)
    _check(req.subject)
    video = _upload_path(req.video)
    job = jobs.submit("splice", req.model_dump(), lambda j: pipeline.run_splice(
        j, key=key, preset_id=req.preset, video=video, seconds=req.seconds, subject=req.subject,
        quality=req.quality, audio_mode=req.audio, seed=req.seed))
    return job.to_dict()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return job.to_dict()


app.mount("/files", StaticFiles(directory=RUNS_DIR), name="files")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")
