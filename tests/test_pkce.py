import unittest
from urllib.parse import parse_qs, urlsplit

from restclients import pkce

# RFC 7636, appendix B
RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


class PkceTests(unittest.TestCase):
    def test_rfc_7636_test_vector(self):
        self.assertEqual(pkce.code_challenge(RFC_VERIFIER), RFC_CHALLENGE)

    def test_plain_method(self):
        self.assertEqual(pkce.code_challenge(RFC_VERIFIER, "plain"), RFC_VERIFIER)

    def test_generated_verifier_is_valid(self):
        for nbytes in (32, 64, 96):
            verifier = pkce.generate_code_verifier(nbytes)
            self.assertTrue(43 <= len(verifier) <= 128)
            pkce.code_challenge(verifier)  # does not raise

    def test_generated_values_are_random(self):
        self.assertNotEqual(pkce.generate_code_verifier(), pkce.generate_code_verifier())
        self.assertNotEqual(pkce.generate_state(), pkce.generate_state())

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            pkce.generate_code_verifier(8)
        with self.assertRaises(ValueError):
            pkce.code_challenge("too-short")
        with self.assertRaises(ValueError):
            pkce.code_challenge("a" * 50 + "!")
        with self.assertRaises(ValueError):
            pkce.code_challenge(RFC_VERIFIER, "S512")

    def test_authorization_url(self):
        url = pkce.authorization_url("https://auth.test/authorize?tenant=a", "app-1",
                                     "http://127.0.0.1:8123/callback", ["read", "write"],
                                     state="xyz", verifier=RFC_VERIFIER)
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        self.assertEqual(parts.netloc, "auth.test")
        self.assertEqual(query["tenant"], ["a"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"], ["read write"])
        self.assertEqual(query["code_challenge"], [RFC_CHALLENGE])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["redirect_uri"], ["http://127.0.0.1:8123/callback"])

    def test_without_verifier_no_pkce_parameters(self):
        query = parse_qs(urlsplit(pkce.authorization_url("https://a/x", "c", "http://r")).query)
        self.assertNotIn("code_challenge", query)


if __name__ == "__main__":
    unittest.main()
