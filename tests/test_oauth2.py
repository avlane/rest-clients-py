import unittest

from restclients.errors import Unauthorized
from restclients.oauth2 import ClientCredentials, OAuthError
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ClientCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.clock = Clock()

    def tearDown(self):
        self.server.__exit__(None, None, None)

    def creds(self, **kwargs):
        kwargs.setdefault("client_secret", "shh")
        return ClientCredentials(self.server.url + "/oauth/token", "svc-reports",
                                 clock=self.clock, **kwargs)

    def test_fetches_token_and_signs_requests(self):
        creds = self.creds()
        api = UrllibClient(base_url=self.server.url, auth=creds)
        self.assertEqual(api.get_json("/oauth/me"), {"client": "svc-reports"})
        self.assertEqual(creds.token().access_token, "at-1")

    def test_token_is_cached(self):
        creds = self.creds()
        api = UrllibClient(base_url=self.server.url, auth=creds)
        api.get("/oauth/me")
        api.get("/oauth/me")
        self.assertEqual(self.server.counters["tokens-issued"], 1)

    def test_token_is_renewed_before_it_expires(self):
        self.server.httpd.token_ttl = 100
        creds = self.creds(leeway=30)
        first = creds.token().access_token
        self.clock.now += 60          # 40 s left, outside the 30 s leeway
        self.assertEqual(creds.token().access_token, first)
        self.clock.now += 20          # 20 s left, inside the leeway
        self.assertNotEqual(creds.token().access_token, first)
        self.assertEqual(self.server.counters["tokens-issued"], 2)

    def test_credentials_in_body_variant(self):
        creds = self.creds(send_credentials_in_body=True)
        self.assertEqual(creds.token().access_token, "at-1")

    def test_scope_is_sent(self):
        creds = self.creds(scope=["read", "write"])
        self.assertEqual(creds.token().scope, "read write")

    def test_wrong_secret(self):
        with self.assertRaises(OAuthError) as ctx:
            self.creds(client_secret="wrong").token()
        self.assertEqual(ctx.exception.error, "invalid_client")
        self.assertEqual(ctx.exception.status, 401)

    def test_special_characters_in_secret_survive_encoding(self):
        creds = ClientCredentials(self.server.url + "/oauth/token", "svc-reports",
                                  "p:w d", clock=self.clock)
        with self.assertRaises(OAuthError):  # wrong secret, but it must reach the server intact
            creds.token()
        sent = [h for m, p, h in self.server.requests if p == "/oauth/token"][0]
        self.assertTrue(sent["Authorization"].startswith("Basic "))

    def test_unprotected_call_is_rejected(self):
        with self.assertRaises(Unauthorized):
            UrllibClient(base_url=self.server.url).get("/oauth/me")

    def test_invalidate_forces_a_new_token(self):
        creds = self.creds()
        creds.token()
        creds.invalidate()
        self.assertEqual(creds.token().access_token, "at-2")


if __name__ == "__main__":
    unittest.main()
