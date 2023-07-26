import unittest

from restclients import errors
from restclients.idempotency import (CONFLICT, IN_PROGRESS, NEW, REPLAY, IdempotencyStore,
                                     fingerprint_of)
from restclients.retry import RetryPolicy
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class StoreTests(unittest.TestCase):
    def test_lifecycle(self):
        store = IdempotencyStore()
        fp = fingerprint_of("POST", "/p", b"{}")
        self.assertEqual(store.begin("k", fp)[0], NEW)
        self.assertEqual(store.begin("k", fp)[0], IN_PROGRESS)
        store.complete("k", (201, {"id": 1}))
        state, entry = store.begin("k", fp)
        self.assertEqual((state, entry.response), (REPLAY, (201, {"id": 1})))

    def test_same_key_different_payload_conflicts(self):
        store = IdempotencyStore()
        store.begin("k", fingerprint_of("POST", "/p", b"a"))
        self.assertEqual(store.begin("k", fingerprint_of("POST", "/p", b"b"))[0], CONFLICT)

    def test_fingerprint_depends_on_method_path_and_body(self):
        base = fingerprint_of("POST", "/p", b"x")
        self.assertEqual(base, fingerprint_of("post", "/p", b"x"))
        for other in (fingerprint_of("PUT", "/p", b"x"), fingerprint_of("POST", "/q", b"x"),
                      fingerprint_of("POST", "/p", b"y")):
            self.assertNotEqual(base, other)
        # length prefixes stop ("ab", "c") and ("a", "bc") from colliding
        self.assertNotEqual(fingerprint_of("POST", "/ab", b"c"), fingerprint_of("POST", "/a", b"bc"))

    def test_entries_expire(self):
        now = [1000.0]
        store = IdempotencyStore(ttl=60, clock=lambda: now[0])
        store.begin("k", "fp")
        store.complete("k", (200, {}))
        now[0] += 61
        self.assertEqual(store.begin("k", "fp")[0], NEW)

    def test_abandon_lets_the_client_retry(self):
        store = IdempotencyStore()
        store.begin("k", "fp")
        store.abandon("k")
        self.assertEqual(store.begin("k", "fp")[0], NEW)
        store.complete("k", (200, {}))
        store.abandon("k")                    # finished work is never abandoned
        self.assertEqual(store.begin("k", "fp")[0], REPLAY)


class ExactlyOnceTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)

    def client(self, **kwargs):
        return UrllibClient(base_url=self.server.url, retry=RetryPolicy(jitter=False),
                            sleep=lambda s: None, **kwargs)

    def test_lost_response_is_retried_without_double_charging(self):
        client = self.client(idempotency_header="Idempotency-Key")
        payment = client.post("/payments", params={"drop_response": 1}, json={"amount": 25}).json()
        self.assertEqual(payment, {"id": 1, "amount": 25})
        self.assertEqual(len(self.server.payments), 1)            # processed once...
        posts = [r for r in self.server.requests if r[0] == "POST"]
        self.assertEqual(len(posts), 2)                           # ...although the client sent two

    def test_without_a_key_the_same_failure_double_charges(self):
        """The bug the key prevents: retry by hand, the server cannot tell it is a repeat."""
        client = self.client()
        with self.assertRaises(errors.TransportError):
            client.post("/payments", params={"drop_response": 1}, json={"amount": 25})
        client.post("/payments", json={"amount": 25})
        self.assertEqual(len(self.server.payments), 2)

    def test_replayed_response_is_marked(self):
        client = UrllibClient(base_url=self.server.url)
        headers = {"Idempotency-Key": "abc"}
        first = client.post("/payments", json={"amount": 5}, headers=headers)
        again = client.post("/payments", json={"amount": 5}, headers=headers)
        self.assertEqual(first.json(), again.json())
        self.assertNotIn("Idempotent-Replayed", first.headers)
        self.assertEqual(again.headers["Idempotent-Replayed"], "true")
        self.assertEqual(len(self.server.payments), 1)

    def test_key_reuse_with_a_different_body_is_rejected(self):
        client = UrllibClient(base_url=self.server.url)
        headers = {"Idempotency-Key": "abc"}
        client.post("/payments", json={"amount": 5}, headers=headers)
        with self.assertRaises(errors.ClientError) as ctx:
            client.post("/payments", json={"amount": 6}, headers=headers)
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(len(self.server.payments), 1)

    def test_a_failed_request_does_not_poison_its_key(self):
        client = UrllibClient(base_url=self.server.url)
        headers = {"Idempotency-Key": "abc"}
        with self.assertRaises(errors.BadRequest):
            client.post("/payments", json={"amount": -1}, headers=headers)
        # same key, corrected payload: the failed attempt was abandoned, so this is new work
        # (a different payload would conflict only if the first attempt had been stored)
        self.assertEqual(client.post("/payments", json={"amount": 5}, headers=headers).status, 201)

    def test_different_keys_make_different_payments(self):
        client = self.client(idempotency_header="Idempotency-Key")
        client.post("/payments", json={"amount": 5})
        client.post("/payments", json={"amount": 5})
        self.assertEqual(len(self.server.payments), 2)


if __name__ == "__main__":
    unittest.main()
