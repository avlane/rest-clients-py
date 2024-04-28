"""Server-Sent Events (the ``text/event-stream`` format) over a streaming response.

The parser follows the WHATWG HTML standard's "event stream interpretation":
``data:`` lines accumulate (joined with newlines), a blank line dispatches the
event, ``:`` lines are comments (used as keep-alives), ``id:`` and ``retry:`` are
remembered, and a field without a colon has an empty value.
"""
import time

from restclients.errors import TransportError
from restclients.streaming import iter_lines


class SseEvent:
    def __init__(self, event, data, id=None, retry=None):
        self.event = event          # "message" unless the stream said otherwise
        self.data = data
        self.id = id
        self.retry = retry          # reconnection time (ms) in force when the event was dispatched

    def __eq__(self, other):
        return (isinstance(other, SseEvent)
                and (self.event, self.data, self.id, self.retry) == (other.event, other.data, other.id, other.retry))

    def __repr__(self):
        return "SseEvent(%r, %r, id=%r)" % (self.event, self.data, self.id)


def parse_sse(lines):
    """Turn an iterable of byte or text lines (no line endings) into :class:`SseEvent` objects.

    Like a browser's EventSource, the ``id`` last seen stays in force for later events
    until a new ``id`` replaces it, and a ``retry`` takes effect as soon as it is read
    (even in an event that has no data and is therefore not dispatched), staying in
    force for the rest of the stream. An event with no ``data`` lines is not dispatched.
    """
    event_type, data, last_id, retry = "", [], None, None
    first = True
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        if first:
            line = line.lstrip("﻿")        # a leading byte order mark is ignored
            first = False
        if line == "":
            if data:
                yield SseEvent(event_type or "message", "\n".join(data), last_id, retry)
            event_type, data = "", []
            continue
        if line.startswith(":"):
            continue
        name, sep, value = line.partition(":")
        if sep and value.startswith(" "):
            value = value[1:]
        if name == "event":
            event_type = value
        elif name == "data":
            data.append(value)
        elif name == "id":
            if "\0" not in value:
                last_id = value
        elif name == "retry":
            if value.isdigit():
                retry = int(value)
        # unknown fields are ignored, as the standard says


def iter_sse(client, path, params=None, last_event_id=None, headers=None):
    """Stream events from one connection. Ends when the server closes the stream."""
    headers = dict(headers or {})
    headers["Accept"] = "text/event-stream"
    headers["Cache-Control"] = "no-cache"
    if last_event_id is not None:
        headers["Last-Event-ID"] = str(last_event_id)
    with client.stream("GET", path, params=params, headers=headers) as resp:
        for event in parse_sse(iter_lines(resp)):
            yield event


def follow_sse(client, path, params=None, max_reconnects=5, default_retry_ms=1000, sleep=time.sleep,
               last_event_id=None):
    """Like :func:`iter_sse` but reconnects when the stream breaks, resuming with ``Last-Event-ID``.

    A stream that ends cleanly (the server closed it) ends the iteration; a broken one
    (``TransportError``) reconnects up to ``max_reconnects`` times, waiting the server's
    ``retry`` interval between attempts. The error is re-raised when the budget is spent.
    """
    reconnects = 0
    retry_ms = default_retry_ms
    while True:
        try:
            for event in iter_sse(client, path, params, last_event_id):
                reconnects = 0                         # a healthy stream earns a fresh budget
                if event.id is not None:
                    last_event_id = event.id
                if event.retry is not None:
                    retry_ms = event.retry
                yield event
            return
        except TransportError:
            reconnects += 1
            if reconnects > max_reconnects:
                raise
            sleep(retry_ms / 1000.0)
