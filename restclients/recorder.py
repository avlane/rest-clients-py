"""Record real HTTP interactions to a JSON "cassette" (VCR-style).

``RecordingClient`` wraps any other client, passes every request through to it
and appends what happened to a :class:`Cassette`. A recorded cassette can later
be replayed without the network (see ``ReplayClient``). It is hand-written and
much smaller than vcrpy, but it works the same way and is easy to read.

Credentials never reach the file: header values and secret-looking query
parameters are redacted *before* storing.
"""
import base64
import json
import os
import tempfile

from restclients.client import HttpClient
from restclients.errors import ApiError
from restclients.logging_utils import redact_headers, redact_url
from restclients.response import Response

FORMAT_VERSION = 1


def encode_body(body):
    """JSON-friendly form of a body: ``{"text": ...}`` when it is UTF-8, else base64."""
    if not body:
        return {"text": ""}
    try:
        return {"text": body.decode("utf-8")}
    except UnicodeDecodeError:
        return {"base64": base64.b64encode(body).decode("ascii")}


def decode_body(stored):
    if "base64" in stored:
        return base64.b64decode(stored["base64"])
    return stored.get("text", "").encode("utf-8")


class Interaction:
    def __init__(self, method, url, request_headers, request_body, status, response_headers,
                 response_body):
        self.method = method
        self.url = url                          # already redacted
        self.request_headers = request_headers  # already redacted
        self.request_body = request_body        # bytes
        self.status = status
        self.response_headers = response_headers  # list of [name, value]
        self.response_body = response_body      # bytes

    def to_dict(self):
        return {
            "request": {"method": self.method, "url": self.url,
                        "headers": self.request_headers, "body": encode_body(self.request_body)},
            "response": {"status": self.status, "headers": self.response_headers,
                         "body": encode_body(self.response_body)},
        }

    @classmethod
    def from_dict(cls, data):
        req, resp = data["request"], data["response"]
        return cls(req["method"], req["url"], req.get("headers", {}), decode_body(req["body"]),
                   resp["status"], resp["headers"], decode_body(resp["body"]))


class Cassette:
    def __init__(self, path=None, interactions=None):
        self.path = path
        self.interactions = list(interactions or [])

    @classmethod
    def load(cls, path):
        """Load ``path``; a missing file gives an empty cassette (nothing recorded yet)."""
        if not os.path.exists(path):
            return cls(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") != FORMAT_VERSION:
            raise ValueError("unsupported cassette version %r in %s" % (data.get("version"), path))
        return cls(path, [Interaction.from_dict(i) for i in data["interactions"]])

    def append(self, interaction):
        self.interactions.append(interaction)

    def save(self, path=None):
        """Write atomically (temp file + rename) so a crash cannot leave half a cassette."""
        path = path or self.path
        if path is None:
            raise ValueError("this cassette has no path")
        payload = {"version": FORMAT_VERSION,
                   "interactions": [i.to_dict() for i in self.interactions]}
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def __len__(self):
        return len(self.interactions)


class RecordingClient(HttpClient):
    """Pass requests to ``inner`` and record each exchange on ``cassette``.

    Recording happens at the transport level (below retries and caching), so a
    request that was retried produces one interaction per attempt.
    """

    def __init__(self, inner, cassette, **kwargs):
        kwargs.setdefault("timeout", inner.timeout)
        super().__init__(**kwargs)
        self.inner = inner
        self.cassette = cassette

    def _send(self, method, url, headers, body, timeout):
        response = self.inner._send(method, url, headers, body, timeout)
        self.cassette.append(Interaction(
            method, redact_url(url), redact_headers(headers), body or b"", response.status,
            [[k, v] for k, v in response.headers.items()], response.content))
        return response

    def close(self):
        if self.cassette.path:
            self.cassette.save()
        self.inner.close()


class NoMatchingInteraction(ApiError):
    """Replay was asked for a request that is not in the cassette.

    Deliberately not a TransportError, so retry policies do not retry it.
    """


def _normalize_body(body):
    """Compare JSON bodies by value (key order and whitespace do not matter)."""
    if not body:
        return b""
    try:
        return json.dumps(json.loads(body.decode("utf-8")), sort_keys=True).encode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return body


class ReplayClient(HttpClient):
    """Answer requests from a cassette without touching the network.

    A request matches a recorded interaction when ``match_on`` agrees; the
    first unused match is served and then marked used, so a recorded
    503-then-200 sequence replays in order. ``allow_playback_repeats=True``
    serves the same interaction again instead.
    """

    def __init__(self, cassette, match_on=("method", "url"), allow_playback_repeats=False, **kwargs):
        super().__init__(**kwargs)
        self.cassette = cassette
        self.match_on = tuple(match_on)
        self.allow_playback_repeats = allow_playback_repeats
        self._used = set()

    def _key(self, method, url, body):
        parts = []
        for name in self.match_on:
            if name == "method":
                parts.append(method)
            elif name == "url":
                parts.append(redact_url(url))
            elif name == "body":
                parts.append(_normalize_body(body or b""))
            else:
                raise ValueError("cannot match on %r" % name)
        return tuple(parts)

    def _send(self, method, url, headers, body, timeout):
        wanted = self._key(method, url, body)
        for index, interaction in enumerate(self.cassette.interactions):
            if index in self._used and not self.allow_playback_repeats:
                continue
            if self._key(interaction.method, interaction.url, interaction.request_body) == wanted:
                self._used.add(index)
                return Response(interaction.status, [tuple(h) for h in interaction.response_headers],
                                interaction.response_body, url)
        raise NoMatchingInteraction("no recorded interaction for %s %s (matching on %s)"
                                    % (method, redact_url(url), ", ".join(self.match_on)), url=url)

    def unused(self):
        """Recorded interactions that were never requested."""
        return [i for n, i in enumerate(self.cassette.interactions) if n not in self._used]

    def assert_all_used(self):
        leftovers = self.unused()
        if leftovers:
            raise AssertionError("%d recorded interaction(s) were never replayed: %s" % (
                len(leftovers), ", ".join("%s %s" % (i.method, i.url) for i in leftovers)))


def cassette_client(path, inner=None, mode="once", **kwargs):
    """Pick record or replay from the cassette file, like vcrpy's record modes.

    * ``"once"`` (default): replay if ``path`` exists, otherwise record to it.
    * ``"none"``: only replay; a missing file or request is an error.
    * ``"all"``: always record, replacing the file when the client is closed.

    ``inner`` is the real client used for recording (not needed for ``"none"``).
    """
    if mode not in ("once", "none", "all"):
        raise ValueError("unknown mode %r" % mode)
    exists = os.path.exists(path)
    if mode == "none" and not exists:
        raise FileNotFoundError("cassette %s does not exist and mode is 'none'" % path)
    if mode == "all" or (mode == "once" and not exists):
        if inner is None:
            raise ValueError("recording needs an inner client")
        return RecordingClient(inner, Cassette(path), **kwargs)
    return ReplayClient(Cassette.load(path), **kwargs)
