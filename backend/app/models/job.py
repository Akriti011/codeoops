"""Domain model for a documentation generation job.

A DocumentationJob is CodeOops's own identity for one generation attempt. It
sits between Repository and the artifact CodeWiki produces, so two runs of one
repository stay distinguishable even though CodeWiki itself keys jobs by
repository name only (see app/services/codewiki/identity.py) and overwrites
its output directory in place on every run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from app.models.enums import JobStatus


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CodeWikiJobInfo:
    """A snapshot of what CodeWiki itself last reported for its own job."""

    codewiki_job_id: str
    codewiki_status: str | None = None
    codewiki_progress: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    main_model: str | None = None
    commit_id: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentationJob:
    """One CodeOops-tracked attempt to generate documentation for a repository."""

    repository_id: uuid.UUID
    codewiki_job_id: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: JobStatus = JobStatus.SUBMITTING
    created_at: datetime = field(default_factory=_utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    progress_message: str | None = None
    codewiki: CodeWikiJobInfo | None = None
    overview_available: bool = False
    served_from_codewiki_cache: bool = False
    provider: str = "codewiki"

    def with_update(self, **changes: object) -> "DocumentationJob":
        return replace(self, **changes)
