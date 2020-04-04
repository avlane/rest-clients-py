"""A small HTTP response store for conditional requests.

It does not decide freshness. Every GET is revalidated with ``If-None-Match``
and the server answers ``304 Not Modified`` (no body) when nothing changed,
which saves bandwidth and parsing. Entries are kept in LRU order.
"""
from collections import OrderedDict

from restclients.response import Response


class CacheEntry:
    def __init__(self, status, headers, content, url):
        self.status = status
        self.headers = list(headers)
        self.content = content
        self.url = url
        lookup = dict((k.lower(), v) for k, v in self.headers)
        self.etag = lookup.get("etag")
        self.last_modified = lookup.get("last-modified")


class ResponseCache:
    def __init__(self, max_entries=256):
        self.max_entries = max_entries
        self._entries = OrderedDict()
        self.hits = 0      # 304 answered from a stored body
        self.stores = 0

    def __len__(self):
        return len(self._entries)

    def __contains__(self, key):
        return key in self._entries

    def get(self, key):
        entry = self._entries.get(key)
        if entry is not None:
            self._entries.move_to_end(key)
        return entry

    def conditional_headers(self, key):
        """Request headers that ask the server to skip the body if unchanged."""
        entry = self.get(key)
        headers = {}
        if entry is not None and entry.etag:
            headers["If-None-Match"] = entry.etag
        return headers

    def store(self, key, response):
        """Remember a 200 response that has an ETag. Returns True if stored."""
        if response.status != 200 or "etag" not in response.headers:
            return False
        if "no-store" in response.headers.get("Cache-Control", "").lower():
            return False
        self._entries[key] = CacheEntry(response.status, response.headers.items(),
                                        response.content, response.url)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        self.stores += 1
        return True

    def revalidated(self, key, not_modified):
        """Build the full response for a 304: stored body, headers refreshed by the 304."""
        entry = self._entries[key]
        merged = dict((k, v) for k, v in entry.headers)
        lowered = dict((k.lower(), k) for k in merged)
        for name, value in not_modified.headers.items():
            if name.lower() in ("content-length", "transfer-encoding", "connection"):
                continue
            merged.pop(lowered.get(name.lower(), name), None)
            merged[name] = value
        self.hits += 1
        response = Response(entry.status, merged, entry.content, entry.url)
        response.from_cache = True
        return response

    def drop(self, key):
        self._entries.pop(key, None)

    def clear(self):
        self._entries.clear()
