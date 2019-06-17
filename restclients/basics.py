"""The plain standard-library way: urllib.request plus json.

Everything later in the package is a refinement of this one function.
"""
import json
import urllib.request
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

USER_AGENT = "rest-clients-py/0.1"


def build_url(url, params=None):
    """Append ``params`` to the query string of ``url``.

    Existing query parameters are kept. ``None`` values are dropped and lists
    become repeated parameters (``tag=a&tag=b``).
    """
    if not params:
        return url
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pairs.extend((key, str(v)) for v in value)
        elif isinstance(value, bool):
            pairs.append((key, "true" if value else "false"))
        else:
            pairs.append((key, str(value)))
    return urlunsplit(parts._replace(query=urlencode(pairs)))


def get_json(url, params=None, headers=None, timeout=10):
    """GET ``url`` and return the decoded JSON body."""
    send_headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    send_headers.update(headers or {})
    req = urllib.request.Request(build_url(url, params), headers=send_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return json.loads(raw.decode(charset))
