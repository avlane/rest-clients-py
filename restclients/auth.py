"""Authentication helpers.

An auth object has one method, ``apply(headers)``, which adds whatever the
scheme needs to the outgoing header dict. Clients call it for every request.
"""
import base64
import hashlib
import os
import re
import threading
from urllib.parse import urlsplit


class BasicAuth:
    """HTTP Basic (RFC 7617): ``Authorization: Basic base64(user:password)``."""

    def __init__(self, username, password):
        self.username = username
        self._password = password

    def apply(self, headers):
        raw = ("%s:%s" % (self.username, self._password)).encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")

    def __repr__(self):
        return "BasicAuth(%r, '***')" % self.username


class BearerAuth:
    """Bearer token (RFC 6750). ``token`` may be a string or a zero-argument callable.

    A callable is evaluated on every request, which is how short-lived tokens
    can be refreshed without rebuilding the client.
    """

    def __init__(self, token):
        self._token = token

    @property
    def token(self):
        return self._token() if callable(self._token) else self._token

    def apply(self, headers):
        headers["Authorization"] = "Bearer " + self.token

    def __repr__(self):
        return "BearerAuth('***')"


class ApiKeyAuth:
    """A static key in a header (default ``X-API-Key``)."""

    def __init__(self, key, header="X-API-Key"):
        self.key = key
        self.header = header

    def apply(self, headers):
        headers[self.header] = self.key

    def __repr__(self):
        return "ApiKeyAuth(header=%r)" % self.header


_CHALLENGE_PARAM = re.compile(r'([A-Za-z0-9_-]+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^\s,]+))')


def parse_digest_challenge(value):
    """Parameters of a ``WWW-Authenticate: Digest ...`` header, or None if it is not a Digest challenge."""
    if not value:
        return None
    match = re.search(r"(?i)\bDigest\s+", value)
    if not match:
        return None
    params = {}
    for name, quoted, bare in _CHALLENGE_PARAM.findall(value[match.end():]):
        params.setdefault(name.lower(), re.sub(r"\\(.)", r"\1", quoted) if quoted else bare)
    return params if "nonce" in params and "realm" in params else None


_DIGESTS = {"md5": "md5", "sha-256": "sha256", "sha-512-256": "sha512_256"}


class DigestAuth:
    """HTTP Digest authentication (RFC 7616) with ``qop=auth``.

    Digest is challenge-response: the first request goes out unauthenticated, the server
    answers 401 with a nonce, and the client repeats the request with a hash of the
    credentials and that nonce. ``HttpClient`` does that retry automatically (via
    :meth:`handle_challenge`); later requests reuse the nonce with an increasing counter,
    so only the first costs a round trip. MD5, SHA-256 and the ``-sess`` variants are
    supported; ``auth-int`` (body hashing) is not.
    """

    def __init__(self, username, password, cnonce_factory=None):
        self.username = username
        self._password = password
        self._cnonce_factory = cnonce_factory or (lambda: os.urandom(8).hex())
        self._challenge = None
        self._nonce_count = 0
        self._lock = threading.Lock()

    def __repr__(self):
        return "DigestAuth(%r, '***')" % self.username

    def apply(self, headers):
        """Digest needs the request's method and URI; ``HttpClient`` calls :meth:`sign` instead."""

    def handle_challenge(self, response_headers):
        """Record the server's challenge from a 401. True if retrying with it can help.

        False when the 401 repeats the nonce we already answered without ``stale=true``: the
        credentials themselves were refused, and resending would just be refused again.
        """
        challenge = parse_digest_challenge(response_headers.get("WWW-Authenticate"))
        if challenge is None:
            return False
        with self._lock:
            known = self._challenge
            stale = challenge.get("stale", "").lower() == "true"
            if known is not None and challenge["nonce"] == known["nonce"] and not stale:
                return False
            self._challenge = challenge
            self._nonce_count = 0
        return True

    def sign(self, headers, method, url):
        with self._lock:
            challenge = self._challenge
            if challenge is None:
                return                                  # nothing to answer yet
            self._nonce_count += 1
            count = self._nonce_count
        headers["Authorization"] = self._header(challenge, method, url, count, self._cnonce_factory())

    def _header(self, challenge, method, url, count, cnonce):
        algorithm = challenge.get("algorithm", "MD5")
        base = algorithm.lower()
        session = base.endswith("-sess")
        if session:
            base = base[:-5]
        if base not in _DIGESTS:
            raise ValueError("unsupported Digest algorithm %r" % algorithm)

        def H(text):
            return hashlib.new(_DIGESTS[base], text.encode("utf-8"), usedforsecurity=False).hexdigest()

        parts = urlsplit(url)
        uri = (parts.path or "/") + ("?" + parts.query if parts.query else "")
        realm, nonce = challenge["realm"], challenge["nonce"]
        qops = [q.strip() for q in challenge.get("qop", "").split(",") if q.strip()]
        use_qop = "auth" in qops
        ha1 = H("%s:%s:%s" % (self.username, realm, self._password))
        if session:
            ha1 = H("%s:%s:%s" % (ha1, nonce, cnonce))
        ha2 = H("%s:%s" % (method, uri))
        nc = "%08x" % count
        if use_qop:
            response = H("%s:%s:%s:%s:auth:%s" % (ha1, nonce, nc, cnonce, ha2))
        else:
            response = H("%s:%s:%s" % (ha1, nonce, ha2))     # the RFC 2069 form, no counter
        fields = [("username", self.username, True), ("realm", realm, True), ("nonce", nonce, True),
                  ("uri", uri, True), ("algorithm", algorithm, False), ("response", response, True)]
        if challenge.get("opaque") is not None:
            fields.append(("opaque", challenge["opaque"], True))
        if use_qop:
            fields += [("qop", "auth", False), ("nc", nc, False), ("cnonce", cnonce, True)]
        return "Digest " + ", ".join(
            '%s="%s"' % (k, v.replace("\\", "\\\\").replace('"', '\\"')) if quoted else "%s=%s" % (k, v)
            for k, v, quoted in fields)
