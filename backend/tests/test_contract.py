from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

VALID = {"target_url": "https://example.com/some/path?a=1"}


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ({"target_url": "javascript:alert(1)"}, "dangerous scheme"),
        ({"target_url": "not-a-url"}, "not a url"),
        ({}, "missing target_url"),
        ({**VALID, "custom_alias": "ab"}, "alias too short"),
        ({**VALID, "custom_alias": "has spaces"}, "illegal characters"),
        ({**VALID, "custom_alias": "a" * 33}, "alias too long"),
        ({**VALID, "custom_alias": "api"}, "reserved alias"),
        ({**VALID, "custom_alias": "docs"}, "reserved alias"),
        (
            {**VALID, "expires_at": (datetime.now(UTC) - timedelta(days=1)).isoformat()},
            "expiry in the past",
        ),
    ],
)
def test_invalid_payloads_are_rejected(client: TestClient, payload: dict, why: str) -> None:
    r = client.post("/api/links", json=payload)
    assert r.status_code == 422, f"should reject: {why}"


def test_catch_all_does_not_shadow_real_routes(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_reserved_codes_are_not_redirect_candidates(client: TestClient) -> None:
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 404


def test_openapi_pins_the_surface(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths) >= {
        "/api/links",
        "/api/links/{code}",
        "/api/links/{code}/stats",
        "/{code}",
        "/health",
        "/health/ready",
    }
