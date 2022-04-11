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
    def __init__(self, access_token, token_type="Bearer", expires_at=None, scope=None,
                 refresh_token=None):
        self.access_token = access_token
        self.token_type = token_type
        self.expires_at = expires_at
        self.scope = scope
        self.refresh_token = refresh_token

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
        return request_token(self.http, self.token_url, form, headers, self._clock)


def request_token(http, token_url, form, headers=None, clock=time.time):
    """POST a token request and turn the answer into a :class:`Token`.

    Raises :class:`OAuthError` for an OAuth error response or an unusable body.
    """
    response = http.request("POST", token_url, form=form, headers=headers or {},
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
    expires_at = clock() + float(expires_in) if expires_in is not None else None
    return Token(data["access_token"], data.get("token_type", "Bearer"), expires_at,
                 data.get("scope"), data.get("refresh_token"))


def exchange_code(token_url, client_id, code, redirect_uri, code_verifier, http=None,
                  clock=time.time):
    """Redeem an authorization code (public client with PKCE; no client secret)."""
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": client_id, "code_verifier": code_verifier}
    return request_token(http or UrllibClient(), token_url, form, clock=clock)


class UserTokenAuth:
    """Auth object for a user's token that renews itself with the refresh token.

    Refresh tokens may rotate: if the server returns a new one it replaces the old.
    """

    def __init__(self, token, token_url, client_id, http=None, clock=time.time, leeway=30.0):
        self._token = token
        self.token_url = token_url
        self.client_id = client_id
        self.http = http or UrllibClient()
        self._clock = clock
        self.leeway = leeway
        self._lock = threading.Lock()

    @property
    def token(self):
        return self._token

    def _refresh(self):
        if not self._token.refresh_token:
            raise OAuthError("invalid_grant", "token expired and no refresh token available")
        form = {"grant_type": "refresh_token", "refresh_token": self._token.refresh_token,
                "client_id": self.client_id}
        fresh = request_token(self.http, self.token_url, form, clock=self._clock)
        if not fresh.refresh_token:
            fresh.refresh_token = self._token.refresh_token  # server did not rotate it
        self._token = fresh

    def apply(self, headers):
        with self._lock:
            if self._token.expired(self._clock(), self.leeway):
                self._refresh()
            headers["Authorization"] = "%s %s" % (self._token.token_type.capitalize(),
                                                  self._token.access_token)

    def invalidate(self):
        """The API said 401: refresh on the next apply()."""
        with self._lock:
            self._token.expires_at = 0
