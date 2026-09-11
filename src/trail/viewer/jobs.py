"""A single-worker job queue (SPEC 13.2).

Analyses are slow and cost money, so they run on one background thread and the page
polls for the result. One worker, deliberately: two concurrent `claude -p` calls
would race on the same files and burn usage twice as fast for no benefit.
"""

from __future__ import annotations

import queue
import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"


@dataclass
class Job:
    id: str
    label: str
    status: str = QUEUED
    message: str = ""
    result_url: str | None = None
    progress: str = ""
    detail: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "message": self.message,
            "result_url": self.result_url,
            "progress": self.progress,
            "detail": self.detail[-20:],
        }


class JobQueue:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._queue: queue.Queue[tuple[Job, Callable[[Job], None]] | None] = queue.Queue()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        if self._worker is not None:
            return
        self._worker = threading.Thread(target=self._run, name="trail-jobs", daemon=True)
        self._worker.start()

    def submit(self, label: str, work: Callable[[Job], None]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], label=label)
        with self._lock:
            self._jobs[job.id] = job
        self.start()
        self._queue.put((job, work))
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def active(self) -> list[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.status in (QUEUED, RUNNING)]

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            job, work = item
            job.status = RUNNING
            try:
                work(job)
                if job.status == RUNNING:
                    job.status = DONE
            except Exception as exc:
                job.status = FAILED
                job.message = str(exc) or type(exc).__name__
                job.detail.append(traceback.format_exc().strip().split("\n")[-1])
            finally:
                self._queue.task_done()
