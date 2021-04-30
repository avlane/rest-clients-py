# urllib vs requests vs httpx vs aiohttp

Notes written while adding the fourth client. Behaviour listed is for the
versions in `requirements.txt` as of this writing (requests 2.25, httpx 0.18,
aiohttp 3.7). "Executed here" says whether this repo's tests ever ran the real
library; see the README for the full list.

| | `urllib.request` | `requests` | `httpx` | `aiohttp` |
|---|---|---|---|---|
| installed | standard library | third party | third party | third party |
| sync / async | sync | sync | both (`Client`, `AsyncClient`) | async only |
| connection pooling | none (a new connection per call) | `Session` | `Client` | `ClientSession` |
| default timeout | none (waits forever) | none (waits forever) | 5 seconds | 5 minutes total |
| redirects followed by default | yes | yes (not for `HEAD`) | yes in 0.18 (`allow_redirects`) | yes |
| error status | raises `HTTPError` | returns the response; `raise_for_status()` raises | returns the response; `raise_for_status()` raises | returns the response; `raise_for_status=True` option |
| JSON body out | `json.loads(resp.read())` | `resp.json()` | `resp.json()` | `await resp.json()` |
| JSON body in | encode it yourself | `json=` | `json=` | `json=` |
| raw body argument | `data=` | `data=` | `content=` (`data=` is for forms) | `data=` |
| streaming | `resp.read(n)` in a loop | `stream=True`, `iter_content` | `client.stream(...)`, `iter_bytes` | `resp.content.iter_chunked(n)` |
| HTTP/2 | no | no | optional (`httpx[http2]`) | no |
| executed in this repo's tests | **yes**, over real sockets | no, fake session | no, fake client | no, fake session |

## Where the libraries disagree in ways that bite

* **Timeouts.** The two most popular libraries wait forever unless told
  otherwise. `HttpClient` therefore always passes one.
* **Status errors.** `urllib` raises for 4xx/5xx, the others do not. The shared
  `Response.raise_for_status()` makes all four behave the same.
* **Reading the body.** aiohttp only lets you read the body while the response
  context manager is open; the other three hand you a finished response.
* **Exceptions.** Each library has its own hierarchy (`URLError`,
  `requests.RequestException`, `httpx.RequestError`, `aiohttp.ClientError`).
  Every client here turns those into `TransportError`, detecting them by module
  name so the library does not have to be imported.

## How this repo hides the differences

`HttpClient` (sync) and `AsyncHttpClient` (async) build the request once; a
subclass only implements `_send(method, url, headers, body, timeout)` and returns
the shared `Response`. Retries, rate limiting, caching, auth and pagination are
written against that interface, so they work with any of the four.
