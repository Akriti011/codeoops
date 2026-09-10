"""Repository business logic.

Routes call this. This calls the URL policy and the store. Nothing here knows
about HTTP, and nothing here knows about documentation generation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from app.core.errors import RepositoryNotFoundError
from app.models.enums import RepositorySource
from app.models.repository import Repository
from app.repositories.repository_repository import RepositoryStore
from app.services.repository_url_policy import RepositoryUrlPolicy


class RepositorySubmission:
    """Result of submitting a repository URL."""

    __slots__ = ("repository", "created")

    def __init__(self, repository: Repository, created: bool) -> None:
        self.repository = repository
        self.created = created


class RepositoryService:
    def __init__(
        self,
        store: RepositoryStore,
        url_policy: RepositoryUrlPolicy,
        default_branch_fallback: str = "main",
    ) -> None:
        self._store = store
        self._url_policy = url_policy
        self._default_branch_fallback = default_branch_fallback

    def submit(self, repository_url: str) -> RepositorySubmission:
        """Validate a repository URL and return its stable record.

        Submitting the same repository twice returns the same record id rather
        than creating a duplicate — the brief asks for a *stable* repository id.
        Distinguishing individual documentation runs is the job of the future
        DocumentationJob entity, not of this record.
        """
        coordinates = self._url_policy.parse(repository_url)

        existing = self._store.get_by_identity(coordinates.identity_key)
        if existing is not None:
            return RepositorySubmission(self._store.add(existing.touch()), created=False)

        repository = Repository(
            owner=coordinates.owner,
            name=coordinates.name,
            repository_url=coordinates.canonical_url,
            # The real default branch is only knowable by talking to the host.
            # We record a documented fallback rather than inventing a fact.
            default_branch=self._default_branch_fallback,
        )
        return RepositorySubmission(self._store.add(repository), created=True)

    def register_upload(
        self,
        *,
        repository_id: uuid.UUID,
        name: str,
        workspace_path: Path,
        original_filename: str,
        file_count: int,
        total_bytes: int,
    ) -> Repository:
        """Register a repository whose source came from an uploaded ZIP archive.

        Unlike :meth:`submit`, there is no stable natural identity to
        deduplicate against — every successful upload becomes its own
        repository record, so two uploads (even of the identical archive)
        never collide or overwrite one another.
        """
        repository = Repository(
            id=repository_id,
            owner="upload",
            name=name,
            repository_url=f"upload://{original_filename}",
            default_branch=self._default_branch_fallback,
            source=RepositorySource.UPLOAD,
            upload_workspace_path=str(workspace_path),
            upload_original_filename=original_filename,
            upload_file_count=file_count,
            upload_total_bytes=total_bytes,
        )
        return self._store.add(repository)

    def get(self, repository_id: uuid.UUID) -> Repository:
        repository = self._store.get(repository_id)
        if repository is None:
            raise RepositoryNotFoundError(
                "No repository with that id.",
                details={"repository_id": str(repository_id)},
            )
        return repository

    def list(self) -> list[Repository]:
        return self._store.list()

    def bin(self, repository_id: uuid.UUID) -> Repository:
        """Send a live repository to the bin (recoverable). Raises
        :class:`RepositoryNotFoundError` if it is not currently live."""
        binned = self._store.bin(repository_id)
        if binned is None:
            raise RepositoryNotFoundError(
                "No repository with that id.",
                details={"repository_id": str(repository_id)},
            )
        return binned

    def restore(self, repository_id: uuid.UUID) -> Repository:
        """Bring a binned repository back to the live set. Raises
        :class:`RepositoryNotFoundError` if it is not in the bin."""
        restored = self._store.restore(repository_id)
        if restored is None:
            raise RepositoryNotFoundError(
                "No repository with that id is in the bin.",
                details={"repository_id": str(repository_id)},
            )
        return restored

    def get_binned(self, repository_id: uuid.UUID) -> Repository:
        repository = self._store.get_binned(repository_id)
        if repository is None:
            raise RepositoryNotFoundError(
                "No repository with that id is in the bin.",
                details={"repository_id": str(repository_id)},
            )
        return repository

    def list_binned(self) -> list[tuple[Repository, datetime]]:
        return self._store.list_binned()

    def delete(self, repository_id: uuid.UUID) -> Repository:
        """Permanently remove one repository record, live or binned.

        Only the record itself — the caller is responsible for purging any
        documentation jobs, artifacts and on-disk workspace that belonged to
        it first (this service deliberately knows nothing about those). Raises
        :class:`RepositoryNotFoundError` if there is no such repository.
        """
        removed = self._store.remove(repository_id)
        if removed is None:
            raise RepositoryNotFoundError(
                "No repository with that id.",
                details={"repository_id": str(repository_id)},
            )
        return removed
