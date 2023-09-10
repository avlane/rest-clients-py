import unittest

from restclients import errors
from restclients.breaker import CLOSED, HALF_OPEN, OPEN, CircuitBreaker, CircuitOpen
from restclients.requests_client import RequestsClient
from restclients.retry import RetryPolicy
from restclients.testing import FakeResponse, FakeSession
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class BreakerAgainstServerTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.clock = Clock()
        self.breaker = CircuitBreaker("api", failure_threshold=3, recovery_timeout=30, clock=self.clock)
        self.client = UrllibClient(base_url=self.server.url, breaker=self.breaker)

    def hits(self, path):
        return len([r for r in self.server.requests if r[1].startswith(path)])

    def test_server_errors_open_the_circuit_and_stop_traffic(self):
        for _ in range(3):
            with self.assertRaises(errors.ServerError):
                self.client.get("/status/503")
        self.assertEqual(self.breaker.state, OPEN)
        with self.assertRaises(CircuitOpen):
            self.client.get("/status/503")
        with self.assertRaises(CircuitOpen):
            self.client.get("/items/1")            # a healthy endpoint is blocked too: the *service* is suspect
        self.assertEqual(self.hits("/status/503"), 3)
        self.assertEqual(self.hits("/items"), 0)

    def test_recovers_through_a_half_open_probe(self):
        for _ in range(3):
            with self.assertRaises(errors.ServerError):
                self.client.get("/status/500")
        self.clock.now = 31
        self.assertEqual(self.breaker.state, HALF_OPEN)
        self.assertEqual(self.client.get_json("/items/1")["id"], 1)    # the probe succeeds
        self.assertEqual(self.breaker.state, CLOSED)

    def test_failed_probe_reopens(self):
        for _ in range(3):
            with self.assertRaises(errors.ServerError):
                self.client.get("/status/500")
        self.clock.now = 31
        with self.assertRaises(errors.ServerError):
            self.client.get("/status/500")
        self.assertEqual(self.breaker.state, OPEN)

    def test_client_errors_and_rate_limits_do_not_trip_it(self):
        for _ in range(5):
            with self.assertRaises(errors.NotFound):
                self.client.get("/items/999")
            with self.assertRaises(errors.RateLimited):
                self.client.get("/status/429")
        self.assertEqual(self.breaker.state, CLOSED)

    def test_connection_failures_trip_it(self):
        with ApiServer() as dead:
            url = dead.url
        client = UrllibClient(base_url=url, breaker=self.breaker)
        for _ in range(3):
            with self.assertRaises(errors.TransportError):
                client.get("/items/1")
        with self.assertRaises(CircuitOpen):
            client.get("/items/1")

    def test_retries_stop_as_soon_as_the_circuit_opens(self):
        sleeps = []
        client = UrllibClient(base_url=self.server.url, breaker=self.breaker, sleep=sleeps.append,
                              retry=RetryPolicy(max_attempts=10, jitter=False))
        with self.assertRaises(CircuitOpen):
            client.get("/status/503")
        self.assertEqual(self.hits("/status/503"), 3)       # not 10: the breaker cut the retries short
        self.assertEqual(len(sleeps), 3)

    def test_circuit_open_is_catchable_as_api_error_but_not_transport_error(self):
        for _ in range(3):
            with self.assertRaises(errors.ServerError):
                self.client.get("/status/500")
        with self.assertRaises(errors.ApiError) as ctx:
            self.client.get("/items/1")
        self.assertNotIsInstance(ctx.exception, errors.TransportError)


class BreakerWithFakeSessionTests(unittest.TestCase):
    def test_requests_client_shares_the_behaviour(self):
        session = FakeSession([FakeResponse(503)] * 2 + [FakeResponse(200)])
        client = RequestsClient(session, breaker=CircuitBreaker(failure_threshold=2, clock=Clock()))
        for _ in range(2):
            with self.assertRaises(errors.ServerError):
                client.get("http://api.test/x")
        with self.assertRaises(CircuitOpen):
            client.get("http://api.test/x")
        self.assertEqual(len(session.calls), 2)


if __name__ == "__main__":
    unittest.main()
