import unittest

from restclients import errors
from restclients.response import Headers, Response
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class HeadersTests(unittest.TestCase):
    def test_case_insensitive(self):
        h = Headers({"Content-Type": "text/plain"})
        self.assertEqual(h["content-type"], "text/plain")
        self.assertEqual(h.get("CONTENT-TYPE"), "text/plain")
        self.assertIn("content-TYPE", h)
        self.assertIsNone(h.get("missing"))

    def test_keeps_original_spelling(self):
        self.assertEqual(list(Headers([("ETag", "x")])), ["ETag"])


class ResponseTests(unittest.TestCase):
    def test_json_and_text(self):
        r = Response(200, {"Content-Type": "application/json; charset=utf-8"}, b'{"a": "\xc3\xa9"}')
        self.assertEqual(r.json(), {"a": "é"})
        self.assertTrue(r.ok)

    def test_raise_for_status(self):
        with self.assertRaises(errors.NotFound):
            Response(404, {}, b'{"error": "gone"}', "http://x").raise_for_status()
        self.assertIs(Response(204).raise_for_status().status, 204)


class UrllibClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()
        cls.client = UrllibClient(base_url=cls.server.url)

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def test_get_json_relative_path(self):
        self.assertEqual(self.client.get_json("/items/2")["name"], "item-02")

    def test_default_headers_and_override(self):
        client = UrllibClient(base_url=self.server.url, headers={"X-App": "demo"})
        echo = client.get_json("/echo", headers={"Accept": "text/plain"})
        self.assertEqual(echo["headers"]["x-app"], "demo")
        self.assertEqual(echo["headers"]["accept"], "text/plain")

    def test_post_json_sets_content_type(self):
        echo = self.client.post("/echo", json={"a": 1}).json()
        self.assertEqual(echo["method"], "POST")
        self.assertEqual(echo["headers"]["content-type"], "application/json")
        self.assertEqual(echo["headers"]["content-length"], str(len('{"a": 1}')))

    def test_error_status_raises_by_default(self):
        with self.assertRaises(errors.NotFound):
            self.client.get("/items/404")

    def test_error_status_can_be_inspected(self):
        resp = self.client.get("/status/418", raise_for_status=False)
        self.assertEqual(resp.status, 418)
        self.assertFalse(resp.ok)

    def test_absolute_url_ignores_base(self):
        other = UrllibClient(base_url="http://invalid.example")
        self.assertEqual(other.get_json(self.server.url + "/items/1")["id"], 1)

    def test_timeout_pair_uses_larger_value(self):
        client = UrllibClient(base_url=self.server.url, timeout=(0.1, 0.3))
        with self.assertRaises(errors.TransportError):
            client.get("/slow", params={"delay": 1})
        self.assertEqual(client.get_json("/slow", params={"delay": 0.05}), {"slept": True})


if __name__ == "__main__":
    unittest.main()
