from fastapi.testclient import TestClient


def test_liveness_does_not_touch_dependencies(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readiness_reports_degraded_instead_of_raising(client: TestClient) -> None:
    # Neither Postgres nor Redis is running. Readiness must still answer.
    r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["postgres"] is False
    assert body["redis"] is False