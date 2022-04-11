import unittest

from restclients import pkce
from restclients.errors import Unauthorized
from restclients.oauth2 import OAuthError, UserTokenAuth, exchange_code
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer

REDIRECT = "http://127.0.0.1:8123/callback"


class Clock:
    def __init__(self):
        self.now = 5000.0

    def __call__(self):
        return self.now


class AuthorizationCodeTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.http = UrllibClient(base_url=self.server.url)
        self.token_url = self.server.url + "/oauth/token"
        self.clock = Clock()

    def tearDown(self):
        self.server.__exit__(None, None, None)

    def authorize(self, verifier, state="s1"):
        url = pkce.authorization_url(self.server.url + "/oauth/authorize", "cli-app", REDIRECT,
                                     ["read"], state=state, verifier=verifier)
        result = self.http.get_json(url)
        self.assertEqual(result["state"], state)   # what a real client must check
        return result["code"]

    def login(self):
        verifier = pkce.generate_code_verifier()
        code = self.authorize(verifier)
        return exchange_code(self.token_url, "cli-app", code, REDIRECT, verifier,
                             http=self.http, clock=self.clock)

    def test_full_flow_gives_access_and_refresh_tokens(self):
        token = self.login()
        self.assertTrue(token.refresh_token.startswith("rt-"))
        api = UrllibClient(base_url=self.server.url, auth=UserTokenAuth(
            token, self.token_url, "cli-app", self.http, self.clock))
        self.assertEqual(api.get_json("/oauth/me"), {"client": "cli-app"})

    def test_wrong_verifier_is_rejected(self):
        code = self.authorize(pkce.generate_code_verifier())
        with self.assertRaises(OAuthError) as ctx:
            exchange_code(self.token_url, "cli-app", code, REDIRECT,
                          pkce.generate_code_verifier(), http=self.http)
        self.assertEqual(ctx.exception.error, "invalid_grant")
        self.assertIn("PKCE", ctx.exception.description)

    def test_code_is_single_use(self):
        verifier = pkce.generate_code_verifier()
        code = self.authorize(verifier)
        exchange_code(self.token_url, "cli-app", code, REDIRECT, verifier, http=self.http)
        with self.assertRaises(OAuthError):
            exchange_code(self.token_url, "cli-app", code, REDIRECT, verifier, http=self.http)

    def test_redirect_uri_must_match(self):
        verifier = pkce.generate_code_verifier()
        code = self.authorize(verifier)
        with self.assertRaises(OAuthError):
            exchange_code(self.token_url, "cli-app", code, "http://evil.test/cb", verifier,
                          http=self.http)

    def test_authorize_endpoint_requires_pkce(self):
        from restclients.errors import BadRequest
        with self.assertRaises(BadRequest):
            self.http.get("/oauth/authorize", params={"client_id": "cli-app"})

    def test_expired_token_is_refreshed_and_refresh_token_rotates(self):
        token = self.login()
        first_refresh = token.refresh_token
        auth = UserTokenAuth(token, self.token_url, "cli-app", self.http, self.clock)
        api = UrllibClient(base_url=self.server.url, auth=auth)
        api.get("/oauth/me")
        self.clock.now += 4000                 # past the 3600 s lifetime
        self.assertEqual(api.get_json("/oauth/me"), {"client": "cli-app"})
        self.assertNotEqual(auth.token.refresh_token, first_refresh)
        self.assertEqual(self.server.counters["tokens-issued"], 2)

    def test_401_triggers_refresh_via_invalidate(self):
        token = self.login()
        auth = UserTokenAuth(token, self.token_url, "cli-app", self.http, self.clock)
        api = UrllibClient(base_url=self.server.url, auth=auth)
        api.post("/oauth/revoke-all")           # access token dies server side
        self.assertEqual(api.get_json("/oauth/me"), {"client": "cli-app"})
        self.assertEqual(self.server.counters["tokens-issued"], 2)

    def test_reusing_an_old_refresh_token_fails(self):
        token = self.login()
        old = token.refresh_token
        auth = UserTokenAuth(token, self.token_url, "cli-app", self.http, self.clock)
        self.clock.now += 4000
        auth.apply({})                          # rotates the refresh token
        stale = UserTokenAuth(type(token)("x", expires_at=0, refresh_token=old), self.token_url,
                              "cli-app", self.http, self.clock)
        with self.assertRaises(OAuthError):
            stale.apply({})

    def test_no_refresh_token_means_oauth_error(self):
        from restclients.oauth2 import Token
        auth = UserTokenAuth(Token("a", expires_at=1.0), self.token_url, "cli-app", self.http, self.clock)
        with self.assertRaises(OAuthError):
            auth.apply({})


if __name__ == "__main__":
    unittest.main()
