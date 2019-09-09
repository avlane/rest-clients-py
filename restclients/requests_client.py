"""HttpClient on top of a ``requests`` session.

``requests`` is imported lazily and only when no session is passed in. Pass
any object with a ``request(method, url, headers=..., data=..., timeout=...)``
method that returns a requests-style response, and nothing is imported at all.
That is how the tests run without the library installed.
"""
from restclients.client import HttpClient
from restclients.errors import TransportError
from restclients.response import Response


def _is_requests_error(exc):
    return any(cls.__module__.split(".")[0] == "requests" for cls in type(exc).__mro__)


class RequestsClient(HttpClient):
    def __init__(self, session=None, **kwargs):
        super().__init__(**kwargs)
        if session is None:
            import requests  # lazy: only needed when the caller did not inject a session
            session = requests.Session()
        self.session = session

    def _send(self, method, url, headers, body, timeout):
        try:
            resp = self.session.request(method, url, headers=headers, data=body, timeout=timeout)
        except Exception as exc:
            if _is_requests_error(exc):
                raise TransportError("%s: %s" % (type(exc).__name__, exc), url=url) from None
            raise
        return Response(resp.status_code, list(resp.headers.items()), resp.content, url)

    def close(self):
        close = getattr(self.session, "close", None)
        if close:
            close()
