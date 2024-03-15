"""Build tuned sessions/clients for the third-party libraries.

Each factory imports its library lazily. Tests substitute stand-in modules in
``sys.modules`` to check the wiring (what is passed where).
"""


def make_requests_session(pool_connections=10, pool_maxsize=10, max_retries=0):
    """A ``requests.Session`` with a sized connection pool.

    ``pool_connections`` is how many different hosts get a pool;
    ``pool_maxsize`` is how many connections each of those pools may keep.
    Set ``pool_maxsize`` to at least the number of threads sharing the session,
    or the extra threads open and discard connections ("Connection pool is full").
    """
    import requests
    from requests.adapters import HTTPAdapter

    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=pool_connections, pool_maxsize=pool_maxsize,
                          max_retries=max_retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def make_httpx_client(max_connections=100, max_keepalive_connections=20, http2=False,
                      **client_options):
    """An ``httpx.Client`` with explicit connection limits.

    ``http2=True`` lets the client negotiate HTTP/2 with servers that support it
    (see docs/http2.md); it needs ``pip install "httpx[http2]"``.
    """
    import httpx

    limits = httpx.Limits(max_connections=max_connections,
                          max_keepalive_connections=max_keepalive_connections)
    client_options.setdefault("follow_redirects", True)  # httpx 0.20+ defaults to False
    if http2:
        client_options["http2"] = True
    return httpx.Client(limits=limits, **client_options)


def make_aiohttp_session(limit=100, limit_per_host=0, **session_options):
    """An ``aiohttp.ClientSession`` with a sized connector.

    Call it from inside a running event loop: the session binds to the loop it
    is created in. ``limit_per_host=0`` means no per-host cap.
    """
    import aiohttp

    connector = aiohttp.TCPConnector(limit=limit, limit_per_host=limit_per_host)
    return aiohttp.ClientSession(connector=connector, **session_options)


def make_oauthlib_session(client_id, token, token_url, client_secret=None, scope=None,
                          token_saver=None):
    """A ``requests_oauthlib.OAuth2Session`` that refreshes its own token.

    The result is a ``requests.Session`` subclass, so it can be handed straight
    to :class:`restclients.requests_client.RequestsClient`. ``token`` is the dict
    the token endpoint returned; ``token_saver(new_token)`` is called after each
    automatic refresh so the caller can persist it.
    """
    from requests_oauthlib import OAuth2Session

    extra = {"client_id": client_id}
    if client_secret:
        extra["client_secret"] = client_secret
    return OAuth2Session(client_id, token=token, scope=scope, auto_refresh_url=token_url,
                         auto_refresh_kwargs=extra, token_updater=token_saver)
