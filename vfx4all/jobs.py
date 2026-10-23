"""A tiny in-process job queue. Comfy Cloud runs a few jobs at once per
workspace, so three workers is enough for one person using the app.

Every job keeps a job.json in its run folder: finished jobs survive a restart,
and a job the restart interrupted is marked failed with the Comfy Cloud job ids
it had submitted, so its result can still be found in the Comfy history.
"""

from __future__ import annotations

import contextvars
import json
import logging
import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx
from comfy_sdk.exceptions import (ComfyError, Forbidden, InsufficientCredits, InvalidWorkflow, JobFailed,
                                  MissingAsset, NotFound, QueueFull, Unauthorized)

from .config import RUNS_DIR, UPLOADS_DIR, daily_runs, hosted, session_jobs

log = logging.getLogger("vfx4all")

# The job the current worker thread runs. The engine reads it to record Comfy job ids and to
# stop when the user cancels, without every engine call taking the job as an argument.
ACTIVE_JOB: contextvars.ContextVar["Job | None"] = contextvars.ContextVar("vfx4all_job", default=None)

PUBLIC_FIELDS = ("id", "kind", "status", "message", "progress", "params", "outputs", "error", "created", "finished")
FINISHED = ("succeeded", "failed", "cancelled")


class Cancelled(Exception):
    """The user cancelled the job."""


class LimitReached(Exception):
    """Too many jobs at once for this session, or the daily cap is used up."""


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"  # queued, running, succeeded, failed, cancelled
    message: str = "Waiting for a free slot"
    progress: float = 0.0
    params: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)  # name -> URL under /files
    error: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None
    owner: str | None = None  # browser session, checked in hosted mode
    comfy_jobs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cancel_requested = False
        self._handles: list[Any] = []

    @property
    def dir(self) -> Path:
        return RUNS_DIR / self.id

    def set(self, progress: float | None = None, message: str | None = None) -> None:
        if progress is not None:
            self.progress = round(float(progress), 3)
        if message:
            self.message = message

    def add_output(self, name: str, path: Path) -> None:
        self.outputs[name] = "/files/" + path.relative_to(RUNS_DIR).as_posix()

    def attach(self, handle: Any) -> None:
        """Remember a submitted Comfy Cloud job, on disk too, so a restart can name it."""
        self._handles.append(handle)
        self.comfy_jobs.append(str(handle.id))
        self.save()

    def cancel(self) -> None:
        self.cancel_requested = True
        if self.status == "queued":
            self.message = "Cancelling"
        for handle in self._handles:
            try:
                handle.cancel()
            except Exception:  # already finished, or the request failed: the flag still stops the pipeline
                pass

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in PUBLIC_FIELDS}

    def save(self) -> None:
        data = {**self.to_dict(), "owner": self.owner, "comfy_jobs": self.comfy_jobs}
        (self.dir / "job.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    def output_paths(self) -> set[str]:
        return {url.removeprefix("/files/") for url in self.outputs.values()}


def friendly_error(exc: BaseException, job_id: str) -> str:
    """What the user reads when a job fails. The traceback goes to the log and error.txt."""
    if isinstance(exc, Cancelled):
        return "Cancelled."
    if isinstance(exc, Unauthorized):
        return "Comfy Cloud rejected the API key. Check the key in Settings or in .env."
    if isinstance(exc, InsufficientCredits):
        return "The Comfy workspace of this API key is out of credits."
    if isinstance(exc, Forbidden):
        return "This Comfy API key is not allowed to run these models."
    if isinstance(exc, QueueFull):
        return "Comfy Cloud is busy right now. Try again in a minute."
    if isinstance(exc, (InvalidWorkflow, MissingAsset, NotFound)):
        return "Comfy Cloud could not run this graph; a model or node may have been renamed in its catalog."
    if isinstance(exc, JobFailed):
        return "The render failed on Comfy Cloud. Try again or use another seed."
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return "Comfy Cloud did not answer in time. Try again."
    if isinstance(exc, ComfyError):
        return "Comfy Cloud returned an error. Try again in a minute."
    # Our own errors already speak to the user: missing key, preset rules, every take black.
    if type(exc).__name__ in ("MissingApiKey", "MediaError") or isinstance(exc, (ValueError, KeyError, RuntimeError)):
        text = exc.args[0] if exc.args else str(exc)
        if isinstance(text, str) and text:
            return text
    return f"Something went wrong. Reference: {job_id}."


class Usage:
    """Generations accepted per UTC day, kept on disk so a restart does not reset the cap."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> dict[str, int]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def take(self, cap: int) -> None:
        """Count one generation, or raise LimitReached when today's cap is used up."""
        today = time.strftime("%Y-%m-%d", time.gmtime())
        with self._lock:
            counts = self._read()
            if cap and counts.get(today, 0) >= cap:
                raise LimitReached("Today's generations on this server are used up. Try again tomorrow.")
            counts = {today: counts.get(today, 0) + 1}  # only today matters
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(counts), encoding="utf-8")

    def today(self) -> int:
        return self._read().get(time.strftime("%Y-%m-%d", time.gmtime()), 0)


