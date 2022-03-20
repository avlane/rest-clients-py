"""PKCE (RFC 7636) helpers for the OAuth2 authorization-code flow.

A public client (a CLI or a single-page app) cannot keep a client secret.
PKCE replaces it with a one-time secret: the client invents a random
``code_verifier``, sends only its hash (the ``code_challenge``) when it starts
the flow, and reveals the verifier when it redeems the authorization code. An
attacker who steals the code cannot redeem it without the verifier.
"""
import base64
import hashlib
import secrets
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

_VERIFIER_ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def generate_code_verifier(nbytes=64):
    """A random verifier of 43-128 characters (``nbytes`` of entropy, base64url encoded)."""
    if not 32 <= nbytes <= 96:
        raise ValueError("nbytes must be between 32 and 96 to give a 43-128 character verifier")
    return secrets.token_urlsafe(nbytes)


def code_challenge(verifier, method="S256"):
    """Derive the challenge sent in the authorization request."""
    if not 43 <= len(verifier) <= 128 or set(verifier) - _VERIFIER_ALPHABET:
        raise ValueError("verifier must be 43-128 characters from [A-Za-z0-9-._~]")
    if method == "plain":
        return verifier
    if method != "S256":
        raise ValueError("unsupported code_challenge_method %r" % method)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_state():
    """Random ``state`` value; compare it on the redirect to defeat CSRF."""
    return secrets.token_urlsafe(24)


def authorization_url(endpoint, client_id, redirect_uri, scope=None, state=None, verifier=None,
                      method="S256", extra=None):
    """The URL to send the user to. Pass ``verifier`` to add the PKCE parameters."""
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri}
    if scope:
        params["scope"] = scope if isinstance(scope, str) else " ".join(scope)
    if state:
        params["state"] = state
    if verifier:
        params["code_challenge"] = code_challenge(verifier, method)
        params["code_challenge_method"] = method
    params.update(extra or {})
    parts = urlsplit(endpoint)
    query = parse_qsl(parts.query, keep_blank_values=True) + list(params.items())
    return urlunsplit(parts._replace(query=urlencode(query)))
