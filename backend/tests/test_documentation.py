"""Documentation state must be honest: nothing exists, and we say so."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.errors import DocumentationProviderNotConfiguredError
from app.models.repository import Repository
from app.providers.documentation_provider import get_documentation_provider
from app.services.documentation_service import DocumentationService
from tests.conftest import API


def test_documentation_is_not_generated_when_no_artifact_exists(
    client: TestClient, created_repository: dict
) -> None:
    response = client.get(
        f"{API}/repositories/{created_repository['id']}/documentation"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["repository_id"] == created_repository["id"]
    assert body["status"] == "NOT_GENERATED"
    assert body["artifact"] is None
    assert body["detail"]


def test_documentation_response_carries_no_document_content(
    client: TestClient, created_repository: dict
) -> None:
    """Guards the core product rule: no substitute documentation, ever."""
    response = client.get(
        f"{API}/repositories/{created_repository['id']}/documentation"
    )

    assert set(response.json()) == {"repository_id", "status", "artifact", "detail"}
    payload = response.text.lower()
    for forbidden in ("# ", "```", "overview.md", "## architecture"):
        assert forbidden not in payload


def test_documentation_for_unknown_repository_is_404(client: TestClient) -> None:
    response = client.get(f"{API}/repositories/{uuid.uuid4()}/documentation")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"


def test_no_documentation_provider_is_registered() -> None:
    """The CodeWiki boundary exists but is intentionally unwired."""
    assert get_documentation_provider() is None


@pytest.mark.anyio
async def test_requesting_generation_fails_loudly_without_a_provider() -> None:
    service = DocumentationService(provider=None)
    repository = Repository(
        owner="octocat",
        name="Hello-World",
        repository_url="https://github.com/octocat/Hello-World",
        default_branch="main",
    )

    with pytest.raises(DocumentationProviderNotConfiguredError):
        await service.request_generation(repository)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
