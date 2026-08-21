"""API schemas for documentation state.

``artifact`` is always ``null`` in this phase. CodeOops does not generate
documentation; a documentation provider (CodeWiki) will, in a later phase.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DocumentationStatus


class DocumentationArtifactResponse(BaseModel):
    """Shape of a documentation artifact reference.

    Declared so the API contract is stable across the CodeWiki integration
    phase. No code path in this build produces one.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repository_id: uuid.UUID
    entry_document: str
    generated_at: datetime
    provider: str


class DocumentationStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    repository_id: uuid.UUID
    status: DocumentationStatus
    artifact: DocumentationArtifactResponse | None = None
    detail: str | None = Field(
        default=None,
        description="Why the documentation is in this state, when useful to show.",
    )
