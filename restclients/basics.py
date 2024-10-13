"""The plain standard-library way: urllib.request plus json.

``get_json`` started life as a 5 line function using urlopen directly. It is
now a thin wrapper over :class:`UrllibClient`, which keeps the same behaviour
(and the same tests) while sharing code with the requests-based client.
"""
from restclients._compat import deprecated
from restclients.urllib_client import UrllibClient
from restclients.urls import build_url  # noqa: F401  (re-exported)


@deprecated("restclients.basics.get_json is a learning example; use "
            "UrllibClient(...).get_json(...) for retries, auth, caching and the rest")
def get_json(url, params=None, headers=None, timeout=10):
    """GET ``url`` and return the decoded JSON body."""
    return UrllibClient(headers=headers, timeout=timeout).get_json(url, params=params)
