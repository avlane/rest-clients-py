import threading
import time
import unittest

from restclients import errors
from restclients.keepalive_client import ConnectionPool, KeepAliveClient, PoolTimeout
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class KeepAliveTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.client = KeepAliveClient(base_url=self.server.url)
        self.addCleanup(self.client.close)

    def tearDown(self):
        self.server.__exit__(None, None, None)

    def kill_idle_connections(self):
        for pool in list(self.client._pools.values()):
            for conn in pool._idle:
                conn.sock.shutdown(2)

    def test_many_requests_share_one_connection(self):
        for n in range(1, 11):
            self.assertEqual(self.client.get_json("/items/%d" % (n % 5 + 1))["id"], n % 5 + 1)
        self.assertEqual(self.server.connections, 1)
        self.assertEqual(self.client.connections_opened, 1)

    def test_urllib_opens_one_connection_per_request(self):
        plain = UrllibClient(base_url=self.server.url)
        for _ in range(5):
            plain.get("/items/1")
        self.assertEqual(self.server.connections, 5)

    def test_post_and_error_responses_keep_the_connection(self):
        self.client.post("/items", json={"name": "x"})
        with self.assertRaises(errors.NotFound):
            self.client.get("/items/999")
        self.client.delete("/items/24")
        self.assertEqual(self.server.connections, 1)

    def test_reconnects_after_the_server_closes_the_connection(self):
        self.client.get("/items/1")
        self.client.get("/drop", params={"key": "ka", "fail": 0})  # normal answer, keeps alive
        # simulate an idle timeout: the connection dies while it sits in the pool
        self.kill_idle_connections()
        self.assertEqual(self.client.get_json("/items/2")["id"], 2)
        self.assertEqual(self.client.connections_opened, 2)

    def test_post_on_dead_connection_is_not_silently_repeated(self):
        self.client.get("/items/1")
        self.kill_idle_connections()
        with self.assertRaises(errors.TransportError):
            self.client.post("/items", json={"name": "y"})

    def test_timeout_discards_the_connection(self):
        with self.assertRaises(errors.TransportError):
            self.client.get("/slow", params={"delay": 1}, timeout=0.1)
        self.assertEqual(self.client.get_json("/items/1")["id"], 1)
        self.assertEqual(self.client.connections_opened, 2)

    def test_connection_close_response_is_honoured(self):
        self.client.get("/items/1", headers={"Connection": "close"})
        self.client.get("/items/1")
        self.assertEqual(self.client.connections_opened, 2)

    def test_connection_refused(self):
        with ApiServer() as dead:
            url = dead.url
        with self.assertRaises(errors.TransportError):
            KeepAliveClient(base_url=url).get("/items/1")


class PoolTests(unittest.TestCase):
    def test_pool_limits_and_reuses(self):
        made = []
        pool = ConnectionPool(lambda: made.append(1) or Dummy(), max_size=2)
        a, reused_a = pool.acquire()
        b, _ = pool.acquire()
        self.assertFalse(reused_a)
        with self.assertRaises(PoolTimeout):
            pool.acquire(timeout=0.05)
        pool.release(a)
        again, reused = pool.acquire(timeout=0.05)
        self.assertIs(again, a)
        self.assertTrue(reused)
        self.assertEqual(len(made), 2)

    def test_unusable_connection_is_closed_not_pooled(self):
        pool = ConnectionPool(Dummy, max_size=1)
        conn, _ = pool.acquire()
        pool.release(conn, reusable=False)
        self.assertTrue(conn.closed)
        fresh, reused = pool.acquire()
        self.assertIsNot(fresh, conn)
        self.assertFalse(reused)

    def test_waiter_is_woken_by_release(self):
        pool = ConnectionPool(Dummy, max_size=1)
        conn, _ = pool.acquire()
        got = []
        t = threading.Thread(target=lambda: got.append(pool.acquire(timeout=2)))
        t.start()
        pool.release(conn)
        t.join(3)
        self.assertEqual(got[0][0], conn)

    def test_invalid_size(self):
        with self.assertRaises(ValueError):
            ConnectionPool(Dummy, max_size=0)


class Dummy:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class ThreadedUseTests(unittest.TestCase):
    def test_threads_share_a_bounded_pool(self):
        with ApiServer() as server:
            client = KeepAliveClient(base_url=server.url, max_connections=3)
            results, failures = [], []

            def work(n):
                try:
                    results.append(client.get_json("/slow", {"delay": 0.05, "n": n})["n"])
                except Exception as exc:  # pragma: no cover - reported below
                    failures.append(exc)

            threads = [threading.Thread(target=work, args=(n,)) for n in range(12)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)
            client.close()
        self.assertEqual(failures, [])
        self.assertEqual(sorted(results), sorted(str(n) for n in range(12)))
        self.assertLessEqual(server.connections, 3)
        self.assertLessEqual(server.max_in_flight, 3)

    def test_pool_timeout_becomes_transport_error(self):
        with ApiServer() as server:
            client = KeepAliveClient(base_url=server.url, max_connections=1, pool_timeout=0.1)
            holder = threading.Thread(target=lambda: client.get("/slow", params={"delay": 0.5}))
            holder.start()
            while server.max_in_flight == 0:
                time.sleep(0.005)
            with self.assertRaises(errors.TransportError) as ctx:
                client.get("/items/1")
            holder.join(5)
            client.close()
        self.assertIn("no free connection", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
