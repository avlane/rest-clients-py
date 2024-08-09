import asyncio
import unittest

from restclients import errors
from restclients.aiohttp_client import AiohttpClient
from restclients.async_client import AsyncHttpxClient
from restclients.breaker import CircuitBreaker, CircuitOpen
from restclients.ratelimit import AsyncTokenBucket
from restclients.retry import RetryPolicy
from restclients.testing import FakeAiohttpSession, FakeAsyncSession, FakeResponse


class ConnectError(Exception):
    pass


ConnectError.__module__ = "httpx"


def fast_policy(**kwargs):
    kwargs.setdefault("jitter", False)
    return RetryPolicy(**kwargs)


class Sleeps:
    """An async sleep that records instead of waiting."""

    def __init__(self):
        self.calls = []

    async def __call__(self, seconds):
        self.calls.append(seconds)


class AsyncRetryTests(unittest.TestCase):
    def setUp(self):
        self.sleeps = Sleeps()

    def client(self, session, **kwargs):
        return AsyncHttpxClient(session, sleep=self.sleeps, retry=fast_policy(), **kwargs)

    def test_retries_503_then_succeeds(self):
        session = FakeAsyncSession([FakeResponse(503), FakeResponse(502), FakeResponse(200, json={"ok": 1})])
        result = asyncio.run(self.client(session).get_json("http://api.test/x"))
        self.assertEqual(result, {"ok": 1})
        self.assertEqual(self.sleeps.calls, [0.5, 1.0])
        self.assertEqual(len(session.calls), 3)

    def test_retry_after_is_honoured_and_too_long_gives_up(self):
        session = FakeAsyncSession([FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(200, json={})])
        asyncio.run(self.client(session).get("http://api.test/x"))
        self.assertEqual(self.sleeps.calls, [7.0])
        session = FakeAsyncSession([FakeResponse(429, headers={"Retry-After": "600"})])
        with self.assertRaises(errors.RateLimited):
            asyncio.run(self.client(session).get("http://api.test/x"))

    def test_transport_errors_are_retried(self):
        session = FakeAsyncSession([ConnectError("refused"), FakeResponse(200, json={"ok": 1})])
        self.assertEqual(asyncio.run(self.client(session).get_json("http://api.test/x")), {"ok": 1})
        self.assertEqual(self.sleeps.calls, [0.5])

    def test_post_is_not_retried(self):
        session = FakeAsyncSession([FakeResponse(503)])
        with self.assertRaises(errors.ServerError):
            asyncio.run(self.client(session).post("http://api.test/x", json={}))
        self.assertEqual(len(session.calls), 1)

    def test_gives_up_after_max_attempts(self):
        session = FakeAsyncSession([FakeResponse(503)] * 10)
        client = AsyncHttpxClient(session, sleep=self.sleeps, retry=fast_policy(max_attempts=3))
        with self.assertRaises(errors.ServerError):
            asyncio.run(client.get("http://api.test/x"))
        self.assertEqual(len(session.calls), 3)

    def test_same_policy_works_for_aiohttp_wrapper(self):
        session = FakeAiohttpSession([FakeResponse(503), FakeResponse(200, json={"ok": 1})])
        client = AiohttpClient(session, timeout_factory=lambda s: s, sleep=self.sleeps, retry=fast_policy())
        self.assertEqual(asyncio.run(client.get_json("http://api.test/x")), {"ok": 1})


class AsyncLimiterAndBreakerTests(unittest.TestCase):
    def test_async_token_bucket_spaces_requests_without_blocking_the_loop(self):
        now = [0.0]
        waits = []

        async def fake_sleep(seconds):
            waits.append(seconds)
            now[0] += seconds

        bucket = AsyncTokenBucket(rate=2, capacity=1, clock=lambda: now[0], sleep=fake_sleep)
        session = FakeAsyncSession()
        client = AsyncHttpxClient(session, rate_limiter=bucket)

        async def main():
            for _ in range(4):
                await client.get("http://api.test/x")

        asyncio.run(main())
        self.assertEqual(waits, [0.5, 0.5, 0.5])

    def test_limiter_lets_other_tasks_run_while_waiting(self):
        order = []

        async def ticker():
            for n in range(3):
                order.append("tick%d" % n)
                await asyncio.sleep(0.01)

        async def main():
            bucket = AsyncTokenBucket(rate=20, capacity=1)      # real sleeps: 50 ms apart
            await bucket.acquire()
            task = asyncio.ensure_future(ticker())
            await bucket.acquire()                              # waits ~50 ms; ticker keeps running
            order.append("acquired")
            await task

        asyncio.run(main())
        self.assertEqual(order[0], "tick0")
        self.assertLess(order.index("tick1"), order.index("acquired"))

    def test_breaker_opens_for_async_clients_too(self):
        session = FakeAsyncSession([FakeResponse(503)] * 5)
        breaker = CircuitBreaker(failure_threshold=2, clock=lambda: 0.0)
        client = AsyncHttpxClient(session, breaker=breaker)

        async def main():
            for _ in range(2):
                with self.assertRaises(errors.ServerError):
                    await client.get("http://api.test/x")
            with self.assertRaises(CircuitOpen):
                await client.get("http://api.test/x")

        asyncio.run(main())
        self.assertEqual(len(session.calls), 2)

    def test_open_circuit_stops_async_retries(self):
        session = FakeAsyncSession([FakeResponse(503)] * 10)
        client = AsyncHttpxClient(session, sleep=Sleeps(), retry=fast_policy(max_attempts=10),
                                  breaker=CircuitBreaker(failure_threshold=3, clock=lambda: 0.0))
        with self.assertRaises(CircuitOpen):
            asyncio.run(client.get("http://api.test/x"))
        self.assertEqual(len(session.calls), 3)


if __name__ == "__main__":
    unittest.main()
