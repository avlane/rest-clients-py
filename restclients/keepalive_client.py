"""HttpClient on ``http.client`` with a reused (keep-alive) connection.

``urllib.request`` opens a new connection for every call. ``http.client`` lets
us keep one open per host and send many requests down it, which is what
``requests.Session`` and ``httpx.Client`` do for you. This version holds one
connection per origin and serialises use of it with a lock; the pooled version
builds on it.
"""
import http.client
import socket
import threading
from urllib.parse import urlsplit

from restclients.client import HttpClient
from restclients.errors import TransportError
from restclients.response import Response
from restclients.retry import IDEMPOTENT_METHODS
from restclients.urllib_client import socket_timeout

_STALE = (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError,
          http.client.CannotSendRequest, http.client.ResponseNotReady)


class KeepAliveClient(HttpClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._connections = {}          # (scheme, netloc) -> HTTPConnection
        self._lock = threading.Lock()
        self.connections_opened = 0

    def _new_connection(self, scheme, netloc, timeout):
        cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        self.connections_opened += 1
        return cls(netloc, timeout=timeout)

    def _send(self, method, url, headers, body, timeout):
        parts = urlsplit(url)
        origin = (parts.scheme, parts.netloc)
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        timeout = socket_timeout(timeout)
        with self._lock:
            for attempt in (1, 2):
                conn = self._connections.get(origin)
                reused = conn is not None
                if conn is None:
                    conn = self._connections[origin] = self._new_connection(*origin, timeout)
                conn.timeout = timeout
                if conn.sock is not None:
                    conn.sock.settimeout(timeout)
                try:
                    conn.request(method, target, body=body, headers=headers)
                    resp = conn.getresponse()
                    content = resp.read()
                except _STALE as exc:
                    self._discard(origin)
                    # The server may have closed an idle connection; one fresh try is safe
                    # for idempotent methods.
                    if attempt == 1 and reused and method in IDEMPOTENT_METHODS:
                        continue
                    raise TransportError("connection to %s failed: %s" % (parts.netloc, exc or
                                         type(exc).__name__), url=url) from None
                except (socket.timeout, OSError, http.client.HTTPException) as exc:
                    self._discard(origin)
                    raise TransportError("%s while talking to %s" % (exc or type(exc).__name__, url),
                                         url=url) from None
                if resp.will_close:
                    self._discard(origin)
                return Response(resp.status, resp.getheaders(), content, url)

    def _discard(self, origin):
        conn = self._connections.pop(origin, None)
        if conn is not None:
            conn.close()

    def close(self):
        with self._lock:
            for conn in self._connections.values():
                conn.close()
            self._connections.clear()
