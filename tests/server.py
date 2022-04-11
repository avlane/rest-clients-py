"""A tiny in-process REST API used by the tests.

It runs on a ThreadingHTTPServer bound to an ephemeral localhost port, so the
urllib code paths are exercised over real sockets. Routes are methods named
``h_<first path segment>``; add a method to add a route.
"""
import base64
import hashlib
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote_plus, urlsplit

ITEMS = [{"id": n, "name": "item-%02d" % n, "price": n * 5} for n in range(1, 24)]


def blob(size):
    """The bytes /blob/<size> serves."""
    pattern = b"0123456789abcdef"
    return (pattern * (size // len(pattern) + 1))[:size]


class Handler(BaseHTTPRequestHandler):
    server_version = "TestApi/1.0"
    protocol_version = "HTTP/1.1"  # keep-alive; every response below sets Content-Length

    def setup(self):
        super().setup()
        with self.server.lock:
            self.server.connections += 1  # one per TCP connection, not per request

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
        try:
            handler()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True  # the client gave up (e.g. a timeout test)

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
    def _json_body(self):
        try:
            return json.loads(self.body or b"{}")
        except ValueError:
            return None

    def _find_item(self, wanted):
        for item in self.server.items:
            if item["id"] == wanted:
                return item
        return None

    def h_items(self):
        """CRUD on an in-memory list. GET /items returns everything, unpaginated."""
        if len(self.segments) == 1:
            if self.command == "POST":
                data = self._json_body()
                if not isinstance(data, dict) or not data.get("name"):
                    return self.send_json({"error": "name is required"}, 400)
                with self.server.lock:
                    new_id = max([i["id"] for i in self.server.items] + [0]) + 1
                    item = {"id": new_id, "name": data["name"], "price": data.get("price", 0)}
                    self.server.items.append(item)
                return self.send_json(item, 201, {"Location": "/items/%d" % new_id})
            return self.send_json(self.server.items)
        try:
            item = self._find_item(int(self.segments[1]))
        except ValueError:
            item = None
        if item is None:
            return self.send_json({"error": "not found"}, 404)
        if self.command in ("PUT", "PATCH"):
            data = self._json_body()
            if not isinstance(data, dict):
                return self.send_json({"error": "invalid JSON"}, 400)
            item.update({k: v for k, v in data.items() if k in ("name", "price")})
        elif self.command == "DELETE":
            self.server.items.remove(item)
            self.send_response(204)
            self.end_headers()
            return
        self.send_json(item)

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
        with self.server.lock:
            self.server.in_flight += 1
            self.server.max_in_flight = max(self.server.max_in_flight, self.server.in_flight)
        try:
            time.sleep(float(self.q("delay", "0.5")))
        finally:
            with self.server.lock:
                self.server.in_flight -= 1
        self.send_json({"slept": True, "n": self.q("n")})

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

    def h_etag(self):
        """A resource whose version bumps on POST /etag/bump; honours If-None-Match."""
        if self.segments[1:] == ["bump"] and self.command == "POST":
            n = self._count("etag-version")
            return self.send_json({"version": n + 1})
        version = self.server.counters.get("etag-version", 0) + 1
        etag = '"v%d"' % version
        candidates = [c.strip() for c in self.headers.get("If-None-Match", "").split(",")]
        if etag in candidates or "W/" + etag in candidates or "*" in candidates:
            self._count("etag-304")
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "max-age=60")
            self.end_headers()
            return
        self._count("etag-200")
        self.send_json({"version": version, "payload": "x" * 200}, headers={"ETag": etag})

    def h_oauth(self):
        """Minimal OAuth2 authorization server plus a protected resource."""
        action = self.segments[1] if len(self.segments) > 1 else ""
        if action == "token" and self.command == "POST":
            return self._oauth_token()
        if action == "authorize" and self.command == "GET":
            # stands in for the browser round trip: the "user" approves immediately
            if not self.q("code_challenge") or self.q("code_challenge_method") != "S256":
                return self.send_json({"error": "invalid_request",
                                       "error_description": "PKCE with S256 is required"}, 400)
            code = "code-%d" % self._count("codes-issued")
            self.server.auth_codes[code] = {"client_id": self.q("client_id"),
                                            "redirect_uri": self.q("redirect_uri"),
                                            "challenge": self.q("code_challenge")}
            return self.send_json({"code": code, "state": self.q("state")})
        if action == "revoke-all" and self.command == "POST":
            self.server.valid_tokens.clear()
            return self.send_json({"revoked": True})
        if action == "me":
            auth = self.headers.get("Authorization", "")
            token = auth[7:] if auth.startswith("Bearer ") else None
            if token not in self.server.valid_tokens:
                return self._challenge("Bearer", ' error="invalid_token"')
            return self.send_json({"client": self.server.valid_tokens[token]})
        self.send_json({"error": "not found"}, 404)

    def _oauth_token(self):
        form = parse_qs(self.body.decode("utf-8"))
        grant = form.get("grant_type", [""])[0]
        if grant == "client_credentials":
            return self._grant_client_credentials(form)
        if grant == "authorization_code":
            return self._grant_authorization_code(form)
        if grant == "refresh_token":
            return self._grant_refresh_token(form)
        self.send_json({"error": "unsupported_grant_type"}, 400)

    def _issue(self, client_id, form, refresh=False):
        n = self._count("tokens-issued")
        token = "at-%d" % n
        self.server.valid_tokens[token] = client_id
        body = {"access_token": token, "token_type": "Bearer",
                "expires_in": self.server.token_ttl, "scope": form.get("scope", [""])[0]}
        if refresh:
            rt = "rt-%d" % n
            self.server.refresh_tokens[rt] = client_id
            body["refresh_token"] = rt
        self.send_json(body, headers={"Cache-Control": "no-store"})

    def _grant_client_credentials(self, form):
        client_id = client_secret = None
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            raw = base64.b64decode(auth[6:]).decode("utf-8")
            client_id, _, client_secret = raw.partition(":")
            client_id, client_secret = unquote_plus(client_id), unquote_plus(client_secret)
        elif "client_id" in form:
            client_id = form["client_id"][0]
            client_secret = form.get("client_secret", [""])[0]
        if (client_id, client_secret) != ("svc-reports", "shh"):
            return self.send_json({"error": "invalid_client"}, 401,
                                  {"WWW-Authenticate": 'Basic realm="oauth"'})
        self._issue(client_id, form)

    def _grant_authorization_code(self, form):
        code = form.get("code", [""])[0]
        pending = self.server.auth_codes.pop(code, None)   # codes are single use
        if pending is None:
            return self.send_json({"error": "invalid_grant", "error_description": "unknown or used code"}, 400)
        if form.get("redirect_uri", [""])[0] != pending["redirect_uri"] or \
                form.get("client_id", [""])[0] != pending["client_id"]:
            return self.send_json({"error": "invalid_grant", "error_description": "client mismatch"}, 400)
        verifier = form.get("code_verifier", [""])[0]
        digest = hashlib.sha256(verifier.encode("ascii", "replace")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        if challenge != pending["challenge"]:
            return self.send_json({"error": "invalid_grant", "error_description": "PKCE verification failed"}, 400)
        self._issue(pending["client_id"], form, refresh=True)

    def _grant_refresh_token(self, form):
        rt = form.get("refresh_token", [""])[0]
        client_id = self.server.refresh_tokens.pop(rt, None)  # rotation: each one works once
        if client_id is None:
            return self.send_json({"error": "invalid_grant", "error_description": "bad refresh token"}, 400)
        self._issue(client_id, form, refresh=True)

    def h_errors(self):
        """Error bodies in the shapes different APIs use."""
        shape = self.q("shape", "plain")
        bodies = {
            "nested": {"error": {"code": 42, "message": "nested message"}},
            "list": {"errors": [{"message": "name is too short"}, {"message": "price must be positive"}]},
            "oauth": {"error": "invalid_request", "error_description": "missing parameter"},
            "problem": {"type": "about:blank", "title": "Unprocessable", "status": 422,
                        "detail": "quantity must be positive"},
        }
        status = int(self.q("status", 422))
        if shape == "text":
            body = b"plain text failure"
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        self.send_json(bodies[shape], status)

    def h_blob(self):
        """GET /blob/<size>: deterministic bytes.

        ``?cut=N`` hangs up after N bytes of the response body. A
        ``Range: bytes=a-`` or ``bytes=a-b`` header gets a 206 (unless ``?norange=1``).
        """
        size = int(self.segments[1])
        data = blob(size)
        status, start, end = 200, 0, size
        spec = self.headers.get("Range", "")
        match = re.match(r"bytes=(\d+)-(\d*)$", spec)
        headers = {"Content-Type": "application/octet-stream", "ETag": '"blob-%d"' % size,
                   "Accept-Ranges": "bytes"}
        if match and not self.q("norange"):
            start = int(match.group(1))
            end = min(size, int(match.group(2)) + 1) if match.group(2) else size
            if start >= size:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
            headers["Content-Range"] = "bytes %d-%d/%d" % (start, end - 1, size)
        body = data[start:end]
        self.send_response(status)
        headers["Content-Length"] = str(len(body))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        cut = self.q("cut")
        if cut is not None:
            self.wfile.write(body[:int(cut)])
            self.wfile.flush()
            self.close_connection = True
            return
        self.wfile.write(body)

    def h_upload(self):
        """POST multipart/form-data; answers with a summary of each part."""
        from email import message_from_bytes
        from email.policy import HTTP
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data"):
            return self.send_json({"error": "expected multipart/form-data"}, 415)
        message = message_from_bytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + self.body,
                                     policy=HTTP)
        parts = []
        for part in message.iter_parts():
            payload = part.get_payload(decode=True) or b""
            parts.append({
                "name": part.get_param("name", header="content-disposition"),
                "filename": part.get_filename(),
                "content_type": part.get_content_type(),
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "text": payload.decode("utf-8", "replace") if part.get_filename() is None else None,
            })
        self.send_json({"parts": parts}, 201)

    def h_orders(self):
        """Nested payloads. /orders/1 is valid, /orders/2 is not, /orders/3 has extra fields."""
        which = self.segments[1] if len(self.segments) > 1 else ""
        if which == "1":
            return self.send_json({"id": 1, "customer": "Rowan Hale", "note": None,
                                   "items": [{"id": 1, "name": "item-01", "price": 5},
                                             {"id": 2, "name": "item-02", "price": 10}]})
        if which == "2":
            return self.send_json({"id": "2", "customer": "Rowan Hale",
                                   "items": [{"id": 1, "name": 7}]})
        if which == "3":
            return self.send_json({"id": 3, "customer": "Mina Park", "loyalty_tier": "gold",
                                   "items": [], "_links": {"self": "/orders/3"}})
        self.send_json({"error": "not found"}, 404)

    # ROUTES-END


class ApiServer:
    """Context manager: ``with ApiServer() as srv: srv.url``."""

    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.requests = []
        self.httpd.counters = {}
        self.httpd.connections = 0
        self.httpd.in_flight = 0
        self.httpd.max_in_flight = 0
        self.httpd.valid_tokens = {}
        self.httpd.refresh_tokens = {}
        self.httpd.auth_codes = {}
        self.httpd.token_ttl = 3600
        self.httpd.items = [dict(i) for i in ITEMS]
        self.httpd.lock = threading.Lock()
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05},
                                       daemon=True)

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.httpd.server_address[1]

    @property
    def connections(self):
        return self.httpd.connections

    @property
    def max_in_flight(self):
        return self.httpd.max_in_flight

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
