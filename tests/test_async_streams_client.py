import asyncio
import time
import unittest

from restclients import errors
from restclients.async_streams_client import AsyncStreamsClient
from restclients.auth import BearerAuth
from restclients.breaker import CircuitBreaker, CircuitOpen
from restclients.concurrency import map_bounded
from restclients.ratelimit import AsyncTokenBucket
from restclients.retry import RetryPolicy
from tests.server import ApiServer, blob


class NativeAsyncTests(unittest.TestCase):
    """The async code paths against a real socket, with no thread pool involved."""

    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def client(self, **kwargs):
        return AsyncStreamsClient(base_url=self.server.url, **kwargs)

    def run_(self, coro):
        return asyncio.run(coro)

    def test_get_json_and_headers(self):
        resp = self.run_(self.client().get("/items/3"))
        self.assertEqual(resp.json(), {"id": 3, "name": "item-03", "price": 15})
        self.assertEqual(resp.headers["Content-Type"], "application/json")
        self.assertEqual(self.server.requests[-1][2]["Host"], self.server.url.split("//")[1])

    def test_post_json_and_auth(self):
        resp = self.run_(self.client(auth=BearerAuth("tok-123")).post("/echo", json={"a": [1, 2]}))
        echo = resp.json()
        self.assertEqual((echo["method"], echo["headers"]["authorization"]), ("POST", "Bearer tok-123"))
        self.assertEqual(echo["headers"]["content-length"], str(len('{"a": [1, 2]}')))

    def test_post_without_body_sends_content_length_zero(self):
        self.run_(self.client().post("/echo"))
        self.assertEqual(self.server.requests[-1][2]["Content-Length"], "0")

    def test_error_statuses_use_the_shared_exceptions(self):
        with self.assertRaises(errors.NotFound):
            self.run_(self.client().get("/items/999"))
        with self.assertRaises(errors.ServerError):
            self.run_(self.client().get("/status/503"))

    def test_204_and_head_have_no_body(self):
        client = self.client()
        created = self.run_(client.post("/items", json={"name": "tmp"})).json()
        resp = self.run_(client.delete("/items/%d" % created["id"]))
        self.assertEqual((resp.status, resp.content), (204, b""))
        head = self.run_(client.request("HEAD", "/items/1"))
        self.assertEqual((head.status, head.content), (200, b""))
        self.assertIn("Content-Length", head.headers)

    def test_chunked_body(self):
        resp = self.run_(self.client().get("/ndjson", params={"count": 4}))
        self.assertEqual(len(resp.text.splitlines()), 4)

    def test_chunked_body_in_one_byte_chunks(self):
        resp = self.run_(self.client().get("/ndjson", params={"count": 3, "split": 1}))
        self.assertEqual(len(resp.text.splitlines()), 3)

    def test_large_content_length_body(self):
        resp = self.run_(self.client().get("/blob/300000"))
        self.assertEqual(resp.content, blob(300000))

    def test_truncated_body_is_a_transport_error(self):
        with self.assertRaises(errors.TransportError):
            self.run_(self.client().get("/blob/5000", params={"cut": 100}))
        with self.assertRaises(errors.TransportError):
            self.run_(self.client().get("/ndjson", params={"count": 10, "fail_after": 3}))

    def test_read_timeout_and_connection_refused(self):
        with self.assertRaisesRegex(errors.TransportError, "timed out"):
            self.run_(self.client(timeout=0.2).get("/slow", params={"delay": 1}))
        with ApiServer() as dead:
            url = dead.url
        with self.assertRaises(errors.TransportError):
            self.run_(AsyncStreamsClient(base_url=url).get("/items/1"))

    def test_unsupported_scheme(self):
        with self.assertRaisesRegex(errors.TransportError, "scheme"):
            self.run_(AsyncStreamsClient().get("ftp://example.test/x"))

    def test_bounded_concurrency_is_real_with_one_thread(self):
        client = self.client()

        async def fetch(n):
            return (await client.get_json("/slow", {"delay": 0.1, "n": n}))["n"]

        started = time.monotonic()
        result = self.run_(map_bounded(fetch, range(12), limit=4))
        elapsed = time.monotonic() - started
        self.assertEqual(result, [str(n) for n in range(12)])
        self.assertLess(elapsed, 0.9)               # 12 x 0.1 s sequentially would be 1.2 s
        self.assertGreaterEqual(self.server.max_in_flight, 3)
        self.assertLessEqual(self.server.max_in_flight, 4)

    def test_retries_over_a_real_socket(self):
        slept = []

        async def sleep(seconds):
            slept.append(seconds)

        client = self.client(retry=RetryPolicy(jitter=False), sleep=sleep)
        body = self.run_(client.get_json("/flaky", {"key": "native", "fail": 2}))
        self.assertEqual(body["call"], 3)
        self.assertEqual(slept, [0.5, 1.0])

    def test_retry_after_over_a_real_socket(self):
        slept = []

        async def sleep(seconds):
            slept.append(seconds)

        client = self.client(retry=RetryPolicy(jitter=False), sleep=sleep)
        self.run_(client.get("/limited", params={"key": "native-429", "times": 1, "after": 9}))
        self.assertEqual(slept, [9.0])

    def test_dropped_connection_is_retried(self):
        async def sleep(seconds):
            pass

        client = self.client(retry=RetryPolicy(jitter=False), sleep=sleep)
        self.assertEqual(self.run_(client.get_json("/drop", {"key": "native-drop", "fail": 1}))["call"], 2)

    def test_rate_limiter_spaces_real_requests(self):
        client = self.client(rate_limiter=AsyncTokenBucket(rate=25, capacity=1))
        started = time.monotonic()

        async def main():
            for _ in range(4):
                await client.get("/items/1")

        self.run_(main())
        self.assertGreaterEqual(time.monotonic() - started, 0.1)

    def test_breaker_with_a_real_failing_server(self):
        breaker = CircuitBreaker(failure_threshold=2, clock=lambda: 0.0)
        client = self.client(breaker=breaker)

        async def main():
            for _ in range(2):
                with self.assertRaises(errors.ServerError):
                    await client.get("/status/500")
            with self.assertRaises(CircuitOpen):
                await client.get("/items/1")

        before = len(self.server.requests)
        self.run_(main())
        self.assertEqual(len(self.server.requests) - before, 2)


if __name__ == "__main__":
    unittest.main()
