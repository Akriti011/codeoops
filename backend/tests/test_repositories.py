import uuid

import pytest
from fastapi.testclient import TestClient

from tests.conftest import API, VALID_REPO_URL


class TestCreateRepository:
    def test_accepts_a_valid_github_url(self, client: TestClient) -> None:
        response = client.post(
            f"{API}/repositories", json={"repository_url": VALID_REPO_URL}
        )

        assert response.status_code == 201, response.text
        body = response.json()
        uuid.UUID(body["id"])  # stable application-level identifier
        assert body["owner"] == "octocat"
        assert body["name"] == "Hello-World"
        assert body["repository_url"] == "https://github.com/octocat/Hello-World"
        assert body["status"] == "READY"
        assert body["default_branch"]
        assert body["created_at"] and body["updated_at"]

    def test_normalises_git_suffix_and_trailing_slash(self, client: TestClient) -> None:
        response = client.post(
            f"{API}/repositories",
            json={"repository_url": "https://github.com/octocat/Hello-World.git/"},
        )

        assert response.status_code == 201, response.text
        assert response.json()["repository_url"] == (
            "https://github.com/octocat/Hello-World"
        )

    def test_resubmitting_returns_the_same_stable_id(self, client: TestClient) -> None:
        first = client.post(
            f"{API}/repositories", json={"repository_url": VALID_REPO_URL}
        )
        second = client.post(
            f"{API}/repositories", json={"repository_url": f"{VALID_REPO_URL}.git"}
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

        listing = client.get(f"{API}/repositories").json()
        assert listing["total"] == 1

    @pytest.mark.parametrize(
        "bad_url",
        [
            "",
            "   ",
            "not-a-url",
            "github.com/octocat/Hello-World",
            "http://github.com/octocat/Hello-World",
            "ftp://github.com/octocat/Hello-World",
            "ssh://git@github.com/octocat/Hello-World",
            "file:///etc/passwd",
            "https://gitlab.com/octocat/Hello-World",
            "https://bitbucket.org/octocat/Hello-World",
            "https://user:secret@github.com/octocat/Hello-World",
            "https://github.com:8080/octocat/Hello-World",
            "https://github.com/octocat",
            "https://github.com/",
            "https://github.com/octocat/Hello-World/tree/main/src",
            "https://github.com/../../etc/passwd",
            "https://169.254.169.254/latest/meta-data",
        ],
    )
    def test_rejects_invalid_repository_urls(
        self, client: TestClient, bad_url: str
    ) -> None:
        response = client.post(f"{API}/repositories", json={"repository_url": bad_url})

        assert response.status_code == 422, f"{bad_url} was accepted"
        error = response.json()["error"]
        assert error["code"] in {
            "INVALID_REPOSITORY_URL",
            "REQUEST_VALIDATION_ERROR",
        }
        assert error["message"]

    def test_rejects_a_missing_body_field(self, client: TestClient) -> None:
        response = client.post(f"{API}/repositories", json={})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"


class TestGetRepository:
    def test_returns_a_known_repository(
        self, client: TestClient, created_repository: dict
    ) -> None:
        response = client.get(f"{API}/repositories/{created_repository['id']}")

        assert response.status_code == 200
        assert response.json() == created_repository

    def test_returns_404_for_an_unknown_id(self, client: TestClient) -> None:
        response = client.get(f"{API}/repositories/{uuid.uuid4()}")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"

    def test_returns_422_for_a_malformed_id(self, client: TestClient) -> None:
        response = client.get(f"{API}/repositories/not-a-uuid")

        assert response.status_code == 422


class TestListRepositories:
    def test_is_empty_initially(self, client: TestClient) -> None:
        response = client.get(f"{API}/repositories")

        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}

    def test_lists_submitted_repositories_newest_first(
        self, client: TestClient
    ) -> None:
        for url in (
            "https://github.com/octocat/Hello-World",
            "https://github.com/angular/angular",
            "https://github.com/fastapi/fastapi",
        ):
            assert (
                client.post(f"{API}/repositories", json={"repository_url": url})
            ).status_code == 201

        body = client.get(f"{API}/repositories").json()

        assert body["total"] == 3
        assert [item["name"] for item in body["items"]] == [
            "fastapi",
            "angular",
            "Hello-World",
        ]
