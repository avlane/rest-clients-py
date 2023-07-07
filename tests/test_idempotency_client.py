import unittest

from restclients import errors
from restclients.requests_client import RequestsClient
from restclients.retry import RetryPolicy
from restclients.testing import FakeResponse, FakeSession
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class IdempotencyKeyTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        self.sleeps = []

    def client(self, **kwargs):
        kwargs.setdefault("idempotency_header", "Idempotency-Key")
        return RequestsClient(self.session, sleep=self.sleeps.append, **kwargs)

    def keys(self):
        return [c["headers"].get("Idempotency-Key") for c in self.session.calls]

    def test_disabled_by_default(self):
        RequestsClient(self.session).post("http://api.test/x", json={})
        self.assertEqual(self.keys(), [None])

    def test_post_and_patch_get_a_key_but_get_and_put_do_not(self):
        client = self.client()
        for method in ("POST", "PATCH", "GET", "PUT", "DELETE"):
            client.request(method, "http://api.test/x")
        self.assertEqual([bool(k) for k in self.keys()], [True, True, False, False, False])

    def test_each_call_gets_its_own_key(self):
        client = self.client()
        client.post("http://api.test/x")
        client.post("http://api.test/x")
        first, second = self.keys()
        self.assertNotEqual(first, second)
        self.assertEqual(len(first), 32)

    def test_callers_key_is_respected_even_on_get(self):
        client = self.client()
        client.post("http://api.test/x", headers={"idempotency-key": "mine"})
        client.get("http://api.test/x", headers={"Idempotency-Key": "also-mine"})
        self.assertEqual([c["headers"] for c in self.session.calls][0].get("idempotency-key"), "mine")
        self.assertNotIn("Idempotency-Key", self.session.calls[0]["headers"])   # no second, generated key

    def test_post_with_a_key_is_retried_with_the_same_key(self):
        self.session.queue = [FakeResponse(503), FakeResponse(502), FakeResponse(201, json={"id": 1})]
        client = self.client(retry=RetryPolicy(jitter=False))
        self.assertEqual(client.post("http://api.test/pay", json={"amount": 5}).status, 201)
        keys = self.keys()
        self.assertEqual(len(keys), 3)
        self.assertEqual(len(set(keys)), 1)
        self.assertEqual(self.sleeps, [0.5, 1.0])

    def test_post_without_a_key_is_still_not_retried(self):
        self.session.queue = [FakeResponse(503)]
        client = RequestsClient(self.session, retry=RetryPolicy(jitter=False), sleep=self.sleeps.append)
        with self.assertRaises(errors.ServerError):
            client.post("http://api.test/pay")
        self.assertEqual(len(self.session.calls), 1)

    def test_post_retried_after_a_transport_error(self):
        class ConnectionError(Exception):
            pass
        ConnectionError.__module__ = "requests.exceptions"
        self.session.queue = [ConnectionError("reset"), FakeResponse(201)]
        client = self.client(retry=RetryPolicy(jitter=False))
        self.assertEqual(client.post("http://api.test/pay").status, 201)
        self.assertEqual(len(set(self.keys())), 1)


class AgainstRealServerTests(unittest.TestCase):
    def test_key_survives_retries_over_real_sockets(self):
        with ApiServer() as server:
            client = UrllibClient(base_url=server.url, idempotency_header="Idempotency-Key",
                                  retry=RetryPolicy(jitter=False), sleep=lambda s: None)
            client.post("/flaky", params={"key": "idem", "fail": 2})
            sent = [h["Idempotency-Key"] for m, p, h in server.requests if p.startswith("/flaky")]
        self.assertEqual(len(sent), 3)
        self.assertEqual(len(set(sent)), 1)


if __name__ == "__main__":
    unittest.main()
