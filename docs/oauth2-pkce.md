# OAuth2 authorization code + PKCE: notes

`restclients/oauth2.py` covers the *client credentials* grant: a service
authenticating as itself. Acting on behalf of a user needs the authorization
code grant, and for public clients (no safe place for a secret) that means PKCE
([RFC 7636](https://www.rfc-editor.org/rfc/rfc7636)).

## The flow

1. Generate a `code_verifier` (random, 43-128 chars) and a `state`.
2. Send the user's browser to the authorization endpoint with
   `response_type=code`, `client_id`, `redirect_uri`, `scope`, `state`,
   `code_challenge=BASE64URL(SHA256(verifier))` and `code_challenge_method=S256`.
3. The user signs in and consents; the server redirects to `redirect_uri` with
   `?code=...&state=...`. Check `state` matches what you sent.
4. POST to the token endpoint: `grant_type=authorization_code`, `code`,
   `redirect_uri`, `client_id` and the original `code_verifier`.
5. The server hashes the verifier and compares it to the stored challenge. If
   they match you get an access token (and usually a refresh token).

`restclients/pkce.py` implements steps 1 and 2 with the standard library and is
checked against the test vector in RFC 7636 appendix B.

## Using requests-oauthlib instead

`requests-oauthlib` wraps a `requests.Session` and handles most of this
(`authorization_url`, `fetch_token`, token refresh). It has its own PKCE support
in newer releases; check the changelog of the version you install. It also
needs `requests`. `RequestsClient` accepts any session object, so
an `OAuth2Session` can be passed in as is.

## Gotchas

* Loopback redirect URIs (`http://127.0.0.1:<port>/callback`) are the usual way
  for a CLI to receive the code. Start the listener *before* opening the browser.
* Use `S256`. `plain` exists only for clients that cannot hash.
* Keep refresh tokens as secret as passwords. An access token is short-lived by
  design; a refresh token is not.
