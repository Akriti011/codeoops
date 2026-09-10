"""Job-oriented documentation generation service.

Owns job creation, status, history and overview retrieval. Shared by
:class:`~app.providers.codewiki_provider.CodeWikiProvider` (for the legacy
per-repository documentation contract) and the job-centric API routes, so
both views are backed by exactly one job pipeline.

``get_job_service`` is the canonical construction point — everything it needs
is either a settings-independent singleton (:func:`get_job_store`) or cheap to
rebuild per call (the HTTP client, artifact store, runner). Nothing here is
cached by settings value, so overriding settings (e.g. in tests) always takes
effect immediately.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from pathlib import Path

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import DocumentationNotAvailableError, JobNotFoundError
from app.models.enums import JobStatus, RepositorySource
from app.models.job import DocumentationJob
from app.models.repository import Repository
from app.repositories.job_repository import JobStore, get_job_store
from app.services.codewiki.client import CodeWikiClient
from app.services.codewiki.identity import derive_codewiki_job_id
from app.services.documentation.artifact_store import ArtifactStore
from app.services.jobs.job_runner import JobRunner

logger = logging.getLogger("codeoops.jobs")

# Keeps fire-and-forget generation tasks alive for their own duration,
# independent of any single request's or service instance's lifetime — see
# https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task.
_RUNNING_TASKS: set[asyncio.Task] = set()


def _track(task: asyncio.Task) -> None:
    _RUNNING_TASKS.add(task)
    task.add_done_callback(_RUNNING_TASKS.discard)


class DocumentationJobService:
    def __init__(
        self,
        jobs: JobStore,
        artifacts: ArtifactStore,
        runner: JobRunner,
        client: CodeWikiClient,
        *,
        base_url: str,
        output_root: Path,
    ) -> None:
        self._jobs = jobs
        self._artifacts = artifacts
        self._runner = runner
        self._client = client
        self._base_url = base_url
        self._output_root = output_root

    def start_generation(self, repository: Repository) -> DocumentationJob:
        """Create a job and schedule its run. Returns immediately — never blocks."""
        if repository.source is RepositorySource.UPLOAD:
            # No owner/name pair exists to derive a stable id from; the
            # repository's own id is already unique per upload (see
            # Repository.identity_key), so reusing it here means a
            # regeneration of the same upload reuses the same CodeWiki job
            # id — exactly matching the GitHub path's behavior.
            codewiki_job_id = f"upload--{repository.id}"
        else:
            codewiki_job_id = derive_codewiki_job_id(repository.owner, repository.name)
        job = DocumentationJob(repository_id=repository.id, codewiki_job_id=codewiki_job_id)
        job = self._jobs.add(job)

        task = asyncio.create_task(self._runner.run(job, repository))
        _track(task)

        return job

    def get_job(self, job_id: uuid.UUID) -> DocumentationJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError("No job with that id.", details={"job_id": str(job_id)})
        return job

    def list_for_repository(self, repository_id: uuid.UUID) -> list[DocumentationJob]:
        return self._jobs.list_for_repository(repository_id)

    def list_all(self) -> list[DocumentationJob]:
        return self._jobs.list_all()

    def latest_for_repository(self, repository_id: uuid.UUID) -> DocumentationJob | None:
        return self._jobs.latest_for_repository(repository_id)

    def binned_for_repository(self, repository_id: uuid.UUID) -> list[DocumentationJob]:
        return self._jobs.binned_for_repository(repository_id)

    def bin_repository_data(self, repository: Repository) -> int:
        """Move a repository's documentation jobs to the bin alongside the
        repository. Nothing on disk or in CodeWiki is touched — a restore is a
        true undo. Returns the number of jobs binned.
        """
        moved = self._jobs.bin_for_repository(repository.id)
        logger.info("Binned %d job(s) for repository %s", len(moved), repository.id)
        return len(moved)

    def restore_repository_data(self, repository: Repository) -> int:
        """Bring a repository's binned jobs back to the live set."""
        moved = self._jobs.restore_for_repository(repository.id)
        logger.info("Restored %d job(s) for repository %s", len(moved), repository.id)
        return len(moved)

    async def purge_repository_data(self, repository: Repository) -> int:
        """Delete every documentation trace of ``repository``: its job records,
        their verified artifacts, CodeWiki's own output directories on the
        shared volume, and CodeWiki's own registry entries. Returns the number
        of job records removed. Safe to call for a repository that never
        generated anything, and whether it is live or in the bin.
        """
        jobs = self._jobs.list_for_repository(repository.id)
        jobs += self._jobs.binned_for_repository(repository.id)
        codewiki_job_ids = {job.codewiki_job_id for job in jobs}

        for job in jobs:
            self._artifacts.delete(job.id)
            self._jobs.remove(job.id)

        # CodeWiki writes each run under output/docs/<codewiki_job_id>-docs on
        # the volume the backend also mounts (settings.codewiki_output_root),
        # and keeps its own job registry — clear both so its console doesn't
        # keep advertising a completed job whose docs are gone.
        docs_root = self._output_root / "docs"
        for codewiki_job_id in codewiki_job_ids:
            self._safe_rmtree(docs_root / f"{codewiki_job_id}-docs")
            await self._client.delete_job(codewiki_job_id)

        # Upload-sourced repositories also have the extracted archive at
        # output/uploads/<repository_id>/ (see ZipUploadService.ingest).
        if repository.source is RepositorySource.UPLOAD:
            self._safe_rmtree(self._output_root / "uploads" / str(repository.id))

        logger.info(
            "Purged documentation data for repository %s: %d job(s), %d CodeWiki output dir(s)",
            repository.id, len(jobs), len(codewiki_job_ids),
        )
        return len(jobs)

    def _safe_rmtree(self, path: Path) -> None:
        """``shutil.rmtree`` guarded so a bad id can never escape the output
        root (belt-and-braces: every id fed in here is a UUID or a
        host-validated ``owner--repo`` slug)."""
        try:
            root = self._output_root.resolve()
            target = path.resolve()
        except OSError:
            return
        if target == root or root not in target.parents:
            logger.warning("Refusing to delete %s — not inside the output root", path)
            return
        shutil.rmtree(target, ignore_errors=True)

    def get_overview_bytes(self, job_id: uuid.UUID) -> bytes:
        job = self.get_job(job_id)
        if job.status != JobStatus.COMPLETED or not job.overview_available:
            raise DocumentationNotAvailableError(
                "This job has no verified documentation available.",
                details={
                    "job_status": job.status.value,
                    "error_code": job.error_code,
                    "error_message": job.error_message,
                },
            )
        content = self._artifacts.read_overview(job_id)
        if content is None:
            raise DocumentationNotAvailableError(
                "This job's documentation could not be located.",
                details={"job_status": job.status.value},
            )
        return content

    async def probe_engine(self) -> dict[str, object]:
        reachable = await self._client.is_reachable()
        return {"engine": "codewiki", "reachable": reachable, "base_url": self._base_url}


def get_job_service(settings: Settings | None = None) -> DocumentationJobService:
    """Build a :class:`DocumentationJobService` from ``settings`` (or the global default)."""
    settings = settings or get_settings()

    base_url = settings.codewiki_base_url or "http://codewiki.invalid"
    http = httpx.AsyncClient(base_url=base_url, timeout=30.0)
    client = CodeWikiClient(http)

    jobs = get_job_store()
    artifacts = ArtifactStore(Path(settings.artifact_root))
    output_root = Path(settings.codewiki_output_root or ".")

    runner = JobRunner(
        client=client,
        jobs=jobs,
        artifacts=artifacts,
        output_root=output_root,
        poll_interval_seconds=settings.codewiki_poll_interval_seconds,
        timeout_seconds=settings.codewiki_timeout_seconds,
    )

    return DocumentationJobService(
        jobs=jobs,
        artifacts=artifacts,
        runner=runner,
        client=client,
        base_url=base_url,
        output_root=output_root,
    )
