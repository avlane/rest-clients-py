"""HMAC signatures for webhooks: signing, and verifying in constant time.

Scheme used here (the same shape as Stripe's): the sender computes
``HMAC-SHA256(secret, "<timestamp>.<raw body>")`` and sends

    X-Signature: t=1685300000,v1=<hex digest>

* the **raw bytes** of the body are signed: re-serialising parsed JSON changes
  whitespace and key order and breaks the signature;
* the timestamp is part of the signed text and is checked against a tolerance,
  so a captured delivery cannot be replayed hours later;
* several ``v1=`` values may be present, and the receiver may hold several
  secrets, which allows rotating a secret without dropping deliveries;
* digests are compared with ``hmac.compare_digest``, never ``==``.

``verify_github_signature`` handles the simpler ``X-Hub-Signature-256: sha256=<hex>``
scheme (no timestamp).
"""
import hashlib
import hmac
import time

from restclients.webhooks import WebhookRejected

DEFAULT_HEADER = "X-Signature"
DEFAULT_TOLERANCE = 300


def _digest(secret, timestamp, body):
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    message = str(int(timestamp)).encode("ascii") + b"." + body
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def sign(secret, body, timestamp=None):
    """Header value for ``body`` (bytes)."""
    timestamp = int(time.time() if timestamp is None else timestamp)
    return "t=%d,v1=%s" % (timestamp, _digest(secret, timestamp, body))


def parse_signature_header(value):
    """``"t=123,v1=aa,v1=bb"`` -> ``(123, ["aa", "bb"])``; raises ValueError if malformed."""
    timestamp, digests = None, []
    for part in value.split(","):
        key, sep, val = part.strip().partition("=")
        if not sep:
            raise ValueError("malformed signature header")
        if key == "t":
            timestamp = int(val)
        elif key == "v1":
            digests.append(val)
    if timestamp is None or not digests:
        raise ValueError("signature header needs t= and at least one v1=")
    return timestamp, digests


def header_value(headers, name):
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


class ReplayGuard:
    """Remembers recent signatures so an identical delivery is accepted only once."""

    def __init__(self, ttl=DEFAULT_TOLERANCE * 2, clock=time.time):
        self.ttl = ttl
        self._clock = clock
        self._seen = {}

    def check(self, signature):
        """Return True the first time ``signature`` is seen within the ttl."""
        now = self._clock()
        self._seen = {s: t for s, t in self._seen.items() if now - t < self.ttl}
        if signature in self._seen:
            return False
        self._seen[signature] = now
        return True


class HmacVerifier:
    """Callable for ``WebhookReceiver(verifier=...)``.

    ``secrets`` is one secret or a list (current first, then older ones still
    accepted during a rotation).
    """

    def __init__(self, secrets, header=DEFAULT_HEADER, tolerance=DEFAULT_TOLERANCE,
                 clock=time.time, replay_guard=None):
        self.secrets = [secrets] if isinstance(secrets, (str, bytes)) else list(secrets)
        if not self.secrets:
            raise ValueError("at least one secret is required")
        self.header = header
        self.tolerance = tolerance
        self._clock = clock
        self.replay_guard = replay_guard

    def __call__(self, headers, body):
        value = header_value(headers, self.header)
        if value is None:
            raise WebhookRejected("missing %s header" % self.header, 401)
        try:
            timestamp, digests = parse_signature_header(value)
        except ValueError as exc:
            raise WebhookRejected(str(exc), 400) from None
        if abs(self._clock() - timestamp) > self.tolerance:
            raise WebhookRejected("timestamp outside the tolerance window", 401)
        matched = False
        for secret in self.secrets:
            expected = _digest(secret, timestamp, body)
            for candidate in digests:
                # evaluate every comparison (no early exit) so timing does not reveal which matched
                matched |= hmac.compare_digest(expected.encode("ascii"), candidate.encode("utf-8", "replace"))
        if not matched:
            raise WebhookRejected("signature mismatch", 401)
        if self.replay_guard is not None and not self.replay_guard.check(value):
            raise WebhookRejected("duplicate delivery", 409)


def verify_github_signature(secret, header, body):
    """True if ``header`` (``sha256=<hex>``) matches ``body``."""
    if not header or not header.startswith("sha256="):
        return False
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode("ascii"), header.encode("utf-8", "replace"))
