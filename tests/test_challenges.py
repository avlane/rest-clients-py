import unittest

from restclients import errors
from restclients.challenges import find_challenge, parse_www_authenticate
from restclients.oauth2 import ClientCredentials
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class ParserTests(unittest.TestCase):
    def test_bearer_error_from_rfc_6750(self):
        (c,) = parse_www_authenticate('Bearer realm="example", error="invalid_token", '
                                      'error_description="The access token expired"')
        self.assertEqual((c.scheme, c.realm, c.error), ("bearer", "example", "invalid_token"))
        self.assertEqual(c.error_description, "The access token expired")

    def test_scope_with_spaces_and_scheme_case(self):
        (c,) = parse_www_authenticate('BEARER error="insufficient_scope", scope="openid profile email"')
        self.assertEqual((c.scheme, c.scope), ("bearer", "openid profile email"))

    def test_several_challenges_in_one_header(self):
        challenges = parse_www_authenticate('Newauth realm="apps", type=1, title="Login to \\"apps\\"", '
                                            'Basic realm="simple"')
        self.assertEqual([c.scheme for c in challenges], ["newauth", "basic"])
        self.assertEqual(challenges[0].params, {"realm": "apps", "type": "1", "title": 'Login to "apps"'})
        self.assertEqual(challenges[1].realm, "simple")

    def test_digest_with_commas_inside_quoted_values(self):
        (c,) = parse_www_authenticate('Digest realm="a, b", qop="auth,auth-int", nonce="n"')
        self.assertEqual((c.realm, c.params["qop"]), ("a, b", "auth,auth-int"))

    def test_token68(self):
        (c,) = parse_www_authenticate("Negotiate YIIBhgYGKwYBBQUCoIIBejCCAXagJDAiBgkq==")
        self.assertEqual((c.scheme, c.token68, c.params), ("negotiate", "YIIBhgYGKwYBBQUCoIIBejCCAXagJDAiBgkq==", {}))

    def test_bare_scheme(self):
        self.assertEqual([c.scheme for c in parse_www_authenticate("Basic, Negotiate")], ["basic", "negotiate"])

    def test_empty_and_garbage(self):
        self.assertEqual(parse_www_authenticate(None), [])
        self.assertEqual(parse_www_authenticate(""), [])
        self.assertEqual(parse_www_authenticate("= = ="), [])

    def test_find_challenge(self):
        value = 'Basic realm="x", Bearer error="invalid_token"'
        self.assertEqual(find_challenge(value, "BEARER").error, "invalid_token")
        self.assertIsNone(find_challenge(value, "digest"))


class ErrorAndRefreshTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.creds = ClientCredentials(self.server.url + "/oauth/token", "svc-reports", "shh")
        self.api = UrllibClient(base_url=self.server.url, auth=self.creds)

    def test_unauthorized_exposes_its_challenges(self):
        with self.assertRaises(errors.Unauthorized) as ctx:
            UrllibClient(base_url=self.server.url).get("/oauth/me")
        (challenge,) = ctx.exception.challenges
        self.assertEqual((challenge.scheme, challenge.error), ("bearer", "invalid_token"))

    def test_invalid_token_triggers_a_refresh(self):
        self.api.get("/oauth/me")
        self.api.post("/oauth/revoke-all")
        self.api.get("/oauth/me")
        self.assertEqual(self.server.counters["tokens-issued"], 2)

    def test_invalid_request_does_not_trigger_a_pointless_refresh(self):
        with self.assertRaises(errors.Unauthorized) as ctx:
            self.api.get("/oauth/strict")
        self.assertEqual(ctx.exception.challenges[0].error, "invalid_request")
        self.assertEqual(self.server.counters["tokens-issued"], 1)         # no second token was requested
        self.assertEqual(len([r for r in self.server.requests if r[1] == "/oauth/strict"]), 1)

    def test_insufficient_scope_is_reported_with_the_required_scope(self):
        with self.assertRaises(errors.Forbidden) as ctx:
            self.api.get("/oauth/scoped")
        challenge = ctx.exception.challenges[0]
        self.assertEqual((challenge.error, challenge.scope), ("insufficient_scope", "admin write"))
        self.assertEqual(self.server.counters["tokens-issued"], 1)


if __name__ == "__main__":
    unittest.main()
