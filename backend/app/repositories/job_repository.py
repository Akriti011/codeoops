"""Storage layer for :class:`~app.models.job.DocumentationJob`.

Same shape as ``repository_repository.py``: an abstract port plus a
thread-safe in-process implementation. ``get_job_store`` is the process-wide
singleton, defined here (not in ``app.api.deps``) so both the legacy
provider-backed route and the job-centric routes share one store without
either module importing the other.
"""

from __future__ import annotations

import threading
import uuid
from abc import ABC, abstractmethod
from functools import lru_cache

from app.models.job import DocumentationJob


class JobStore(ABC):
    """Port for documentation job persistence."""

    @abstractmethod
    def add(self, job: DocumentationJob) -> DocumentationJob: ...

    @abstractmethod
    def update(self, job: DocumentationJob) -> DocumentationJob: ...

    @abstractmethod
    def get(self, job_id: uuid.UUID) -> DocumentationJob | None: ...

    @abstractmethod
    def list_for_repository(self, repository_id: uuid.UUID) -> list[DocumentationJob]: ...

    @abstractmethod
    def latest_for_repository(self, repository_id: uuid.UUID) -> DocumentationJob | None: ...

    @abstractmethod
    def list_all(self) -> list[DocumentationJob]: ...

    @abstractmethod
    def clear(self) -> None: ...


class InMemoryJobStore(JobStore):
    """Thread-safe in-process store, ordered newest-first on read."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[uuid.UUID, DocumentationJob] = {}

    def add(self, job: DocumentationJob) -> DocumentationJob:
        with self._lock:
            self._by_id[job.id] = job
            return job

    def update(self, job: DocumentationJob) -> DocumentationJob:
        with self._lock:
            self._by_id[job.id] = job
            return job

    def get(self, job_id: uuid.UUID) -> DocumentationJob | None:
        with self._lock:
            return self._by_id.get(job_id)

    def list_for_repository(self, repository_id: uuid.UUID) -> list[DocumentationJob]:
        with self._lock:
            items = [j for j in self._by_id.values() if j.repository_id == repository_id]
            return sorted(items, key=lambda job: job.created_at, reverse=True)

    def latest_for_repository(self, repository_id: uuid.UUID) -> DocumentationJob | None:
        items = self.list_for_repository(repository_id)
        return items[0] if items else None

    def list_all(self) -> list[DocumentationJob]:
        with self._lock:
            return sorted(self._by_id.values(), key=lambda job: job.created_at, reverse=True)

    def clear(self) -> None:
        with self._lock:
            self._by_id.clear()


@lru_cache
def get_job_store() -> JobStore:
    return InMemoryJobStore()
