import secrets
import string

ALPHABET = string.digits + string.ascii_lowercase + string.ascii_uppercase
BASE = len(ALPHABET)


def generate_code(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def keyspace(length: int) -> int:
    """Number of distinct codes of this length. 62**7 is about 3.5 trillion."""
    return BASE**length
