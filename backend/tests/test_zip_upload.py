"""Tests for ZIP-file repository ingestion.

Two layers:

- ``TestZipIngestion*``: pure unit tests of ``app.services.uploads.zip_ingestion``
  (validation/extraction/root-detection), no HTTP, no CodeWiki.
- ``TestUploadRoute*`` / ``TestUploadJobPipeline*``: drive the real CodeOops
  API against ``tests.support.fake_codewiki.FakeCodeWiki``, exactly like
  ``test_codewiki_integration.py`` — proving an uploaded ZIP converges onto
  the exact same job pipeline (JobRunner, polling, artifact binding) a
  GitHub submission uses, with only the ingestion boundary differing.
"""

from __future__ import annotations

import io
import time
import uuid
import zipfile
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_documentation_job_service, get_provider, get_repository_store
from app.core.config import Settings, get_settings
from app.core.errors import (
    ArchiveTooLargeError,
    EmptyRepositoryError,
    InvalidArchiveError,
    UnsafeArchiveError,
)
from app.main import create_app
from app.providers.codewiki_provider import CodeWikiProvider
from app.repositories.job_repository import InMemoryJobStore
from app.services.codewiki.client import CodeWikiClient
from app.services.documentation.artifact_store import ArtifactStore
from app.services.documentation.job_service import DocumentationJobService
from app.services.jobs.job_runner import JobRunner
from app.services.uploads.zip_ingestion import ZipIngestionLimits, validate_and_extract
from tests.conftest import API
from tests.support.fake_codewiki import FakeCodeWiki

POLL_INTERVAL = 0.02
DEFAULT_TIMEOUT = 3.0

_CODEWIKI_ENABLED_SETTINGS = Settings(
    documentation_provider="codewiki",
    codewiki_base_url="http://codewiki.test",
    codewiki_output_root="/tmp/does-not-matter",  # overridden per-test via output_root below
)

_GENEROUS_LIMITS = ZipIngestionLimits(
    max_archive_bytes=10 * 1024 * 1024,
    max_extracted_bytes=50 * 1024 * 1024,
    max_file_count=10_000,
)


# --- ZIP-building helpers -----------------------------------------------


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _zip_with_symlink() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("README.md", "# hi\n")
        info = zipfile.ZipInfo("evil_link")
        info.external_attr = (0o120777) << 16  # S_IFLNK
        zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


# --- Unit tests: zip_ingestion.validate_and_extract ----------------------


class TestZipIngestionValidExtraction:
    def test_files_directly_at_root_become_the_repository_root(self, tmp_path: Path) -> None:
        archive = tmp_path / "upload.zip"
        archive.write_bytes(_zip_bytes({"src/main.py": "print(1)\n", "README.md": "# x\n"}))

        result = validate_and_extract(archive, tmp_path / "repo", _GENEROUS_LIMITS)

        assert result.repo_root == tmp_path / "repo"
        assert (result.repo_root / "src" / "main.py").is_file()
        assert result.file_count == 2

    def test_single_top_level_directory_is_detected_as_repository_root(
        self, tmp_path: Path
    ) -> None:
        archive = tmp_path / "upload.zip"
        archive.write_bytes(
            _zip_bytes({"my-project/src/main.py": "print(1)\n", "my-project/pom.xml": "<x/>\n"})
        )

        result = validate_and_extract(archive, tmp_path / "repo", _GENEROUS_LIMITS)

        assert result.repo_root == tmp_path / "repo" / "my-project"
        assert result.repo_root.name == "my-project"
        assert (result.repo_root / "pom.xml").is_file()
        assert result.file_count == 2

    def test_macos_metadata_directory_does_not_defeat_root_detection(self, tmp_path: Path) -> None:
        archive = tmp_path / "upload.zip"
        archive.write_bytes(
            _zip_bytes(
                {
                    "my-project/main.py": "print(1)\n",
                    "__MACOSX/my-project/._main.py": "\x00",
                }
            )
        )

        result = validate_and_extract(archive, tmp_path / "repo", _GENEROUS_LIMITS)

        assert result.repo_root.name == "my-project"

    def test_multilingual_repository_extracts_every_file(self, tmp_path: Path) -> None:
        archive = tmp_path / "upload.zip"
        archive.write_bytes(
            _zip_bytes(
                {
                    "proj/app.py": "print(1)\n",
                    "proj/Main.java": "class Main {}\n",
                    "proj/script.sh": "#!/bin/sh\necho hi\n",
                    "proj/schema.sql": "SELECT 1;\n",
                    "proj/job.scala": "object Job\n",
                    "proj/config.yaml": "key: value\n",
                    "proj/pom.xml": "<project/>\n",
                    "proj/data.json": "{}\n",
                    "proj/README.md": "# proj\n",
                }
            )
        )

        result = validate_and_extract(archive, tmp_path / "repo", _GENEROUS_LIMITS)

        assert result.file_count == 9
        assert (result.repo_root / "Main.java").is_file()
        assert (result.repo_root / "job.scala").is_file()


