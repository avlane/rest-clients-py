"""A native-asyncio HTTP/1.1 client written on ``asyncio.open_connection``.

It exists so the async code paths (retries, limiter, breaker, bounded concurrency) can run
against a real socket with nothing installed, and to show what an async HTTP library does
underneath. It is deliberately minimal and **not** a replacement for aiohttp or httpx:

* one connection per request (``Connection: close``), no pooling or keep-alive;
* no redirects, no proxies, no compression, no cookies;
* bodies framed by ``Content-Length``, ``Transfer-Encoding: chunked`` or end of stream.
"""
import asyncio
import ssl
from urllib.parse import urlsplit

from restclients.async_client import AsyncHttpClient
from restclients.errors import TransportError
from restclients.response import Response

_NO_BODY_STATUSES = frozenset([204, 304])
_MAX_LINE = 65536


def _timeouts(timeout):
    """(connect, read) seconds from a number, a pair, or None."""
    if isinstance(timeout, (tuple, list)):
        return timeout[0], timeout[1]
    return timeout, timeout


class AsyncStreamsClient(AsyncHttpClient):
    def __init__(self, ssl_context=None, **kwargs):
        super().__init__(**kwargs)
        self._ssl_context = ssl_context

    async def _send(self, method, url, headers, body, timeout):
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise TransportError("unsupported URL scheme %r" % parts.scheme, url=url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        target = (parts.path or "/") + ("?" + parts.query if parts.query else "")
        connect_timeout, read_timeout = _timeouts(timeout)
        use_ssl = (self._ssl_context or ssl.create_default_context()) if parts.scheme == "https" else None
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(parts.hostname, port, ssl=use_ssl), connect_timeout)
            writer.write(self._request_bytes(method, target, parts, headers, body))
            await writer.drain()
            return await asyncio.wait_for(self._read_response(reader, method, url), read_timeout)
        except asyncio.TimeoutError:
            raise TransportError("timed out talking to %s" % url, url=url) from None
        except (OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError) as exc:
            raise TransportError("%s while talking to %s" % (exc or type(exc).__name__, url), url=url) from None
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass        # the peer may already have gone away

    @staticmethod
    def _request_bytes(method, target, parts, headers, body):
        lines = ["%s %s HTTP/1.1" % (method, target), "Host: %s" % parts.netloc.rpartition("@")[2]]
        sent = {k.lower() for k in headers}
        for name, value in headers.items():
            lines.append("%s: %s" % (name, value))
        if "connection" not in sent:
            lines.append("Connection: close")
        if body is not None and "content-length" not in sent:
            lines.append("Content-Length: %d" % len(body))
        elif body is None and method in ("POST", "PUT", "PATCH") and "content-length" not in sent:
            lines.append("Content-Length: 0")
        return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + (body or b"")

    async def _read_response(self, reader, method, url):
        status_line = await reader.readuntil(b"\r\n")
        try:
            _, status, _ = status_line.decode("latin-1").split(" ", 2)
            status = int(status)
        except ValueError:
            raise TransportError("malformed status line from %s: %r" % (url, status_line[:60]), url=url) from None
        headers = []
        while True:
            line = await reader.readuntil(b"\r\n")
            if line == b"\r\n":
                break
            name, sep, value = line.decode("latin-1").partition(":")
            if not sep:
                raise TransportError("malformed header from %s: %r" % (url, line[:60]), url=url)
            headers.append((name.strip(), value.strip()))
        lookup = {k.lower(): v for k, v in headers}
        if method == "HEAD" or status in _NO_BODY_STATUSES or 100 <= status < 200:
            content = b""
        elif lookup.get("transfer-encoding", "").lower() == "chunked":
            content = await self._read_chunked(reader)
        elif "content-length" in lookup:
            content = await reader.readexactly(int(lookup["content-length"]))
        else:
            content = await reader.read()           # delimited by the server closing the connection
        return Response(status, headers, content, url)

    @staticmethod
    async def _read_chunked(reader):
        out = []
        while True:
            size_line = await reader.readuntil(b"\r\n")
            size = int(size_line.split(b";")[0].strip(), 16)
            if size == 0:
                while (await reader.readuntil(b"\r\n")) != b"\r\n":
                    pass                            # trailers, ignored
                return b"".join(out)
            out.append(await reader.readexactly(size))
            await reader.readexactly(2)             # the CRLF after each chunk
