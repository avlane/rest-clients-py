"""A small HTTP response store for conditional requests.

It does not decide freshness. Every GET is revalidated with ``If-None-Match``
(from the stored ``ETag``) and/or ``If-Modified-Since`` (from ``Last-Modified``),
and the server answers ``304 Not Modified`` (no body) when nothing changed, which
saves bandwidth and parsing. Entries are kept in LRU order.

ETags are the better validator (they are exact); ``Last-Modified`` has one-second
resolution, so two changes inside the same second look identical. When a response has
both, both validators are sent and the server gives ``If-None-Match`` precedence.
"""
import re
import time
from collections import OrderedDict
from email.utils import parsedate_to_datetime

from restclients.response import Headers, Response

_MAX_AGE = re.compile(r"(?:^|[\s,])max-age\s*=\s*\"?(\d+)", re.I)


def cache_control_directives(value):
    """Lowercased directive names in a Cache-Control value, e.g. {"no-cache", "max-age"}."""
    return {part.split("=", 1)[0].strip().lower() for part in (value or "").split(",") if part.strip()}


def freshness_lifetime(headers, now):
    """Seconds a stored response may be reused without asking the server, or 0 if none.

    ``Cache-Control: max-age`` wins; otherwise ``Expires`` minus ``Date``; ``no-cache`` and
    ``max-age=0`` mean "always revalidate". (No heuristic freshness from Last-Modified.)
    """
    control = headers.get("Cache-Control", "")
    directives = cache_control_directives(control)
    if "no-cache" in directives:
        return 0.0
    match = _MAX_AGE.search(control)
    if match:
        return float(match.group(1))
    expires = headers.get("Expires")
    if expires:
        try:
            expiry = parsedate_to_datetime(expires)
            date = headers.get("Date")
            base = parsedate_to_datetime(date).timestamp() if date else now
            return max(0.0, expiry.timestamp() - base)
        except (TypeError, ValueError):
            return 0.0          # an invalid Expires means "already expired"
    return 0.0


class CacheEntry:
    def __init__(self, status, headers, content, url, stored_at=0.0, lifetime=0.0, age=0.0):
        self.stored_at = stored_at
        self.lifetime = lifetime
        self.initial_age = age
        self.status = status
        self.headers = list(headers)
        self.content = content
        self.url = url
        lookup = dict((k.lower(), v) for k, v in self.headers)
        self.etag = lookup.get("etag")
        self.last_modified = lookup.get("last-modified")


class ResponseCache:
    def __init__(self, max_entries=256, clock=time.time):
        self.max_entries = max_entries
        self._clock = clock
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
        if entry is not None:
            if entry.etag:
                headers["If-None-Match"] = entry.etag
            if entry.last_modified:
                headers["If-Modified-Since"] = entry.last_modified
        return headers

    def store(self, key, response):
        """Remember a 200 response that has an ETag or Last-Modified. Returns True if stored."""
        if response.status != 200 or ("etag" not in response.headers
                                      and "last-modified" not in response.headers):
            return False
        if "no-store" in response.headers.get("Cache-Control", "").lower():
            return False
        now = self._clock()
        self._entries[key] = CacheEntry(response.status, response.headers.items(), response.content,
                                        response.url, now, freshness_lifetime(response.headers, now),
                                        self._age_header(response.headers))
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        self.stores += 1
        return True

    @staticmethod
    def _age_header(headers):
        value = headers.get("Age", "")
        return float(value) if value.isdigit() else 0.0

    def fresh(self, key):
        """The stored response if it can be reused without contacting the server, else None.

        Age is the time since we stored it plus any ``Age`` the response arrived with.
        """
        entry = self._entries.get(key)
        if entry is None:
            return None
        age = (self._clock() - entry.stored_at) + entry.initial_age
        if age >= entry.lifetime:
            return None
        self._entries.move_to_end(key)
        self.hits += 1
        response = Response(entry.status, dict(entry.headers), entry.content, entry.url)
        response.from_cache = True
        response.age = age
        return response

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
        # a 304 carries fresh caching headers: the entry is young again
        now = self._clock()
        entry.headers = list(merged.items())
        entry.stored_at = now
        entry.initial_age = self._age_header(Headers(merged))
        entry.lifetime = freshness_lifetime(Headers(merged), now)
        response = Response(entry.status, merged, entry.content, entry.url)
        response.from_cache = True
        return response

    def drop(self, key):
        self._entries.pop(key, None)

    def clear(self):
        self._entries.clear()
