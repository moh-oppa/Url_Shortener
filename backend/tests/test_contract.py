"""The contract these tests lock down is the deliverable of phase 0.

Handlers return 501 for now. A 501 here means validation passed and routing
worked -- which is exactly what we want to assert before writing logic.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

VALID = {"target_url": "https://example.com/some/path?a=1"}


def test_valid_payload_reaches_the_handler(client: TestClient) -> None:
    r = client.post("/api/links", json=VALID)
    assert r.status_code == 501


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


def test_future_expiry_is_accepted(client: TestClient) -> None:
    payload = {**VALID, "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat()}
    assert client.post("/api/links", json=payload).status_code == 501


def test_catch_all_does_not_shadow_real_routes(client: TestClient) -> None:
    # If GET /{code} were registered first, these would all 404 or 501.
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/api/links/abc123/stats").status_code == 501


def test_reserved_codes_are_not_redirect_candidates(client: TestClient) -> None:
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 404


def test_unknown_code_reaches_redirect_handler(client: TestClient) -> None:
    r = client.get("/abc1234", follow_redirects=False)
    assert r.status_code == 501


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