"""A response type shared by every client in the package.

urllib, requests and httpx each have their own response object. Wrapping them
all in this one means pagination, caching and error handling are written once.
"""
import json as _json

from restclients.errors import ApiError, error_for_status


class Headers:
    """Read-only, case-insensitive header mapping."""

    def __init__(self, items=None):
        self._data = {}
        pairs = items.items() if hasattr(items, "items") else (items or [])
        for key, value in pairs:
            self._data[str(key).lower()] = (str(key), str(value))

    def get(self, name, default=None):
        entry = self._data.get(name.lower())
        return entry[1] if entry else default

    def __getitem__(self, name):
        entry = self._data[name.lower()]
        return entry[1]

    def __contains__(self, name):
        return name.lower() in self._data

    def __iter__(self):
        return (original for original, _ in self._data.values())

    def __len__(self):
        return len(self._data)

    def items(self):
        return list(self._data.values())

    def as_dict(self):
        return dict(self._data.values())

    def __repr__(self):
        return "Headers(%r)" % self.as_dict()


class Response:
    def __init__(self, status, headers=None, content=b"", url=None):
        self.status = status
        self.headers = headers if isinstance(headers, Headers) else Headers(headers)
        self.content = content
        self.url = url

    @property
    def ok(self):
        return 200 <= self.status < 400

    @property
    def text(self):
        charset = "utf-8"
        content_type = self.headers.get("Content-Type", "")
        if "charset=" in content_type:
            charset = content_type.split("charset=", 1)[1].split(";")[0].strip(' "')
        return self.content.decode(charset, "replace")

    def json(self):
        try:
            return _json.loads(self.text)
        except ValueError:
            raise ApiError("response body is not valid JSON", self.status,
                           self.url, self.content, self.headers.as_dict()) from None

    def raise_for_status(self):
        if self.status >= 400:
            raise error_for_status(self.status, self.url, self.content, self.headers.as_dict())
        return self

    def __repr__(self):
        return "<Response %s %s>" % (self.status, self.url)
