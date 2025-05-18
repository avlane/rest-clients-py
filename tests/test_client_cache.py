import unittest

from restclients.etag_cache import ResponseCache
from restclients.requests_client import RequestsClient
from restclients.urllib_client import UrllibClient
from tests.fakes import FakeRequestsResponse, FakeSession
from tests.server import ApiServer


class CacheAgainstServerTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.cache = ResponseCache()
        self.client = UrllibClient(base_url=self.server.url, cache=self.cache)

    def tearDown(self):
        self.server.__exit__(None, None, None)

    def test_second_get_is_a_304_served_from_the_store(self):
        first = self.client.get("/etag")
        second = self.client.get("/etag")
        self.assertEqual(first.json(), second.json())
        self.assertFalse(hasattr(first, "from_cache"))
        self.assertTrue(second.from_cache)
        self.assertEqual(self.server.counters["etag-200"], 1)
        self.assertEqual(self.server.counters["etag-304"], 1)
        self.assertEqual(second.headers["Cache-Control"], "max-age=60")

    def test_changed_resource_is_refetched(self):
        self.client.get("/etag")
        self.client.post("/etag/bump")
        fresh = self.client.get("/etag")
        self.assertEqual(fresh.json()["version"], 2)
        self.assertEqual(self.server.counters["etag-200"], 2)
        self.assertEqual(self.client.get("/etag").json()["version"], 2)
        self.assertEqual(self.server.counters["etag-304"], 1)

    def test_conditional_header_is_sent(self):
        self.client.get("/etag")
        self.client.get("/etag")
        sent = [h for m, p, h in self.server.requests if p == "/etag"]
        self.assertNotIn("If-None-Match", sent[0])
        self.assertEqual(sent[1]["If-None-Match"], '"v1"')

    def test_post_is_never_cached(self):
        self.client.post("/etag/bump")
        self.assertEqual(len(self.cache), 0)

    def test_without_cache_nothing_is_conditional(self):
        plain = UrllibClient(base_url=self.server.url)
        plain.get("/etag")
        plain.get("/etag")
        self.assertEqual(self.server.counters["etag-200"], 2)


class LastModifiedAgainstServerTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.client = UrllibClient(base_url=self.server.url, cache=ResponseCache())

    def test_unchanged_resource_is_a_304_from_if_modified_since(self):
        first = self.client.get("/lastmod")
        second = self.client.get("/lastmod")
        self.assertEqual(first.json(), second.json())
        self.assertTrue(second.from_cache)
        self.assertEqual((self.server.counters["lastmod-200"], self.server.counters["lastmod-304"]), (1, 1))
        sent = [h for m, p, h in self.server.requests if p == "/lastmod"][1]
        self.assertEqual(sent["If-Modified-Since"], "Thu, 01 May 2025 12:00:00 GMT")
        self.assertNotIn("If-None-Match", sent)

    def test_modified_resource_is_refetched(self):
        self.client.get("/lastmod")
        self.client.post("/lastmod/touch")
        fresh = self.client.get("/lastmod")
        self.assertFalse(hasattr(fresh, "from_cache"))
        self.assertEqual(fresh.json()["modified"], "Thu, 01 May 2025 13:00:00 GMT")
        self.assertEqual(self.server.counters["lastmod-200"], 2)


class CacheWithFakeSessionTests(unittest.TestCase):
    def test_requests_client_uses_the_same_cache_logic(self):
        session = FakeSession([
            FakeRequestsResponse(200, b'{"a": 1}', {"ETag": '"e1"'}),
            FakeRequestsResponse(304, b"", {"ETag": '"e1"'}),
        ])
        client = RequestsClient(session, cache=ResponseCache())
        self.assertEqual(client.get_json("http://api.test/r"), {"a": 1})
        self.assertEqual(client.get_json("http://api.test/r"), {"a": 1})
        self.assertEqual(session.calls[1]["headers"]["If-None-Match"], '"e1"')


if __name__ == "__main__":
    unittest.main()
