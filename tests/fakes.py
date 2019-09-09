"""Fakes for the third-party HTTP libraries the clients wrap."""


class FakeHeaders(dict):
    """Stands in for requests' CaseInsensitiveDict (only items() is used)."""


class FakeRequestsResponse:
    def __init__(self, status_code=200, body=b"", headers=None):
        self.status_code = status_code
        self.content = body
        self.headers = FakeHeaders(headers or {})


class FakeSession:
    """Looks like requests.Session for the one method the client calls."""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []
        self.closed = False

    def request(self, method, url, headers=None, data=None, timeout=None, **kwargs):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "data": data, "timeout": timeout, **kwargs})
        item = self.responses.pop(0) if self.responses else FakeRequestsResponse(200, b"{}")
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True
