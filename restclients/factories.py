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


def make_httpx_client(max_connections=100, max_keepalive_connections=20, **client_options):
    """An ``httpx.Client`` with explicit connection limits."""
    import httpx

    limits = httpx.Limits(max_connections=max_connections,
                          max_keepalive_connections=max_keepalive_connections)
    return httpx.Client(limits=limits, **client_options)


def make_aiohttp_session(limit=100, limit_per_host=0, **session_options):
    """An ``aiohttp.ClientSession`` with a sized connector.

    Call it from inside a running event loop: the session binds to the loop it
    is created in. ``limit_per_host=0`` means no per-host cap.
    """
    import aiohttp

    connector = aiohttp.TCPConnector(limit=limit, limit_per_host=limit_per_host)
    return aiohttp.ClientSession(connector=connector, **session_options)
