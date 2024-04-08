"""HttpClient on top of urllib.request (standard library only)."""
import http.client
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from restclients.client import HttpClient
from restclients.errors import TransportError
from restclients.response import Response, StreamResponse


def socket_timeout(timeout):
    """urllib has a single socket timeout, so a (connect, read) pair becomes the larger one."""
    if isinstance(timeout, (tuple, list)):
        return max(t for t in timeout if t is not None) if any(t is not None for t in timeout) else None
    return timeout


def _origin(url):
    parts = urlsplit(url)
    return (parts.scheme, parts.hostname, parts.port or {"http": 80, "https": 443}.get(parts.scheme))


class _TranslatingReader:
    """Wrap a urllib response so errors while reading the body surface as TransportError.

    Headers arrive first and the body later, so a connection can die half way through
    (``http.client.IncompleteRead``, ``ConnectionResetError``, a read timeout). Callers
    of a stream should see the same exception type as for a failed request.
    """

    def __init__(self, raw, url):
        self._raw = raw
        self._url = url
        self._pending_error = None

    def _broke(self, exc):
        return TransportError("stream from %s broke off: %s" % (self._url, exc or type(exc).__name__),
                              url=self._url)

    def read(self, size=-1):
        if self._pending_error is not None:
            error, self._pending_error = self._pending_error, None
            raise error from None
        try:
            return self._raw.read(size)
        except http.client.IncompleteRead as exc:
            # hand over what did arrive first; the failure is raised by the next read()
            error = self._broke(exc)
            if exc.partial:
                self._pending_error = error
                return exc.partial
            raise error from None
        except (http.client.HTTPException, OSError) as exc:
            raise self._broke(exc) from None

    def close(self):
        self._raw.close()


class RedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect policy closer to what requests/httpx do than urllib's default.

    * 301/302/303 turn POST (and friends) into a body-less GET; 303 always does;
    * 307/308 repeat the request with the same method and body (urllib refuses
      for anything but GET/HEAD);
    * credentials (``Authorization``, ``Cookie``) are dropped when the redirect
      leaves the original origin; urllib would forward them to the new host.
    """

    max_redirections = 10

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if code in (307, 308):
            new = urllib.request.Request(newurl, data=req.data, method=req.get_method(),
                                         headers=dict(req.headers), origin_req_host=req.origin_req_host,
                                         unverifiable=True)
        else:
            method = req.get_method()
            if code == 303 or method == "POST":
                method = "GET" if method != "HEAD" else "HEAD"
                skip = ("content-length", "content-type", "transfer-encoding")
                new = urllib.request.Request(
                    newurl, method=method, origin_req_host=req.origin_req_host, unverifiable=True,
                    headers={k: v for k, v in req.headers.items() if k.lower() not in skip})
            else:
                new = urllib.request.Request(newurl, data=req.data, method=method,
                                             headers=dict(req.headers),
                                             origin_req_host=req.origin_req_host, unverifiable=True)
        if _origin(newurl) != _origin(req.full_url):
            for name in list(new.headers):
                if name.lower() in ("authorization", "cookie", "proxy-authorization"):
                    del new.headers[name]
        return new


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # leave the 3xx as the response


class UrllibClient(HttpClient):
    def __init__(self, follow_redirects=True, **kwargs):
        super().__init__(**kwargs)
        self.follow_redirects = follow_redirects
        self._opener = urllib.request.build_opener(
            RedirectHandler() if follow_redirects else _NoRedirects())

    def _send(self, method, url, headers, body, timeout):
        timeout = socket_timeout(timeout)
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                return Response(resp.status, list(resp.headers.items()), resp.read(), resp.geturl())
        except urllib.error.HTTPError as exc:
            # An error status is still a response; the caller decides whether to raise.
            try:
                return Response(exc.code, list(exc.headers.items()), exc.read(), url)
            finally:
                exc.close()
        except urllib.error.URLError as exc:
            raise TransportError("cannot reach %s: %s" % (url, exc.reason), url=url) from None
        except OSError as exc:
            raise TransportError("%s while talking to %s" % (exc or type(exc).__name__, url),
                                 url=url) from None

    def _open_stream(self, method, url, headers, body, timeout):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            resp = self._opener.open(req, timeout=socket_timeout(timeout))
            return StreamResponse(resp.status, list(resp.headers.items()),
                                  _TranslatingReader(resp, resp.geturl()), resp.geturl())
        except urllib.error.HTTPError as exc:
            return StreamResponse(exc.code, list(exc.headers.items()), _TranslatingReader(exc, url), url)
        except urllib.error.URLError as exc:
            raise TransportError("cannot reach %s: %s" % (url, exc.reason), url=url) from None
        except OSError as exc:
            raise TransportError("%s while talking to %s" % (exc or type(exc).__name__, url),
                                 url=url) from None
