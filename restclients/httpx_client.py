"""HttpClient on top of an ``httpx.Client`` (synchronous API).

Like the requests client, httpx is imported lazily and only when no client is
injected, so tests can pass a fake. httpx's API is deliberately close to
requests, which is why this file is almost a copy of ``requests_client.py``.
"""
from restclients._util import is_library_error
from restclients.client import HttpClient
from restclients.errors import TransportError
from restclients.response import IterReader, Response, StreamResponse


class HttpxClient(HttpClient):
    def __init__(self, client=None, http2=False, **kwargs):
        super().__init__(**kwargs)
        if client is None:
            import httpx  # lazy: only needed when the caller did not inject a client
            # httpx 0.20 stopped following redirects by default; the other clients do, so match them
            options = {"follow_redirects": True}
            if http2:
                options["http2"] = True      # needs the optional extra: pip install "httpx[http2]"
            client = httpx.Client(**options)
        self.client = client

    def _send(self, method, url, headers, body, timeout):
        try:
            resp = self.client.request(method, url, headers=headers, content=body, timeout=timeout)
        except Exception as exc:
            if is_library_error(exc, "httpx"):
                raise TransportError("%s: %s" % (type(exc).__name__, exc), url=url) from None
            raise
        return Response(resp.status_code, list(resp.headers.items()), resp.content, url)

    def _open_stream(self, method, url, headers, body, timeout):
        context = self.client.stream(method, url, headers=headers, content=body, timeout=timeout)
        try:
            resp = context.__enter__()
        except Exception as exc:
            if is_library_error(exc, "httpx"):
                raise TransportError("%s: %s" % (type(exc).__name__, exc), url=url) from None
            raise
        reader = IterReader(resp.iter_bytes(), lambda: context.__exit__(None, None, None))
        return StreamResponse(resp.status_code, list(resp.headers.items()), reader, url)

    def close(self):
        close = getattr(self.client, "close", None)
        if close:
            close()
