from app.geoip import CountryResolver
from app.models import UNKNOWN_COUNTRY


def test_no_configured_path_resolves_to_unknown() -> None:
    resolver = CountryResolver(None)
    assert resolver.resolve("8.8.8.8") == UNKNOWN_COUNTRY


def test_missing_database_file_resolves_to_unknown_not_an_exception() -> None:
    resolver = CountryResolver("/nonexistent/path/GeoLite2-Country.mmdb")
    assert resolver.resolve("8.8.8.8") == UNKNOWN_COUNTRY


def test_repeated_calls_do_not_retry_opening_a_missing_file(tmp_path) -> None:
    resolver = CountryResolver(str(tmp_path / "does-not-exist.mmdb"))
    for _ in range(5):
        assert resolver.resolve("8.8.8.8") == UNKNOWN_COUNTRY


def test_malformed_ip_resolves_to_unknown() -> None:
    resolver = CountryResolver(None)
    assert resolver.resolve("not-an-ip-address") == UNKNOWN_COUNTRY
    assert resolver.resolve("") == UNKNOWN_COUNTRY


def test_private_and_loopback_addresses_resolve_to_unknown() -> None:
    resolver = CountryResolver(None)
    assert resolver.resolve("127.0.0.1") == UNKNOWN_COUNTRY
    assert resolver.resolve("192.168.1.1") == UNKNOWN_COUNTRY
    assert resolver.resolve("10.0.0.5") == UNKNOWN_COUNTRY


def test_close_is_safe_when_nothing_was_ever_opened() -> None:
    resolver = CountryResolver(None)
    resolver.close()
