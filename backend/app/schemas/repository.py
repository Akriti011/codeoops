"""API schemas for repositories."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RepositorySource, RepositoryStatus


class RepositoryCreateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"repository_url": "https://github.com/owner/repository"}]
        }
    )

    repository_url: str = Field(
        min_length=1,
        max_length=2048,
        description="HTTPS URL of a public GitHub repository.",
    )


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner: str
    name: str
    repository_url: str
    default_branch: str
    source: RepositorySource
    upload_original_filename: str | None = None
    upload_file_count: int | None = None
    upload_total_bytes: int | None = None
    status: RepositoryStatus
    created_at: datetime
    updated_at: datetime


class RepositoryListResponse(BaseModel):
    items: list[RepositoryResponse]
    total: int = Field(ge=0)


class BinnedRepositoryResponse(BaseModel):
    """A repository in the bin, plus what is recoverable with it."""

    repository: RepositoryResponse
    binned_at: datetime
    job_count: int = Field(ge=0)
    has_overview: bool


class BinnedRepositoryListResponse(BaseModel):
    items: list[BinnedRepositoryResponse]
    total: int = Field(ge=0)
