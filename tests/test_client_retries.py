import unittest

from restclients import errors
from restclients.requests_client import RequestsClient
from restclients.retry import RetryPolicy
from restclients.urllib_client import UrllibClient
from tests.fakes import FakeRequestsResponse, FakeSession
from tests.server import ApiServer


class RetryAgainstServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def setUp(self):
        self.sleeps = []
        self.policy = RetryPolicy(max_attempts=4, backoff_base=0.5, jitter=False)
        self.client = UrllibClient(base_url=self.server.url, retry=self.policy,
                                   sleep=self.sleeps.append)

    def test_recovers_from_503s(self):
        body = self.client.get_json("/flaky", params={"key": "recover", "fail": 2})
        self.assertEqual(body, {"ok": True, "call": 3})
        self.assertEqual(self.sleeps, [0.5, 1.0])

    def test_gives_up_after_max_attempts(self):
        with self.assertRaises(errors.ServerError):
            self.client.get("/flaky", params={"key": "giveup", "fail": 10})
        self.assertEqual(self.server.counters["flaky:giveup"], 4)
        self.assertEqual(len(self.sleeps), 3)

    def test_no_retry_for_404(self):
        with self.assertRaises(errors.NotFound):
            self.client.get("/items/999")
        self.assertEqual(self.sleeps, [])

    def test_post_is_not_retried(self):
        with self.assertRaises(errors.ServerError):
            self.client.post("/flaky", params={"key": "post", "fail": 1})
        self.assertEqual(self.server.counters["flaky:post"], 1)

    def test_429_honours_retry_after(self):
        body = self.client.get_json("/limited", params={"key": "rl", "times": 2, "after": 7})
        self.assertEqual(body["call"], 3)
        self.assertEqual(self.sleeps, [7.0, 7.0])

    def test_retry_after_too_long_raises_rate_limited(self):
        client = UrllibClient(base_url=self.server.url, sleep=self.sleeps.append,
                              retry=RetryPolicy(jitter=False, max_retry_after=5))
        with self.assertRaises(errors.RateLimited) as ctx:
            client.get("/limited", params={"key": "long", "times": 1, "after": 120})
        self.assertEqual(ctx.exception.retry_after, 120.0)
        self.assertEqual(self.sleeps, [])

    def test_dropped_connection_is_retried(self):
        body = self.client.get_json("/drop", params={"key": "drop", "fail": 1})
        self.assertEqual(body["call"], 2)
        self.assertEqual(self.sleeps, [0.5])

    def test_without_policy_nothing_is_retried(self):
        client = UrllibClient(base_url=self.server.url)
        with self.assertRaises(errors.ServerError):
            client.get("/flaky", params={"key": "plain", "fail": 1})


class RetryWithFakeSessionTests(unittest.TestCase):
    def test_requests_client_shares_the_retry_loop(self):
        session = FakeSession([
            FakeRequestsResponse(503, b"{}"),
            FakeRequestsResponse(429, b"{}", {"Retry-After": "3"}),
            FakeRequestsResponse(200, b'{"ok": true}'),
        ])
        sleeps = []
        client = RequestsClient(session, retry=RetryPolicy(jitter=False), sleep=sleeps.append)
        self.assertEqual(client.get_json("http://api.test/x"), {"ok": True})
        self.assertEqual(sleeps, [0.5, 3.0])
        self.assertEqual(len(session.calls), 3)


if __name__ == "__main__":
    unittest.main()
