import unittest

from restclients import errors
from restclients.signatures import (HmacVerifier, ReplayGuard, parse_signature_header, sign,
                                    verify_github_signature)
from restclients.urllib_client import UrllibClient
from restclients.webhooks import WebhookReceiver, WebhookRejected

BODY = b'{"type": "item.created", "id": 5}'


class GithubSchemeTests(unittest.TestCase):
    def test_documented_example(self):
        # the worked example from GitHub's webhook documentation
        header = "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"
        self.assertTrue(verify_github_signature("It's a Secret to Everybody", header, b"Hello, World!"))

    def test_rejections(self):
        header = "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"
        self.assertFalse(verify_github_signature("wrong", header, b"Hello, World!"))
        self.assertFalse(verify_github_signature("It's a Secret to Everybody", header, b"Hello, World?"))
        self.assertFalse(verify_github_signature("s", None, b""))
        self.assertFalse(verify_github_signature("s", "sha1=abc", b""))


class HeaderTests(unittest.TestCase):
    def test_sign_and_parse_round_trip(self):
        timestamp, digests = parse_signature_header(sign("s3cret", BODY, timestamp=1685300000))
        self.assertEqual(timestamp, 1685300000)
        self.assertEqual(len(digests[0]), 64)

    def test_signature_changes_with_every_input(self):
        base = sign("s3cret", BODY, 100)
        self.assertNotEqual(base, sign("other", BODY, 100))
        self.assertNotEqual(base, sign("s3cret", BODY + b" ", 100))
        self.assertNotEqual(base, sign("s3cret", BODY, 101))

    def test_str_and_bytes_secrets_agree(self):
        self.assertEqual(sign("abc", BODY, 5), sign(b"abc", BODY, 5))

    def test_parse_rejects_garbage(self):
        for bad in ("", "nonsense", "t=abc,v1=aa", "t=1", "v1=aa"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_signature_header(bad)

    def test_parse_ignores_unknown_schemes(self):
        self.assertEqual(parse_signature_header("t=5, v0=old, v1=new"), (5, ["new"]))


class VerifierTests(unittest.TestCase):
    NOW = 1685300000

    def verifier(self, **kwargs):
        kwargs.setdefault("clock", lambda: self.NOW)
        return HmacVerifier("s3cret", **kwargs)

    def headers(self, body=BODY, secret="s3cret", timestamp=None):
        return {"x-signature": sign(secret, body, self.NOW if timestamp is None else timestamp)}

    def reason(self, verifier, headers, body=BODY):
        with self.assertRaises(WebhookRejected) as ctx:
            verifier(headers, body)
        return ctx.exception.status, ctx.exception.message

    def test_valid_signature_passes_regardless_of_header_case(self):
        self.verifier()(self.headers(), BODY)
        self.verifier()({"X-SIGNATURE": self.headers()["x-signature"]}, BODY)

    def test_tampered_body(self):
        self.assertEqual(self.reason(self.verifier(), self.headers(), BODY + b"x"),
                         (401, "signature mismatch"))

    def test_wrong_secret(self):
        self.assertEqual(self.reason(self.verifier(), self.headers(secret="nope")),
                         (401, "signature mismatch"))

    def test_missing_and_malformed_header(self):
        self.assertEqual(self.reason(self.verifier(), {}), (401, "missing X-Signature header"))
        self.assertEqual(self.reason(self.verifier(), {"X-Signature": "garbage"})[0], 400)

    def test_old_and_future_timestamps_are_rejected(self):
        for offset in (-301, 301):
            with self.subTest(offset=offset):
                headers = self.headers(timestamp=self.NOW + offset)
                self.assertEqual(self.reason(self.verifier(), headers),
                                 (401, "timestamp outside the tolerance window"))
        self.verifier()(self.headers(timestamp=self.NOW - 300), BODY)       # the edge is allowed

    def test_secret_rotation(self):
        verifier = HmacVerifier(["new-secret", "old-secret"], clock=lambda: self.NOW)
        verifier(self.headers(secret="old-secret"), BODY)
        verifier(self.headers(secret="new-secret"), BODY)
        self.assertEqual(self.reason(verifier, self.headers(secret="retired")), (401, "signature mismatch"))

    def test_several_v1_values_one_of_which_matches(self):
        good = sign("s3cret", BODY, self.NOW)
        header = good + ",v1=" + "0" * 64
        self.verifier()({"X-Signature": header}, BODY)

    def test_replay_guard(self):
        clock = [self.NOW]
        verifier = HmacVerifier("s3cret", clock=lambda: clock[0],
                                replay_guard=ReplayGuard(ttl=600, clock=lambda: clock[0]))
        headers = self.headers()
        verifier(headers, BODY)
        self.assertEqual(self.reason(verifier, headers), (409, "duplicate delivery"))
        clock[0] += 700           # remembered long enough; the tolerance check now stops it anyway
        self.assertEqual(self.reason(verifier, headers)[0], 401)

    def test_no_secrets_is_an_error(self):
        with self.assertRaises(ValueError):
            HmacVerifier([])


class ReceiverWithSignatureTests(unittest.TestCase):
    def test_over_real_sockets(self):
        with WebhookReceiver(verifier=HmacVerifier("s3cret")) as receiver:
            client = UrllibClient()
            good = {"X-Signature": sign("s3cret", BODY)}
            client.post(receiver.url, data=BODY, headers=dict(good, **{"Content-Type": "application/json"}))
            with self.assertRaises(errors.Unauthorized):
                client.post(receiver.url, data=BODY, headers={"X-Signature": sign("wrong", BODY)})
            with self.assertRaises(errors.Unauthorized):
                client.post(receiver.url, data=BODY)
            self.assertEqual([e.payload["id"] for e in receiver.wait_for(1)], [5])
            self.assertEqual([s for s, _ in receiver.wait_for_rejections(2)], [401, 401])

    def test_reserialised_json_does_not_verify(self):
        """Signing parsed-and-dumped JSON instead of the raw bytes is a classic bug."""
        raw = b'{"id":5,   "type":"x"}'
        with WebhookReceiver(verifier=HmacVerifier("s3cret")) as receiver:
            header = {"X-Signature": sign("s3cret", b'{"id": 5, "type": "x"}')}
            with self.assertRaises(errors.Unauthorized):
                UrllibClient().post(receiver.url, data=raw, headers=header)


if __name__ == "__main__":
    unittest.main()
