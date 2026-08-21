"""Shared test fixtures."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.deps import get_repository_store  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.repositories.job_repository import get_job_store  # noqa: E402

API = get_settings().api_prefix

VALID_REPO_URL = "https://github.com/octocat/Hello-World"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient over a fresh application with empty repository/job stores."""
    get_repository_store().clear()
    get_job_store().clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_repository_store().clear()
    get_job_store().clear()


@pytest.fixture
def created_repository(client: TestClient) -> dict:
    response = client.post(f"{API}/repositories", json={"repository_url": VALID_REPO_URL})
    assert response.status_code == 201, response.text
    return response.json()
