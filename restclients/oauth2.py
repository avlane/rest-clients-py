"""OAuth 2.0 client-credentials grant (RFC 6749 section 4.4).

``ClientCredentials`` is an auth object: pass it as ``auth=`` to any client and
it fetches, caches and renews an access token on demand. The token endpoint is
called through an injected ``HttpClient``, so any transport works.
"""
import threading
import time
from urllib.parse import quote_plus

from restclients.errors import ApiError
from restclients.urllib_client import UrllibClient


class OAuthError(ApiError):
    """The authorization server refused to issue a token."""

    def __init__(self, error, description=None, status=None):
        message = error if not description else "%s: %s" % (error, description)
        super().__init__(message, status=status)
        self.error = error
        self.description = description


class Token:
    def __init__(self, access_token, token_type="Bearer", expires_at=None, scope=None):
        self.access_token = access_token
        self.token_type = token_type
        self.expires_at = expires_at
        self.scope = scope

    def expired(self, now, leeway=0.0):
        return self.expires_at is not None and now >= self.expires_at - leeway

    def __repr__(self):
        return "Token(type=%r, expires_at=%r)" % (self.token_type, self.expires_at)


class ClientCredentials:
    def __init__(self, token_url, client_id, client_secret, scope=None, http=None,
                 clock=time.time, leeway=30.0, send_credentials_in_body=False):
        self.token_url = token_url
        self.client_id = client_id
        self._client_secret = client_secret
        self.scope = scope
        self.http = http or UrllibClient()
        self._clock = clock
        self.leeway = leeway
        self.send_credentials_in_body = send_credentials_in_body
        self._token = None
        self._lock = threading.Lock()

    def token(self):
        """A valid access token, requesting a new one if needed."""
        with self._lock:
            if self._token is None or self._token.expired(self._clock(), self.leeway):
                self._token = self._fetch()
            return self._token

    def invalidate(self):
        """Forget the cached token (e.g. after the API answered 401)."""
        with self._lock:
            self._token = None

    def apply(self, headers):
        token = self.token()
        headers["Authorization"] = "%s %s" % (token.token_type.capitalize(), token.access_token)

    def _fetch(self):
        form = {"grant_type": "client_credentials"}
        if self.scope:
            form["scope"] = self.scope if isinstance(self.scope, str) else " ".join(self.scope)
        headers = {}
        if self.send_credentials_in_body:
            form["client_id"] = self.client_id
            form["client_secret"] = self._client_secret
        else:
            # client_secret_basic: id and secret are form-urlencoded *before* base64 (RFC 6749 2.3.1)
            from restclients.auth import BasicAuth
            BasicAuth(quote_plus(self.client_id), quote_plus(self._client_secret)).apply(headers)
        response = self.http.request("POST", self.token_url, form=form, headers=headers,
                                     raise_for_status=False)
        try:
            data = response.json()
        except ApiError:
            data = None
        if response.status >= 400 or not isinstance(data, dict) or "access_token" not in data:
            if isinstance(data, dict) and "error" in data:
                raise OAuthError(data["error"], data.get("error_description"), response.status)
            raise OAuthError("invalid_token_response", "HTTP %s" % response.status, response.status)
        expires_in = data.get("expires_in")
        expires_at = self._clock() + float(expires_in) if expires_in is not None else None
        return Token(data["access_token"], data.get("token_type", "Bearer"), expires_at,
                     data.get("scope"))
