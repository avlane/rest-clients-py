# rest-clients-py

Notes and code from learning how to consume REST APIs from Python: first with
the standard library (`urllib.request` and `json`), then with the HTTP
libraries people actually reach for.

## Layout

- `restclients/basics.py` the plain `urllib.request` + `json` function
- `restclients/client.py` `HttpClient`: base URL, default headers, JSON bodies, status checks
- `restclients/urllib_client.py` the client on `urllib.request`
- `restclients/requests_client.py` the same client on a `requests` session
- `restclients/errors.py` one exception class per kind of failure
- `tests/` stdlib `unittest` tests; run `python3 -m unittest discover`

## How the code is tested

`tests/server.py` starts a real HTTP server on localhost and the urllib client
talks to it over real sockets. The `requests` client is tested against a fake session (`tests/fakes.py`).

## Notes on timeouts

`requests` has no default timeout: a call without `timeout=` can hang forever.
`HttpClient` always has one. A `(connect, read)` pair is passed straight to
`requests`; `urllib` has one socket timeout, so it uses the larger value.
