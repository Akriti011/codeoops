"""Storage layer for :class:`~app.models.repository.Repository`.

An abstract port plus an in-process implementation. Everything above this layer
depends on the port, so introducing a real database later means adding one
adapter and changing one line of wiring — no service or route changes.

In-memory storage is a deliberate choice for this phase: the brief asks for no
unnecessary database complexity, and nothing here needs to survive a restart
yet. That includes the bin: a repository sent to the bin is recoverable until
the process restarts, exactly like every other record here.
"""

from __future__ import annotations

import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from app.models.repository import Repository


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RepositoryStore(ABC):
    """Port for repository persistence."""

    @abstractmethod
    def add(self, repository: Repository) -> Repository: ...

    @abstractmethod
    def get(self, repository_id: uuid.UUID) -> Repository | None: ...

    @abstractmethod
    def get_by_identity(self, identity_key: str) -> Repository | None: ...

    @abstractmethod
    def list(self) -> list[Repository]: ...

    @abstractmethod
    def bin(self, repository_id: uuid.UUID) -> Repository | None:
        """Move a live repository to the bin. Returns it, or ``None`` if there
        was no live repository with that id. Idempotent."""

    @abstractmethod
    def restore(self, repository_id: uuid.UUID) -> Repository | None:
        """Move a binned repository back to the live set. Returns it, or
        ``None`` if it was not in the bin. Idempotent."""

    @abstractmethod
    def get_binned(self, repository_id: uuid.UUID) -> Repository | None: ...

    @abstractmethod
    def list_binned(self) -> list[tuple[Repository, datetime]]:
        """Binned repositories with the time each was binned, newest first."""

    @abstractmethod
    def remove(self, repository_id: uuid.UUID) -> Repository | None:
        """Permanently delete one repository, live or binned. Returns the
        removed record, or ``None`` if there was no such id. Idempotent."""

    @abstractmethod
    def clear(self) -> None: ...


class InMemoryRepositoryStore(RepositoryStore):
    """Thread-safe in-process store, ordered newest-first on read."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[uuid.UUID, Repository] = {}
        self._identity_to_id: dict[str, uuid.UUID] = {}
        # id -> (repository, binned_at). A binned repository is invisible to
        # list()/get()/get_by_identity() — so resubmitting a binned GitHub URL
        # makes a fresh record — until it is restored or permanently removed.
        self._binned: dict[uuid.UUID, tuple[Repository, datetime]] = {}

    def add(self, repository: Repository) -> Repository:
        with self._lock:
            self._by_id[repository.id] = repository
            self._identity_to_id[repository.identity_key] = repository.id
            return repository

    def get(self, repository_id: uuid.UUID) -> Repository | None:
        with self._lock:
            return self._by_id.get(repository_id)

    def get_by_identity(self, identity_key: str) -> Repository | None:
        with self._lock:
            repository_id = self._identity_to_id.get(identity_key)
            return self._by_id.get(repository_id) if repository_id else None

    def list(self) -> list[Repository]:
        with self._lock:
            return sorted(
                self._by_id.values(), key=lambda item: item.created_at, reverse=True
            )

    def bin(self, repository_id: uuid.UUID) -> Repository | None:
        with self._lock:
            repository = self._by_id.pop(repository_id, None)
            if repository is None:
                return None
            self._identity_to_id.pop(repository.identity_key, None)
            self._binned[repository_id] = (repository, _utcnow())
            return repository

    def restore(self, repository_id: uuid.UUID) -> Repository | None:
        with self._lock:
            entry = self._binned.pop(repository_id, None)
            if entry is None:
                return None
            repository = entry[0]
            self._by_id[repository_id] = repository
            self._identity_to_id[repository.identity_key] = repository_id
            return repository

    def get_binned(self, repository_id: uuid.UUID) -> Repository | None:
        with self._lock:
            entry = self._binned.get(repository_id)
            return entry[0] if entry else None

    def list_binned(self) -> list[tuple[Repository, datetime]]:
        with self._lock:
            return sorted(
                self._binned.values(), key=lambda entry: entry[1], reverse=True
            )

    def remove(self, repository_id: uuid.UUID) -> Repository | None:
        with self._lock:
            repository = self._by_id.pop(repository_id, None)
            binned = self._binned.pop(repository_id, None)
            if binned is not None and repository is None:
                repository = binned[0]
            if repository is not None:
                self._identity_to_id.pop(repository.identity_key, None)
            return repository

    def clear(self) -> None:
        with self._lock:
            self._by_id.clear()
            self._identity_to_id.clear()
            self._binned.clear()
