"""Documentation job routes.

Job creation always returns immediately (``202``); generation runs out of
band and is tracked through these same endpoints via polling. Routes
translate HTTP to service calls and back — no orchestration logic lives here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import DocumentationJobServiceDep, RepositoryServiceDep, SettingsDep
from app.core.errors import DocumentationProviderNotConfiguredError
from app.schemas.common import ErrorResponse
from app.schemas.job import (
    EngineStatusResponse,
    JobCreateRequest,
    JobListResponse,
    JobResponse,
)
from app.services.documentation import export_service

_NO_PROVIDER_DETAIL = (
    "No documentation provider is connected. CodeWiki integration is not "
    "enabled in this build."
)

router = APIRouter(prefix="/documentation", tags=["documentation-jobs"])


@router.post(
    "/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a documentation generation job",
    responses={
        422: {"model": ErrorResponse, "description": "Invalid repository URL"},
        501: {
            "model": ErrorResponse,
            "description": "No documentation provider is configured",
        },
    },
)
async def create_job(
    payload: JobCreateRequest,
    settings: SettingsDep,
    repositories: RepositoryServiceDep,
    jobs: DocumentationJobServiceDep,
) -> JobResponse:
    """Start a CodeWiki job for a repository, from a GitHub URL or an id.

    Fails loudly, synchronously, if no engine is configured — the same rule
    the legacy `/repositories/{id}/documentation` path follows — rather than
    creating a job doomed to fail against an unset CodeWiki URL. Otherwise
    returns as soon as the job is created; generation happens out of band.
    Poll ``GET /documentation/jobs/{job_id}`` for progress.

    ``repository_id`` (from a prior ``POST /repositories/upload``) and
    ``repository_url`` (registered idempotently here, exactly as before)
    both converge on the same call to ``jobs.start_generation`` — one job
    pipeline regardless of how the repository's source arrived.
    """
    if settings.documentation_provider != "codewiki" or not settings.codewiki_base_url:
        raise DocumentationProviderNotConfiguredError(_NO_PROVIDER_DETAIL)

    if payload.repository_id is not None:
        repository = repositories.get(payload.repository_id)
    else:
        submission = repositories.submit(payload.repository_url)
        repository = submission.repository

    job = jobs.start_generation(repository)
    return JobResponse.model_validate(job)


@router.get(
    "/engine",
    response_model=EngineStatusResponse,
    summary="Check whether the CodeWiki engine is reachable",
)
async def get_engine_status(jobs: DocumentationJobServiceDep) -> EngineStatusResponse:
    return EngineStatusResponse.model_validate(await jobs.probe_engine())


@router.get(
    "/jobs",
    response_model=JobListResponse,
    summary="List documentation jobs for a repository",
    responses={404: {"model": ErrorResponse, "description": "Unknown repository"}},
)
async def list_jobs(
    repository_id: uuid.UUID,
    repositories: RepositoryServiceDep,
    jobs: DocumentationJobServiceDep,
) -> JobListResponse:
    repositories.get(repository_id)  # 404s if unknown
    items = jobs.list_for_repository(repository_id)
    return JobListResponse(
        items=[JobResponse.model_validate(item) for item in items], total=len(items)
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="Get one documentation job",
    responses={404: {"model": ErrorResponse, "description": "Unknown job"}},
)
async def get_job(job_id: uuid.UUID, jobs: DocumentationJobServiceDep) -> JobResponse:
    return JobResponse.model_validate(jobs.get_job(job_id))


@router.get(
    "/jobs/{job_id}/overview",
    summary="Fetch the exact overview.md bytes CodeWiki produced",
    responses={
        404: {"model": ErrorResponse, "description": "Unknown job"},
        409: {
            "model": ErrorResponse,
            "description": "This job has no verified documentation available",
        },
    },
)
async def get_job_overview(job_id: uuid.UUID, jobs: DocumentationJobServiceDep) -> Response:
    content = jobs.get_overview_bytes(job_id)
    return Response(
        content=content,
        media_type="text/markdown",
        headers={
            "X-CodeOops-Job-Id": str(job_id),
            "X-CodeOops-Engine": "codewiki",
        },
    )


@router.get(
    "/jobs/{job_id}/overview.pdf",
    summary="Export the overview as a PDF",
    responses={
        404: {"model": ErrorResponse, "description": "Unknown job"},
        409: {
            "model": ErrorResponse,
            "description": "This job has no verified documentation available",
        },
    },
)
async def get_job_overview_pdf(job_id: uuid.UUID, jobs: DocumentationJobServiceDep) -> Response:
    content = jobs.get_overview_bytes(job_id)
    pdf_bytes = export_service.render_pdf(content.decode("utf-8"))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "X-CodeOops-Job-Id": str(job_id),
            "X-CodeOops-Engine": "codewiki",
            "Content-Disposition": f'attachment; filename="overview-{job_id}.pdf"',
        },
    )


@router.get(
    "/jobs/{job_id}/overview.csv",
    summary="Export the overview as a structured CSV (one row per top-level section)",
    responses={
        404: {"model": ErrorResponse, "description": "Unknown job"},
        409: {
            "model": ErrorResponse,
            "description": "This job has no verified documentation available",
        },
    },
)
async def get_job_overview_csv(job_id: uuid.UUID, jobs: DocumentationJobServiceDep) -> Response:
    content = jobs.get_overview_bytes(job_id)
    csv_bytes = export_service.render_csv(content.decode("utf-8"))
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={
            "X-CodeOops-Job-Id": str(job_id),
            "X-CodeOops-Engine": "codewiki",
            "Content-Disposition": f'attachment; filename="overview-{job_id}.csv"',
        },
    )
