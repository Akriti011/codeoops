"""Repository routes.

Routes translate HTTP to service calls and back. They contain no business logic
and no validation beyond request-shape checking.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Response, UploadFile, status

from app.api.deps import (
    DocumentationJobServiceDep,
    DocumentationServiceDep,
    RepositoryServiceDep,
    SettingsDep,
    ZipUploadServiceDep,
)
from app.core.errors import DocumentationProviderNotConfiguredError
from app.schemas.common import ErrorResponse
from app.schemas.documentation import DocumentationStatusResponse
from app.schemas.job import JobListResponse, JobResponse
from app.schemas.repository import (
    BinnedRepositoryListResponse,
    BinnedRepositoryResponse,
    RepositoryCreateRequest,
    RepositoryListResponse,
    RepositoryResponse,
)

_NO_PROVIDER_DETAIL = (
    "No documentation provider is connected. CodeWiki integration is not "
    "enabled in this build."
)

router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.post(
    "",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a GitHub repository",
    responses={422: {"model": ErrorResponse, "description": "Invalid repository URL"}},
)
async def create_repository(
    payload: RepositoryCreateRequest,
    service: RepositoryServiceDep,
    response: Response,
) -> RepositoryResponse:
    """Validate a repository URL and return its stable record.

    Resubmitting the same repository returns the existing record with ``200``
    instead of creating a duplicate.
    """
    submission = service.submit(payload.repository_url)
    if not submission.created:
        response.status_code = status.HTTP_200_OK
    return RepositoryResponse.model_validate(submission.repository)


@router.post(
    "/upload",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a ZIP archive as a repository",
    responses={
        413: {"model": ErrorResponse, "description": "Archive exceeds a configured size limit"},
        422: {"model": ErrorResponse, "description": "Invalid, unsafe, or empty archive"},
        501: {
            "model": ErrorResponse,
            "description": "No documentation provider is configured",
        },
    },
)
async def upload_repository(
    settings: SettingsDep,
    uploads: ZipUploadServiceDep,
    file: UploadFile = File(...),
) -> RepositoryResponse:
    """Validate, extract, and register a ZIP archive as a new repository.

    Every upload becomes its own repository record — never deduplicated
    against a prior upload — so two archives never share a workspace or an
    artifact. This only ingests the archive; it does not start generation.
    Call ``POST /documentation/jobs`` with the returned ``id`` next, exactly
    as for a GitHub repository.
    """
    if not settings.codewiki_output_root or (
        settings.documentation_provider != "codewiki" or not settings.codewiki_base_url
    ):
        raise DocumentationProviderNotConfiguredError(_NO_PROVIDER_DETAIL)

    repository = await uploads.ingest(file)
    return RepositoryResponse.model_validate(repository)


@router.get(
    "",
    response_model=RepositoryListResponse,
    summary="List submitted repositories",
)
async def list_repositories(service: RepositoryServiceDep) -> RepositoryListResponse:
    items = service.list()
    return RepositoryListResponse(
        items=[RepositoryResponse.model_validate(item) for item in items],
        total=len(items),
    )


@router.get(
    "/bin",
    response_model=BinnedRepositoryListResponse,
    summary="List repositories in the bin",
)
async def list_bin(
    repositories: RepositoryServiceDep,
    jobs: DocumentationJobServiceDep,
) -> BinnedRepositoryListResponse:
    """Repositories that were deleted but can still be restored (until the
    backend restarts — the bin is in memory like everything else here)."""
    items: list[BinnedRepositoryResponse] = []
    for repository, binned_at in repositories.list_binned():
        binned_jobs = jobs.binned_for_repository(repository.id)
        items.append(
            BinnedRepositoryResponse(
                repository=RepositoryResponse.model_validate(repository),
                binned_at=binned_at,
                job_count=len(binned_jobs),
                has_overview=any(j.overview_available for j in binned_jobs),
            )
        )
    return BinnedRepositoryListResponse(items=items, total=len(items))


@router.get(
    "/{repository_id}",
    response_model=RepositoryResponse,
    summary="Get one repository",
    responses={404: {"model": ErrorResponse, "description": "Unknown repository"}},
)
async def get_repository(
    repository_id: uuid.UUID, service: RepositoryServiceDep
) -> RepositoryResponse:
    return RepositoryResponse.model_validate(service.get(repository_id))


@router.get(
    "/{repository_id}/documentation",
    response_model=DocumentationStatusResponse,
    summary="Get documentation state for a repository",
    responses={404: {"model": ErrorResponse, "description": "Unknown repository"}},
)
async def get_repository_documentation(
    repository_id: uuid.UUID,
    repositories: RepositoryServiceDep,
    documentation: DocumentationServiceDep,
) -> DocumentationStatusResponse:
    """Report what the documentation provider has produced.

    With no provider connected this always returns ``NOT_GENERATED`` and a
    ``null`` artifact. It never returns substitute content.
    """
    repository = repositories.get(repository_id)
    state = await documentation.get_state(repository)
    return DocumentationStatusResponse.model_validate(state)


@router.get(
    "/{repository_id}/jobs",
    response_model=JobListResponse,
    summary="Generation history for a repository",
    responses={404: {"model": ErrorResponse, "description": "Unknown repository"}},
)
async def get_repository_jobs(
    repository_id: uuid.UUID,
    repositories: RepositoryServiceDep,
    jobs: DocumentationJobServiceDep,
) -> JobListResponse:
    repositories.get(repository_id)  # 404s if unknown
    items = jobs.list_for_repository(repository_id)
    return JobListResponse(
        items=[JobResponse.model_validate(item) for item in items], total=len(items)
    )


@router.delete(
    "/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Move a repository to the bin",
    responses={404: {"model": ErrorResponse, "description": "Unknown repository"}},
)
async def delete_repository(
    repository_id: uuid.UUID,
    repositories: RepositoryServiceDep,
    jobs: DocumentationJobServiceDep,
) -> Response:
    """Send a repository and its documentation jobs to the bin.

    Nothing is destroyed: the generated overview, the extracted archive and
    CodeWiki's own state are all left in place, so ``POST
    /{repository_id}/restore`` is a true undo. Use ``DELETE
    /{repository_id}/bin`` to erase it for good.
    """
    repository = repositories.get(repository_id)  # 404s if unknown
    jobs.bin_repository_data(repository)
    repositories.bin(repository_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{repository_id}/restore",
    response_model=RepositoryResponse,
    summary="Restore a repository from the bin",
    responses={404: {"model": ErrorResponse, "description": "Not in the bin"}},
)
async def restore_repository(
    repository_id: uuid.UUID,
    repositories: RepositoryServiceDep,
    jobs: DocumentationJobServiceDep,
) -> RepositoryResponse:
    """Bring a binned repository — and every documentation job that went to
    the bin with it — back to the live set."""
    repository = repositories.get_binned(repository_id)  # 404s if not binned
    jobs.restore_repository_data(repository)
    restored = repositories.restore(repository_id)
    return RepositoryResponse.model_validate(restored)


@router.delete(
    "/{repository_id}/bin",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete a repository from the bin",
    responses={404: {"model": ErrorResponse, "description": "Not in the bin"}},
)
async def purge_repository(
    repository_id: uuid.UUID,
    repositories: RepositoryServiceDep,
    jobs: DocumentationJobServiceDep,
) -> Response:
    """Erase a binned repository for good: its record, its jobs, their
    verified artifacts, CodeWiki's output directories and registry entries,
    and (for an uploaded ZIP) the extracted archive on disk. No undo.
    """
    repository = repositories.get_binned(repository_id)  # 404s if not binned
    await jobs.purge_repository_data(repository)
    repositories.delete(repository_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
