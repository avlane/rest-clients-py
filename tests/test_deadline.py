import time
import unittest

from restclients import errors
from restclients.client import _clamp_timeout
from restclients.requests_client import RequestsClient
from restclients.retry import RetryPolicy
from restclients.testing import FakeResponse, FakeSession
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class ClampTests(unittest.TestCase):
    def test_numbers_pairs_and_none(self):
        self.assertEqual(_clamp_timeout(10, 3), 3)
        self.assertEqual(_clamp_timeout(2, 3), 2)
        self.assertEqual(_clamp_timeout((3, 30), 5), (3, 5))
        self.assertEqual(_clamp_timeout((None, 30), 5), (5, 5))
        self.assertEqual(_clamp_timeout(None, 5), 5)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class DeadlineWithFakeSessionTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()

    def client(self, session, **kwargs):
        return RequestsClient(session, clock=self.clock, sleep=self.clock.sleep,
                              retry=RetryPolicy(max_attempts=10, backoff_base=1, jitter=False), **kwargs)

    def test_timeout_is_clamped_to_the_time_left(self):
        session = FakeSession()
        self.client(session, timeout=30).get("http://api.test/x", deadline=5)
        self.assertEqual(session.calls[0]["timeout"], 5)

    def test_retries_stop_when_the_deadline_would_pass_while_waiting(self):
        session = FakeSession([FakeResponse(503)] * 10)
        with self.assertRaises(errors.DeadlineExceeded) as ctx:
            self.client(session).get("http://api.test/x", deadline=5)
        # waits of 1, 2 then 4 s: after 3 s the next 4 s wait would cross the 5 s deadline
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(self.clock.now, 103.0)
        self.assertIn("would pass while waiting", ctx.exception.message)

    def test_each_attempt_gets_less_time(self):
        session = FakeSession([FakeResponse(503), FakeResponse(503), FakeResponse(200)])
        self.client(session, timeout=30).get("http://api.test/x", deadline=20)
        self.assertEqual([c["timeout"] for c in session.calls], [20, 19, 17])

    def test_success_within_the_budget(self):
        session = FakeSession([FakeResponse(503), FakeResponse(200, json={"ok": 1})])
        self.assertEqual(self.client(session).get_json("http://api.test/x", deadline=10), {"ok": 1})

    def test_default_deadline_on_the_client_and_per_call_override(self):
        session = FakeSession([FakeResponse(503)] * 10)
        client = self.client(session, deadline=2)
        with self.assertRaises(errors.DeadlineExceeded):
            client.get("http://api.test/x")
        session.queue = [FakeResponse(200, json={})]
        self.assertEqual(client.get("http://api.test/x", deadline=100).status, 200)

    def test_deadline_exceeded_is_a_transport_error_but_never_retried(self):
        self.assertTrue(issubclass(errors.DeadlineExceeded, errors.TransportError))
        session = FakeSession([FakeResponse(503)] * 10)
        with self.assertRaises(errors.TransportError):
            self.client(session).get("http://api.test/x", deadline=0)
        self.assertEqual(session.calls, [])            # budget gone before the first attempt

    def test_no_deadline_means_no_limit(self):
        session = FakeSession([FakeResponse(503)] * 3 + [FakeResponse(200)])
        self.assertEqual(self.client(session).get("http://api.test/x").status, 200)


class DeadlineAgainstServerTests(unittest.TestCase):
    def test_slow_response_is_cut_off_by_the_remaining_budget(self):
        with ApiServer() as server:
            client = UrllibClient(base_url=server.url, timeout=30)
            started = time.monotonic()
            with self.assertRaises(errors.TransportError):
                client.get("/slow", params={"delay": 2}, deadline=0.3)
            self.assertLess(time.monotonic() - started, 1.5)

    def test_retry_loop_over_real_sockets_respects_the_deadline(self):
        with ApiServer() as server:
            client = UrllibClient(base_url=server.url,
                                  retry=RetryPolicy(max_attempts=50, backoff_base=0.05, jitter=False))
            started = time.monotonic()
            with self.assertRaises(errors.DeadlineExceeded):
                client.get("/flaky", params={"key": "deadline", "fail": 1000}, deadline=0.4)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertLess(server.counters["flaky:deadline"], 50)


if __name__ == "__main__":
    unittest.main()
