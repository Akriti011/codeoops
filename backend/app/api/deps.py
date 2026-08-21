"""FastAPI dependency wiring.

The single place where concrete implementations are chosen. Swapping the
in-memory store for a database, or registering the future CodeWiki provider,
happens here and nowhere else.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.providers.documentation_provider import (
    DocumentationProvider,
    get_documentation_provider,
)
from app.repositories.repository_repository import (
    InMemoryRepositoryStore,
    RepositoryStore,
)
from app.services.documentation.job_service import DocumentationJobService, get_job_service
from app.services.documentation_service import DocumentationService
from app.services.repository_service import RepositoryService
from app.services.repository_url_policy import RepositoryUrlPolicy
from app.services.uploads.upload_service import ZipUploadService
from app.services.uploads.zip_ingestion import ZipIngestionLimits

SettingsDep = Annotated[Settings, Depends(get_settings)]


@lru_cache
def _repository_store() -> RepositoryStore:
    return InMemoryRepositoryStore()


def get_repository_store() -> RepositoryStore:
    return _repository_store()


def get_repository_service(
    settings: SettingsDep,
    store: Annotated[RepositoryStore, Depends(get_repository_store)],
) -> RepositoryService:
    return RepositoryService(
        store=store,
        url_policy=RepositoryUrlPolicy(settings.allowed_repository_hosts),
        default_branch_fallback=settings.default_branch_fallback,
    )


def get_provider(settings: SettingsDep) -> DocumentationProvider | None:
    return get_documentation_provider(settings)


def get_documentation_service(
    provider: Annotated[DocumentationProvider | None, Depends(get_provider)],
) -> DocumentationService:
    return DocumentationService(provider)


def get_documentation_job_service(settings: SettingsDep) -> DocumentationJobService:
    return get_job_service(settings)


def get_zip_upload_service(
    settings: SettingsDep,
    repositories: Annotated[RepositoryService, Depends(get_repository_service)],
) -> ZipUploadService:
    return ZipUploadService(
        repositories=repositories,
        output_root=Path(settings.codewiki_output_root or "."),
        limits=ZipIngestionLimits(
            max_archive_bytes=settings.upload_max_archive_bytes,
            max_extracted_bytes=settings.upload_max_extracted_bytes,
            max_file_count=settings.upload_max_file_count,
        ),
    )


RepositoryServiceDep = Annotated[RepositoryService, Depends(get_repository_service)]
DocumentationServiceDep = Annotated[
    DocumentationService, Depends(get_documentation_service)
]
DocumentationJobServiceDep = Annotated[
    DocumentationJobService, Depends(get_documentation_job_service)
]
ZipUploadServiceDep = Annotated[ZipUploadService, Depends(get_zip_upload_service)]
