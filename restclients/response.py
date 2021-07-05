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
        """Decode the body. An empty body (204, HEAD) gives None instead of an error."""
        if not self.content.strip():
            return None
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


class StreamResponse:
    """A response whose body has not been read yet.

    Use it as a context manager so the connection is always released::

        with client.stream("GET", "/big") as resp:
            for chunk in resp.iter_bytes():
                ...
    """

    def __init__(self, status, headers, raw, url=None):
        self.status = status
        self.headers = headers if isinstance(headers, Headers) else Headers(headers)
        self.url = url
        self._raw = raw          # anything with read(n) and close()
        self.bytes_read = 0

    @property
    def content_length(self):
        value = self.headers.get("Content-Length")
        return int(value) if value and value.isdigit() else None

    def iter_bytes(self, chunk_size=65536):
        while True:
            chunk = self._raw.read(chunk_size)
            if not chunk:
                return
            self.bytes_read += len(chunk)
            yield chunk

    def read(self):
        return b"".join(self.iter_bytes())

    def close(self):
        self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class IterReader:
    """Adapt a chunk iterator (requests' ``iter_content``, httpx's ``iter_bytes``) to ``read(n)``."""

    def __init__(self, chunks, close=None):
        self._chunks = iter(chunks)
        self._close = close
        self._buffer = b""

    def read(self, size=-1):
        while size < 0 or len(self._buffer) < size:
            try:
                self._buffer += next(self._chunks)
            except StopIteration:
                break
        if size < 0:
            data, self._buffer = self._buffer, b""
        else:
            data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data

    def close(self):
        if self._close is not None:
            self._close()