class TestZipIngestionRejections:
    def test_malformed_archive_is_rejected(self, tmp_path: Path) -> None:
        archive = tmp_path / "upload.zip"
        archive.write_bytes(b"this is not a zip file at all")

        with pytest.raises(InvalidArchiveError):
            validate_and_extract(archive, tmp_path / "repo", _GENEROUS_LIMITS)

    def test_path_traversal_entry_is_rejected(self, tmp_path: Path) -> None:
        archive = tmp_path / "upload.zip"
        archive.write_bytes(_zip_bytes({"../../etc/passwd": "pwned\n"}))

        with pytest.raises(UnsafeArchiveError):
            validate_and_extract(archive, tmp_path / "repo", _GENEROUS_LIMITS)

    def test_absolute_path_entry_is_rejected(self, tmp_path: Path) -> None:
        archive = tmp_path / "upload.zip"
        archive.write_bytes(_zip_bytes({"/etc/passwd": "pwned\n"}))

        with pytest.raises(UnsafeArchiveError):
            validate_and_extract(archive, tmp_path / "repo", _GENEROUS_LIMITS)

    def test_symlink_entry_is_rejected(self, tmp_path: Path) -> None:
        archive = tmp_path / "upload.zip"
        archive.write_bytes(_zip_with_symlink())

        with pytest.raises(UnsafeArchiveError):
            validate_and_extract(archive, tmp_path / "repo", _GENEROUS_LIMITS)

    def test_oversized_compressed_archive_is_rejected(self, tmp_path: Path) -> None:
        archive = tmp_path / "upload.zip"
        archive.write_bytes(_zip_bytes({"a.txt": "x" * 1000}))
        tiny_limits = ZipIngestionLimits(
            max_archive_bytes=10, max_extracted_bytes=10_000, max_file_count=100
        )

        with pytest.raises(ArchiveTooLargeError):
            validate_and_extract(archive, tmp_path / "repo", tiny_limits)

    def test_excessive_extracted_size_is_rejected(self, tmp_path: Path) -> None:
        archive = tmp_path / "upload.zip"
        archive.write_bytes(_zip_bytes({"a.txt": "x" * 10_000}))
        tight_limits = ZipIngestionLimits(
            max_archive_bytes=10 * 1024 * 1024, max_extracted_bytes=100, max_file_count=100
        )

        with pytest.raises(ArchiveTooLargeError):
            validate_and_extract(archive, tmp_path / "repo", tight_limits)

    def test_excessive_file_count_is_rejected(self, tmp_path: Path) -> None:
        archive = tmp_path / "upload.zip"
        archive.write_bytes(_zip_bytes({f"file_{i}.txt": "x" for i in range(50)}))
        tight_limits = ZipIngestionLimits(
            max_archive_bytes=10 * 1024 * 1024, max_extracted_bytes=10 * 1024 * 1024, max_file_count=10
        )

        with pytest.raises(ArchiveTooLargeError):
            validate_and_extract(archive, tmp_path / "repo", tight_limits)

    def test_empty_archive_is_rejected(self, tmp_path: Path) -> None:
        archive = tmp_path / "upload.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w"):
            pass
        archive.write_bytes(buf.getvalue())

        with pytest.raises(EmptyRepositoryError):
            validate_and_extract(archive, tmp_path / "repo", _GENEROUS_LIMITS)

    def test_archive_of_only_empty_directories_is_rejected_as_empty_repository(
        self, tmp_path: Path
    ) -> None:
        archive = tmp_path / "upload.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("empty_dir/", "")
        archive.write_bytes(buf.getvalue())

        with pytest.raises(EmptyRepositoryError):
            validate_and_extract(archive, tmp_path / "repo", _GENEROUS_LIMITS)


