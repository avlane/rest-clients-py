"""Helpers that turn a paginated endpoint into one flat iterator of items.

All of them take an ``HttpClient`` (any transport) and yield items lazily, so
callers can stop early without fetching every page.
"""


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
