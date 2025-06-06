import unittest

from restclients.etag_cache import ResponseCache, cache_control_directives, freshness_lifetime
from restclients.requests_client import RequestsClient
from restclients.response import Headers, Response
from restclients.testing import FakeResponse, FakeSession
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer

NOW = 1_700_000_000.0


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def stored(headers, clock=None):
    clock = clock or Clock()
    cache = ResponseCache(clock=clock)
    base = {"ETag": '"v1"'}
    base.update(headers)
    cache.store("k", Response(200, base, b'{"n": 1}', "http://x/a"))
    return cache, clock


class LifetimeTests(unittest.TestCase):
    def lifetime(self, **headers):
        return freshness_lifetime(Headers(headers), NOW)

    def test_max_age(self):
        self.assertEqual(self.lifetime(**{"Cache-Control": "public, max-age=120"}), 120)
        self.assertEqual(self.lifetime(**{"Cache-Control": "MAX-AGE=5"}), 5)
        self.assertEqual(self.lifetime(**{"Cache-Control": 'max-age="7"'}), 7)

    def test_no_cache_and_max_age_zero_mean_revalidate(self):
        self.assertEqual(self.lifetime(**{"Cache-Control": "no-cache, max-age=60"}), 0)
        self.assertEqual(self.lifetime(**{"Cache-Control": "max-age=0"}), 0)

    def test_expires_relative_to_date(self):
        self.assertEqual(self.lifetime(Expires="Thu, 01 May 2025 12:10:00 GMT", Date="Thu, 01 May 2025 12:00:00 GMT"), 600)

    def test_max_age_beats_expires(self):
        self.assertEqual(self.lifetime(**{"Cache-Control": "max-age=5", "Expires": "Thu, 01 May 2099 00:00:00 GMT"}), 5)

    def test_invalid_or_past_expires_is_not_fresh(self):
        self.assertEqual(self.lifetime(Expires="0"), 0)
        self.assertEqual(self.lifetime(Expires="Thu, 01 May 2000 00:00:00 GMT", Date="Thu, 01 May 2025 12:00:00 GMT"), 0)

    def test_nothing_means_no_freshness(self):
        self.assertEqual(self.lifetime(), 0)

    def test_directive_names(self):
        self.assertEqual(cache_control_directives("Private, max-age=5, no-transform"),
                         {"private", "max-age", "no-transform"})
        self.assertEqual(cache_control_directives(None), set())


class StoreFreshnessTests(unittest.TestCase):
    def test_fresh_until_max_age_then_stale(self):
        cache, clock = stored({"Cache-Control": "max-age=60"})
        clock.now += 59
        response = cache.fresh("k")
        self.assertEqual((response.json(), response.from_cache, response.age), ({"n": 1}, True, 59))
        clock.now += 1
        self.assertIsNone(cache.fresh("k"))

    def test_the_age_header_counts_against_freshness(self):
        cache, clock = stored({"Cache-Control": "max-age=60", "Age": "50"})
        clock.now += 9
        self.assertIsNotNone(cache.fresh("k"))
        clock.now += 1
        self.assertIsNone(cache.fresh("k"))

    def test_no_cache_responses_are_never_fresh(self):
        cache, _ = stored({"Cache-Control": "no-cache"})
        self.assertIsNone(cache.fresh("k"))

    def test_unknown_key(self):
        self.assertIsNone(ResponseCache().fresh("nope"))

    def test_a_304_renews_freshness(self):
        cache, clock = stored({"Cache-Control": "max-age=10"})
        clock.now += 30
        self.assertIsNone(cache.fresh("k"))
        cache.revalidated("k", Response(304, {"Cache-Control": "max-age=100", "ETag": '"v1"'}, b""))
        clock.now += 50
        self.assertIsNotNone(cache.fresh("k"))


class ClientFreshnessTests(unittest.TestCase):
    def test_fresh_entries_make_no_request_at_all(self):
        clock = Clock()
        session = FakeSession([FakeResponse(200, json={"n": 1}, headers={"ETag": '"v1"', "Cache-Control": "max-age=60"})])
        client = RequestsClient(session, cache=ResponseCache(clock=clock))
        client.get("http://api.test/r")
        clock.now += 30
        again = client.get("http://api.test/r")
        self.assertEqual(again.json(), {"n": 1})
        self.assertEqual(len(session.calls), 1)

    def test_stale_entries_are_revalidated_not_refetched(self):
        clock = Clock()
        session = FakeSession([FakeResponse(200, json={"n": 1}, headers={"ETag": '"v1"', "Cache-Control": "max-age=60"}),
                               FakeResponse(304, headers={"ETag": '"v1"', "Cache-Control": "max-age=60"})])
        client = RequestsClient(session, cache=ResponseCache(clock=clock))
        client.get("http://api.test/r")
        clock.now += 61
        self.assertEqual(client.get_json("http://api.test/r"), {"n": 1})
        self.assertEqual(session.calls[1]["headers"]["If-None-Match"], '"v1"')

    def test_request_no_cache_forces_revalidation(self):
        clock = Clock()
        session = FakeSession([FakeResponse(200, json={"n": 1}, headers={"ETag": '"v1"', "Cache-Control": "max-age=60"}),
                               FakeResponse(304, headers={"ETag": '"v1"', "Cache-Control": "max-age=60"})])
        client = RequestsClient(session, cache=ResponseCache(clock=clock))
        client.get("http://api.test/r")
        client.get("http://api.test/r", headers={"Cache-Control": "no-cache"})
        self.assertEqual(len(session.calls), 2)


class AgainstRealServerTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.clock = Clock()
        self.client = UrllibClient(base_url=self.server.url, cache=ResponseCache(clock=self.clock))

    def test_within_max_age_the_server_sees_one_request(self):
        for _ in range(4):
            self.client.get("/fresh", params={"max_age": 60})
            self.clock.now += 10
        self.assertEqual(self.server.counters["fresh-200"], 1)
        self.assertNotIn("fresh-304", self.server.counters)

    def test_after_max_age_a_conditional_request_gets_a_304(self):
        self.client.get("/fresh", params={"max_age": 30})
        self.clock.now += 31
        self.client.get("/fresh", params={"max_age": 30})
        self.assertEqual((self.server.counters["fresh-200"], self.server.counters["fresh-304"]), (1, 1))

    def test_changed_resource_after_expiry_is_fetched_again(self):
        self.client.get("/fresh", params={"max_age": 30})
        self.client.post("/fresh/bump")
        self.assertEqual(self.client.get_json("/fresh", params={"max_age": 30})["version"], 1)   # still fresh: stale data!
        self.clock.now += 31
        self.assertEqual(self.client.get_json("/fresh", params={"max_age": 30})["version"], 2)

    def test_expires_header(self):
        self.client.get("/fresh", params={"expires": 100})
        self.clock.now += 50
        self.client.get("/fresh", params={"expires": 100})
        self.assertEqual(self.server.counters["fresh-200"], 1)

    def test_no_store_is_not_kept(self):
        self.client.get("/fresh", params={"cc": "no-store"})
        self.client.get("/fresh", params={"cc": "no-store"})
        self.assertEqual(self.server.counters["fresh-200"], 2)


if __name__ == "__main__":
    unittest.main()
