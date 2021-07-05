"""Test doubles for code that takes an injected ``requests``-style session.

The same fake also stands in for an ``httpx.Client`` (same ``request`` shape).

``RequestsClient`` never imports ``requests`` when it is given a session, so a
``FakeSession`` is all a unit test needs. Responses can be queued in order, or
registered per (method, url) with ``respond``. Every call is recorded.
"""
import json as _json


class FakeHeaders(dict):
    """Stands in for requests' CaseInsensitiveDict (only items() is used)."""


class FakeResponse:
    def __init__(self, status_code=200, body=b"", headers=None, json=None, url=None):
        if json is not None:
            body = _json.dumps(json).encode("utf-8")
            headers = dict(headers or {})
            headers.setdefault("Content-Type", "application/json")
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.status_code = status_code
        self.content = body
        self.headers = FakeHeaders(headers or {})
        self.url = url

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")

    def json(self):
        return _json.loads(self.text)

    def iter_content(self, chunk_size=1):
        """requests-style streaming."""
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def iter_bytes(self, chunk_size=None):
        """httpx-style streaming."""
        return self.iter_content(chunk_size or 4)

    def close(self):
        self.closed = True


class _FakeStreamContext:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self.response

    def __exit__(self, *exc):
        self.response.close()
        return False


class FakeSession:
    def __init__(self, responses=None):
        self.queue = list(responses or [])
        self.routes = {}
        self.calls = []
        self.closed = False

    def respond(self, method, url, *responses):
        """Register responses for one (method, url). The last one repeats forever."""
        self.routes.setdefault((method.upper(), url), []).extend(responses)
        return self

    def request(self, method, url, headers=None, data=None, timeout=None, content=None, **kwargs):
        if data is None:
            data = content  # httpx names the raw body "content"
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "data": data, "timeout": timeout, **kwargs})
        scripted = self.routes.get((method.upper(), url))
        if scripted:
            item = scripted.pop(0) if len(scripted) > 1 else scripted[0]
        elif self.queue:
            item = self.queue.pop(0)
        else:
            item = FakeResponse(200, b"{}")
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True

    def stream(self, method, url, headers=None, content=None, timeout=None, **kwargs):
        """httpx.Client.stream: a context manager that yields the response."""
        response = self.request(method, url, headers=headers, data=content, timeout=timeout, **kwargs)
        return _FakeStreamContext(response)

    # -- assertions -------------------------------------------------------
    def calls_to(self, method, url):
        return [c for c in self.calls if c["method"] == method.upper() and c["url"] == url]

    def sent_json(self, index=-1):
        """The decoded JSON body of one recorded call."""
        return _json.loads(self.calls[index]["data"].decode("utf-8"))


class FakeAsyncSession(FakeSession):
    """Like FakeSession, but ``request`` and ``aclose`` are coroutines (httpx.AsyncClient)."""

    async def request(self, method, url, headers=None, data=None, timeout=None, content=None,
                      **kwargs):
        return super().request(method, url, headers, data, timeout, content, **kwargs)

    async def aclose(self):
        self.closed = True


class _FakeAiohttpResponse:
    """The object ``async with session.request(...)`` yields in aiohttp."""

    def __init__(self, fake):
        self.status = fake.status_code
        self.headers = fake.headers
        self._body = fake.content

    async def read(self):
        return self._body


class _FakeRequestContext:
    def __init__(self, outcome):
        self._outcome = outcome

    async def __aenter__(self):
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return _FakeAiohttpResponse(self._outcome)

    async def __aexit__(self, *exc):
        return False


class FakeAiohttpSession(FakeSession):
    """Stands in for aiohttp.ClientSession: ``request`` returns an async context manager."""

    def request(self, method, url, headers=None, data=None, timeout=None, **kwargs):
        try:
            outcome = super().request(method, url, headers, data, timeout, **kwargs)
        except Exception as exc:  # scripted exceptions are raised when entering the context
            outcome = exc
        return _FakeRequestContext(outcome)

    async def close(self):
        self.closed = True
