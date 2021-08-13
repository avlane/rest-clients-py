"""Asynchronous clients.

``AsyncHttpClient`` mirrors ``HttpClient`` with ``async def`` methods and reuses
``RequestBuilder`` for everything before the bytes go out. Two transports:

* ``ThreadedAsyncClient`` runs a synchronous client (urllib, requests, ...) in a
  thread pool. Not "true" async I/O, but it makes any blocking client usable
  from an event loop, and it is how the urllib code is exercised for real.
* ``AsyncHttpxClient`` wraps an ``httpx.AsyncClient``.
"""
import asyncio
from functools import partial

from restclients._util import is_library_error
from restclients.client import RequestBuilder
from restclients.errors import TransportError
from restclients.response import Response


class AsyncHttpClient(RequestBuilder):
    async def request(self, method, path, params=None, headers=None, json=None, data=None,
                      timeout=None, raise_for_status=True, auth=None, form=None, files=None):
        prepared = self.prepare(method, path, params, headers, json, data, timeout, auth, form,
                                files)
        response = await self._send(prepared.method, prepared.url, prepared.headers,
                                    prepared.body, prepared.timeout)
        if raise_for_status:
            response.raise_for_status()
        return response

    async def get(self, path, params=None, **kwargs):
        return await self.request("GET", path, params=params, **kwargs)

    async def post(self, path, **kwargs):
        return await self.request("POST", path, **kwargs)

    async def put(self, path, **kwargs):
        return await self.request("PUT", path, **kwargs)

    async def patch(self, path, **kwargs):
        return await self.request("PATCH", path, **kwargs)

    async def delete(self, path, **kwargs):
        return await self.request("DELETE", path, **kwargs)

    async def get_json(self, path, params=None, **kwargs):
        return (await self.get(path, params=params, **kwargs)).json()

    async def aclose(self):
        """Release transport resources."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()

    async def _send(self, method, url, headers, body, timeout):
        raise NotImplementedError


class ThreadedAsyncClient(AsyncHttpClient):
    """Run a blocking ``HttpClient`` in an executor.

    The wrapped client's retry policy and rate limiter apply, because its
    whole send loop runs in the worker thread (its sleeps block that thread,
    not the event loop).
    """

    def __init__(self, sync_client, executor=None):
        super().__init__(sync_client.base_url, sync_client.headers, sync_client.timeout,
                         sync_client.auth)
        self.sync_client = sync_client
        self.executor = executor

    async def _send(self, method, url, headers, body, timeout):
        loop = asyncio.get_running_loop()
        call = partial(self.sync_client._send_with_retries, method, url, headers, body, timeout)
        return await loop.run_in_executor(self.executor, call)

    async def aclose(self):
        self.sync_client.close()


class AsyncHttpxClient(AsyncHttpClient):
    def __init__(self, client=None, **kwargs):
        super().__init__(**kwargs)
        if client is None:
            import httpx  # lazy: only needed when the caller did not inject a client
            client = httpx.AsyncClient()
        self.client = client

    async def _send(self, method, url, headers, body, timeout):
        try:
            resp = await self.client.request(method, url, headers=headers, content=body,
                                             timeout=timeout)
        except Exception as exc:
            if is_library_error(exc, "httpx"):
                raise TransportError("%s: %s" % (type(exc).__name__, exc), url=url) from None
            raise
        return Response(resp.status_code, list(resp.headers.items()), resp.content, url)

    async def aclose(self):
        close = getattr(self.client, "aclose", None)
        if close:
            await close()
