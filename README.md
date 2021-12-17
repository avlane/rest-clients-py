# rest-clients-py

Notes and code from learning how to consume REST APIs from Python: first with
the standard library (`urllib.request` and `json`), then with the HTTP
libraries people actually reach for.

## How the code is tested

`tests/server.py` starts a real HTTP server (`ThreadingHTTPServer`) on
localhost. It serves JSON, three kinds of pagination, Basic/Bearer/API key
challenges, flaky 503s, 429s with `Retry-After`, dropped connections, ETags
and an OAuth2 token endpoint.

| code path | how it is tested |
|---|---|
| `urllib.request` (`UrllibClient`, `basics`) | for real, over sockets, against the local server |
| `requests` (`RequestsClient`) | **against a fake session** |
| `httpx` (`HttpxClient`, `AsyncHttpxClient`) | **against fakes** |
| `aiohttp` (`AiohttpClient`) | **against a fake session** |
| `asyncio` (`ThreadedAsyncClient`, `gather_bounded`) | for real: the urllib client driven from an event loop against the local server |
| `http.client` (`KeepAliveClient`) | for real: connection reuse, pool limits and stale-connection recovery against the local server (which counts TCP connections) |
| `requests`/`httpx`/`aiohttp` pool factories (`factories.py`) | wiring, with stand-in modules in `sys.modules` |

Everything that is not transport specific (retries, rate limiting, caching,
pagination, auth, OAuth2) lives in `HttpClient` and the helper modules, so the
real-server tests exercise it through the urllib client, and the fake-session
tests check that the requests client shares it.

See `docs/library-comparison.md` for how the four libraries differ.

Run the tests with `python3 -m unittest discover`.

## Layout

- `restclients/basics.py` the plain `urllib.request` + `json` function
- `restclients/client.py` `HttpClient`: base URL, default headers, JSON and form bodies,
  status checks, retries, rate limiting, ETag caching, auth
- `restclients/urllib_client.py`, `requests_client.py`, `httpx_client.py` the sync transports
- `restclients/keepalive_client.py` pooled keep-alive client on `http.client`
- `restclients/async_client.py`, `aiohttp_client.py` the async transports; `concurrency.py` bounded gather
- `restclients/streaming.py`, `multipart.py`, `uploads.py` downloads (with resume) and uploads
- `docs/` library comparison and connection pooling notes
- `restclients/errors.py` one exception class per kind of failure
- `restclients/pagination.py` page/limit, `Link` header and cursor iterators
- `restclients/retry.py` backoff with jitter and `Retry-After` parsing
- `restclients/ratelimit.py` token bucket
- `restclients/etag_cache.py` response store for `If-None-Match`
- `restclients/auth.py`, `restclients/oauth2.py` Basic, Bearer, API key, client credentials
- `restclients/base.py` `ApiClient`, a base class for per-API clients (see `examples/`)
- `restclients/testing.py` fake sessions for tests that must not touch the network

## Notes

**Timeouts.** `requests` has no default timeout: a call without `timeout=` can
hang forever. `HttpClient` always has one. A `(connect, read)` pair is passed
straight to `requests`; `urllib` has one socket timeout, so it uses the larger
value.

**Retries.** `RetryPolicy` retries `GET`, `HEAD`, `PUT`, `DELETE` and `OPTIONS`
on connection errors and on 429/500/502/503/504, with exponential backoff and
full jitter. `POST` is not retried, because repeating it could do the work twice.
A `Retry-After` header (seconds or HTTP-date) raises the wait; if it asks for
longer than `max_retry_after` the error is raised instead.

**Caching.** `ResponseCache` revalidates every GET with `If-None-Match`; a 304
is answered from the stored body. It does not do freshness lifetimes.
