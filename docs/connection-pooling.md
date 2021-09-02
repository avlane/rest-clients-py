# Connection pooling notes

Opening a TCP connection costs a round trip; a TLS handshake on top costs one or
two more. A client that opens a fresh connection per request pays that every
time. A pool keeps connections open (HTTP/1.1 keep-alive) and reuses them.

| library | pooling object | defaults worth knowing |
|---|---|---|
| `urllib.request` | none | every `urlopen` call connects and closes |
| `requests` | `Session` (via `HTTPAdapter`) | pools for 10 hosts, 10 connections each |
| `httpx` | `Client` / `AsyncClient` | `Limits`: 100 connections, 20 kept alive |
| `aiohttp` | `ClientSession` (via `TCPConnector`) | 100 connections total, no per-host cap |

## Rules of thumb

* Create one session or client and reuse it. `requests.get(...)` in a loop
  builds a throwaway `Session` every call, which defeats the pool.
* Size the pool to the concurrency you actually use. With `requests` and N
  threads, set `pool_maxsize >= N`; otherwise surplus connections are opened and
  thrown away.
* Close what you open (`with` blocks, or `close()` / `aclose()`).
* An aiohttp session belongs to the event loop it was created in.
* Servers close idle connections. A pooled connection can be stale, so
  idempotent requests should be retried on a reset (`RetryPolicy` does this).

## In this repo

`restclients/factories.py` builds sized sessions for requests, httpx and
aiohttp. They are tested for wiring, with stand-in modules. The urllib client has no pool; a keep-alive
transport built on `http.client` (which can be tested for real) follows.
