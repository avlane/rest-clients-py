"""A tiny in-process REST API used by the tests.

It runs on a ThreadingHTTPServer bound to an ephemeral localhost port, so the
urllib code paths are exercised over real sockets. Routes are methods named
``h_<first path segment>``; add a method to add a route.
"""
import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ITEMS = [{"id": n, "name": "item-%02d" % n, "price": n * 5} for n in range(1, 24)]


class Handler(BaseHTTPRequestHandler):
    server_version = "TestApi/1.0"

    def log_message(self, fmt, *args):
        pass  # keep test output quiet

    # -- plumbing ---------------------------------------------------------
    def _dispatch(self):
        parts = urlsplit(self.path)
        self.query = parse_qs(parts.query)
        self.segments = [s for s in parts.path.split("/") if s]
        length = int(self.headers.get("Content-Length") or 0)
        self.body = self.rfile.read(length) if length else b""
        self.server.requests.append((self.command, self.path, dict(self.headers)))
        name = "h_" + (self.segments[0] if self.segments else "root")
        handler = getattr(self, name.replace("-", "_"), None)
        if handler is None:
            return self.send_json({"error": "no such route"}, 404)
        handler()

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _dispatch

    def send_json(self, payload, status=200, headers=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def q(self, name, default=None):
        values = self.query.get(name)
        return values[0] if values else default

    # -- routes -----------------------------------------------------------
    def h_items(self):
        if len(self.segments) == 2:
            wanted = int(self.segments[1])
            for item in ITEMS:
                if item["id"] == wanted:
                    return self.send_json(item)
            return self.send_json({"error": "not found"}, 404)
        self.send_json(ITEMS)

    def h_echo(self):
        self.send_json({
            "method": self.command,
            "path": "/" + "/".join(self.segments),
            "query": self.query,
            "headers": {k.lower(): v for k, v in self.headers.items()},
        })

    def h_status(self):
        code = int(self.segments[1])
        self.send_json({"error": "status %d requested" % code}, code)

    def h_slow(self):
        time.sleep(float(self.q("delay", "0.5")))
        self.send_json({"slept": True})

    def h_html(self):
        body = b"<html><body>not json</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def h_pages(self):
        """page/limit pagination with an envelope."""
        page = max(1, int(self.q("page", 1)))
        limit = min(50, max(1, int(self.q("limit", 10))))
        start = (page - 1) * limit
        self.send_json({"items": ITEMS[start:start + limit], "page": page,
                        "limit": limit, "total": len(ITEMS)})

    def h_linked(self):
        """GitHub-style pagination: a bare list plus a Link header."""
        page = max(1, int(self.q("page", 1)))
        per_page = min(50, max(1, int(self.q("per_page", 10))))
        start = (page - 1) * per_page
        last = (len(ITEMS) + per_page - 1) // per_page
        base = "http://%s/linked?per_page=%d&page=" % (self.headers["Host"], per_page)
        links = []
        if page < last:
            links.append('<%s%d>; rel="next"' % (base, page + 1))
            links.append('<%s%d>; rel="last"' % (base, last))
        if page > 1:
            links.append('<%s%d>; rel="prev"' % (base, page - 1))
            links.append('<%s1>; rel="first"' % base)
        headers = {"Link": ", ".join(links)} if links else {}
        self.send_json(ITEMS[start:start + per_page], headers=headers)

    def h_cursor(self):
        """Opaque-cursor pagination: ``next_cursor`` is null on the last page."""
        offset = 0
        if self.q("cursor"):
            try:
                offset = int(base64.urlsafe_b64decode(self.q("cursor").encode()).decode().split(":")[1])
            except (ValueError, IndexError):
                return self.send_json({"error": "bad cursor"}, 400)
        limit = min(50, max(1, int(self.q("limit", 10))))
        end = offset + limit
        nxt = None
        if end < len(ITEMS):
            nxt = base64.urlsafe_b64encode(("offset:%d" % end).encode()).decode()
        self.send_json({"data": ITEMS[offset:end], "meta": {"next_cursor": nxt}})

    def _challenge(self, scheme, extra=""):
        self.send_json({"error": "authentication required"}, 401,
                       {"WWW-Authenticate": scheme + extra})

    def h_basic(self):
        expected = "Basic " + base64.b64encode(b"avery:s3cret").decode()
        if self.headers.get("Authorization") != expected:
            return self._challenge("Basic", ' realm="test"')
        self.send_json({"user": "avery"})

    def h_bearer(self):
        if self.headers.get("Authorization") != "Bearer tok-123":
            return self._challenge("Bearer", ' realm="test"')
        self.send_json({"user": "avery", "scope": "read"})

    def h_apikey(self):
        if self.headers.get("X-API-Key") != "key-abc":
            return self.send_json({"error": "bad key"}, 403)
        self.send_json({"ok": True})

    def _count(self, key):
        with self.server.lock:
            self.server.counters[key] = self.server.counters.get(key, 0) + 1
            return self.server.counters[key]

    def h_flaky(self):
        """Fail with ``status`` (default 503) for the first ``fail`` calls per ``key``."""
        n = self._count("flaky:" + self.q("key", "default"))
        if n <= int(self.q("fail", 2)):
            return self.send_json({"error": "temporarily broken", "call": n},
                                  int(self.q("status", 503)))
        self.send_json({"ok": True, "call": n})

    def h_limited(self):
        """429 with Retry-After for the first ``times`` calls per ``key``."""
        n = self._count("limited:" + self.q("key", "default"))
        if n <= int(self.q("times", 1)):
            return self.send_json({"error": "slow down"}, 429,
                                  {"Retry-After": self.q("after", "1")})
        self.send_json({"ok": True, "call": n})

    def h_drop(self):
        """Close the connection without answering for the first ``fail`` calls."""
        n = self._count("drop:" + self.q("key", "default"))
        if n <= int(self.q("fail", 1)):
            self.close_connection = True
            return
        self.send_json({"ok": True, "call": n})

    # ROUTES-END


class ApiServer:
    """Context manager: ``with ApiServer() as srv: srv.url``."""

    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.requests = []
        self.httpd.counters = {}
        self.httpd.lock = threading.Lock()
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05},
                                       daemon=True)

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.httpd.server_address[1]

    @property
    def counters(self):
        return self.httpd.counters

    @property
    def requests(self):
        return self.httpd.requests

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
