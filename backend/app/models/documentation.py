"""Domain model for the documentation state of a repository.

The shape below is the contract the frontend renders against. It intentionally
carries an ``artifact`` slot that is ``None`` in this phase: CodeOops has no
documentation engine wired, so there is nothing to put in it.

The future CodeWiki integration will fill ``artifact`` with a reference to a
verified CodeWiki output. It will never be filled by CodeOops itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.models.enums import DocumentationStatus


@dataclass(frozen=True, slots=True)
class DocumentationArtifactRef:
    """Reference to a documentation artifact produced by an external engine.

    Reserved for the CodeWiki integration phase. Nothing in this codebase
    constructs one.
    """

    id: uuid.UUID
    repository_id: uuid.UUID
    entry_document: str
    generated_at: datetime
    provider: str


@dataclass(frozen=True, slots=True)
class DocumentationState:
    """The documentation state of one repository at a point in time."""

    repository_id: uuid.UUID
    status: DocumentationStatus
    artifact: DocumentationArtifactRef | None = None
    detail: str | None = None
