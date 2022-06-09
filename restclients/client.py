"""HttpClient: the interface every transport-specific client implements.

Subclasses only provide ``_send``. Everything else (base URL, default headers,
JSON bodies, status checking) lives here, so the urllib, requests and httpx
clients behave the same way.
"""
import json as _json
import logging
import time
import uuid
from urllib.parse import urlencode

from restclients.errors import TransportError, error_for_status
from restclients.logging_utils import correlation_id, redact_url
from restclients.multipart import FilePart, encode_multipart
from restclients.response import Response
from restclients.retry import parse_retry_after
from restclients.urls import build_url, join_url

USER_AGENT = "rest-clients-py/0.1"
log = logging.getLogger("restclients.http")


def _as_file_parts(files):
    """Accept ``{"field": FilePart}`` or ``{"field": (filename, bytes[, content_type])}``."""
    pairs = files.items() if hasattr(files, "items") else files
    return [(name, part if isinstance(part, FilePart) else FilePart(*part)) for name, part in pairs]


class PreparedRequest:
    """Everything a transport needs to send one request."""

    def __init__(self, method, url, headers, body, timeout, auth=None):
        self.method = method
        self.url = url
        self.headers = headers
        self.body = body
        self.timeout = timeout
        self.auth = auth


class RequestBuilder:
    """Turns (path, params, json, ...) into a PreparedRequest.

    Shared by the synchronous and asynchronous clients, so that URL joining,
    default headers, body encoding and auth are written once.
    """

    def __init__(self, base_url="", headers=None, timeout=10.0, auth=None):
        self.base_url = base_url
        self.auth = auth
        self.timeout = timeout
        self.headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        self.headers.update(headers or {})

    def prepare(self, method, path, params=None, headers=None, json=None, data=None,
                timeout=None, auth=None, form=None, files=None):
        url = build_url(join_url(self.base_url, path), params)
        send_headers = dict(self.headers)
        send_headers.update(headers or {})
        auth = auth or self.auth
        if auth is not None:
            auth.apply(send_headers)
        body = data
        if files:
            # text fields (``form``) and files travel together in one multipart body
            body, content_type = encode_multipart(form, _as_file_parts(files))
            send_headers["Content-Type"] = content_type
        elif json is not None:
            body = _json.dumps(json).encode("utf-8")
            send_headers.setdefault("Content-Type", "application/json")
        elif form is not None:
            body = urlencode(form).encode("ascii")
            send_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        return PreparedRequest(method.upper(), url, send_headers, body,
                               self.timeout if timeout is None else timeout, auth)


