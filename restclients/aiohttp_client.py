"""AsyncHttpClient on top of an ``aiohttp.ClientSession``.

aiohttp differs from requests and httpx in three ways that matter here:

* the response body must be read *inside* ``async with session.request(...)``,
  before the connection goes back to the pool;
* timeouts are a ``ClientTimeout`` object, not a number, so we need aiohttp to
  build one (``timeout_factory`` can be injected for tests);
* a timeout raises ``asyncio.TimeoutError``, which is not an aiohttp exception.
"""
import asyncio

from restclients._util import is_library_error
from restclients.async_client import AsyncHttpClient
from restclients.errors import TransportError
from restclients.response import Response


def _default_timeout_factory(seconds):
    import aiohttp  # lazy
    if isinstance(seconds, (tuple, list)):
        connect, read = seconds
        return aiohttp.ClientTimeout(sock_connect=connect, sock_read=read)
    return aiohttp.ClientTimeout(total=seconds)


class AiohttpClient(AsyncHttpClient):
    def __init__(self, session=None, timeout_factory=_default_timeout_factory, **kwargs):
        super().__init__(**kwargs)
        if session is None:
            import aiohttp  # lazy: only needed when the caller did not inject a session
            session = aiohttp.ClientSession()
        self.session = session
        self._timeout_factory = timeout_factory

    async def _send(self, method, url, headers, body, timeout):
        try:
            async with self.session.request(method, url, headers=headers, data=body,
                                            timeout=self._timeout_factory(timeout)) as resp:
                content = await resp.read()
                return Response(resp.status, list(resp.headers.items()), content, url)
        except asyncio.TimeoutError:
            raise TransportError("timed out talking to %s" % url, url=url) from None
        except Exception as exc:
            if is_library_error(exc, "aiohttp"):
                raise TransportError("%s: %s" % (type(exc).__name__, exc), url=url) from None
            raise

    async def aclose(self):
        close = getattr(self.session, "close", None)
        if close:
            await close()