class JobManager:
    def __init__(self, workers: int = 3) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="vfx4all")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.usage = Usage(RUNS_DIR / "usage.json")

    def submit(self, kind: str, params: dict[str, Any], work: Callable[[Job], None], owner: str | None = None) -> Job:
        with self._lock:
            if hosted() and owner is not None:
                busy = sum(1 for j in self._jobs.values() if j.owner == owner and j.status not in FINISHED)
                if busy >= session_jobs():
                    raise LimitReached(f"You already have {busy} jobs running. Wait for one to finish.")
            self.usage.take(daily_runs())
            job = Job(id=f"{kind}-{uuid.uuid4().hex[:10]}", kind=kind, params=params, owner=owner)
            self._jobs[job.id] = job
        job.dir.mkdir(parents=True, exist_ok=True)
        job.save()
        self._pool.submit(self._execute, job, work)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            job = self._from_disk(job_id)
        return job

    def _from_disk(self, job_id: str) -> Job | None:
        path = RUNS_DIR / Path(job_id).name / "job.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            job = Job(**{k: v for k, v in data.items() if k in Job.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return None
        if job.status not in FINISHED:
            return job  # interrupted by a restart; recover() will mark it, keep it out of memory meanwhile
        with self._lock:
            self._jobs[job.id] = job
        return job

    def recover(self) -> int:
        """Mark the jobs a restart interrupted as failed, naming their Comfy Cloud job ids."""
        count = 0
        for path in RUNS_DIR.glob("*/job.json"):
            job = self._from_disk(path.parent.name)
            if job is None or job.status in FINISHED or job.id in self._jobs:
                continue
            job.status, job.message, job.finished = "failed", "Failed", time.time()
            job.error = "The server restarted while this job ran."
            if job.comfy_jobs:
                job.error += f" Its Comfy Cloud jobs ({', '.join(job.comfy_jobs)}) may still finish in your Comfy history."
            job.save()
            count += 1
        return count

    def cleanup(self, max_age_hours: int) -> int:
        """Delete finished runs and uploads older than max_age_hours, and forget them in memory."""
        if max_age_hours <= 0:
            return 0
        cutoff = time.time() - max_age_hours * 3600
        removed = 0
        for path in RUNS_DIR.glob("*/job.json"):
            job = self._from_disk(path.parent.name)
            if job and job.status in FINISHED and (job.finished or job.created) < cutoff:
                shutil.rmtree(job.dir, ignore_errors=True)
                with self._lock:
                    self._jobs.pop(job.id, None)
                removed += 1
        if UPLOADS_DIR.exists():
            for upload in UPLOADS_DIR.iterdir():
                if upload.is_file() and upload.stat().st_mtime < cutoff:
                    upload.unlink(missing_ok=True)
                    removed += 1
        return removed

    def forget_finished(self, max_age_seconds: float = 3600) -> None:
        """Finished jobs older than an hour leave memory; their job.json still answers for them."""
        cutoff = time.time() - max_age_seconds
        with self._lock:
            for job_id in [k for k, j in self._jobs.items() if j.status in FINISHED and (j.finished or 0) < cutoff]:
                del self._jobs[job_id]

    def _execute(self, job: Job, work: Callable[[Job], None]) -> None:
        token = ACTIVE_JOB.set(job)
        try:
            if job.cancel_requested:
                raise Cancelled()
            job.status = "running"
            job.set(0.01, "Starting")
            job.save()
            work(job)
            job.status = "succeeded"
            job.set(1.0, "Done")
        except Exception as exc:  # surfaced to the UI as a friendly sentence
            cancelled = isinstance(exc, Cancelled) or job.cancel_requested
            job.status = "cancelled" if cancelled else "failed"
            job.message = "Cancelled" if cancelled else "Failed"
            job.error = friendly_error(Cancelled() if cancelled else exc, job.id)
            if not cancelled:
                (job.dir / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
                log.warning("job %s failed: %s", job.id, exc)
        finally:
            ACTIVE_JOB.reset(token)
            job.finished = time.time()
            job.save()
            self.forget_finished()
