# rest-clients-py

Notes and code from learning how to consume REST APIs from Python: first with
the standard library (`urllib.request` and `json`), then with the HTTP
libraries people actually reach for (`requests`, `httpx`, `aiohttp`), plus the
practical parts around them: pagination, retries, rate limits, caching, auth,
streaming, typed models and record/replay fixtures.

## How the code is tested

The code for `requests`, `httpx`, `aiohttp` and `requests-oauthlib` is imported lazily, every
client takes an injected session, and the tests use fakes for them. So:

| code path | how it is tested |
|---|---|
| `urllib.request` (`UrllibClient`, `basics`) | **for real**, over sockets, against a local `ThreadingHTTPServer` |
| `http.client` (`KeepAliveClient`) | **for real**: connection reuse, pool limits, stale-connection recovery (the server counts TCP connections) |
| `asyncio` (`ThreadedAsyncClient`, `gather_bounded`) | **for real**: the urllib client driven from an event loop against the local server |
| everything transport independent (retries, rate limiting, caching, pagination, auth, OAuth2, PKCE, streaming, uploads, recorder, config) | **for real**, through the urllib client and the local server |
| `requests` (`RequestsClient`) | **fakes**: a fake session records the call and returns canned responses. |
| `httpx` (`HttpxClient`, `AsyncHttpxClient`) | **fakes** |
| `aiohttp` (`AiohttpClient`) | **fakes** |
| `requests-oauthlib`, and the pool-sizing factories in `factories.py` | **wiring**: stand-in modules in `sys.modules` check which arguments are passed where |

`tests/server.py` serves JSON, three kinds of pagination, Basic/Bearer/API key
challenges, flaky 503s, 429s with `Retry-After`, dropped connections, ETags,
redirects, byte ranges, multipart uploads and a small OAuth2 server (client
credentials, authorization code with PKCE, refresh tokens).

Run the tests with `python3 -m unittest discover`.

## Layout

- `restclients/basics.py` the plain `urllib.request` + `json` function this started as
- `restclients/client.py` `HttpClient`: base URL, default headers, JSON/form/multipart bodies,
  status checks, retries, rate limiting, ETag caching, auth, request IDs and logging
- `restclients/urllib_client.py`, `keepalive_client.py`, `requests_client.py`, `httpx_client.py`
  the synchronous transports
- `restclients/async_client.py`, `aiohttp_client.py`, `concurrency.py` the async transports and bounded gather
- `restclients/errors.py` one exception class per kind of failure
- `restclients/pagination.py` page/limit, `Link` header and cursor iterators
- `restclients/retry.py`, `ratelimit.py`, `etag_cache.py`
- `restclients/auth.py`, `oauth2.py`, `pkce.py`, `loopback.py` Basic/Bearer/API key, client credentials,
  authorization code with PKCE and a loopback redirect listener
- `restclients/streaming.py`, `multipart.py`, `uploads.py` downloads (with resume) and uploads
- `restclients/models.py`, `validation.py` dataclass models and payload validation
- `restclients/base.py` `ApiClient`, the base class for per-API clients (see `examples/items_client.py`)
- `restclients/logging_utils.py` JSON log formatter and secret redaction
- `restclients/recorder.py` VCR-style `RecordingClient` / `ReplayClient` with scrubbing
- `restclients/config.py` build a client from a TOML file
- `restclients/testing.py` fake sessions for tests that must not touch the network
- `restclients/openapi.py`, `openapi_gen.py` read an OpenAPI 3 JSON file and generate a client with models
- `restclients/webhooks.py`, `signatures.py`, `webhook_sender.py` webhook receiver, HMAC verification and signed delivery
- `restclients/idempotency.py`, `breaker.py`, `bulk.py` idempotency store, circuit breaker, batched bulk posts
- `docs/` library comparison, connection pooling, OAuth2 PKCE, webhooks and idempotency notes
- `tools/record_fixtures.py` regenerates `tests/fixtures/`

## A taste

```python
from restclients.urllib_client import UrllibClient
from restclients.retry import RetryPolicy
from restclients.auth import BearerAuth
from restclients.pagination import paginate_links

client = UrllibClient(base_url="https://api.example.test", auth=BearerAuth("..."),
                      retry=RetryPolicy(max_attempts=4), timeout=(3, 10))
for item in paginate_links(client, "/items", params={"per_page": 50}):
    print(item["name"])
```

Swap `UrllibClient` for `RequestsClient(session)` or `HttpxClient(client)` and
nothing else changes.

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

**Redirects.** `UrllibClient` follows redirects with an explicit policy:
307/308 keep the method and body, 301/302/303 turn POST into GET, and
`Authorization`/`Cookie` are dropped when the host changes.

**Secrets.** Logs and cassettes redact `Authorization`, cookies, API keys and
secret-looking query parameters and JSON keys. Config files name environment
variables for secrets and never hold them.
