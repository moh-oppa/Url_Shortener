import re

from app.shortcode import ALPHABET, generate_code, keyspace

BASE62 = re.compile(r"^[0-9a-zA-Z]+$")


def test_length_is_respected() -> None:
    for n in (4, 7, 12):
        assert len(generate_code(n)) == n


def test_only_base62_characters() -> None:
    assert BASE62.match(generate_code(64))
    assert len(ALPHABET) == 62
    assert len(set(ALPHABET)) == 62


def test_codes_do_not_repeat() -> None:
    codes = {generate_code(7) for _ in range(1000)}
    assert len(codes) == 1000


def test_every_position_varies() -> None:
    samples = [generate_code(7) for _ in range(200)]
    for position in range(7):
        assert len({s[position] for s in samples}) > 1


def test_keyspace_is_large_enough_to_matter() -> None:
    assert keyspace(7) == 62**7
    assert keyspace(7) > 3_000_000_000_000
