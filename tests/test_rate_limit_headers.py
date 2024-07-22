import time
import unittest

from restclients import errors
from restclients.ratelimit import RateLimitInfo
from restclients.requests_client import RequestsClient
from restclients.testing import FakeResponse, FakeSession
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer

NOW = 1_700_000_000.0


class ParseTests(unittest.TestCase):
    def test_github_style_epoch_reset(self):
        info = RateLimitInfo.from_headers({"X-RateLimit-Limit": "60", "X-RateLimit-Remaining": "0",
                                           "X-RateLimit-Reset": str(int(NOW) + 42)}, now=NOW)
        self.assertEqual((info.limit, info.remaining, info.reset_at), (60, 0, NOW + 42))
        self.assertEqual(info.wait_needed(NOW), 42)

    def test_ietf_style_delta_reset(self):
        info = RateLimitInfo.from_headers({"RateLimit-Limit": "100", "RateLimit-Remaining": "0",
                                           "RateLimit-Reset": "7"}, now=NOW)
        self.assertEqual(info.reset_at, NOW + 7)

    def test_small_x_reset_is_seconds_from_now(self):
        info = RateLimitInfo.from_headers({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "30"}, now=NOW)
        self.assertEqual(info.wait_needed(NOW), 30)

    def test_remaining_requests_mean_no_wait(self):
        info = RateLimitInfo.from_headers({"X-RateLimit-Remaining": "5", "X-RateLimit-Reset": "30"}, now=NOW)
        self.assertEqual(info.wait_needed(NOW), 0)

    def test_nothing_useful(self):
        self.assertIsNone(RateLimitInfo.from_headers({}, now=NOW))
        self.assertIsNone(RateLimitInfo.from_headers({"X-RateLimit-Remaining": "lots"}, now=NOW))
        self.assertIsNone(RateLimitInfo.from_headers(None, now=NOW))

    def test_policy_style_values_with_parameters(self):
        info = RateLimitInfo.from_headers({"RateLimit-Remaining": "0;w=60", "RateLimit-Reset": "4"}, now=NOW)
        self.assertEqual((info.remaining, info.wait_needed(NOW)), (0, 4))

    def test_past_reset_needs_no_wait(self):
        info = RateLimitInfo.from_headers({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(NOW) - 5)}, now=NOW)
        self.assertEqual(info.wait_needed(NOW), 0)


class ClientBehaviourTests(unittest.TestCase):
    def setUp(self):
        self.sleeps = []
        self.now = [NOW]

    def client(self, session, **kwargs):
        return RequestsClient(session, follow_rate_limit_headers=True, wall_clock=lambda: self.now[0],
                              sleep=self.sleeps.append, **kwargs)

    def limited(self, reset_in=10):
        return FakeResponse(200, json={}, headers={"X-RateLimit-Remaining": "0",
                                                   "X-RateLimit-Reset": str(int(NOW) + reset_in)})

    def test_waits_for_the_window_before_the_next_request(self):
        session = FakeSession([self.limited(10), FakeResponse(200, json={})])
        client = self.client(session)
        client.get("http://api.test/x")
        client.get("http://api.test/x")
        self.assertEqual(self.sleeps, [10.0])

    def test_waits_only_once_per_exhausted_window(self):
        session = FakeSession([self.limited(10), FakeResponse(200, json={}), FakeResponse(200, json={})])
        client = self.client(session)
        for _ in range(3):
            client.get("http://api.test/x")
        self.assertEqual(self.sleeps, [10.0])

    def test_too_long_a_wait_is_not_taken(self):
        session = FakeSession([self.limited(3600), FakeResponse(200, json={})])
        client = self.client(session, max_rate_limit_wait=30)
        client.get("http://api.test/x")
        client.get("http://api.test/x")
        self.assertEqual(self.sleeps, [])

    def test_off_by_default(self):
        session = FakeSession([self.limited(10), FakeResponse(200, json={})])
        client = RequestsClient(session, wall_clock=lambda: self.now[0], sleep=self.sleeps.append)
        client.get("http://api.test/x")
        client.get("http://api.test/x")
        self.assertEqual(self.sleeps, [])

    def test_no_wait_while_requests_remain(self):
        ok = FakeResponse(200, json={}, headers={"X-RateLimit-Remaining": "4", "X-RateLimit-Reset": str(int(NOW) + 10)})
        session = FakeSession([ok, ok])
        client = self.client(session)
        client.get("http://api.test/x")
        client.get("http://api.test/x")
        self.assertEqual(self.sleeps, [])


class AgainstRealServerTests(unittest.TestCase):
    def test_polite_client_avoids_every_429(self):
        with ApiServer() as server:
            client = UrllibClient(base_url=server.url, follow_rate_limit_headers=True)
            started = time.monotonic()
            for _ in range(7):
                client.get("/metered", params={"limit": 3, "window": 0.4, "key": "polite"})
            elapsed = time.monotonic() - started
            self.assertEqual(server.counters.get("metered:polite:429", 0), 0)
        self.assertGreater(elapsed, 0.3)          # it did have to wait for a window to renew

    def test_impolite_client_gets_429s(self):
        with ApiServer() as server:
            client = UrllibClient(base_url=server.url)
            statuses = [client.get("/metered", params={"limit": 3, "window": 5, "key": "rude"},
                                   raise_for_status=False).status for _ in range(5)]
        self.assertEqual(statuses, [200, 200, 200, 429, 429])

    def test_ietf_header_names(self):
        with ApiServer() as server:
            client = UrllibClient(base_url=server.url, follow_rate_limit_headers=True)
            for _ in range(4):
                client.get("/metered", params={"limit": 2, "window": 0.3, "key": "ietf", "ietf": 1})
            self.assertEqual(server.counters.get("metered:ietf:429", 0), 0)


if __name__ == "__main__":
    unittest.main()
