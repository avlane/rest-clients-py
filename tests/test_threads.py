import threading
import time
import unittest

from restclients import errors
from restclients.keepalive_client import KeepAliveClient
from restclients.logging_utils import correlation_id
from restclients.threads import get_many, map_concurrent
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class MapConcurrentTests(unittest.TestCase):
    def test_results_keep_input_order(self):
        def work(n):
            time.sleep(0.01 * (6 - n))
            return n * n

        self.assertEqual(map_concurrent(work, range(6), workers=3), [0, 1, 4, 9, 16, 25])

    def test_worker_limit(self):
        state = {"now": 0, "peak": 0}
        lock = threading.Lock()

        def work(n):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.02)
            with lock:
                state["now"] -= 1

        map_concurrent(work, range(12), workers=3)
        self.assertEqual(state["peak"], 3)

    def test_first_error_is_raised_and_unstarted_work_is_skipped(self):
        started = []

        def work(n):
            started.append(n)
            if n == 0:
                raise KeyError("boom")
            time.sleep(0.05)

        with self.assertRaises(KeyError):
            map_concurrent(work, range(40), workers=2)
        self.assertLess(len(started), 40)

    def test_return_exceptions(self):
        def work(n):
            if n % 2:
                raise ValueError(n)
            return n

        result = map_concurrent(work, range(4), workers=2, return_exceptions=True)
        self.assertEqual(result[0], 0)
        self.assertIsInstance(result[1], ValueError)
        self.assertEqual(result[2], 2)

    def test_context_variables_reach_the_workers(self):
        token = correlation_id.set("job-9")
        try:
            seen = map_concurrent(lambda _: correlation_id.get(), range(5), workers=3)
        finally:
            correlation_id.reset(token)
        self.assertEqual(seen, ["job-9"] * 5)

    def test_workers_do_not_leak_context_changes_to_each_other(self):
        def work(n):
            correlation_id.set("task-%d" % n)
            time.sleep(0.01)
            return correlation_id.get()

        self.assertEqual(map_concurrent(work, range(6), workers=3), ["task-%d" % n for n in range(6)])
        self.assertIsNone(correlation_id.get())

    def test_invalid_worker_count_and_empty_input(self):
        with self.assertRaises(ValueError):
            map_concurrent(len, [], workers=0)
        self.assertEqual(map_concurrent(len, []), [])


class AgainstRealServerTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)

    def test_get_many_with_a_shared_client(self):
        client = UrllibClient(base_url=self.server.url)
        started = time.monotonic()
        paths = ["/slow?delay=0.1&n=%d" % n for n in range(12)]
        bodies = get_many(client, paths, workers=4)
        elapsed = time.monotonic() - started
        self.assertEqual([b["n"] for b in bodies], [str(n) for n in range(12)])
        self.assertLessEqual(self.server.max_in_flight, 4)
        self.assertGreaterEqual(self.server.max_in_flight, 3)
        self.assertLess(elapsed, 0.9)

    def test_keep_alive_pool_shared_by_the_workers(self):
        client = KeepAliveClient(base_url=self.server.url, max_connections=4)
        try:
            bodies = get_many(client, ["/items/%d" % (n % 20 + 1) for n in range(60)], workers=4)
        finally:
            client.close()
        self.assertEqual(len(bodies), 60)
        self.assertLessEqual(self.server.connections, 4)

    def test_per_item_errors(self):
        client = UrllibClient(base_url=self.server.url)
        result = get_many(client, ["/items/1", "/items/999", "/items/3"], workers=2, return_exceptions=True)
        self.assertEqual(result[0]["id"], 1)
        self.assertIsInstance(result[1], errors.NotFound)
        self.assertEqual(result[2]["id"], 3)

    def test_request_ids_follow_the_correlation_context_into_threads(self):
        client = UrllibClient(base_url=self.server.url)
        token = correlation_id.set("batch-77")
        try:
            get_many(client, ["/items/1", "/items/2", "/items/3"], workers=3)
        finally:
            correlation_id.reset(token)
        sent = {h["X-Request-Id"] for m, p, h in self.server.requests}
        self.assertEqual(sent, {"batch-77"})


if __name__ == "__main__":
    unittest.main()
