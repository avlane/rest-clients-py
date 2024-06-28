"""Optimistic concurrency: read, change, write back only if nobody else changed it meanwhile.

The server labels each version of a resource with an ETag. Writing with
``If-Match: <etag>`` succeeds only if the resource still has that version;
otherwise the server answers ``412 Precondition Failed`` and we read again and
redo our change on top of the newer data.
"""

from restclients.errors import PreconditionFailed


class ConflictRetriesExhausted(PreconditionFailed):
    """Every attempt lost the race against another writer."""


def update_resource(client, path, change, method="PUT", max_attempts=5, on_conflict=None):
    """Read ``path``, apply ``change(data) -> new data`` and write it back conditionally.

    ``change`` may be called several times (once per attempt), so it must not have side effects
    other than building the new value. Returns the server's response to the successful write.
    Raises :class:`ConflictRetriesExhausted` when ``max_attempts`` were all beaten by other writers
    (the last 412 is attached as ``__cause__``), or any other error unchanged.
    """
    last = None
    for attempt in range(1, max_attempts + 1):
        current = client.get(path)
        etag = current.headers.get("ETag")
        if etag is None:
            raise ValueError("%s sends no ETag, so it cannot be updated conditionally" % path)
        updated = change(current.json())
        try:
            return client.request(method, path, json=updated, headers={"If-Match": etag})
        except PreconditionFailed as exc:
            last = exc
            if on_conflict is not None:
                on_conflict(attempt, exc)
    raise ConflictRetriesExhausted("gave up on %s after %d conflicting attempt(s)" % (path, max_attempts),
                                   status=412, url=path) from last
