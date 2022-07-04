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
from restclients.logging_utils import redact_headers, redact_url

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
