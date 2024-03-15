# HTTP/2 notes

**Nothing in this repo speaks HTTP/2 on the wire.** The standard library's
`http.client` and `urllib` are HTTP/1.1 only and the test server is HTTP/1.1. The only code is the option that asks httpx for HTTP/2 (`http2=True`).

## What changes compared with HTTP/1.1

| | HTTP/1.1 | HTTP/2 |
|---|---|---|
| concurrent requests per connection | one at a time (pipelining is not used in practice) | many, as interleaved streams |
| connections to one origin | a pool of several (see `KeepAliveClient`) | normally one |
| headers | repeated in full on every request | compressed with HPACK; repeated headers cost almost nothing |
| negotiation | none | `h2` via ALPN during the TLS handshake (browsers and most clients require TLS) |
| head-of-line blocking | per connection, in the HTTP layer | gone at the HTTP layer, but one lost TCP packet still stalls every stream (HTTP/3 moves to QUIC for that) |

## What it means for client code

* **Connection pool sizing mostly stops mattering** for one origin: a single
  connection carries all the concurrent requests. A concurrency limit is still
  needed so you do not open thousands of streams at once; servers advertise
  `SETTINGS_MAX_CONCURRENT_STREAMS` (often 100) and a client queues beyond that.
  `gather_bounded` remains the right tool.
* **The benchmarks in `docs/benchmarks.md` do not transfer.** They compare
  HTTP/1.1 strategies. HTTP/2 mainly helps when there are many small requests
  to one TLS origin over a link with real latency.
* **Retries and idempotency are unchanged**: HTTP/2 is a transport detail, the
  semantics of methods and status codes are the same.
* **Debugging gets harder**: it is binary, so `curl --http2 -v`, the browser dev
  tools or a proxy are how you look at it.

## Library support (as of this writing)

* `httpx`: opt in with `httpx.Client(http2=True)`; needs the `h2` package, i.e.
  `pip install "httpx[http2]"`. The server must also agree to it, otherwise the
  client silently uses HTTP/1.1. Check `response.http_version`.
* `requests`: HTTP/1.1 only.
* `aiohttp`: the client is HTTP/1.1 only.
* `urllib`, `http.client`: HTTP/1.1 only.

In this repo: `HttpxClient(http2=True)`, `AsyncHttpxClient(http2=True)` and
`factories.make_httpx_client(http2=True)` pass the flag through when they build
the underlying client. The `http2` extra in `pyproject.toml` installs the
dependency. Whether a given server ends up speaking `h2` can only be seen against
a real server with the real library.
