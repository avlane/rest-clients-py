"""Helpers that turn a paginated endpoint into one flat iterator of items.

All of them take an ``HttpClient`` (any transport) and yield items lazily, so
callers can stop early without fetching every page.
"""

import re

_TOKEN = re.compile(r"[^\s;,=<>\"]+")


def _scan_links(value):
    """Yield ``(url, {param: value})`` for each link in an RFC 8288 header.

    A small scanner instead of a regex split: quoted-string parameter values may
    contain commas, semicolons and ``<``, which a split on commas would cut apart.
    """
    pos, n = 0, len(value)
    while pos < n:
        while pos < n and value[pos] in " \t,":
            pos += 1
        if pos >= n:
            return
        if value[pos] != "<":
            # malformed: skip to the next comma outside quotes
            pos = _skip_junk(value, pos)
            continue
        end = value.find(">", pos)
        if end == -1:
            return
        url, pos, params = value[pos + 1:end], end + 1, {}
        while pos < n:
            while pos < n and value[pos] in " \t":
                pos += 1
            if pos >= n or value[pos] == ",":
                break
            if value[pos] != ";":
                pos = _skip_junk(value, pos)
                break
            pos += 1
            while pos < n and value[pos] in " \t":
                pos += 1
            match = _TOKEN.match(value, pos)
            if not match:
                continue
            name, pos = match.group(0).lower(), match.end()
            while pos < n and value[pos] in " \t":
                pos += 1
            param = ""
            if pos < n and value[pos] == "=":
                pos += 1
                while pos < n and value[pos] in " \t":
                    pos += 1
                if pos < n and value[pos] == '"':
                    pos += 1
                    chars = []
                    while pos < n and value[pos] != '"':
                        if value[pos] == "\\" and pos + 1 < n:
                            pos += 1
                        chars.append(value[pos])
                        pos += 1
                    pos += 1  # closing quote
                    param = "".join(chars)
                else:
                    bare = _TOKEN.match(value, pos)
                    if bare:
                        param, pos = bare.group(0), bare.end()
            params.setdefault(name, param)
        yield url, params


def _skip_junk(value, pos):
    in_quotes = False
    while pos < len(value):
        char = value[pos]
        if char == '"':
            in_quotes = not in_quotes
        elif char == "," and not in_quotes:
            return pos
        pos += 1
    return pos


def parse_link_header(value):
    """Parse an RFC 8288 ``Link`` header into ``{rel: url}``.

    A link whose ``rel`` lists several relations (``rel="prev next"``) is
    registered under each of them. If the same relation appears twice the first
    one wins. Links without a ``rel`` are ignored. Returns ``{}`` for an empty
    or missing header.
    """
    links = {}
    if not value:
        return links
    for url, params in _scan_links(value):
        for rel in params.get("rel", "").lower().split():
            links.setdefault(rel, url)
    return links


def paginate_links(client, path, params=None, items_key=None, max_pages=None):
    """Follow ``rel="next"`` links until the server stops sending one."""
    response = client.get(path, params=params)
    fetched = 1
    while True:
        body = response.json()
        items = body if items_key is None else body.get(items_key, [])
        for item in items:
            yield item
        next_url = parse_link_header(response.headers.get("Link")).get("next")
        if not next_url or (max_pages is not None and fetched >= max_pages):
            return
        response = client.get(next_url)  # absolute URL: params are already in it
        fetched += 1


def paginate_pages(client, path, params=None, limit=10, items_key="items",
                   start_page=1, max_pages=None, page_param="page", limit_param="limit"):
    """Walk a ``?page=N&limit=M`` API.

    The response is either a JSON list or an object holding the list under
    ``items_key``. Iteration stops on an empty page, a short page, or when an
    envelope's ``total`` has been reached.
    """
    page = start_page
    seen = 0
    fetched = 0
    while max_pages is None or fetched < max_pages:
        query = dict(params or {})
        query[page_param] = page
        query[limit_param] = limit
        body = client.get_json(path, params=query)
        items = body if isinstance(body, list) else body.get(items_key, [])
        for item in items:
            yield item
        seen += len(items)
        fetched += 1
        total = body.get("total") if isinstance(body, dict) else None
        if not items or len(items) < limit or (total is not None and seen >= total):
            return
        page += 1


def _dig(data, dotted, default=None):
    """``_dig({"a": {"b": 1}}, "a.b")`` -> 1."""
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return default
        data = data[part]
    return data


def paginate_cursor(client, path, params=None, items_key="data", next_key="meta.next_cursor",
                    cursor_param="cursor", max_pages=None):
    """Walk a cursor API: send back the opaque token the server gave us.

    ``next_key`` may be dotted for nested envelopes. A missing, null or empty
    token ends the walk.
    """
    cursor = None
    fetched = 0
    while max_pages is None or fetched < max_pages:
        query = dict(params or {})
        if cursor:
            query[cursor_param] = cursor
        body = client.get_json(path, params=query)
        for item in _dig(body, items_key, []):
            yield item
        fetched += 1
        cursor = _dig(body, next_key)
        if not cursor:
            return
