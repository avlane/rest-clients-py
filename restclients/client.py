"""HttpClient: the interface every transport-specific client implements.

Subclasses only provide ``_send``. Everything else (base URL, default headers,
JSON bodies, status checking) lives here, so the urllib, requests and httpx
clients behave the same way.
"""
import json as _json
import time

from restclients.errors import TransportError
from restclients.response import Response
from restclients.retry import parse_retry_after
from restclients.urls import build_url, join_url

USER_AGENT = "rest-clients-py/0.1"


class HttpClient:
    """Base class.

    ``timeout`` is seconds, or a ``(connect, read)`` pair. Unlike requests,
    which waits forever unless told otherwise, a client here always has one.
    """

    def __init__(self, base_url="", headers=None, timeout=10.0, auth=None, retry=None,
                 sleep=time.sleep):
        self.retry = retry
        self._sleep = sleep
        self.base_url = base_url
        self.auth = auth
        self.timeout = timeout
        self.headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        self.headers.update(headers or {})

    # -- public API -------------------------------------------------------
    def request(self, method, path, params=None, headers=None, json=None, data=None,
                timeout=None, raise_for_status=True, auth=None):
        """Send a request and return a :class:`Response`.

        ``json`` is encoded as the body (with a Content-Type); ``data`` is sent
        as raw bytes. Error statuses raise unless ``raise_for_status`` is False.
        ``auth`` (or the client's default) signs the request.
        """
        url = build_url(join_url(self.base_url, path), params)
        send_headers = dict(self.headers)
        send_headers.update(headers or {})
        auth = auth or self.auth
        if auth is not None:
            auth.apply(send_headers)
        body = data
        if json is not None:
            body = _json.dumps(json).encode("utf-8")
            send_headers.setdefault("Content-Type", "application/json")
        response = self._send_with_retries(method.upper(), url, send_headers, body,
                                           self.timeout if timeout is None else timeout)
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

    def _send_with_retries(self, method, url, headers, body, timeout):
        policy = self.retry
        attempt = 0
        while True:
            attempt += 1
            retryable = (policy is not None and policy.should_retry_method(method)
                         and policy.attempts_left(attempt))
            try:
                response = self._send(method, url, headers, body, timeout)
            except TransportError:
                if not retryable:
                    raise
                self._sleep(policy.wait_seconds(attempt))
                continue
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
