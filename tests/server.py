"""A tiny in-process REST API used by the tests.

It runs on a ThreadingHTTPServer bound to an ephemeral localhost port, so the
urllib code paths are exercised over real sockets. Routes are methods named
``h_<first path segment>``; add a method to add a route.
"""
import json
import threading
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

    # ROUTES-END


class ApiServer:
    """Context manager: ``with ApiServer() as srv: srv.url``."""

    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.requests = []
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05},
                                       daemon=True)

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.httpd.server_address[1]

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
