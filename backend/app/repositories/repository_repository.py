"""Storage layer for :class:`~app.models.repository.Repository`.

An abstract port plus an in-process implementation. Everything above this layer
depends on the port, so introducing a real database later means adding one
adapter and changing one line of wiring — no service or route changes.

In-memory storage is a deliberate choice for this phase: the brief asks for no
unnecessary database complexity, and nothing here needs to survive a restart yet.
"""

from __future__ import annotations

import threading
import uuid
from abc import ABC, abstractmethod

from app.models.repository import Repository


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
    def clear(self) -> None: ...


class InMemoryRepositoryStore(RepositoryStore):
    """Thread-safe in-process store, ordered newest-first on read."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[uuid.UUID, Repository] = {}
        self._identity_to_id: dict[str, uuid.UUID] = {}

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

    def clear(self) -> None:
        with self._lock:
            self._by_id.clear()
            self._identity_to_id.clear()
