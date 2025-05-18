import unittest

from restclients.etag_cache import ResponseCache
from restclients.response import Response


def ok(etag='"v1"', body=b'{"n": 1}', **extra):
    headers = {"ETag": etag, "Content-Type": "application/json"}
    headers.update(extra)
    return Response(200, headers, body, "http://x/a")


class ResponseCacheTests(unittest.TestCase):
    def test_stores_only_200_with_etag(self):
        cache = ResponseCache()
        self.assertTrue(cache.store("k", ok()))
        self.assertFalse(cache.store("k2", Response(200, {}, b"x")))
        self.assertFalse(cache.store("k3", Response(404, {"ETag": '"z"'}, b"x")))
        self.assertEqual(len(cache), 1)

    def test_no_store_is_respected(self):
        cache = ResponseCache()
        self.assertFalse(cache.store("k", ok(**{"Cache-Control": "private, No-Store"})))

    def test_conditional_headers(self):
        cache = ResponseCache()
        self.assertEqual(cache.conditional_headers("k"), {})
        cache.store("k", ok('W/"abc"'))
        self.assertEqual(cache.conditional_headers("k"), {"If-None-Match": 'W/"abc"'})

    def test_revalidated_uses_stored_body_and_new_headers(self):
        cache = ResponseCache()
        cache.store("k", ok(**{"Cache-Control": "max-age=10"}))
        not_modified = Response(304, {"Cache-Control": "max-age=60", "Content-Length": "0",
                                      "ETag": '"v1"'}, b"")
        full = cache.revalidated("k", not_modified)
        self.assertEqual((full.status, full.json()), (200, {"n": 1}))
        self.assertEqual(full.headers["cache-control"], "max-age=60")
        self.assertEqual(full.headers["content-type"], "application/json")
        self.assertTrue(full.from_cache)
        self.assertEqual(cache.hits, 1)

    def test_last_modified_alone_is_enough_to_store_and_revalidate(self):
        cache = ResponseCache()
        stamp = "Thu, 01 May 2025 12:00:00 GMT"
        self.assertTrue(cache.store("k", Response(200, {"Last-Modified": stamp}, b"{}", "http://x/a")))
        self.assertEqual(cache.conditional_headers("k"), {"If-Modified-Since": stamp})

    def test_both_validators_are_sent_when_both_exist(self):
        cache = ResponseCache()
        stamp = "Thu, 01 May 2025 12:00:00 GMT"
        cache.store("k", ok('"v9"', **{"Last-Modified": stamp}))
        self.assertEqual(cache.conditional_headers("k"), {"If-None-Match": '"v9"', "If-Modified-Since": stamp})

    def test_neither_validator_means_not_stored(self):
        self.assertFalse(ResponseCache().store("k", Response(200, {"Content-Type": "x"}, b"")))

    def test_lru_eviction(self):
        cache = ResponseCache(max_entries=2)
        cache.store("a", ok('"1"'))
        cache.store("b", ok('"2"'))
        cache.get("a")  # b is now the oldest
        cache.store("c", ok('"3"'))
        self.assertIn("a", cache)
        self.assertNotIn("b", cache)
        self.assertIn("c", cache)


if __name__ == "__main__":
    unittest.main()
