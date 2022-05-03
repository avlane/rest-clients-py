"""Catch the OAuth2 redirect on a loopback address (for command line logins)."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

_PAGE = b"<html><body><p>Signed in. You can close this tab.</p></body></html>"


class CallbackServer:
    """Listen once on ``127.0.0.1`` for ``/callback?code=...&state=...``.

    Start it *before* sending the user to the authorization URL, use
    :attr:`redirect_uri` as the redirect, then call :meth:`wait`.
    """

    def __init__(self, port=0, path="/callback"):
        owner = self
        self.path = path
        self.params = None
        self._done = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def do_GET(self):
                parts = urlsplit(self.path)
                if parts.path != owner.path:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                owner.params = {k: v[0] for k, v in parse_qs(parts.query).items()}
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(_PAGE)))
                self.end_headers()
                self.wfile.write(_PAGE)
                owner._done.set()

        self._httpd = HTTPServer(("127.0.0.1", port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)

    @property
    def redirect_uri(self):
        return "http://127.0.0.1:%d%s" % (self._httpd.server_address[1], self.path)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def wait(self, timeout=120.0, expected_state=None):
        """Block until the redirect arrives; return its query parameters as a dict.

        Raises ``TimeoutError`` if nothing arrives and ``ValueError`` if the
        ``state`` does not match ``expected_state`` or the server sent ``error``.
        """
        if not self._done.wait(timeout):
            raise TimeoutError("no OAuth redirect received within %s seconds" % timeout)
        params = self.params
        if "error" in params:
            raise ValueError("authorization failed: %s" % params.get("error_description", params["error"]))
        if expected_state is not None and params.get("state") != expected_state:
            raise ValueError("state mismatch: possible CSRF")
        return params
