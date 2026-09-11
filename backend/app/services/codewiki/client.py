"""Thin HTTP client for the CodeWiki web app.

Confined here so no other module in the codebase knows CodeWiki's HTTP shape:
the ``POST /`` submission form and the ``GET /api/job/{job_id}`` status
endpoint (codewiki/src/fe/web_app.py, codewiki/src/fe/models.py).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.services.codewiki.errors import (
    CodeWikiSubmitRejectedError,
    CodeWikiUnreachableError,
)

logger = logging.getLogger(__name__)

# A job's HTTP calls to CodeWiki (a submit, then minutes of status polling)
# are numerous enough that one transient connection blip must not sink the
# whole run. Retried only for network-level failures (httpx.HTTPError) —
# never for a 4xx/5xx response, which is CodeWiki actually answering.
_MAX_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 1.0


async def _with_retries(
    description: str, call: Callable[[], Awaitable[httpx.Response]]
) -> httpx.Response:
    last_exc: httpx.HTTPError | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return await call()
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < _MAX_ATTEMPTS:
                logger.warning(
                    "CodeWiki call failed (%s), attempt %d/%d: %s",
                    description,
                    attempt,
                    _MAX_ATTEMPTS,
                    exc,
                )
                await asyncio.sleep(_RETRY_DELAY_SECONDS * attempt)
    assert last_exc is not None
    raise last_exc


@dataclass(frozen=True, slots=True)
class CodeWikiJobStatus:
    """CodeWiki's own job record, as returned by ``GET /api/job/{job_id}``."""

    job_id: str
    repo_url: str
    status: str
    created_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    progress: str | None
    docs_path: str | None
    main_model: str | None
    commit_id: str | None


class CodeWikiClient:
    """Talks to one CodeWiki instance over HTTP."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def is_reachable(self) -> bool:
        try:
            response = await self._http.get("/", timeout=5.0)
        except httpx.HTTPError:
            return False
        return response.status_code < 500

    async def submit(self, repository_url: str, commit_id: str | None = None) -> None:
        """POST the submission form. CodeWiki replies with HTML, not a job id."""
        try:
            response = await _with_retries(
                "submit",
                lambda: self._http.post(
                    "/", data={"repo_url": repository_url, "commit_id": commit_id or ""}
                ),
            )
        except httpx.HTTPError as exc:
            raise CodeWikiUnreachableError(
                "Could not reach CodeWiki to submit the repository.",
                details={"reason": str(exc)},
            ) from exc
        if response.status_code >= 400:
            raise CodeWikiSubmitRejectedError(
                "CodeWiki rejected the submission.",
                details={"status_code": response.status_code},
            )

    async def submit_local(self, codewiki_job_id: str, local_path: str) -> None:
        """Submit a repository CodeOops already placed on the shared output volume.

        Used for ZIP uploads: CodeWiki's normal ``POST /`` only accepts a
        GitHub URL it clones itself, so this hits the small additive
        ``/api/local-job`` endpoint instead, telling CodeWiki to analyze an
        already-extracted directory directly. Everything downstream (job
        tracking, ``GET /api/job/{id}``, output layout) is identical to the
        GitHub path.
        """
        try:
            response = await _with_retries(
                "submit_local",
                lambda: self._http.post(
                    "/api/local-job", json={"job_id": codewiki_job_id, "local_path": local_path}
                ),
            )
        except httpx.HTTPError as exc:
            raise CodeWikiUnreachableError(
                "Could not reach CodeWiki to submit the repository.",
                details={"reason": str(exc)},
            ) from exc
        if response.status_code >= 400:
            raise CodeWikiSubmitRejectedError(
                "CodeWiki rejected the local repository submission.",
                details={"status_code": response.status_code},
            )

    async def get_job(self, codewiki_job_id: str) -> CodeWikiJobStatus | None:
        """Return CodeWiki's own job record, or ``None`` if it knows no such id."""
        try:
            response = await _with_retries(
                "get_job", lambda: self._http.get(f"/api/job/{codewiki_job_id}")
            )
        except httpx.HTTPError as exc:
            raise CodeWikiUnreachableError(
                "Could not reach CodeWiki to check job status.",
                details={"reason": str(exc)},
            ) from exc
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise CodeWikiUnreachableError(
                "CodeWiki returned an unexpected status while checking the job.",
                details={"status_code": response.status_code},
            )
        body = response.json()
        return CodeWikiJobStatus(
            job_id=body["job_id"],
            repo_url=body["repo_url"],
            status=body["status"],
            created_at=_parse_dt(body.get("created_at")),
            started_at=_parse_dt(body.get("started_at")),
            completed_at=_parse_dt(body.get("completed_at")),
            error_message=body.get("error_message"),
            progress=body.get("progress"),
            docs_path=body.get("docs_path"),
            main_model=body.get("main_model"),
            commit_id=body.get("commit_id"),
        )

    async def delete_job(self, codewiki_job_id: str) -> bool:
        """Ask CodeWiki to forget one job from its own registry.

        Best-effort: the CodeOops-side deletion has already happened by the
        time this is called, so an unreachable engine or an error here must
        not fail the request — it only leaves a cosmetic stale row in
        CodeWiki's own console. Returns True if CodeWiki removed an entry.
        """
        try:
            response = await self._http.delete(f"/api/job/{codewiki_job_id}")
        except httpx.HTTPError:
            return False
        return response.status_code == 200


def _parse_dt(value: str | None) -> datetime | None:
    """Parse a CodeWiki timestamp, treating a naive one as UTC.

    CodeWiki stamps its own job records with ``datetime.now()`` (naive) on a
    container clock that runs UTC. Left naive, this datetime later serializes
    to JSON without a ``Z``/offset, and the frontend's `new Date()` then reads
    it as local time — a multi-hour skew that broke duration display.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
