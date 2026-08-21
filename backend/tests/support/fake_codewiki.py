"""A protocol double for the CodeWiki web app.

Reproduces the HTTP contract described in the integration reference exactly:

    GET  /                    -> 200 (liveness)
    POST /                    -> 200 HTML, no job id in the body
    POST /api/local-job       -> 202 JSON, queues a job for an already-placed
                                  local repository (the ZIP-upload path)
    GET  /api/job/{job_id}    -> JobStatusResponse-shaped JSON, or 404

Job state is driven directly by the test (``complete`` / ``fail`` /
``seed_completed`` / ``set_reject_submissions`` / ``set_unreachable``) rather
than by a real generation pipeline — this exercises CodeOops's own
orchestration (submission, polling, the anti-stale handshake, artifact
retrieval and binding) against a faithful but controllable stand-in, not a
real LLM run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class FakeJobRecord:
    job_id: str
    repo_url: str
    status: str = "processing"
    created_at: str = field(default_factory=_now_iso)
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    progress: str | None = None
    docs_path: str | None = None
    main_model: str | None = "qwen2.5-coder-32k"
    commit_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "repo_url": self.repo_url,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error_message": self.error_message,
            "progress": self.progress,
            "docs_path": self.docs_path,
            "main_model": self.main_model,
            "commit_id": self.commit_id,
        }


class FakeCodeWiki:
    """An in-memory CodeWiki double with a real ASGI surface."""

    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root
        self.unreachable = False
        self.reject_submissions = False
        self._jobs: dict[str, FakeJobRecord] = {}
        self._frozen: set[str] = set()
        self.app = Starlette(
            routes=[
                Route("/", self._index, methods=["GET"]),
                Route("/", self._submit, methods=["POST"]),
                Route("/api/local-job", self._submit_local, methods=["POST"]),
                Route("/api/job/{job_id}", self._get_job, methods=["GET"]),
            ]
        )

    # --- ASGI handlers ------------------------------------------------

    async def _index(self, request: Request) -> HTMLResponse:
        if self.unreachable:
            return HTMLResponse("unreachable", status_code=503)
        return HTMLResponse("<html><body>CodeWiki</body></html>")

    async def _submit(self, request: Request) -> HTMLResponse:
        if self.unreachable:
            return HTMLResponse("unreachable", status_code=503)
        if self.reject_submissions:
            return HTMLResponse("cooldown active, try again later", status_code=429)

        form = await request.form()
        repo_url = str(form.get("repo_url", ""))
        owner, name = repo_url.rstrip("/").split("/")[-2:]
        job_id = f"{owner}--{name}"

        if job_id in self._frozen:
            return HTMLResponse("<html><body>submitted</body></html>")

        existing = self._jobs.get(job_id)
        if existing is None or existing.status in ("completed", "failed"):
            # A brand new run: move straight to "processing" so pollers see a
            # fresh, non-terminal entry — mirrors CodeWiki picking a job up.
            self._jobs[job_id] = FakeJobRecord(
                job_id=job_id, repo_url=repo_url, status="processing", started_at=_now_iso()
            )
        return HTMLResponse("<html><body>submitted</body></html>")

    async def _submit_local(self, request: Request) -> JSONResponse:
        """Mirror the real CodeWiki-side ``/api/local-job`` route (see
        codewiki/src/fe/routes.py::local_job_post) used for ZIP uploads."""
        if self.unreachable:
            return JSONResponse({"error": "unreachable"}, status_code=503)
        if self.reject_submissions:
            return JSONResponse({"error": "rejected"}, status_code=429)

        body = await request.json()
        job_id = str(body.get("job_id", "")).strip()
        local_path = str(body.get("local_path", "")).strip()
        if not job_id or not local_path:
            return JSONResponse({"error": "job_id and local_path are required"}, status_code=400)

        if job_id in self._frozen:
            return JSONResponse({"status": "queued", "job_id": job_id}, status_code=202)

        self._get_or_create_by_id(job_id, f"local:{local_path}")
        return JSONResponse({"status": "queued", "job_id": job_id}, status_code=202)

    async def _get_job(self, request: Request) -> JSONResponse:
        if self.unreachable:
            return JSONResponse({"detail": "unreachable"}, status_code=503)
        job_id = request.path_params["job_id"]
        record = self._jobs.get(job_id)
        if record is None:
            return JSONResponse({"detail": "not found"}, status_code=404)
        return JSONResponse(record.to_json())

    # --- test control ---------------------------------------------------

    @staticmethod
    def _job_id(owner: str, name: str) -> str:
        return f"{owner}--{name}"

    def seed_completed(self, owner: str, name: str, **overrides: Any) -> FakeJobRecord:
        """Pre-populate a job as if a prior run already completed (staleness tests)."""
        job_id = self._job_id(owner, name)
        record = FakeJobRecord(
            job_id=job_id,
            repo_url=f"https://github.com/{owner}/{name}",
            status="completed",
            completed_at=_now_iso(),
        )
        for key, value in overrides.items():
            setattr(record, key, value)
        self._jobs[job_id] = record
        return record

    def write_docs(
        self,
        owner: str,
        name: str,
        *,
        overview: str | None = "# Overview\n\nHello.\n",
        metadata: dict[str, Any] | None = None,
        docs_dir_name: str | None = None,
        skip_metadata: bool = False,
        skip_overview: bool = False,
    ) -> Path:
        """Write overview.md/metadata.json to the shared output volume."""
        return self.write_docs_for_job_id(
            self._job_id(owner, name),
            overview=overview,
            metadata=metadata,
            docs_dir_name=docs_dir_name,
            skip_metadata=skip_metadata,
            skip_overview=skip_overview,
        )

    def write_docs_for_job_id(
        self,
        job_id: str,
        *,
        overview: str | None = "# Overview\n\nHello.\n",
        metadata: dict[str, Any] | None = None,
        docs_dir_name: str | None = None,
        skip_metadata: bool = False,
        skip_overview: bool = False,
    ) -> Path:
        """Same as :meth:`write_docs`, keyed directly by CodeWiki job id.

        Needed for ZIP-upload jobs, whose id is ``upload--{uuid}`` rather
        than a derivable ``{owner}--{name}`` pair.
        """
        docs_dir = self.output_root / (docs_dir_name or f"{job_id}-docs")
        docs_dir.mkdir(parents=True, exist_ok=True)

        if not skip_overview and overview is not None:
            (docs_dir / "overview.md").write_text(overview, encoding="utf-8")

        if not skip_metadata:
            payload = {
                "generation_info": {
                    "timestamp": _now_iso(),
                    "main_model": "qwen2.5-coder-32k",
                    "generator_version": "1.0.1",
                    "repo_path": f"output/temp/{job_id}",
                    "commit_id": None,
                }
            }
            if metadata:
                payload["generation_info"].update(metadata)
            import json

            (docs_dir / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")

        return docs_dir

    def _get_or_create_by_id(self, job_id: str, repo_url: str) -> FakeJobRecord:
        """Look up a job's record, creating one as if freshly submitted.

        A test may want to drive a job straight to completion/failure without
        first waiting for CodeOops's background submit() call to actually
        reach this double — this makes that safe regardless of ordering.
        """
        record = self._jobs.get(job_id)
        if record is None:
            record = FakeJobRecord(
                job_id=job_id, repo_url=repo_url, status="processing", started_at=_now_iso()
            )
            self._jobs[job_id] = record
        return record

    def _get_or_create(self, owner: str, name: str) -> FakeJobRecord:
        return self._get_or_create_by_id(
            self._job_id(owner, name), f"https://github.com/{owner}/{name}"
        )

    def complete(
        self,
        owner: str,
        name: str,
        *,
        docs_dir_name: str | None = None,
        main_model: str = "qwen2.5-coder-32k",
        commit_id: str | None = None,
    ) -> None:
        self.complete_job_id(
            self._job_id(owner, name),
            repo_url=f"https://github.com/{owner}/{name}",
            docs_dir_name=docs_dir_name,
            main_model=main_model,
            commit_id=commit_id,
        )

    def complete_job_id(
        self,
        job_id: str,
        *,
        repo_url: str = "",
        docs_dir_name: str | None = None,
        main_model: str = "qwen2.5-coder-32k",
        commit_id: str | None = None,
    ) -> None:
        """Same as :meth:`complete`, keyed directly by CodeWiki job id."""
        record = self._get_or_create_by_id(job_id, repo_url or f"local:{job_id}")
        record.status = "completed"
        record.completed_at = _now_iso()
        record.main_model = main_model
        record.commit_id = commit_id
        record.docs_path = str(self.output_root / (docs_dir_name or f"{job_id}-docs"))

    def complete_without_docs_path(self, owner: str, name: str) -> None:
        """Simulate CodeWiki completing without ever reporting a docs_path."""
        record = self._get_or_create(owner, name)
        record.status = "completed"
        record.completed_at = _now_iso()
        record.docs_path = None

    def freeze(self, owner: str, name: str) -> None:
        """Make submissions to this repository's job id a no-op.

        Simulates a CodeWiki that accepted the HTTP request but never
        actually picked up a new run — the scenario the anti-stale handshake
        guards against.
        """
        self._frozen.add(self._job_id(owner, name))

    def fail(self, owner: str, name: str, message: str) -> None:
        record = self._get_or_create(owner, name)
        record.status = "failed"
        record.completed_at = _now_iso()
        record.error_message = message

    def set_reject_submissions(self, value: bool) -> None:
        self.reject_submissions = value

    def set_unreachable(self, value: bool) -> None:
        self.unreachable = value
