# API overview

`import restclients` is cheap: the names below load their module on first use.

```python
from restclients import UrllibClient, RetryPolicy, BearerAuth, paginate_links, NotFound

client = UrllibClient(base_url="https://api.example.test", auth=BearerAuth(token),
                      retry=RetryPolicy(max_attempts=4), timeout=(3, 10), deadline=30)
try:
    for item in paginate_links(client, "/items"):
        ...
except NotFound:
    ...
```

## Choosing a client

| class | needs | notes |
|---|---|---|
| `UrllibClient` | nothing | redirects with a safe policy, proxies from the environment; a connection per request |
| `KeepAliveClient` | nothing | pooled keep-alive connections; no proxy support |
| `RequestsClient(session)` | `requests` | pass your own `Session` (or `OAuth2Session`) |
| `HttpxClient(client)` | `httpx` | optional HTTP/2 |
| `AsyncStreamsClient` | nothing | native asyncio, minimal |
| `AsyncHttpxClient`, `AiohttpClient` | `httpx`, `aiohttp` | async |
| `ThreadedAsyncClient(sync_client)` | nothing | any blocking client from an event loop |

All sync clients share `HttpClient`'s keyword options: `base_url`, `headers`, `timeout`, `auth`,
`retry`, `rate_limiter`, `cache`, `breaker`, `deadline`, `idempotency_header`,
`follow_rate_limit_headers`, `logger`. The async clients take `retry`, `rate_limiter` and `breaker`.

## Errors

`ApiError` is the root. `TransportError` (no response; `DeadlineExceeded` is a subclass) and
`HttpStatusError` (`ClientError`: `NotFound`, `Unauthorized`, `RateLimited`, `PreconditionFailed`...;
`ServerError`) split what went wrong. `CircuitOpen`, `ValidationError`, `PaginationLoop`, `OAuthError` and
`ConfigError` are also `ApiError`s. Error responses expose `.status`, `.headers`, `.data`, `.problem`
(RFC 9457) and `.challenges` (`WWW-Authenticate`).

## Everything else

Not in the top-level namespace but documented in the README layout: the recorder and replay clients,
webhooks and signatures, the OpenAPI generator, streaming helpers (NDJSON, SSE, downloads, uploads),
`update_resource`, the benchmark harness and `build_client` for TOML configuration.
