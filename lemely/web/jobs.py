"""In-memory job registry for background grading / extraction work.

A job tracks the lifecycle of a long-running pipeline (extraction, grading,
aggregation) whose progress is streamed over SSE. The registry is a simple
thread-safe dict keyed by a generated job id — sufficient for a single-process
backend. Swap for Redis / a DB when horizontal scaling is required.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

JobStatus = Literal["pending", "running", "done", "error"]


@dataclass
class Job:
    """A single tracked background job."""

    id: str
    kind: str
    status: JobStatus = "pending"
    result: Any = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class JobRegistry:
    """Thread-safe in-memory registry of :class:`Job` records."""

    def __init__(self) -> None:
        """Initialise an empty registry."""
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    def create(self, kind: str, **meta: Any) -> Job:
        """Create and register a new job in the ``pending`` state."""
        job = Job(id=uuid.uuid4().hex, kind=kind, meta=dict(meta))
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        """Return the job with ``job_id``, or ``None`` if unknown."""
        with self._lock:
            return self._jobs.get(job_id)

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        """Mutate an existing job's status / result / error fields in place."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if status is not None:
                job.status = status
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error

    def clear(self) -> None:
        """Remove all jobs. Intended for tests."""
        with self._lock:
            self._jobs.clear()


# Module-level singleton — import this in routers that spawn background jobs.
registry: JobRegistry = JobRegistry()
