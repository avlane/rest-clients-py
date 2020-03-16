import time
import unittest

from restclients.ratelimit import TokenBucket
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class TokenBucketTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()

    def bucket(self, rate, capacity=1):
        return TokenBucket(rate, capacity, clock=self.clock, sleep=self.clock.sleep)

    def test_burst_then_spacing(self):
        bucket = self.bucket(rate=2, capacity=3)
        waits = [bucket.acquire() for _ in range(6)]
        self.assertEqual(waits, [0, 0, 0, 0.5, 0.5, 0.5])
        self.assertAlmostEqual(self.clock.now, 101.5)

    def test_refills_over_time_up_to_capacity(self):
        bucket = self.bucket(rate=1, capacity=2)
        bucket.acquire()
        bucket.acquire()
        self.clock.now += 100
        self.assertEqual([bucket.acquire() for _ in range(3)], [0, 0, 1.0])

    def test_try_acquire_never_blocks(self):
        bucket = self.bucket(rate=1, capacity=1)
        self.assertTrue(bucket.try_acquire())
        self.assertFalse(bucket.try_acquire())
        self.clock.now += 1
        self.assertTrue(bucket.try_acquire())
        self.assertEqual(self.clock.slept, [])

    def test_invalid_arguments(self):
        with self.assertRaises(ValueError):
            TokenBucket(0)
        with self.assertRaises(ValueError):
            TokenBucket(1, capacity=0)


class ClientRateLimitTests(unittest.TestCase):
    def test_requests_are_spaced_out(self):
        with ApiServer() as server:
            client = UrllibClient(base_url=server.url,
                                  rate_limiter=TokenBucket(rate=20, capacity=1))
            started = time.monotonic()
            for _ in range(5):
                client.get("/items/1")
            elapsed = time.monotonic() - started
        # first request is free, the other four wait 1/20 s each
        self.assertGreaterEqual(elapsed, 0.19)

    def test_retries_consume_tokens(self):
        clock = FakeClock()
        bucket = TokenBucket(rate=1, capacity=10, clock=clock, sleep=clock.sleep)
        from restclients.retry import RetryPolicy
        with ApiServer() as server:
            client = UrllibClient(base_url=server.url, rate_limiter=bucket,
                                  retry=RetryPolicy(jitter=False), sleep=lambda s: None)
            client.get("/flaky", params={"fail": 2})
        self.assertAlmostEqual(bucket._tokens, 7.0)


if __name__ == "__main__":
    unittest.main()
