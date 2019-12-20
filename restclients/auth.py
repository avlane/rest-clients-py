"""Authentication helpers.

An auth object has one method, ``apply(headers)``, which adds whatever the
scheme needs to the outgoing header dict. Clients call it for every request.
"""
import base64


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
