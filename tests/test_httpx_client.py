import unittest

from restclients import errors
from restclients.auth import BearerAuth
from restclients.httpx_client import HttpxClient
from restclients.retry import RetryPolicy
from restclients.testing import FakeResponse, FakeSession


class ReadTimeout(Exception):  # shaped like httpx.ReadTimeout
    pass


ReadTimeout.__module__ = "httpx"


class HttpxClientTests(unittest.TestCase):
    def test_request_shape(self):
        fake = FakeSession([FakeResponse(json={"id": 7})])
        client = HttpxClient(fake, base_url="http://api.test", timeout=(2, 5),
                             auth=BearerAuth("tok"))
        self.assertEqual(client.get_json("/items/7", params={"expand": "tags"}), {"id": 7})
        call = fake.calls[0]
        self.assertEqual(call["url"], "http://api.test/items/7?expand=tags")
        self.assertEqual(call["timeout"], (2, 5))
        self.assertEqual(call["headers"]["Authorization"], "Bearer tok")

    def test_body_is_sent_as_content(self):
        fake = FakeSession()
        HttpxClient(fake).post("http://api.test/items", json={"a": 1})
        self.assertEqual(fake.sent_json(), {"a": 1})

    def test_status_errors(self):
        fake = FakeSession([FakeResponse(404, json={"error": "nope"})])
        with self.assertRaises(errors.NotFound):
            HttpxClient(fake).get("http://api.test/x")

    def test_httpx_exceptions_become_transport_errors(self):
        fake = FakeSession([ReadTimeout("timed out")])
        with self.assertRaises(errors.TransportError) as ctx:
            HttpxClient(fake).get("http://api.test/x")
        self.assertIn("ReadTimeout", ctx.exception.message)

    def test_retry_loop_is_shared(self):
        fake = FakeSession([ReadTimeout("timeout"), FakeResponse(json={"ok": 1})])
        sleeps = []
        client = HttpxClient(fake, retry=RetryPolicy(jitter=False), sleep=sleeps.append)
        self.assertEqual(client.get_json("http://api.test/x"), {"ok": 1})
        self.assertEqual(sleeps, [0.5])

    def test_close(self):
        fake = FakeSession()
        with HttpxClient(fake):
            pass
        self.assertTrue(fake.closed)


if __name__ == "__main__":
    unittest.main()
