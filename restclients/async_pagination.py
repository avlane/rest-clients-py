"""Async counterparts of the iterators in :mod:`restclients.pagination`.

They take an ``AsyncHttpClient`` and are consumed with ``async for``. Pages are fetched one
at a time and lazily, so breaking out of the loop stops requesting.
"""
from restclients.errors import PaginationLoop
from restclients.pagination import HARD_PAGE_LIMIT, _dig, parse_link_header


async def apaginate_pages(client, path, params=None, limit=10, items_key="items", start_page=1,
                          max_pages=None, page_param="page", limit_param="limit"):
    page, seen, fetched, previous = start_page, 0, 0, None
    while max_pages is None or fetched < max_pages:
        query = dict(params or {})
        query[page_param] = page
        query[limit_param] = limit
        body = await client.get_json(path, params=query)
        items = body if isinstance(body, list) else body.get(items_key, [])
        if items and items == previous:
            raise PaginationLoop("%s returned page %d identical to page %d; the server may be "
                                 "ignoring '%s'" % (path, page, page - 1, page_param))
        if fetched >= HARD_PAGE_LIMIT:
            raise PaginationLoop("%s still has pages after %d requests" % (path, fetched))
        previous = items
        for item in items:
            yield item
        seen += len(items)
        fetched += 1
        total = body.get("total") if isinstance(body, dict) else None
        if not items or len(items) < limit or (total is not None and seen >= total):
            return
        page += 1


async def apaginate_links(client, path, params=None, items_key=None, max_pages=None):
    response = await client.get(path, params=params)
    fetched = 1
    seen = {response.url}
    while True:
        body = response.json()
        items = body if items_key is None else body.get(items_key, [])
        for item in items:
            yield item
        next_url = parse_link_header(response.headers.get("Link")).get("next")
        if not next_url or (max_pages is not None and fetched >= max_pages):
            return
        if next_url in seen:
            raise PaginationLoop("%s links back to a page already fetched: %s" % (path, next_url))
        if fetched >= HARD_PAGE_LIMIT:
            raise PaginationLoop("%s still has a next link after %d pages" % (path, fetched))
        seen.add(next_url)
        response = await client.get(next_url)
        fetched += 1


async def apaginate_cursor(client, path, params=None, items_key="data", next_key="meta.next_cursor",
                           cursor_param="cursor", max_pages=None):
    cursor, fetched, seen = None, 0, set()
    while max_pages is None or fetched < max_pages:
        query = dict(params or {})
        if cursor:
            query[cursor_param] = cursor
        body = await client.get_json(path, params=query)
        for item in _dig(body, items_key, []):
            yield item
        fetched += 1
        cursor = _dig(body, next_key)
        if not cursor:
            return
        if cursor in seen:
            raise PaginationLoop("%s handed out cursor %r twice" % (path, cursor))
        if fetched >= HARD_PAGE_LIMIT:
            raise PaginationLoop("%s still has a next cursor after %d pages" % (path, fetched))
        seen.add(cursor)


async def alist(async_iterable):
    """Collect an async iterator into a list."""
    return [item async for item in async_iterable]
