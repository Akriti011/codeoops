from fastapi.testclient import TestClient

from tests.conftest import API


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get(f"{API}/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"]
    assert body["version"]
