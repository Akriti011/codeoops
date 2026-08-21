"""Domain model for a submitted repository.

This is a plain in-process domain object, deliberately free of any persistence
framework. The storage layer (``app.repositories``) is what decides where these
live; swapping the in-memory store for SQLAlchemy later touches only that layer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from app.models.enums import RepositorySource, RepositoryStatus


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Repository:
    """A repository submitted to CodeOops, either a GitHub URL or an uploaded ZIP."""

    owner: str
    name: str
    repository_url: str
    default_branch: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    source: RepositorySource = RepositorySource.GITHUB
    # The following four are set only when source is UPLOAD.
    upload_workspace_path: str | None = None
    """Absolute host path to the extracted repository root, inside the
    directory bind-mounted onto CodeWiki's shared output volume."""
    upload_original_filename: str | None = None
    upload_file_count: int | None = None
    upload_total_bytes: int | None = None
    status: RepositoryStatus = RepositoryStatus.READY
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    @property
    def identity_key(self) -> str:
        """Deterministic identity for a repository, independent of its record id.

        Used to keep repeated submissions of the same GitHub repository
        pointing at one stable record id. Uploads have no natural identity to
        deduplicate against — each successful upload becomes its own record,
        so this incorporates the record's own id and is therefore always
        unique, never colliding with another upload.
        """
        if self.source is RepositorySource.UPLOAD:
            return f"upload:{self.id}"
        return f"github:{self.owner.lower()}/{self.name.lower()}"

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    def touch(self) -> "Repository":
        """Return a copy with ``updated_at`` refreshed."""
        return replace(self, updated_at=_utcnow())
