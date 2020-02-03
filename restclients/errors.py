"""Exceptions, one per kind of failure a caller might want to handle."""


class ApiError(Exception):
    """Base class for everything this package raises."""

    def __init__(self, message, status=None, url=None, body=None, headers=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.url = url
        self.body = body
        self.headers = headers or {}

    def __str__(self):
        if self.status is None:
            return self.message
        return "HTTP %s: %s" % (self.status, self.message)


class TransportError(ApiError):
    """No usable response: DNS failure, refused connection, timeout."""


class HttpStatusError(ApiError):
    """The server answered, but with an error status."""


class ClientError(HttpStatusError):
    """4xx: the request was wrong, retrying it unchanged will not help."""


class ServerError(HttpStatusError):
    """5xx: the server failed; retrying may help."""


class BadRequest(ClientError):
    pass


class Unauthorized(ClientError):
    pass


class Forbidden(ClientError):
    pass


class NotFound(ClientError):
    pass


class Conflict(ClientError):
    pass


class RateLimited(ClientError):
    """429. ``retry_after`` is the server's requested wait in seconds, if it gave one."""

    @property
    def retry_after(self):
        from restclients.retry import parse_retry_after
        return parse_retry_after(_header(self.headers, "Retry-After"))


_BY_STATUS = {
    400: BadRequest,
    401: Unauthorized,
    403: Forbidden,
    404: NotFound,
    409: Conflict,
    429: RateLimited,
}


def error_for_status(status, url=None, body=None, headers=None):
    """Return the exception instance for an error ``status`` (not raised)."""
    if status in _BY_STATUS:
        cls = _BY_STATUS[status]
    elif 400 <= status < 500:
        cls = ClientError
    elif status >= 500:
        cls = ServerError
    else:
        cls = HttpStatusError
    return cls(_summarize(body) or "request failed", status, url, body, headers)


def _header(headers, name):
    wanted = name.lower()
    for key, value in (headers or {}).items():
        if key.lower() == wanted:
            return value
    return None


def _summarize(body):
    """Short human readable text from an error body (JSON ``error`` or raw text)."""
    if not body:
        return ""
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
    try:
        import json
        data = json.loads(text)
    except ValueError:
        return text.strip()[:200]
    if isinstance(data, dict):
        for key in ("error", "message", "detail", "title"):
            if isinstance(data.get(key), str):
                return data[key]
    return text.strip()[:200]
