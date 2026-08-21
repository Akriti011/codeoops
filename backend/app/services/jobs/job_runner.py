"""Orchestrates one documentation generation job end to end.

    SUBMITTING  -> hand the repository to CodeWiki
    GENERATING  -> poll CodeWiki's own job status until it reaches a terminal state
    RETRIEVING  -> map docs_path onto the shared volume, verify, copy bytes
    COMPLETED / FAILED

The anti-stale guard (:meth:`JobRunner._is_fresh`): CodeWiki keys jobs by
repository name only, so an old completed job can still be sitting under the
id CodeOops is about to submit. Before submitting, this records CodeWiki's
current entry for that id (``baseline``); after submitting, it will not treat
any completion as belonging to this run until CodeWiki's entry is
demonstrably new — a later ``created_at``/``completed_at`` than the baseline,
or a transition back through a non-terminal status. If that never happens
before the timeout, the job fails with ``CODEWIKI_JOB_NOT_FOUND`` rather than
silently adopting the earlier run's documentation.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path, PurePosixPath

from app.models.enums import JobStatus, RepositorySource
from app.models.job import CodeWikiJobInfo, DocumentationJob
from app.models.repository import Repository
from app.repositories.job_repository import JobStore
from app.services.codewiki.artifacts import read_metadata, read_overview
from app.services.codewiki.binding import verify_binding
from app.services.codewiki.client import CodeWikiClient, CodeWikiJobStatus
from app.services.codewiki.errors import (
    CodeWikiError,
    CodeWikiFailedError,
    CodeWikiJobNotFoundError,
    CodeWikiTimeoutError,
    DocsPathMissingError,
    UploadWorkspaceOutsideSharedVolumeError,
)
from app.services.documentation.artifact_store import ArtifactStore

logger = logging.getLogger("codeoops.jobs")

_TERMINAL_CODEWIKI_STATUSES = frozenset({"completed", "failed"})

# CodeWiki's own web app always writes under ``OUTPUT_DIR = "./output"``
# resolved against its container's fixed WorkingDir (codewiki/src/fe/config.py,
# Dockerfile WORKDIR /app) — so the docs path CodeWiki reports for a job is
# always this exact absolute *container* path, never a path meaningful on
# whatever host CodeOops itself runs on. ``codewiki_output_root`` is the host
# directory bind-mounted onto that same container path; every docs_path is
# rebased from one onto the other by stripping this fixed prefix.
_CODEWIKI_CONTAINER_OUTPUT_DIR = PurePosixPath("/app/output")


class JobRunner:
    """Drives one :class:`DocumentationJob` from SUBMITTING to a terminal state."""

    def __init__(
        self,
        client: CodeWikiClient,
        jobs: JobStore,
        artifacts: ArtifactStore,
        output_root: Path,
        *,
        poll_interval_seconds: float,
        timeout_seconds: float,
    ) -> None:
        self._client = client
        self._jobs = jobs
        self._artifacts = artifacts
        self._output_root = output_root
        self._poll_interval = poll_interval_seconds
        self._timeout = timeout_seconds

    async def run(self, job: DocumentationJob, repository: Repository) -> None:
        """Run ``job`` to completion. Never raises — failures land on the job record."""
        try:
            await self._run(job, repository)
        except CodeWikiError as exc:
            self._fail(job, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 - last-resort containment
            logger.exception("Unhandled error running job %s", job.id)
            self._fail(job, "RUNNER_ERROR", str(exc))

    async def _run(self, job: DocumentationJob, repository: Repository) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout

        baseline = await self._client.get_job(job.codewiki_job_id)

        self._jobs.update(job.with_update(progress_message="Submitting to CodeWiki…"))
        if repository.source is RepositorySource.UPLOAD:
            container_path = self._to_container_local_path(repository.upload_workspace_path)
            await self._client.submit_local(job.codewiki_job_id, container_path)
        else:
            await self._client.submit(repository.repository_url)

        job = self._jobs.update(
            job.with_update(
                status=JobStatus.GENERATING,
                progress_message="CodeWiki is generating documentation…",
            )
        )

        fresh = await self._await_handshake(job, baseline, deadline, loop)

        if fresh.status == "failed":
            raise CodeWikiFailedError(
                fresh.error_message or "CodeWiki reported a failure.",
                details={"codewiki_job_id": job.codewiki_job_id},
            )

        job = self._jobs.update(
            job.with_update(
                status=JobStatus.RETRIEVING,
                progress_message="Verifying and storing the generated documentation…",
            )
        )

        if not fresh.docs_path:
            raise DocsPathMissingError(
                "CodeWiki completed without reporting a documentation path.",
                details={"codewiki_job_id": job.codewiki_job_id},
            )

        docs_dir = self._resolve_docs_dir(fresh.docs_path)

        overview_text = read_overview(docs_dir)
        metadata = read_metadata(docs_dir)
        verify_binding(metadata, job.codewiki_job_id)

        self._artifacts.save_overview(job.id, overview_text.encode("utf-8"))

        served_from_cache = bool(
            baseline is not None
            and baseline.completed_at is not None
            and metadata.timestamp is not None
            and baseline.completed_at.isoformat() == metadata.timestamp
        )

        self._jobs.update(
            job.with_update(
                status=JobStatus.COMPLETED,
                completed_at=fresh.completed_at,
                overview_available=True,
                served_from_codewiki_cache=served_from_cache,
                progress_message=None,
                codewiki=_to_job_info(job.codewiki_job_id, fresh),
            )
        )

    async def _await_handshake(
        self,
        job: DocumentationJob,
        baseline: CodeWikiJobStatus | None,
        deadline: float,
        loop: asyncio.AbstractEventLoop,
    ) -> CodeWikiJobStatus:
        """Poll until CodeWiki's entry is demonstrably a new, terminal run.

        Two distinct timeout outcomes: if CodeWiki never acknowledged a fresh
        run at all, that's ``CODEWIKI_JOB_NOT_FOUND`` — CodeOops refuses to
        adopt the stale entry that was already sitting there. If it did
        acknowledge one but generation simply never finished, that's
        ``CODEWIKI_TIMEOUT``.
        """
        seen_fresh = False
        while True:
            if loop.time() > deadline:
                if seen_fresh:
                    raise CodeWikiTimeoutError(
                        "CodeWiki did not finish generating documentation in time.",
                        details={"timeout_seconds": self._timeout},
                    )
                raise CodeWikiJobNotFoundError(
                    "CodeWiki never reported a new run for this repository.",
                    details={"codewiki_job_id": job.codewiki_job_id},
                )

            current = await self._client.get_job(job.codewiki_job_id)
            if current is not None and self._is_fresh(baseline, current):
                seen_fresh = True
                self._jobs.update(
                    job.with_update(codewiki=_to_job_info(job.codewiki_job_id, current))
                )
                if current.status in _TERMINAL_CODEWIKI_STATUSES:
                    return current

            await asyncio.sleep(self._poll_interval)

    def _resolve_docs_dir(self, docs_path: str) -> Path:
        """Rebase a CodeWiki-reported ``docs_path`` onto ``_output_root``.

        A real CodeWiki instance always reports an absolute path under
        ``_CODEWIKI_CONTAINER_OUTPUT_DIR`` (its own container's fixed output
        root) — that prefix is stripped and the remainder is rejoined onto
        the configured host mount. Any other absolute path (e.g. a test
        double whose ``docs_path`` is already a valid path in the current
        process) is used as-is, and a relative path is joined onto the host
        mount — both matching the pre-existing convention.
        """
        raw = PurePosixPath(docs_path)
        if raw.is_absolute():
            try:
                relative = raw.relative_to(_CODEWIKI_CONTAINER_OUTPUT_DIR)
            except ValueError:
                return Path(docs_path)
            return self._output_root.joinpath(*relative.parts)
        return self._output_root / docs_path

    def _to_container_local_path(self, host_path: str | None) -> str:
        """Rebase a host-side upload workspace path onto CodeWiki's container mount.

        Inverse of :meth:`_resolve_docs_dir`: CodeOops extracts an uploaded
        archive under ``self._output_root`` (the host directory bind-mounted
        onto CodeWiki's fixed ``/app/output``); CodeWiki needs that same
        directory's path as it appears inside its own container.
        """
        if not host_path:
            raise UploadWorkspaceOutsideSharedVolumeError(
                "This repository has no recorded upload workspace.",
            )
        resolved = Path(host_path).resolve()
        try:
            relative = resolved.relative_to(self._output_root.resolve())
        except ValueError as exc:
            raise UploadWorkspaceOutsideSharedVolumeError(
                "The upload workspace is not inside the shared CodeWiki output volume.",
                details={"path": host_path},
            ) from exc
        return str(_CODEWIKI_CONTAINER_OUTPUT_DIR.joinpath(*relative.parts))

    @staticmethod
    def _is_fresh(baseline: CodeWikiJobStatus | None, current: CodeWikiJobStatus) -> bool:
        """True once CodeWiki's entry is demonstrably a new run, not the old one."""
        if baseline is None:
            return True
        if current.status not in _TERMINAL_CODEWIKI_STATUSES:
            return True
        if (
            current.created_at
            and baseline.created_at
            and current.created_at > baseline.created_at
        ):
            return True
        if (
            current.completed_at
            and baseline.completed_at
            and current.completed_at > baseline.completed_at
        ):
            return True
        return False

    def _fail(self, job: DocumentationJob, code: str, message: str) -> None:
        self._jobs.update(
            job.with_update(
                status=JobStatus.FAILED,
                error_code=code,
                error_message=message,
                progress_message=None,
            )
        )


def _to_job_info(codewiki_job_id: str, status: CodeWikiJobStatus) -> CodeWikiJobInfo:
    return CodeWikiJobInfo(
        codewiki_job_id=codewiki_job_id,
        codewiki_status=status.status,
        codewiki_progress=status.progress,
        created_at=status.created_at,
        started_at=status.started_at,
        completed_at=status.completed_at,
        main_model=status.main_model,
        commit_id=status.commit_id,
    )