# --- HTTP-level upload route tests ---------------------------------------


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
def upload_client(
    job_service: DocumentationJobService, fake_codewiki: FakeCodeWiki
) -> Iterator[TestClient]:
    """Same shape as test_codewiki_integration's codewiki_client, but with
    codewiki_output_root pointed at the fake's own output_root — required
    for the upload route (it extracts under codewiki_output_root/uploads/)."""
    settings = Settings(
        documentation_provider="codewiki",
        codewiki_base_url="http://codewiki.test",
        codewiki_output_root=str(fake_codewiki.output_root),
    )
    get_repository_store().clear()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_documentation_job_service] = lambda: job_service
    app.dependency_overrides[get_provider] = lambda: CodeWikiProvider(job_service)
    with TestClient(app) as test_client:
        yield test_client
    get_repository_store().clear()


def _upload(
    client: TestClient, entries: dict[str, str], *, filename: str = "upload.zip"
) -> httpx.Response:
    content = _zip_bytes(entries)
    return client.post(
        f"{API}/repositories/upload",
        files={"file": (filename, content, "application/zip")},
    )


class TestUploadRoute:
    def test_valid_upload_creates_an_upload_source_repository(
        self, upload_client: TestClient
    ) -> None:
        response = _upload(
            upload_client,
            {"my-project/src/main.py": "print(1)\n", "my-project/README.md": "# hi\n"},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["source"] == "UPLOAD"
        assert body["name"] == "my-project"
        assert body["upload_file_count"] == 2
        assert body["upload_total_bytes"] > 0
        assert body["upload_original_filename"] == "upload.zip"

    def test_upload_with_root_files_registers_successfully(self, upload_client: TestClient) -> None:
        response = _upload(
            upload_client, {"index.js": "console.log(1);\n"}, filename="frontend-app.zip"
        )

        assert response.status_code == 201, response.text
        body = response.json()
        # No single wrapping directory — the project name falls back to the
        # uploaded filename rather than the meaningless extraction dir name.
        assert body["name"] == "frontend-app"

    def test_malformed_zip_is_rejected(self, upload_client: TestClient) -> None:
        response = upload_client.post(
            f"{API}/repositories/upload",
            files={"file": ("upload.zip", b"not a real zip", "application/zip")},
        )

        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "INVALID_ARCHIVE"

    def test_path_traversal_attempt_is_rejected_over_http(self, upload_client: TestClient) -> None:
        response = _upload(upload_client, {"../../etc/passwd": "pwned\n"})

        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "UNSAFE_ARCHIVE"

    def test_oversized_archive_is_rejected_over_http(self, fake_codewiki: FakeCodeWiki) -> None:
        settings = Settings(
            documentation_provider="codewiki",
            codewiki_base_url="http://codewiki.test",
            codewiki_output_root=str(fake_codewiki.output_root),
            upload_max_archive_bytes=50,
        )
        get_repository_store().clear()
        app = create_app()
        app.dependency_overrides[get_settings] = lambda: settings
        with TestClient(app) as client:
            response = _upload(client, {"a.txt": "x" * 1000})
        get_repository_store().clear()

        assert response.status_code == 413, response.text
        assert response.json()["error"]["code"] == "ARCHIVE_TOO_LARGE"

    def test_empty_repository_is_rejected_over_http(self, upload_client: TestClient) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w"):
            pass
        response = upload_client.post(
            f"{API}/repositories/upload",
            files={"file": ("upload.zip", buf.getvalue(), "application/zip")},
        )

        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "EMPTY_REPOSITORY"

    def test_upload_without_configured_provider_is_rejected(self, client: TestClient) -> None:
        response = _upload(client, {"a.py": "print(1)\n"})

        assert response.status_code == 501, response.text
        assert response.json()["error"]["code"] == "DOCUMENTATION_PROVIDER_NOT_CONFIGURED"

    def test_two_uploads_produce_two_separate_repositories(self, upload_client: TestClient) -> None:
        first = _upload(upload_client, {"proj/main.py": "print(1)\n"})
        second = _upload(upload_client, {"proj/main.py": "print(1)\n"})  # identical content

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] != second.json()["id"]

        first_repo = Path(_workspace_path(upload_client, first.json()["id"]))
        second_repo = Path(_workspace_path(upload_client, second.json()["id"]))
        assert first_repo != second_repo
        assert first_repo.is_dir()
        assert second_repo.is_dir()