class HttpClient(RequestBuilder):
    """Base class.

    ``timeout`` is seconds, or a ``(connect, read)`` pair. Unlike requests,
    which waits forever unless told otherwise, a client here always has one.
    """

    def __init__(self, base_url="", headers=None, timeout=10.0, auth=None, retry=None,
                 sleep=time.sleep, rate_limiter=None, cache=None, logger=None, request_id_header="X-Request-ID"):
        super().__init__(base_url, headers, timeout, auth)
        self.logger = logger or log
        self.request_id_header = request_id_header
        self.cache = cache
        self.retry = retry
        self.rate_limiter = rate_limiter
        self._sleep = sleep

    def close(self):
        """Release transport resources. Subclasses with sessions override this."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- public API -------------------------------------------------------
    def request(self, method, path, params=None, headers=None, json=None, data=None,
                timeout=None, raise_for_status=True, auth=None, form=None, files=None):
        """Send a request and return a :class:`Response`.

        ``json`` is encoded as the body (with a Content-Type); ``form`` is sent
        as application/x-www-form-urlencoded; ``files`` makes it a multipart upload
        (``form`` then supplies the text fields); ``data`` is sent as raw bytes. Error
        statuses raise unless ``raise_for_status`` is False. ``auth`` (or the
        client's default) signs the request. With a ``cache``, GETs are
        revalidated using ``If-None-Match`` and 304s are answered from the store.
        """
        prepared = self.prepare(method, path, params, headers, json, data, timeout, auth, form,
                               files)
        method, url, send_headers = prepared.method, prepared.url, prepared.headers
        request_id = self._request_id(send_headers)
        body, timeout, auth = prepared.body, prepared.timeout, prepared.auth
        cache_key = url if method == "GET" and self.cache is not None else None
        if cache_key is not None:
            for name, value in self.cache.conditional_headers(cache_key).items():
                send_headers.setdefault(name, value)
        response = self._send_with_retries(method, url, send_headers, body, timeout, request_id)
        if response.status == 401 and hasattr(auth, "invalidate"):
            # The token may have been revoked or expired early: get a fresh one and try once more.
            auth.invalidate()
            auth.apply(send_headers)
            response = self._send_with_retries(method, url, send_headers, body, timeout,
                                               request_id)
        if cache_key is not None:
            if response.status == 304 and cache_key in self.cache:
                response = self.cache.revalidated(cache_key, response)
            else:
                self.cache.store(cache_key, response)
        if raise_for_status:
            response.raise_for_status()
        return response

    def get(self, path, params=None, **kwargs):
        return self.request("GET", path, params=params, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path, **kwargs):
        return self.request("PUT", path, **kwargs)

    def patch(self, path, **kwargs):
        return self.request("PATCH", path, **kwargs)

    def delete(self, path, **kwargs):
        return self.request("DELETE", path, **kwargs)

    def get_json(self, path, params=None, **kwargs):
        return self.get(path, params=params, **kwargs).json()

    def stream(self, method, path, params=None, headers=None, json=None, data=None,
               timeout=None, raise_for_status=True, auth=None):
        """Open a request and return a :class:`StreamResponse` without reading the body.

        Streams are not retried (the caller may already have consumed part of
        one) but they do count against the rate limiter.
        """
        prepared = self.prepare(method, path, params, headers, json, data, timeout, auth)
        if self.rate_limiter is not None:
            self.rate_limiter.acquire()
        response = self._open_stream(prepared.method, prepared.url, prepared.headers,
                                     prepared.body, prepared.timeout)
        if raise_for_status and response.status >= 400:
            with response:
                body = response.read()
            raise error_for_status(response.status, prepared.url, body, response.headers.as_dict())
        return response

    def _request_id(self, send_headers):
        """Id shared by all attempts of one call: caller's header, else the context's, else new."""
        name = self.request_id_header
        if not name:
            return None
        existing = next((v for k, v in send_headers.items() if k.lower() == name.lower()), None)
        request_id = existing or correlation_id.get() or uuid.uuid4().hex
        if not existing:
            send_headers[name] = request_id
        return request_id

    def _log(self, level, method, url, status, started, attempt, error=None, request_id=None,
             response=None):
        if not self.logger.isEnabledFor(level):
            return
        safe_url = redact_url(url)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        info = {"method": method, "url": safe_url, "status": status,
                "duration_ms": elapsed_ms, "attempt": attempt}
        if request_id:
            info["request_id"] = request_id
        if response is not None and "X-Request-ID" in response.headers:
            info["server_request_id"] = response.headers["X-Request-ID"]
        if error:
            info["error"] = error
        self.logger.log(level, "%s %s -> %s", method, safe_url, status if status else "failed",
                        extra=info)

    def _send_with_retries(self, method, url, headers, body, timeout, request_id=None):
        policy = self.retry
        attempt = 0
        while True:
            attempt += 1
            retryable = (policy is not None and policy.should_retry_method(method)
                         and policy.attempts_left(attempt))
            if self.rate_limiter is not None:
                self.rate_limiter.acquire()  # retries count against the limit too
            started = time.perf_counter()
            try:
                response = self._send(method, url, headers, body, timeout)
            except TransportError as exc:
                self._log(logging.WARNING if retryable else logging.ERROR, method, url, None,
                          started, attempt, error=exc.message, request_id=request_id)
                if not retryable:
                    raise
                self._sleep(policy.wait_seconds(attempt))
                continue
            self._log(logging.INFO if response.status < 400 else logging.WARNING, method, url,
                      response.status, started, attempt, request_id=request_id, response=response)
            if retryable and policy.should_retry_status(response.status):
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                wait = policy.wait_seconds(attempt, retry_after)
                if wait is not None:
                    self._sleep(wait)
                    continue
            return response

    # -- to be provided by subclasses --------------------------------------
    def _send(self, method, url, headers, body, timeout):
        raise NotImplementedError

    def _open_stream(self, method, url, headers, body, timeout):
        raise NotImplementedError("%s does not support streaming" % type(self).__name__)
