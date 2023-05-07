"""Receive webhooks: a small HTTP server that collects JSON events.

The receiver answers quickly (providers retry slow or failing endpoints) and
hands each event to a callback and to an in-memory list. Verification is a
pluggable ``verifier(headers, body)`` that raises :class:`WebhookRejected` to
refuse a delivery; see ``restclients.signatures`` for the HMAC implementation.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from restclients.errors import ApiError


class WebhookRejected(ApiError):
    """A delivery that must not be processed. ``status`` is the HTTP code to answer with."""

    def __init__(self, message, status=400):
        super().__init__(message, status=status)


class Event:
    def __init__(self, payload, headers, received_at):
        self.payload = payload
        self.headers = headers
        self.received_at = received_at

    def __repr__(self):
        return "Event(%r)" % (self.payload,)


class WebhookReceiver:
    """Listen on ``127.0.0.1`` (put a reverse proxy in front for anything else)."""

    def __init__(self, path="/webhooks", port=0, verifier=None, on_event=None,
                 max_body=1024 * 1024, clock=time.time):
        self.path = path
        self.verifier = verifier
        self.on_event = on_event
        self.max_body = max_body
        self.events = []
        self.rejected = []                  # (status, reason) for each refused delivery
        self._cond = threading.Condition()
        self._clock = clock
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                pass

            def _reply(self, status, payload=None):
                body = json.dumps(payload if payload is not None else {}).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                if self.path != receiver.path:
                    self.rfile.read(min(length, receiver.max_body))
                    return self._reply(404, {"error": "unknown endpoint"})
                if length > receiver.max_body:
                    self.close_connection = True      # do not read a body we will not accept
                    return self._reply(413, {"error": "payload too large"})
                body = self.rfile.read(length)
                status, payload = receiver._handle(dict(self.headers), body)
                self._reply(status, payload)

            def _not_allowed(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self.send_response(405)
                self.send_header("Allow", "POST")
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_GET = do_PUT = do_DELETE = do_PATCH = _not_allowed

        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)

    # -- request handling ---------------------------------------------------
    def _handle(self, headers, body):
        try:
            if self.verifier is not None:
                self.verifier(headers, body)
            try:
                payload = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise WebhookRejected("body is not valid JSON", 400) from None
        except WebhookRejected as exc:
            with self._cond:
                self.rejected.append((exc.status, exc.message))
                self._cond.notify_all()
            return exc.status, {"error": exc.message}
        event = Event(payload, headers, self._clock())
        with self._cond:
            self.events.append(event)
            self._cond.notify_all()
        if self.on_event is not None:
            self.on_event(event)
        return 200, {"received": True}

    # -- server lifecycle ---------------------------------------------------
    @property
    def url(self):
        return "http://127.0.0.1:%d%s" % (self._httpd.server_address[1], self.path)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def wait_for(self, count=1, timeout=5.0):
        """Block until ``count`` events have been accepted; returns the list of events."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while len(self.events) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("got %d of %d events" % (len(self.events), count))
                self._cond.wait(remaining)
            return list(self.events)

    def wait_for_rejections(self, count=1, timeout=5.0):
        deadline = time.monotonic() + timeout
        with self._cond:
            while len(self.rejected) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("got %d of %d rejections" % (len(self.rejected), count))
                self._cond.wait(remaining)
            return list(self.rejected)
