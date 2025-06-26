import json
import os
import stat
import tempfile
import unittest

from restclients.etag_cache import ResponseCache
from restclients.response import Response
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


def response(name, etag, body=b'{"ok": true}', **headers):
    base = {"ETag": etag, "Cache-Control": "max-age=100"}
    base.update(headers)
    return Response(200, base, body, "http://x/" + name)


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "sub", "cache.json")

    def test_round_trip_keeps_bodies_headers_and_freshness(self):
        clock = Clock()
        cache = ResponseCache(clock=clock)
        cache.store("a", response("a", '"1"', "café".encode("utf-8")))
        cache.store("b", response("b", '"2"', b"\xff\x00binary", Age="20"))
        cache.save(self.path)
        loaded = ResponseCache.load(self.path, clock=clock)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded.fresh("a").content, "café".encode("utf-8"))
        self.assertEqual(loaded.fresh("b").content, b"\xff\x00binary")
        self.assertEqual(loaded.conditional_headers("a"), {"If-None-Match": '"1"'})
        clock.now += 85                               # 100 s lifetime, 20 s old on arrival: stale after 80
        self.assertIsNotNone(loaded.fresh("a"))
        self.assertIsNone(loaded.fresh("b"))

    def test_lru_order_survives(self):
        cache = ResponseCache(max_entries=3)
        for name in "abc":
            cache.store(name, response(name, '"%s"' % name))
        cache.get("a")                                # a is now the most recent; b the oldest
        cache.save(self.path)
        loaded = ResponseCache.load(self.path, max_entries=3)
        loaded.store("d", response("d", '"d"'))
        self.assertNotIn("b", loaded)
        self.assertIn("a", loaded)

    def test_smaller_limit_on_load_evicts_the_oldest(self):
        cache = ResponseCache()
        for name in "abcd":
            cache.store(name, response(name, '"%s"' % name))
        cache.save(self.path)
        loaded = ResponseCache.load(self.path, max_entries=2)
        self.assertEqual([k for k in "abcd" if k in loaded], ["c", "d"])

    @unittest.skipIf(os.name != "posix", "file permissions are POSIX specific")
    def test_file_is_private_to_the_owner(self):
        cache = ResponseCache()
        cache.store("a", response("a", '"1"'))
        cache.save(self.path)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_missing_file_is_an_empty_cache(self):
        self.assertEqual(len(ResponseCache.load(self.path)), 0)

    def test_corrupt_or_foreign_files_are_ignored_with_a_warning(self):
        os.makedirs(os.path.dirname(self.path))
        for content in ("{not json", json.dumps({"version": 99, "entries": []}),
                        json.dumps({"version": 1, "entries": [{"key": "a"}]}), "[]"):
            with self.subTest(content=content[:20]):
                with open(self.path, "w") as f:
                    f.write(content)
                with self.assertLogs("restclients.cache", "WARNING"):
                    self.assertEqual(len(ResponseCache.load(self.path)), 0)

    def test_no_temp_files_are_left_behind(self):
        cache = ResponseCache()
        cache.store("a", response("a", '"1"'))
        cache.save(self.path)
        cache.save(self.path)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["cache.json"])


class SharedAcrossProcessesTests(unittest.TestCase):
    def test_a_new_client_with_a_loaded_cache_revalidates_with_the_stored_etag(self):
        with tempfile.TemporaryDirectory() as tmp, ApiServer() as server:
            path = os.path.join(tmp, "cache.json")
            first = UrllibClient(base_url=server.url, cache=ResponseCache())
            first.get("/etag")
            first.cache.save(path)
            second = UrllibClient(base_url=server.url, cache=ResponseCache.load(path))   # "next run"
            again = second.get("/etag")
            self.assertTrue(again.from_cache)
            self.assertEqual((server.counters["etag-200"], server.counters["etag-304"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
