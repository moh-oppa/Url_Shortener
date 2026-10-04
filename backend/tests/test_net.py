import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.config import get_settings
from app.net import client_ip

probe = FastAPI()


@probe.get("/whoami")
async def whoami(request: Request) -> dict[str, str]:
    return {"ip": client_ip(request)}


@pytest.fixture
def probe_client() -> TestClient:
    with TestClient(probe) as c:
        yield c


def test_forwarded_header_ignored_when_not_behind_proxy(
    probe_client: TestClient, monkeypatch, settings_cache_reset
) -> None:
    monkeypatch.setenv("TRUST_PROXY", "false")
    get_settings.cache_clear()
    r = probe_client.get("/whoami", headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.json()["ip"] == "testclient"


def test_forwarded_header_used_when_behind_proxy(
    probe_client: TestClient, monkeypatch, settings_cache_reset
) -> None:
    monkeypatch.setenv("TRUST_PROXY", "true")
    get_settings.cache_clear()
    r = probe_client.get("/whoami", headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.json()["ip"] == "203.0.113.9"


def test_last_hop_wins_against_spoofed_chain(
    probe_client: TestClient, monkeypatch, settings_cache_reset
) -> None:
    monkeypatch.setenv("TRUST_PROXY", "true")
    get_settings.cache_clear()
    r = probe_client.get("/whoami", headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.9"})
    assert r.json()["ip"] == "203.0.113.9"
