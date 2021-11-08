import unittest

from restclients import errors
from restclients.keepalive_client import KeepAliveClient
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class KeepAliveTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.client = KeepAliveClient(base_url=self.server.url)
        self.addCleanup(self.client.close)

    def tearDown(self):
        self.server.__exit__(None, None, None)

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
        # simulate an idle timeout: close the server side of every open connection
        for conn in list(self.client._connections.values()):
            conn.sock.shutdown(2)
        self.assertEqual(self.client.get_json("/items/2")["id"], 2)
        self.assertEqual(self.client.connections_opened, 2)

    def test_post_on_dead_connection_is_not_silently_repeated(self):
        self.client.get("/items/1")
        for conn in list(self.client._connections.values()):
            conn.sock.shutdown(2)
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


if __name__ == "__main__":
    unittest.main()
