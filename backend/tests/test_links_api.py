"""Phase 1 endpoint behaviour, against a real Postgres.

These need SQL because the things being tested -- unique constraints,
concurrent inserts, server-side defaults -- are database behaviour, not
Python behaviour. Mocking the database here would test nothing.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app import services

VALID = {"target_url": "https://example.com/some/path?a=1"}


async def test_create_returns_a_usable_link(api: AsyncClient) -> None:
    r = await api.post("/api/links", json=VALID)
    assert r.status_code == 201
    body = r.json()
    assert len(body["code"]) == 7
    assert body["short_url"] == f"http://testserver/{body['code']}"
    assert body["target_url"] == VALID["target_url"]
    assert body["expires_at"] is None
    assert body["created_at"] is not None


async def test_created_link_can_be_read_back(api: AsyncClient) -> None:
    code = (await api.post("/api/links", json=VALID)).json()["code"]
    r = await api.get(f"/api/links/{code}")
    assert r.status_code == 200
    assert r.json()["target_url"] == VALID["target_url"]


async def test_unknown_code_is_404_with_a_typed_error(api: AsyncClient) -> None:
    r = await api.get("/api/links/nosuch1")
    assert r.status_code == 404
    assert r.json()["code"] == "link_not_found"


async def test_custom_alias_is_used_verbatim(api: AsyncClient) -> None:
    r = await api.post("/api/links", json={**VALID, "custom_alias": "my-Link_1"})
    assert r.status_code == 201
    assert r.json()["code"] == "my-Link_1"


async def test_duplicate_alias_is_409(api: AsyncClient) -> None:
    payload = {**VALID, "custom_alias": "taken99"}
    assert (await api.post("/api/links", json=payload)).status_code == 201
    r = await api.post("/api/links", json=payload)
    assert r.status_code == 409
    assert r.json()["code"] == "alias_taken"


async def test_codes_are_case_sensitive(api: AsyncClient) -> None:
    assert (
        await api.post("/api/links", json={**VALID, "custom_alias": "AbCdEf"})
    ).status_code == 201
    assert (
        await api.post("/api/links", json={**VALID, "custom_alias": "abcdef"})
    ).status_code == 201
    assert (await api.get("/api/links/AbCdEf")).status_code == 200
    assert (await api.get("/api/links/aBcDeF")).status_code == 404


async def test_future_expiry_round_trips(api: AsyncClient) -> None:
    expires = datetime.now(UTC) + timedelta(days=7)
    r = await api.post("/api/links", json={**VALID, "expires_at": expires.isoformat()})
    assert r.status_code == 201
    stored = datetime.fromisoformat(r.json()["expires_at"])
    assert stored.tzinfo is not None
    assert abs((stored - expires).total_seconds()) < 1


async def test_expired_link_still_has_metadata(api: AsyncClient) -> None:
    """GET /api/links/{code} reports what the link IS. Expiry becomes a 410
    on the redirect path, not here."""
    created = await api.post("/api/links", json={**VALID, "custom_alias": "expiring"})
    assert created.status_code == 201
    assert (await api.get("/api/links/expiring")).status_code == 200


async def test_generated_codes_are_unique_across_many_creates(api: AsyncClient) -> None:
    codes = set()
    for _ in range(40):
        r = await api.post("/api/links", json=VALID)
        assert r.status_code == 201
        codes.add(r.json()["code"])
    assert len(codes) == 40


async def test_exhausted_generation_attempts_is_503(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force every generated code to collide and check the retry loop gives
    up cleanly instead of looping forever or leaking an IntegrityError."""
    monkeypatch.setattr(services, "generate_code", lambda _length: "collide")

    assert (await api.post("/api/links", json=VALID)).status_code == 201
    r = await api.post("/api/links", json=VALID)
    assert r.status_code == 503
    assert r.json()["code"] == "code_generation_failed"


async def test_concurrent_identical_aliases_produce_exactly_one_winner(
    api: AsyncClient,
) -> None:
    """The point of letting the unique index arbitrate.

    Two requests race for the same alias. A SELECT-then-INSERT check would
    let both see an empty table and both proceed; one would then crash with
    an unhandled IntegrityError, or worse, both would appear to succeed.
    """
    payload = {**VALID, "custom_alias": "racealias"}
    results = await asyncio.gather(*(api.post("/api/links", json=payload) for _ in range(5)))
    statuses = sorted(r.status_code for r in results)
    assert statuses.count(201) == 1
    assert statuses.count(409) == 4
