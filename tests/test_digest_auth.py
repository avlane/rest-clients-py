import unittest

from restclients import errors
from restclients.auth import DigestAuth, parse_digest_challenge
from restclients.requests_client import RequestsClient
from restclients.testing import FakeResponse, FakeSession
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class ChallengeParsingTests(unittest.TestCase):
    def test_rfc_2617_example_challenge(self):
        value = ('Digest realm="testrealm@host.com", qop="auth,auth-int", '
                 'nonce="dcd98b7102dd2f0e8b11d0f600bfb0c093", opaque="5ccc069c403ebaf9f0171e9517f40e41"')
        challenge = parse_digest_challenge(value)
        self.assertEqual(challenge["realm"], "testrealm@host.com")
        self.assertEqual(challenge["qop"], "auth,auth-int")
        self.assertEqual(challenge["opaque"], "5ccc069c403ebaf9f0171e9517f40e41")

    def test_unquoted_values_and_escapes(self):
        challenge = parse_digest_challenge('Digest realm="a \\"quoted\\" realm", nonce=abc, algorithm=SHA-256, stale=TRUE')
        self.assertEqual((challenge["realm"], challenge["algorithm"], challenge["stale"]),
                         ('a "quoted" realm', "SHA-256", "TRUE"))

    def test_digest_among_other_challenges(self):
        value = 'Basic realm="x", Digest realm="y", nonce="n"'
        self.assertEqual(parse_digest_challenge(value)["realm"], "y")

    def test_not_a_digest_challenge(self):
        for value in (None, "", 'Basic realm="x"', 'Bearer realm="x"', 'Digest realm="no nonce"'):
            with self.subTest(value=value):
                self.assertIsNone(parse_digest_challenge(value))


class HeaderComputationTests(unittest.TestCase):
    def signed(self, challenge, cnonce, method="GET", url="http://h/dir/index.html", count=1, **kwargs):
        auth = DigestAuth(kwargs.get("user", "Mufasa"), kwargs.get("password", "Circle Of Life"),
                          cnonce_factory=lambda: cnonce)
        auth._challenge = challenge
        auth._nonce_count = count - 1
        headers = {}
        auth.sign(headers, method, url)
        return headers["Authorization"]

    def test_rfc_2617_md5_test_vector(self):
        header = self.signed({"realm": "testrealm@host.com", "nonce": "dcd98b7102dd2f0e8b11d0f600bfb0c093",
                              "qop": "auth,auth-int", "opaque": "5ccc069c403ebaf9f0171e9517f40e41"}, "0a4f113b")
        self.assertIn('response="6629fae49393a05397450978507c4ef1"', header)
        self.assertIn("nc=00000001", header)
        self.assertIn('opaque="5ccc069c403ebaf9f0171e9517f40e41"', header)
        self.assertIn('uri="/dir/index.html"', header)

    def test_rfc_7616_sha256_test_vector(self):
        header = self.signed({"realm": "http-auth@example.org", "algorithm": "SHA-256", "qop": "auth",
                              "nonce": "7ypf/xlj9XXwfDPEoM4URrv/xwf94BcCAzFZH4GiTo0v"},
                             "f2/wE4q74E6zIJEtWaHKaf5wv/H5QzzpXusqGemxURZJ", password="Circle of Life")
        self.assertIn('response="753927fa0e85d155564e2e272a28d1802ca10daf4496794697cf8db5856cb6c1"', header)
        self.assertIn("algorithm=SHA-256", header)

    def test_query_string_is_part_of_the_uri(self):
        header = self.signed({"realm": "r", "nonce": "n", "qop": "auth"}, "c", url="http://h/a/b?x=1&y=2")
        self.assertIn('uri="/a/b?x=1&y=2"', header)

    def test_without_qop_uses_the_rfc_2069_form(self):
        header = self.signed({"realm": "r", "nonce": "n"}, "c")
        self.assertNotIn("nc=", header)
        self.assertNotIn("cnonce", header)

    def test_session_variant_differs_from_the_plain_one(self):
        base = {"realm": "r", "nonce": "n", "qop": "auth"}
        self.assertNotEqual(self.signed(dict(base, algorithm="MD5"), "c"),
                            self.signed(dict(base, algorithm="MD5-sess"), "c"))

    def test_unsupported_algorithm(self):
        with self.assertRaises(ValueError):
            self.signed({"realm": "r", "nonce": "n", "algorithm": "CRC32"}, "c")

    def test_no_header_before_the_first_challenge(self):
        headers = {}
        DigestAuth("u", "p").sign(headers, "GET", "http://h/x")
        self.assertEqual(headers, {})

    def test_secret_not_in_repr(self):
        self.assertNotIn("hunter2", repr(DigestAuth("u", "hunter2")))


class DigestAgainstServerTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)

    def client(self, password="s3cret", **kwargs):
        return UrllibClient(base_url=self.server.url, auth=DigestAuth("avery", password), **kwargs)

    def test_automatic_challenge_response(self):
        client = self.client()
        self.assertEqual(client.get_json("/digest"), {"user": "avery", "nc": "00000001"})
        hits = [r for r in self.server.requests if r[1] == "/digest"]
        self.assertEqual(len(hits), 2)                       # unauthenticated try, then the answer
        self.assertNotIn("Authorization", hits[0][2])

    def test_later_requests_reuse_the_nonce_with_an_increasing_counter(self):
        client = self.client()
        counters = [client.get_json("/digest")["nc"] for _ in range(3)]
        self.assertEqual(counters, ["00000001", "00000002", "00000003"])
        self.assertEqual(len([r for r in self.server.requests if r[1] == "/digest"]), 4)   # 1 + 3, not 6
        self.assertEqual(self.server.counters["digest-nonces"], 1)

    def test_sha256(self):
        self.assertEqual(self.client().get_json("/digest", {"algorithm": "SHA-256"})["user"], "avery")

    def test_query_string_requests(self):
        self.assertEqual(self.client().get_json("/digest", {"algorithm": "MD5", "x": "a b"})["user"], "avery")

    def test_post_requests_are_signed_with_their_own_method(self):
        client = self.client()
        resp = client.post("/digest", json={"a": 1})
        self.assertEqual(resp.json()["user"], "avery")

    def test_wrong_password_fails_without_a_retry_loop(self):
        with self.assertRaises(errors.Unauthorized):
            self.client(password="wrong").get("/digest")
        self.assertEqual(self.server.counters["digest-rejected"], 1)
        self.assertEqual(len([r for r in self.server.requests if r[1] == "/digest"]), 2)

    def test_stale_nonce_is_replaced_transparently(self):
        client = self.client()
        self.assertEqual(client.get_json("/digest", {"expire_after": 2})["nc"], "00000001")
        self.assertEqual(client.get_json("/digest", {"expire_after": 2})["nc"], "00000002")
        self.assertEqual(client.get_json("/digest", {"expire_after": 2})["nc"], "00000001")    # new nonce
        self.assertEqual(self.server.counters["digest-nonces"], 2)

    def test_non_digest_401_is_not_retried(self):
        with self.assertRaises(errors.Unauthorized):
            self.client().get("/basic")
        self.assertEqual(len([r for r in self.server.requests if r[1] == "/basic"]), 1)


class DigestWithFakeSessionTests(unittest.TestCase):
    def test_requests_client_retries_with_an_authorization_header(self):
        challenge = 'Digest realm="r", qop="auth", nonce="n1"'
        session = FakeSession([FakeResponse(401, headers={"WWW-Authenticate": challenge}), FakeResponse(200, json={})])
        client = RequestsClient(session, auth=DigestAuth("u", "p", cnonce_factory=lambda: "cn"))
        client.get("http://api.test/x?q=1")
        self.assertNotIn("Authorization", session.calls[0]["headers"])
        self.assertIn('uri="/x?q=1"', session.calls[1]["headers"]["Authorization"])


if __name__ == "__main__":
    unittest.main()
