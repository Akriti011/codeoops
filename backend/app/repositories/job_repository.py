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
    def update(self, job: DocumentationJob) -> DocumentationJob:
        """Persist a new state for an existing job.

        A no-op if the job is no longer stored: a job whose repository was
        deleted while its runner was still in flight must not be resurrected
        by the runner's next progress/fail write.
        """

    @abstractmethod
    def get(self, job_id: uuid.UUID) -> DocumentationJob | None: ...

    @abstractmethod
    def list_for_repository(self, repository_id: uuid.UUID) -> list[DocumentationJob]: ...

    @abstractmethod
    def latest_for_repository(self, repository_id: uuid.UUID) -> DocumentationJob | None: ...

    @abstractmethod
    def list_all(self) -> list[DocumentationJob]: ...

    @abstractmethod
    def bin_for_repository(self, repository_id: uuid.UUID) -> list[DocumentationJob]:
        """Move every job of one repository to the bin (they stop appearing in
        list_all / list_for_repository). Returns the jobs moved."""

    @abstractmethod
    def restore_for_repository(self, repository_id: uuid.UUID) -> list[DocumentationJob]:
        """Move a repository's binned jobs back to the live set."""

    @abstractmethod
    def binned_for_repository(self, repository_id: uuid.UUID) -> list[DocumentationJob]:
        """A repository's jobs currently in the bin."""

    @abstractmethod
    def remove(self, job_id: uuid.UUID) -> DocumentationJob | None:
        """Delete one job, live or binned. Returns the removed record, or
        ``None`` if there was no such id. Idempotent."""

    @abstractmethod
    def clear(self) -> None: ...


class InMemoryJobStore(JobStore):
    """Thread-safe in-process store, ordered newest-first on read."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[uuid.UUID, DocumentationJob] = {}
        self._binned: dict[uuid.UUID, DocumentationJob] = {}

    def add(self, job: DocumentationJob) -> DocumentationJob:
        with self._lock:
            self._by_id[job.id] = job
            return job

    def update(self, job: DocumentationJob) -> DocumentationJob:
        with self._lock:
            # Persist wherever the job currently lives; never re-create it. A
            # job whose repository was permanently deleted mid-run must not be
            # resurrected, but one that was only binned should still reflect
            # its final state when the repository is restored.
            if job.id in self._by_id:
                self._by_id[job.id] = job
            elif job.id in self._binned:
                self._binned[job.id] = job
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

    def bin_for_repository(self, repository_id: uuid.UUID) -> list[DocumentationJob]:
        with self._lock:
            moved = [j for j in self._by_id.values() if j.repository_id == repository_id]
            for job in moved:
                del self._by_id[job.id]
                self._binned[job.id] = job
            return moved

    def restore_for_repository(self, repository_id: uuid.UUID) -> list[DocumentationJob]:
        with self._lock:
            moved = [j for j in self._binned.values() if j.repository_id == repository_id]
            for job in moved:
                del self._binned[job.id]
                self._by_id[job.id] = job
            return moved

    def binned_for_repository(self, repository_id: uuid.UUID) -> list[DocumentationJob]:
        with self._lock:
            return [j for j in self._binned.values() if j.repository_id == repository_id]

    def remove(self, job_id: uuid.UUID) -> DocumentationJob | None:
        with self._lock:
            return self._by_id.pop(job_id, None) or self._binned.pop(job_id, None)

    def clear(self) -> None:
        with self._lock:
            self._by_id.clear()
            self._binned.clear()


@lru_cache
def get_job_store() -> JobStore:
    return InMemoryJobStore()
