"""CodeWikiProvider — the one adapter this application wires to CodeWiki.

Implements the :class:`~app.providers.documentation_provider.DocumentationProvider`
port by delegating to :class:`~app.services.documentation.job_service.DocumentationJobService`.
No other file needs to change to add this provider — see
``get_documentation_provider`` in ``app/providers/documentation_provider.py``.
"""

from __future__ import annotations

import uuid

from app.models.documentation import DocumentationArtifactRef, DocumentationState
from app.models.enums import DocumentationStatus, JobStatus
from app.models.job import DocumentationJob
from app.models.repository import Repository
from app.providers.documentation_provider import DocumentationProvider
from app.services.documentation.job_service import DocumentationJobService

_STATUS_MAP: dict[JobStatus, DocumentationStatus] = {
    JobStatus.SUBMITTING: DocumentationStatus.QUEUED,
    JobStatus.GENERATING: DocumentationStatus.GENERATING,
    JobStatus.RETRIEVING: DocumentationStatus.GENERATING,
    JobStatus.COMPLETED: DocumentationStatus.COMPLETED,
    JobStatus.FAILED: DocumentationStatus.FAILED,
}


class CodeWikiProvider(DocumentationProvider):
    name = "codewiki"

    def __init__(self, jobs: DocumentationJobService) -> None:
        self._jobs = jobs

    async def get_state(self, repository: Repository) -> DocumentationState:
        job = self._jobs.latest_for_repository(repository.id)
        if job is None:
            return DocumentationState(
                repository_id=repository.id,
                status=DocumentationStatus.NOT_GENERATED,
                artifact=None,
                detail="No documentation has been requested for this repository yet.",
            )
        return self._to_state(repository.id, job)

    async def request_generation(self, repository: Repository) -> DocumentationState:
        job = self._jobs.start_generation(repository)
        return self._to_state(repository.id, job)

    async def read_document(
        self, repository: Repository, artifact_id: uuid.UUID, document_path: str
    ) -> bytes:
        return self._jobs.get_overview_bytes(artifact_id)

    def _to_state(self, repository_id: uuid.UUID, job: DocumentationJob) -> DocumentationState:
        status = _STATUS_MAP[job.status]

        artifact = None
        if job.status is JobStatus.COMPLETED and job.overview_available:
            overview = self._jobs.get_overview_bytes(job.id).decode("utf-8")
            artifact = DocumentationArtifactRef(
                id=job.id,
                repository_id=repository_id,
                entry_document=overview,
                generated_at=job.completed_at or job.created_at,
                provider=self._provider_label(job),
            )

        if job.status is JobStatus.FAILED:
            detail = job.error_message
        elif job.status is JobStatus.COMPLETED:
            detail = "Served from CodeWiki's cache." if job.served_from_codewiki_cache else None
        else:
            detail = job.progress_message

        return DocumentationState(
            repository_id=repository_id, status=status, artifact=artifact, detail=detail
        )

    @staticmethod
    def _provider_label(job: DocumentationJob) -> str:
        model = job.codewiki.main_model if job.codewiki else None
        return f"codewiki ({model})" if model else "codewiki"
