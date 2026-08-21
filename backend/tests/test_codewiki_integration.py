"""End-to-end tests for the CodeWiki job pipeline.

Drives the real CodeOops API (routes -> services -> job runner -> CodeWiki
client) against ``tests.support.fake_codewiki.FakeCodeWiki`` — a protocol
double reproducing CodeWiki's actual HTTP contract, job-id derivation,
directory layout and metadata fields (see app/services/codewiki/*). This
exercises CodeOops's own orchestration for real; it does not, and cannot,
prove anything about CodeWiki's own behaviour under a real LLM.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_documentation_job_service, get_provider, get_repository_store
from app.core.config import Settings, get_settings
from app.main import create_app
from app.providers.codewiki_provider import CodeWikiProvider
from app.repositories.job_repository import InMemoryJobStore
from app.services.codewiki.client import CodeWikiClient
from app.services.documentation.artifact_store import ArtifactStore
from app.services.documentation.job_service import DocumentationJobService
from app.services.jobs.job_runner import JobRunner
from tests.conftest import API
from tests.support.fake_codewiki import FakeCodeWiki

POLL_INTERVAL = 0.02
DEFAULT_TIMEOUT = 3.0

# The job-creation route requires this exact configuration to be present
# before it will start a run — the same gate the legacy provider path uses.
_CODEWIKI_ENABLED_SETTINGS = Settings(
    documentation_provider="codewiki", codewiki_base_url="http://codewiki.test"
)


@pytest.fixture
def fake_codewiki(tmp_path: Path) -> FakeCodeWiki:
    return FakeCodeWiki(output_root=tmp_path / "output")


def _make_service(
    fake: FakeCodeWiki, tmp_path: Path, *, timeout_seconds: float = DEFAULT_TIMEOUT
) -> DocumentationJobService:
    transport = httpx.ASGITransport(app=fake.app)
    http = httpx.AsyncClient(transport=transport, base_url="http://codewiki.test")
    client = CodeWikiClient(http)
    jobs_store = InMemoryJobStore()
    artifacts = ArtifactStore(tmp_path / "artifacts")
    runner = JobRunner(
        client=client,
        jobs=jobs_store,
        artifacts=artifacts,
        output_root=fake.output_root,
        poll_interval_seconds=POLL_INTERVAL,
        timeout_seconds=timeout_seconds,
    )
    return DocumentationJobService(
        jobs=jobs_store,
        artifacts=artifacts,
        runner=runner,
        client=client,
        base_url="http://codewiki.test",
    )


@pytest.fixture
def job_service(fake_codewiki: FakeCodeWiki, tmp_path: Path) -> DocumentationJobService:
    return _make_service(fake_codewiki, tmp_path)


@pytest.fixture
def codewiki_client(job_service: DocumentationJobService) -> Iterator[TestClient]:
    get_repository_store().clear()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: _CODEWIKI_ENABLED_SETTINGS
    app.dependency_overrides[get_documentation_job_service] = lambda: job_service
    app.dependency_overrides[get_provider] = lambda: CodeWikiProvider(job_service)
    with TestClient(app) as test_client:
        yield test_client
    get_repository_store().clear()


def _create_repository(client: TestClient, owner: str, name: str) -> dict:
    response = client.post(
        f"{API}/repositories", json={"repository_url": f"https://github.com/{owner}/{name}"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_job(client: TestClient, owner: str, name: str) -> dict:
    response = client.post(
        f"{API}/documentation/jobs",
        json={"repository_url": f"https://github.com/{owner}/{name}"},
    )
    assert response.status_code == 202, response.text
    return response.json()


def _wait_for_terminal(client: TestClient, job_id: str, *, timeout: float = DEFAULT_TIMEOUT) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"{API}/documentation/jobs/{job_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] in ("COMPLETED", "FAILED"):
            return body
        time.sleep(POLL_INTERVAL)
    raise AssertionError(f"job {job_id} did not reach a terminal state within {timeout}s")


def _wait_until_submitted(client: TestClient, job_id: str, *, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Block until the background task's own submit() call has landed.

    Tests that drive the fake CodeWiki's job state directly must wait for
    this first — otherwise a test's premature ``complete()``/``fail()`` can
    race the background task's real ``POST /``, which resets a terminal
    entry back to "processing" when it thinks it's picking up a fresh run.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"{API}/documentation/jobs/{job_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] != "SUBMITTING":
            return body
        time.sleep(POLL_INTERVAL)
    raise AssertionError(f"job {job_id} never left SUBMITTING within {timeout}s")


class TestEngineProbe:
    def test_reports_reachable_when_codewiki_is_up(self, codewiki_client: TestClient) -> None:
        response = codewiki_client.get(f"{API}/documentation/engine")

        assert response.status_code == 200
        body = response.json()
        assert body["engine"] == "codewiki"
        assert body["reachable"] is True

    def test_reports_unreachable_when_codewiki_is_down(
        self, codewiki_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        fake_codewiki.set_unreachable(True)

        response = codewiki_client.get(f"{API}/documentation/engine")

        assert response.status_code == 200
        assert response.json()["reachable"] is False


class TestSuccessfulGeneration:
    def test_two_repositories_get_distinct_verified_overviews(
        self, codewiki_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        job_a = _create_job(codewiki_client, "octocat", "Hello-World")
        job_b = _create_job(codewiki_client, "angular", "angular")
        assert job_a["status"] == "SUBMITTING"
        assert job_a["id"] != job_b["id"]

        _wait_until_submitted(codewiki_client, job_a["id"])
        _wait_until_submitted(codewiki_client, job_b["id"])

        fake_codewiki.write_docs("octocat", "Hello-World", overview="# Hello World\n\nRepo A.\n")
        fake_codewiki.complete("octocat", "Hello-World")
        fake_codewiki.write_docs("angular", "angular", overview="# Angular\n\nRepo B.\n")
        fake_codewiki.complete("angular", "angular")

        final_a = _wait_for_terminal(codewiki_client, job_a["id"])
        final_b = _wait_for_terminal(codewiki_client, job_b["id"])

        assert final_a["status"] == "COMPLETED"
        assert final_b["status"] == "COMPLETED"
        assert final_a["overview_available"] is True

        overview_a = codewiki_client.get(f"{API}/documentation/jobs/{job_a['id']}/overview")
        overview_b = codewiki_client.get(f"{API}/documentation/jobs/{job_b['id']}/overview")

        assert overview_a.status_code == 200
        assert overview_a.text == "# Hello World\n\nRepo A.\n"
        assert overview_a.headers["content-type"].startswith("text/markdown")
        assert overview_a.headers["x-codeoops-job-id"] == job_a["id"]
        assert overview_a.headers["x-codeoops-engine"] == "codewiki"

        assert overview_b.text == "# Angular\n\nRepo B.\n"
        assert overview_b.text != overview_a.text

    def test_legacy_repository_documentation_endpoint_is_job_backed(
        self, codewiki_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        repository = _create_repository(codewiki_client, "octocat", "Hello-World")
        job = _create_job(codewiki_client, "octocat", "Hello-World")
        _wait_until_submitted(codewiki_client, job["id"])

        fake_codewiki.write_docs(
            "octocat", "Hello-World", overview="# Overview\n\nContent.\n", metadata={"main_model": "qwen2.5-coder-32k"}
        )
        fake_codewiki.complete("octocat", "Hello-World", main_model="qwen2.5-coder-32k")
        _wait_for_terminal(codewiki_client, job["id"])

        response = codewiki_client.get(
            f"{API}/repositories/{repository['id']}/documentation"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "COMPLETED"
        assert body["artifact"]["entry_document"] == "# Overview\n\nContent.\n"
        assert "qwen2.5-coder-32k" in body["artifact"]["provider"]

    def test_regeneration_keeps_the_older_jobs_own_content(
        self, codewiki_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        """CodeWiki overwrites its own output dir on every run; CodeOops must not."""
        job_1 = _create_job(codewiki_client, "octocat", "Hello-World")
        _wait_until_submitted(codewiki_client, job_1["id"])
        fake_codewiki.write_docs("octocat", "Hello-World", overview="# Version One\n")
        fake_codewiki.complete("octocat", "Hello-World")
        _wait_for_terminal(codewiki_client, job_1["id"])

        job_2 = _create_job(codewiki_client, "octocat", "Hello-World")
        _wait_until_submitted(codewiki_client, job_2["id"])
        # CodeWiki overwrites the same directory in place on a second run.
        fake_codewiki.write_docs("octocat", "Hello-World", overview="# Version Two\n")
        fake_codewiki.complete("octocat", "Hello-World")
        _wait_for_terminal(codewiki_client, job_2["id"])

        overview_1 = codewiki_client.get(f"{API}/documentation/jobs/{job_1['id']}/overview")
        overview_2 = codewiki_client.get(f"{API}/documentation/jobs/{job_2['id']}/overview")

        assert overview_1.text == "# Version One\n"
        assert overview_2.text == "# Version Two\n"

    def test_job_history_lists_both_runs_newest_first(
        self, codewiki_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        repository = _create_repository(codewiki_client, "octocat", "Hello-World")
        job_1 = _create_job(codewiki_client, "octocat", "Hello-World")
        _wait_until_submitted(codewiki_client, job_1["id"])
        fake_codewiki.write_docs("octocat", "Hello-World")
        fake_codewiki.complete("octocat", "Hello-World")
        _wait_for_terminal(codewiki_client, job_1["id"])

        job_2 = _create_job(codewiki_client, "octocat", "Hello-World")
        _wait_until_submitted(codewiki_client, job_2["id"])
        fake_codewiki.write_docs("octocat", "Hello-World")
        fake_codewiki.complete("octocat", "Hello-World")
        _wait_for_terminal(codewiki_client, job_2["id"])

        response = codewiki_client.get(f"{API}/repositories/{repository['id']}/jobs")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert [item["id"] for item in body["items"]] == [job_2["id"], job_1["id"]]

        via_query = codewiki_client.get(
            f"{API}/documentation/jobs", params={"repository_id": repository["id"]}
        )
        assert via_query.json()["total"] == 2


class TestFailurePaths:
    def test_engine_unreachable_fails_the_job(
        self, codewiki_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        fake_codewiki.set_unreachable(True)
        job = _create_job(codewiki_client, "octocat", "Hello-World")

        final = _wait_for_terminal(codewiki_client, job["id"])

        assert final["status"] == "FAILED"
        assert final["error_code"] == "CODEWIKI_UNREACHABLE"

    def test_submission_rejected_fails_the_job(
        self, codewiki_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        fake_codewiki.set_reject_submissions(True)
        job = _create_job(codewiki_client, "octocat", "Hello-World")

        final = _wait_for_terminal(codewiki_client, job["id"])

        assert final["status"] == "FAILED"
        assert final["error_code"] == "CODEWIKI_SUBMIT_REJECTED"

    def test_codewiki_reported_failure_propagates(
        self, codewiki_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        job = _create_job(codewiki_client, "octocat", "Hello-World")
        _wait_until_submitted(codewiki_client, job["id"])
        fake_codewiki.fail("octocat", "Hello-World", "the model produced invalid output")

        final = _wait_for_terminal(codewiki_client, job["id"])

        assert final["status"] == "FAILED"
        assert final["error_code"] == "CODEWIKI_FAILED"
        assert "invalid output" in final["error_message"]

    def test_completion_without_docs_path_fails_cleanly(
        self, codewiki_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        job = _create_job(codewiki_client, "octocat", "Hello-World")
        _wait_until_submitted(codewiki_client, job["id"])
        fake_codewiki.complete_without_docs_path("octocat", "Hello-World")

        final = _wait_for_terminal(codewiki_client, job["id"])

        assert final["status"] == "FAILED"
        assert final["error_code"] == "DOCS_PATH_MISSING"

    def test_artifact_directory_missing_entirely(
        self, codewiki_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        job = _create_job(codewiki_client, "octocat", "Hello-World")
        _wait_until_submitted(codewiki_client, job["id"])
        # complete() points at a docs dir that was never created on disk.
        fake_codewiki.complete("octocat", "Hello-World")

        final = _wait_for_terminal(codewiki_client, job["id"])

        assert final["status"] == "FAILED"
        assert final["error_code"] == "ARTIFACT_DIR_NOT_FOUND"

    def test_missing_overview_file(
        self, codewiki_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        job = _create_job(codewiki_client, "octocat", "Hello-World")
        _wait_until_submitted(codewiki_client, job["id"])
        fake_codewiki.write_docs("octocat", "Hello-World", skip_overview=True)
        fake_codewiki.complete("octocat", "Hello-World")

        final = _wait_for_terminal(codewiki_client, job["id"])

        assert final["status"] == "FAILED"
        assert final["error_code"] == "OVERVIEW_NOT_FOUND"

    def test_empty_overview_file(
        self, codewiki_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        job = _create_job(codewiki_client, "octocat", "Hello-World")
        _wait_until_submitted(codewiki_client, job["id"])
        fake_codewiki.write_docs("octocat", "Hello-World", overview="   \n\n  ")
        fake_codewiki.complete("octocat", "Hello-World")

        final = _wait_for_terminal(codewiki_client, job["id"])

        assert final["status"] == "FAILED"
        assert final["error_code"] == "OVERVIEW_EMPTY"

    def test_missing_metadata_file(
        self, codewiki_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        job = _create_job(codewiki_client, "octocat", "Hello-World")
        _wait_until_submitted(codewiki_client, job["id"])
        fake_codewiki.write_docs("octocat", "Hello-World", skip_metadata=True)
        fake_codewiki.complete("octocat", "Hello-World")

        final = _wait_for_terminal(codewiki_client, job["id"])

        assert final["status"] == "FAILED"
        assert final["error_code"] == "METADATA_NOT_FOUND"

    def test_artifact_belonging_to_another_repository_is_refused(
        self, codewiki_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        job = _create_job(codewiki_client, "octocat", "Hello-World")
        _wait_until_submitted(codewiki_client, job["id"])
        fake_codewiki.write_docs(
            "octocat",
            "Hello-World",
            metadata={"repo_path": "output/temp/someone-else--other-repo"},
        )
        fake_codewiki.complete("octocat", "Hello-World")

        final = _wait_for_terminal(codewiki_client, job["id"])

        assert final["status"] == "FAILED"
        assert final["error_code"] == "ARTIFACT_BINDING_MISMATCH"

    def test_stale_codewiki_state_is_never_adopted(
        self, fake_codewiki: FakeCodeWiki, tmp_path: Path
    ) -> None:
        """The anti-stale guard: a CodeWiki that never picks up the new run
        must not have its old, already-completed entry adopted as fresh."""
        fake_codewiki.write_docs("octocat", "Hello-World", overview="# Stale\n")
        fake_codewiki.seed_completed("octocat", "Hello-World")
        fake_codewiki.freeze("octocat", "Hello-World")

        service = _make_service(fake_codewiki, tmp_path, timeout_seconds=0.3)
        app = create_app()
        app.dependency_overrides[get_settings] = lambda: _CODEWIKI_ENABLED_SETTINGS
        app.dependency_overrides[get_documentation_job_service] = lambda: service
        get_repository_store().clear()

        with TestClient(app) as client:
            job = _create_job(client, "octocat", "Hello-World")
            final = _wait_for_terminal(client, job["id"], timeout=2.0)

        get_repository_store().clear()

        assert final["status"] == "FAILED"
        assert final["error_code"] == "CODEWIKI_JOB_NOT_FOUND"

    def test_overview_not_available_before_completion(
        self, codewiki_client: TestClient
    ) -> None:
        job = _create_job(codewiki_client, "octocat", "Hello-World")

        response = codewiki_client.get(f"{API}/documentation/jobs/{job['id']}/overview")

        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "DOCUMENTATION_NOT_AVAILABLE"
        assert "job_status" in error["details"]

    def test_unknown_job_id_is_404(self, codewiki_client: TestClient) -> None:
        response = codewiki_client.get(f"{API}/documentation/jobs/{uuid.uuid4()}")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "JOB_NOT_FOUND"

    def test_jobs_for_unknown_repository_is_404(self, codewiki_client: TestClient) -> None:
        response = codewiki_client.get(
            f"{API}/documentation/jobs", params={"repository_id": str(uuid.uuid4())}
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"


class TestNoProviderConfigured:
    """The job API must fail loudly and synchronously when unconfigured —
    never create a job that's doomed to fail against an unset CodeWiki URL."""

    def test_job_creation_is_rejected_without_a_configured_engine(
        self, client: TestClient
    ) -> None:
        response = client.post(
            f"{API}/documentation/jobs",
            json={"repository_url": "https://github.com/octocat/Hello-World"},
        )

        assert response.status_code == 501
        assert response.json()["error"]["code"] == "DOCUMENTATION_PROVIDER_NOT_CONFIGURED"

    def test_engine_probe_reports_unreachable_without_a_configured_url(
        self, client: TestClient
    ) -> None:
        response = client.get(f"{API}/documentation/engine")

        assert response.status_code == 200
        assert response.json()["reachable"] is False
