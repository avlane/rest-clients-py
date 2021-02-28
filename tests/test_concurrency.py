import asyncio
import time
import unittest

from restclients import errors
from restclients.async_client import ThreadedAsyncClient
from restclients.concurrency import gather_bounded, map_bounded
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class GatherBoundedTests(unittest.TestCase):
    def test_results_keep_input_order(self):
        async def work(n):
            await asyncio.sleep(0.01 * (5 - n))
            return n * n

        result = asyncio.run(map_bounded(work, range(5), limit=3))
        self.assertEqual(result, [0, 1, 4, 9, 16])

    def test_limit_is_respected(self):
        state = {"now": 0, "peak": 0}

        async def work(n):
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
            await asyncio.sleep(0.01)
            state["now"] -= 1

        asyncio.run(map_bounded(work, range(20), limit=4))
        self.assertEqual(state["peak"], 4)

    def test_first_error_cancels_the_rest(self):
        started = []

        async def work(n):
            started.append(n)
            if n == 1:
                raise ValueError("boom")
            await asyncio.sleep(0.2)

        with self.assertRaises(ValueError):
            asyncio.run(map_bounded(work, range(10), limit=2))
        self.assertLess(len(started), 10)

    def test_return_exceptions(self):
        async def work(n):
            if n % 2:
                raise KeyError(n)
            return n

        result = asyncio.run(map_bounded(work, range(4), limit=2, return_exceptions=True))
        self.assertEqual(result[0], 0)
        self.assertIsInstance(result[1], KeyError)
        self.assertEqual(result[2], 2)

    def test_invalid_limit(self):
        with self.assertRaises(ValueError):
            asyncio.run(gather_bounded([], limit=0))


class AgainstRealServerTests(unittest.TestCase):
    def test_bounded_requests_overlap_but_stay_under_the_limit(self):
        with ApiServer() as server:
            client = ThreadedAsyncClient(UrllibClient(base_url=server.url))

            async def fetch(n):
                return (await client.get_json("/slow", {"delay": 0.1, "n": n}))["n"]

            started = time.monotonic()
            result = asyncio.run(map_bounded(fetch, range(12), limit=4))
            elapsed = time.monotonic() - started
        self.assertEqual(result, [str(n) for n in range(12)])
        self.assertLessEqual(server.max_in_flight, 4)
        self.assertGreaterEqual(server.max_in_flight, 2)
        # 12 requests of 0.1 s with 4 in parallel is about 0.3 s, far below the 1.2 s sequential cost
        self.assertLess(elapsed, 1.0)

    def test_errors_surface_as_api_errors(self):
        with ApiServer() as server:
            client = ThreadedAsyncClient(UrllibClient(base_url=server.url))

            async def fetch(n):
                return await client.get_json("/items/%d" % n)

            result = asyncio.run(map_bounded(fetch, [1, 999, 3], limit=2, return_exceptions=True))
        self.assertEqual(result[0]["id"], 1)
        self.assertIsInstance(result[1], errors.NotFound)
        self.assertEqual(result[2]["id"], 3)


if __name__ == "__main__":
    unittest.main()
