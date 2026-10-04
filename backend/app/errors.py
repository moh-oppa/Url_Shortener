class ShortenerError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.code)
        self.detail = detail or self.code


class LinkNotFound(ShortenerError):
    status_code = 404
    code = "link_not_found"


class LinkExpired(ShortenerError):
    status_code = 410
    code = "link_expired"


class AliasTaken(ShortenerError):
    status_code = 409
    code = "alias_taken"


class CodeGenerationFailed(ShortenerError):
    status_code = 503
    code = "code_generation_failed"


class RateLimited(ShortenerError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, retry_after: int, detail: str | None = None) -> None:
        super().__init__(detail)
        self.retry_after = retry_after
