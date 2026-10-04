from fastapi import Request

from app.config import get_settings

UNKNOWN_IP = "0.0.0.0"


def client_ip(request: Request) -> str:
    settings = get_settings()
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                return parts[-1]
    if request.client is None:
        return UNKNOWN_IP
    return request.client.host
