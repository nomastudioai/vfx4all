"""HTTP API and static web app. The Comfy key never leaves the server.

Local mode (the default) is one person on their own machine. Hosted mode
(VFX4ALL_MODE=hosted) ties jobs and files to a session cookie, lowers the video
limits, caps the jobs a session runs at once and deletes old runs. An access
code (VFX4ALL_ACCESS_CODE) and a daily cap (VFX4ALL_DAILY_RUNS) work in both.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, media, pipeline
from .config import (ASPECTS, IMAGE_LIMITS, RUNS_DIR, UPLOADS_DIR, WEB_DIR, access_code, api_key, check_image,
                     check_video, hosted, load_dotenv, mode, retention_hours, video_limits)
from .jobs import LimitReached, JobManager
from .presets import get_preset, load_presets, public_view

load_dotenv()
RUNS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
log = logging.getLogger("vfx4all")
jobs = JobManager()


def _housekeeping() -> None:
    while True:
        try:
            removed = jobs.cleanup(retention_hours())
            if removed:
                log.info("cleanup removed %d old runs and uploads", removed)
        except Exception:  # never let the cleanup thread die
            log.exception("cleanup failed")
        time.sleep(1800)


@asynccontextmanager
async def lifespan(_: FastAPI):
    interrupted = jobs.recover()
    if interrupted:
        log.warning("%d jobs were interrupted by the last restart", interrupted)
    threading.Thread(target=_housekeeping, name="vfx4all-cleanup", daemon=True).start()
    yield


app = FastAPI(title="VFX 4 All", version=__version__, lifespan=lifespan)

IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_TYPES = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
HEIC_TYPES = {".heic", ".heif"}
SESSION_COOKIE = "vfx4all_session"
CHUNK = 1024 * 1024
MB = 1024 * 1024

Subject = Literal["man", "woman", "person"]
Aspect = Literal["16:9", "9:16"]
Quality = Literal["draft", "hq"]

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data: blob:; "
       "media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
       "frame-ancestors 'none'")


def _asset_version() -> str:
    """Changes whenever app.js or app.css change, so browsers never keep a stale copy."""
    digest = hashlib.sha256(__version__.encode())
    for name in ("app.js", "app.css"):
        path = WEB_DIR / name
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


ASSET_VERSION = _asset_version()


# ------------------------------------------------------------------ middleware

@app.middleware("http")
async def session_and_headers(request: Request, call_next):
    """Give every browser a session id, guard the upload size and add the security headers."""
    session = request.cookies.get(SESSION_COOKIE) or ""
    fresh = not (16 <= len(session) <= 64 and session.replace("-", "").replace("_", "").isalnum())
    if fresh:
        session = secrets.token_urlsafe(18)
    request.state.session = session

    if request.url.path == "/api/upload":
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > (video_limits()["max_mb"] + 1) * MB:
            return JSONResponse({"detail": f"That file is over {video_limits()['max_mb']} MB."}, status_code=413)

    response = await call_next(request)
    if fresh:
        response.set_cookie(SESSION_COOKIE, session, max_age=30 * 86400, httponly=True, samesite="lax",
                            secure=request.url.scheme == "https")
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/static/") and request.query_params.get("v"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


# ------------------------------------------------------------------ helpers

def _owner(request: Request) -> str:
    return request.state.session


def _require_code(given: str | None) -> None:
    code = access_code()
    if code and not hmac.compare_digest((given or "").strip().encode(), code.encode()):
        raise HTTPException(403, "This app needs an access code. Add it in Settings.")


def _may_see(owner: str | None, request: Request) -> bool:
    return not hosted() or owner == _owner(request)


def _upload_path(upload_id: str, request: Request) -> Path:
    name = Path(upload_id).name
    path = (UPLOADS_DIR / name).resolve()
    ok = (path.suffix.lower() in IMAGE_TYPES | VIDEO_TYPES and path.exists()
          and path.parent == UPLOADS_DIR.resolve())
    if ok and hosted():
        owner_file = UPLOADS_DIR / f"{name}.owner"
        ok = owner_file.exists() and owner_file.read_text(encoding="utf-8") == _owner(request)
    if not ok:
        raise HTTPException(404, f"Upload not found: {upload_id}")
    return path


def _key(user_key: str | None) -> str | None:
    """The key a generation bills: the user's own if they sent one, else the server's."""
    key = (user_key or "").strip() or None
    if not key and not api_key():
        raise HTTPException(401, "No Comfy API key. Add yours in Settings or set COMFY_API_KEY in .env.")
    return key


def _preset(preset_id: str, run_mode: str) -> dict:
    try:
        preset = get_preset(preset_id)
    except KeyError:
        raise HTTPException(404, f"Unknown effect: {preset_id}") from None
    if not pipeline.supports(preset, run_mode):
        what = {"scene": "from a photo scene", "own_image": "on your own image", "video": "inside a video"}[run_mode]
        raise HTTPException(400, f"{preset['name']} does not run {what}. Pick another effect.")
    return preset


def _submit(kind: str, params: dict, work, request: Request) -> dict:
    try:
        job = jobs.submit(kind, params, work, owner=_owner(request))
    except LimitReached as exc:
        raise HTTPException(429, str(exc)) from None
    return job.to_dict()


# ------------------------------------------------------------------ API

@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__, "mode": mode(), "has_key": bool(api_key()),
            "access_required": bool(access_code()), "video_limits": video_limits(), "image_limits": IMAGE_LIMITS}


@app.get("/api/presets")
def presets() -> list[dict]:
    return [public_view(p) for p in load_presets()]


@app.post("/api/upload")
def upload(request: Request, file: UploadFile = File(...), consent: str = Form(""),
           x_access_code: str | None = Header(default=None)) -> dict:
    _require_code(x_access_code)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix in HEIC_TYPES:
        raise HTTPException(400, "HEIC photos are not supported yet. Export the photo as JPG and try again.")
    if suffix not in IMAGE_TYPES | VIDEO_TYPES:
        raise HTTPException(400, "Upload a PNG, JPG or WEBP image, or an MP4, MOV, WEBM or MKV video")
    if consent.strip().lower() not in ("true", "1", "yes", "on"):
        raise HTTPException(400, "Confirm that everyone in it agreed to be used before you upload.")
    is_video = suffix in VIDEO_TYPES
    cap = (video_limits()["max_mb"] if is_video else IMAGE_LIMITS["max_mb"]) * MB
    upload_id = f"{uuid.uuid4().hex}{suffix}"
    dest = UPLOADS_DIR / upload_id
    written = 0
    with dest.open("wb") as fh:
        while chunk := file.file.read(CHUNK):
            written += len(chunk)
            if written > cap:
                break
            fh.write(chunk)
    if written > cap:
        dest.unlink(missing_ok=True)
        raise HTTPException(413, f"That file is over {cap // MB} MB.")
    try:
        info = media.probe(dest)
    except media.MediaError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "That file has no picture we can read.") from exc
    problem = (check_video(info["width"], info["height"], info["duration"], written) if is_video
               else check_image(info["width"], info["height"], written))
    if problem:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, problem)
    (UPLOADS_DIR / f"{upload_id}.owner").write_text(_owner(request), encoding="utf-8")
    return {"id": upload_id, "name": file.filename, "url": f"/files/uploads/{upload_id}", **info}


class SceneRequest(BaseModel):
    preset: str
    refs: list[str] = Field(min_length=1, max_length=2)
    subject: Subject = "person"
    notes: str = Field("", max_length=300)
    aspect: Aspect = "16:9"
    seed: int | None = None


class EffectRequest(BaseModel):
    preset: str
    scene_job: str | None = None   # animate the frame a scene job built
    image: str | None = None       # or animate an uploaded image as it is
    subject: Subject = "person"
    aspect: Aspect = "16:9"
    quality: Quality = "draft"
    seed: int | None = None


class SpliceRequest(BaseModel):
    preset: str
    video: str
    seconds: float = Field(0.0, ge=0)
    subject: Subject = "person"
    quality: Quality = "draft"
    audio: Literal["effect", "original"] = "effect"
    seed: int | None = None


@app.post("/api/jobs/scene")
def scene(req: SceneRequest, request: Request, x_comfy_key: str | None = Header(default=None),
          x_access_code: str | None = Header(default=None)) -> dict:
    _require_code(x_access_code)
    key = _key(x_comfy_key)
    _preset(req.preset, "scene")
    refs = [_upload_path(r, request) for r in req.refs]
    return _submit("scene", req.model_dump(), lambda j: pipeline.run_scene(
        j, key=key, preset_id=req.preset, refs=refs, subject=req.subject, notes=req.notes,
        aspect=req.aspect, seed=req.seed), request)


@app.post("/api/jobs/effect")
def effect(req: EffectRequest, request: Request, x_comfy_key: str | None = Header(default=None),
           x_access_code: str | None = Header(default=None)) -> dict:
    _require_code(x_access_code)
    key = _key(x_comfy_key)
    if req.scene_job:
        _preset(req.preset, "scene")
        source_job = jobs.get(req.scene_job)
        if not source_job or "scene" not in source_job.outputs or not _may_see(source_job.owner, request):
            raise HTTPException(400, "That scene is not ready")
        image = RUNS_DIR / source_job.outputs["scene"].removeprefix("/files/")
        source = "scene"
    elif req.image:
        _preset(req.preset, "own_image")
        image, source = _upload_path(req.image, request), "own"
    else:
        raise HTTPException(400, "Send scene_job or image")
    return _submit("effect", req.model_dump(), lambda j: pipeline.run_effect(
        j, key=key, preset_id=req.preset, image=image, source=source, subject=req.subject,
        aspect=req.aspect, quality=req.quality, seed=req.seed), request)


@app.post("/api/jobs/splice")
def splice(req: SpliceRequest, request: Request, x_comfy_key: str | None = Header(default=None),
           x_access_code: str | None = Header(default=None)) -> dict:
    _require_code(x_access_code)
    key = _key(x_comfy_key)
    _preset(req.preset, "video")
    video = _upload_path(req.video, request)
    return _submit("splice", req.model_dump(), lambda j: pipeline.run_splice(
        j, key=key, preset_id=req.preset, video=video, seconds=req.seconds, subject=req.subject,
        quality=req.quality, audio_mode=req.audio, seed=req.seed), request)


def _job_for(job_id: str, request: Request):
    job = jobs.get(job_id)
    if not job or not _may_see(job.owner, request):
        raise HTTPException(404, "Unknown job")
    return job


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, request: Request) -> dict:
    return _job_for(job_id, request).to_dict()


@app.post("/api/jobs/{job_id}/cancel")
def job_cancel(job_id: str, request: Request, x_access_code: str | None = Header(default=None)) -> dict:
    _require_code(x_access_code)
    job = _job_for(job_id, request)
    if job.status in ("queued", "running"):
        job.cancel()
    return job.to_dict()


@app.get("/files/{path:path}")
def files(path: str, request: Request) -> FileResponse:
    """Only what a job produced and what was uploaded: never job.json or error.txt."""
    parts = Path(path).parts
    if len(parts) == 2 and parts[0] == "uploads":
        return FileResponse(_upload_path(parts[1], request))
    job = jobs.get(parts[0]) if parts else None
    if not job or not _may_see(job.owner, request) or path not in job.output_paths():
        raise HTTPException(404, "Not found")
    target = (RUNS_DIR / path).resolve()
    if not target.is_file() or RUNS_DIR.resolve() not in target.parents:
        raise HTTPException(404, "Not found")
    return FileResponse(target)


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def index() -> HTMLResponse:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace("{{v}}", ASSET_VERSION)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
