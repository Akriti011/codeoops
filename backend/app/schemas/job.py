"""API schemas for documentation generation jobs."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from app.models.enums import JobStatus


class JobCreateRequest(BaseModel):
    """Start a job either for a GitHub URL or an already-registered repository.

    ``repository_id`` is how a ZIP upload starts generation — uploading
    (``POST /repositories/upload``) only registers and extracts the
    repository; it does not implicitly start a job, matching the two-step
    GitHub flow (``POST /repositories`` then this endpoint) rather than
    creating a divergent shortcut for uploads.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"repository_url": "https://github.com/owner/repository"}]
        }
    )

    repository_url: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
        description="HTTPS URL of a public GitHub repository.",
    )
    repository_id: uuid.UUID | None = Field(
        default=None,
        description="Id of an already-registered repository (e.g. from a ZIP upload).",
    )

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "JobCreateRequest":
        if bool(self.repository_url) == bool(self.repository_id):
            # PydanticCustomError, not a bare ValueError: pydantic embeds a
            # raised ValueError itself (not just its message) into the
            # resulting error's ctx, which is not JSON-serializable and
            # would break app.main's validation-error response.
            raise PydanticCustomError(
                "exactly_one_repository_source",
                "Provide exactly one of repository_url or repository_id.",
            )
        return self


class CodeWikiJobInfoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    codewiki_job_id: str
    codewiki_status: str | None = None
    codewiki_progress: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    main_model: str | None = None
    commit_id: str | None = None


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repository_id: uuid.UUID
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    progress_message: str | None = None
    overview_available: bool
    served_from_codewiki_cache: bool
    provider: str
    documents: list[str] = []
    codewiki: CodeWikiJobInfoResponse | None = None


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int = Field(ge=0)


class EngineStatusResponse(BaseModel):
    engine: str
    reachable: bool
    base_url: str
