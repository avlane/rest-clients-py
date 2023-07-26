"""Server-side idempotency: remember the outcome of a keyed request and replay it.

A client that times out cannot know whether its POST was processed. With an
``Idempotency-Key`` it can simply send the same request again, provided the
server stores the first outcome under that key. This is the store.

``begin(key, fingerprint)`` answers one of:

* ``NEW``: first time; the caller does the work, then calls ``complete``;
* ``REPLAY``: a finished request with the same payload; reuse ``entry.response``;
* ``CONFLICT``: the key was used with a *different* payload (a client bug);
* ``IN_PROGRESS``: the first attempt has not finished (answer 409, retry later).
"""
import hashlib
import threading
import time

NEW = "new"
REPLAY = "replay"
CONFLICT = "conflict"
IN_PROGRESS = "in_progress"


class Entry:
    def __init__(self, fingerprint, created):
        self.fingerprint = fingerprint
        self.created = created
        self.response = None            # set by complete()


def fingerprint_of(method, path, body):
    """Stable digest of what makes two requests "the same"."""
    h = hashlib.sha256()
    for part in (method.upper().encode(), path.encode(), body or b""):
        h.update(len(part).to_bytes(8, "big"))
        h.update(part)
    return h.hexdigest()


class IdempotencyStore:
    def __init__(self, ttl=24 * 3600, clock=time.time):
        self.ttl = ttl
        self._clock = clock
        self._entries = {}
        self._lock = threading.Lock()

    def begin(self, key, fingerprint):
        now = self._clock()
        with self._lock:
            self._entries = {k: e for k, e in self._entries.items() if now - e.created < self.ttl}
            entry = self._entries.get(key)
            if entry is None:
                self._entries[key] = Entry(fingerprint, now)
                return NEW, None
            if entry.fingerprint != fingerprint:
                return CONFLICT, entry
            if entry.response is None:
                return IN_PROGRESS, entry
            return REPLAY, entry

    def complete(self, key, response):
        """Store the outcome of a request that ``begin`` reported as NEW."""
        with self._lock:
            self._entries[key].response = response

    def abandon(self, key):
        """The work failed before any outcome existed; let the client try again."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.response is None:
                del self._entries[key]

    def __len__(self):
        return len(self._entries)
