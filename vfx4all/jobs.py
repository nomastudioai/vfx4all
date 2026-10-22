"""A tiny in-process job queue. Comfy Cloud runs a few jobs at once per
workspace, so three workers is enough for one person using the app."""

from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import RUNS_DIR


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"  # queued, running, succeeded, failed
    message: str = "Waiting for a free slot"
    progress: float = 0.0
    params: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)  # name -> URL under /files
    error: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None

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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JobManager:
    def __init__(self, workers: int = 3) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="vfx4all")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, params: dict[str, Any], work: Callable[[Job], None]) -> Job:
        job = Job(id=f"{kind}-{uuid.uuid4().hex[:10]}", kind=kind, params=params)
        job.dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(self._execute, job, work)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            job = self._from_disk(job_id)
        return job

    def _from_disk(self, job_id: str) -> Job | None:
        """Finished jobs survive a server restart through their job.json."""
        path = RUNS_DIR / Path(job_id).name / "job.json"
        if not path.exists():
            return None
        job = Job(**json.loads(path.read_text(encoding="utf-8")))
        with self._lock:
            self._jobs[job.id] = job
        return job

    def _execute(self, job: Job, work: Callable[[Job], None]) -> None:
        job.status = "running"
        job.set(0.01, "Starting")
        try:
            work(job)
            job.status = "succeeded"
            job.set(1.0, "Done")
        except Exception as exc:  # surfaced to the UI as text
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.message = "Failed"
            (job.dir / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        finally:
            job.finished = time.time()
            (job.dir / "job.json").write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")
