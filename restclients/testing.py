"""Test doubles for code that takes an injected ``requests``-style session.

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

    def request(self, method, url, headers=None, data=None, timeout=None, **kwargs):
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

    # -- assertions -------------------------------------------------------
    def calls_to(self, method, url):
        return [c for c in self.calls if c["method"] == method.upper() and c["url"] == url]

    def sent_json(self, index=-1):
        """The decoded JSON body of one recorded call."""
        return _json.loads(self.calls[index]["data"].decode("utf-8"))