def _workspace_path(client: TestClient, repository_id: str) -> str:
    """Peek at the underlying store to read the (response-hidden) workspace path."""
    store = get_repository_store()
    repository = store.get(uuid.UUID(repository_id))
    assert repository is not None
    assert repository.upload_workspace_path is not None
    return repository.upload_workspace_path


# --- Full pipeline: upload -> CodeWiki -> artifact -----------------------


class TestUploadJobPipeline:
    def test_upload_then_job_creation_invokes_codewikis_local_job_endpoint(
        self, upload_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        repository = _upload(
            upload_client, {"proj/main.py": "print(1)\n", "proj/README.md": "# proj\n"}
        ).json()

        response = upload_client.post(
            f"{API}/documentation/jobs", json={"repository_id": repository["id"]}
        )
        assert response.status_code == 202, response.text
        job = response.json()
        assert job["status"] == "SUBMITTING"

        codewiki_job_id = _wait_until_local_job_seen(fake_codewiki, timeout=DEFAULT_TIMEOUT)
        assert codewiki_job_id == f"upload--{repository['id']}"
        assert fake_codewiki._jobs[codewiki_job_id].repo_url.startswith("local:")

    def test_artifact_is_retrieved_and_bound_for_an_uploaded_repository(
        self, upload_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        repository = _upload(upload_client, {"proj/main.py": "print(1)\n"}).json()
        codewiki_job_id = f"upload--{repository['id']}"

        job = upload_client.post(
            f"{API}/documentation/jobs", json={"repository_id": repository["id"]}
        ).json()
        _wait_until_local_job_seen(fake_codewiki, timeout=DEFAULT_TIMEOUT)

        fake_codewiki.write_docs_for_job_id(
            codewiki_job_id,
            overview="# proj\n\nA tiny uploaded project.\n",
            metadata={"repo_path": f"output/temp/{codewiki_job_id}"},
        )
        fake_codewiki.complete_job_id(codewiki_job_id)

        final = _wait_for_terminal(upload_client, job["id"])
        assert final["status"] == "COMPLETED"
        assert final["overview_available"] is True

        overview = upload_client.get(f"{API}/documentation/jobs/{job['id']}/overview")
        assert overview.status_code == 200
        assert overview.text == "# proj\n\nA tiny uploaded project.\n"

    def test_artifact_bound_to_a_different_repository_is_refused(
        self, upload_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        repository = _upload(upload_client, {"proj/main.py": "print(1)\n"}).json()
        codewiki_job_id = f"upload--{repository['id']}"

        job = upload_client.post(
            f"{API}/documentation/jobs", json={"repository_id": repository["id"]}
        ).json()
        _wait_until_local_job_seen(fake_codewiki, timeout=DEFAULT_TIMEOUT)

        # metadata.json claims a repo_path belonging to some other job entirely.
        fake_codewiki.write_docs_for_job_id(
            codewiki_job_id, metadata={"repo_path": "output/temp/upload--not-this-repository"}
        )
        fake_codewiki.complete_job_id(codewiki_job_id)

        final = _wait_for_terminal(upload_client, job["id"])
        assert final["status"] == "FAILED"
        assert final["error_code"] == "ARTIFACT_BINDING_MISMATCH"

    def test_regenerating_an_uploaded_repository_reuses_its_workspace(
        self, upload_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        repository = _upload(upload_client, {"proj/main.py": "print(1)\n"}).json()
        codewiki_job_id = f"upload--{repository['id']}"

        job_1 = upload_client.post(
            f"{API}/documentation/jobs", json={"repository_id": repository["id"]}
        ).json()
        _wait_until_local_job_seen(fake_codewiki, timeout=DEFAULT_TIMEOUT)
        fake_codewiki.write_docs_for_job_id(codewiki_job_id, overview="# Version One\n")
        fake_codewiki.complete_job_id(codewiki_job_id)
        _wait_for_terminal(upload_client, job_1["id"])

        job_2 = upload_client.post(
            f"{API}/documentation/jobs", json={"repository_id": repository["id"]}
        ).json()
        assert job_2["id"] != job_1["id"]
        # Same underlying CodeWiki job id — regeneration of the same upload,
        # not a brand-new one.
        _wait_until_local_job_seen(fake_codewiki, timeout=DEFAULT_TIMEOUT)
        fake_codewiki.write_docs_for_job_id(codewiki_job_id, overview="# Version Two\n")
        fake_codewiki.complete_job_id(codewiki_job_id)
        final_2 = _wait_for_terminal(upload_client, job_2["id"])

        assert final_2["status"] == "COMPLETED"
        overview_1 = upload_client.get(f"{API}/documentation/jobs/{job_1['id']}/overview")
        overview_2 = upload_client.get(f"{API}/documentation/jobs/{job_2['id']}/overview")
        assert overview_1.text == "# Version One\n"
        assert overview_2.text == "# Version Two\n"

    def test_github_and_upload_repositories_use_the_identical_job_endpoint(
        self, upload_client: TestClient, fake_codewiki: FakeCodeWiki
    ) -> None:
        """Both input modes converge on one POST /documentation/jobs contract
        and one JobResponse shape — the "single generation pipeline" requirement."""
        github_job = upload_client.post(
            f"{API}/documentation/jobs",
            json={"repository_url": "https://github.com/octocat/Hello-World"},
        )
        repository = _upload(upload_client, {"proj/main.py": "print(1)\n"}).json()
        upload_job = upload_client.post(
            f"{API}/documentation/jobs", json={"repository_id": repository["id"]}
        )

        assert github_job.status_code == 202
        assert upload_job.status_code == 202
        assert set(github_job.json().keys()) == set(upload_job.json().keys())
        assert github_job.json()["status"] == upload_job.json()["status"] == "SUBMITTING"
        assert github_job.json()["provider"] == upload_job.json()["provider"] == "codewiki"

    def test_job_creation_requires_exactly_one_of_url_or_id(self, upload_client: TestClient) -> None:
        both = upload_client.post(
            f"{API}/documentation/jobs",
            json={
                "repository_url": "https://github.com/octocat/Hello-World",
                "repository_id": str(uuid.uuid4()),
            },
        )
        neither = upload_client.post(f"{API}/documentation/jobs", json={})

        assert both.status_code == 422
        assert neither.status_code == 422


def _wait_until_local_job_seen(
    fake: FakeCodeWiki, *, timeout: float = DEFAULT_TIMEOUT
) -> str:
    """Block until the background submit() call reaches the fake, return its job id."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        upload_ids = [job_id for job_id in fake._jobs if job_id.startswith("upload--")]
        if upload_ids:
            return upload_ids[0]
        time.sleep(POLL_INTERVAL)
    raise AssertionError("no local-job submission reached the fake CodeWiki in time")


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
