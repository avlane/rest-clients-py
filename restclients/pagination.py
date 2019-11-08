"""Helpers that turn a paginated endpoint into one flat iterator of items.

All of them take an ``HttpClient`` (any transport) and yield items lazily, so
callers can stop early without fetching every page.
"""

import re

_LINK_SPLIT = re.compile(r",\s*(?=<)")
_LINK_PARAM = re.compile(r';\s*([A-Za-z*][\w*-]*)\s*=\s*(?:"([^"]*)"|([^\s;,]+))')


def parse_link_header(value):
    """Parse an RFC 8288 ``Link`` header into ``{rel: url}``.

    Only the first ``rel`` of each link is kept, and links without a ``rel``
    are ignored. Returns ``{}`` for an empty or missing header.
    """
    links = {}
    if not value:
        return links
    for part in _LINK_SPLIT.split(value.strip()):
        match = re.match(r"\s*<([^>]*)>(.*)", part, re.S)
        if not match:
            continue
        url, rest = match.groups()
        for name, quoted, bare in _LINK_PARAM.findall(rest):
            if name.lower() == "rel":
                rel = (quoted or bare).split()[0].lower()
                links.setdefault(rel, url)
                break
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
