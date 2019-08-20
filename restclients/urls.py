"""URL helpers."""
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl


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


def join_url(base_url, path):
    """Join a base URL and a path; absolute URLs in ``path`` win."""
    if path.startswith(("http://", "https://")):
        return path
    if not base_url:
        return path
    return base_url.rstrip("/") + "/" + path.lstrip("/")
