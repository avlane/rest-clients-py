"""HttpClient on ``http.client`` with a pool of reused (keep-alive) connections.

``urllib.request`` opens a new connection for every call. ``http.client`` lets
us keep connections open and send many requests down each, which is what
``requests.Session`` and ``httpx.Client`` do for you. Here every origin gets a
``ConnectionPool`` holding at most ``max_connections`` connections; threads
that find all of them busy wait for one to come back.
"""
import http.client
import socket
import threading
import time
import urllib.request
from urllib.parse import urlsplit

from restclients.client import HttpClient
from restclients.errors import TransportError
from restclients.response import Response
from restclients.retry import IDEMPOTENT_METHODS
from restclients.urllib_client import socket_timeout

_STALE = (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError,
          http.client.CannotSendRequest, http.client.ResponseNotReady)


class PoolTimeout(Exception):
    """No connection became free in time."""


class ConnectionPool:
    """A bounded set of connections for one origin."""

    def __init__(self, factory, max_size=10):
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        self._factory = factory
        self.max_size = max_size
        self._idle = []            # most recently used last
        self._in_use = 0
        self._cond = threading.Condition()
        self.opened = 0

    def acquire(self, timeout=None):
        """Return ``(connection, reused)``; waits while ``max_size`` are checked out."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while True:
                if self._idle:
                    self._in_use += 1
                    return self._idle.pop(), True
                if self._in_use < self.max_size:
                    self._in_use += 1
                    self.opened += 1
                    return self._factory(), False
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise PoolTimeout()
                self._cond.wait(remaining)

    def release(self, conn, reusable=True):
        with self._cond:
            self._in_use -= 1
            if reusable:
                self._idle.append(conn)
            else:
                conn.close()
            self._cond.notify()

    def close(self):
        with self._cond:
            for conn in self._idle:
                conn.close()
            self._idle.clear()


class KeepAliveClient(HttpClient):
    """Pooled keep-alive client. It cannot use proxies.

    http.client has no proxy support of its own. Rather than quietly connecting
    directly and bypassing a proxy the environment asks for, a request that the
    environment says must go through a proxy raises ``TransportError`` (unless
    ``trust_env=False``). Use :class:`UrllibClient` there.
    """

    def __init__(self, max_connections=10, pool_timeout=30.0, trust_env=True, **kwargs):
        super().__init__(**kwargs)
        self.trust_env = trust_env
        self.max_connections = max_connections
        self.pool_timeout = pool_timeout
        self._pools = {}                # (scheme, netloc) -> ConnectionPool
        self._lock = threading.Lock()

    @property
    def connections_opened(self):
        with self._lock:
            return sum(pool.opened for pool in self._pools.values())

    def _pool_for(self, scheme, netloc):
        with self._lock:
            pool = self._pools.get((scheme, netloc))
            if pool is None:
                cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
                pool = self._pools[(scheme, netloc)] = ConnectionPool(
                    lambda: cls(netloc), self.max_connections)
            return pool

    def _send(self, method, url, headers, body, timeout):
        parts = urlsplit(url)
        if self.trust_env and self._needs_proxy(parts):
            raise TransportError("the environment configures a proxy for %s, which KeepAliveClient "
                                 "cannot use; use UrllibClient or set trust_env=False" % parts.netloc,
                                 url=url)
        pool = self._pool_for(parts.scheme, parts.netloc)
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        timeout = socket_timeout(timeout)
        for attempt in (1, 2):
            try:
                conn, reused = pool.acquire(self.pool_timeout)
            except PoolTimeout:
                raise TransportError("no free connection to %s within %ss"
                                     % (parts.netloc, self.pool_timeout), url=url) from None
            conn.timeout = timeout
            if conn.sock is not None:
                conn.sock.settimeout(timeout)
            reusable = False
            try:
                conn.request(method, target, body=body, headers=headers)
                resp = conn.getresponse()
                content = resp.read()
                reusable = not resp.will_close
                return Response(resp.status, resp.getheaders(), content, url)
            except _STALE as exc:
                # The server may have closed an idle connection; one fresh try is safe
                # for idempotent methods.
                if attempt == 1 and reused and method in IDEMPOTENT_METHODS:
                    continue
                raise TransportError("connection to %s failed: %s"
                                     % (parts.netloc, exc or type(exc).__name__), url=url) from None
            except (socket.timeout, OSError, http.client.HTTPException) as exc:
                raise TransportError("%s while talking to %s" % (exc or type(exc).__name__, url),
                                     url=url) from None
            finally:
                pool.release(conn, reusable)

    @staticmethod
    def _needs_proxy(parts):
        proxy = urllib.request.getproxies().get(parts.scheme)
        return bool(proxy) and not urllib.request.proxy_bypass(parts.netloc)

    def close(self):
        with self._lock:
            pools = list(self._pools.values())
            self._pools.clear()
        for pool in pools:
            pool.close()
