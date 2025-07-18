"""Small, readable REST client building blocks.

The names below are the public API. They are imported lazily (PEP 562), so
``import restclients`` stays cheap and does not pull in the whole package.
"""
import logging
from importlib import import_module

# A library should not configure logging; this silences the "no handlers" warning
# and leaves the decision to the application.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__version__ = "0.9.0"

_EXPORTS = {
    # clients
    "UrllibClient": "urllib_client",
    "KeepAliveClient": "keepalive_client",
    "RequestsClient": "requests_client",
    "HttpxClient": "httpx_client",
    "AsyncStreamsClient": "async_streams_client",
    "AsyncHttpxClient": "async_client",
    "ThreadedAsyncClient": "async_client",
    "AiohttpClient": "aiohttp_client",
    "HttpClient": "client",
    "ApiClient": "base",
    # building blocks
    "Response": "response",
    "RetryPolicy": "retry",
    "TokenBucket": "ratelimit",
    "AsyncTokenBucket": "ratelimit",
    "CircuitBreaker": "breaker",
    "ResponseCache": "etag_cache",
    "BasicAuth": "auth",
    "BearerAuth": "auth",
    "ApiKeyAuth": "auth",
    "DigestAuth": "auth",
    "ClientCredentials": "oauth2",
    "paginate_pages": "pagination",
    "paginate_links": "pagination",
    "paginate_cursor": "pagination",
    "gather_bounded": "concurrency",
    "parse": "validation",
    # errors
    "ApiError": "errors",
    "TransportError": "errors",
    "HttpStatusError": "errors",
    "ClientError": "errors",
    "ServerError": "errors",
    "NotFound": "errors",
    "Unauthorized": "errors",
    "RateLimited": "errors",
}

__all__ = ["__version__"] + sorted(_EXPORTS)


def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError("module %r has no attribute %r" % (__name__, name))
    value = getattr(import_module("restclients." + module), name)
    globals()[name] = value            # cache it: later lookups skip __getattr__
    return value


def __dir__():
    return sorted(set(globals()) | set(_EXPORTS))
