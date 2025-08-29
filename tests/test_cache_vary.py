import unittest

from restclients.etag_cache import ResponseCache, vary_names
from restclients.response import Headers, Response
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


def resp(vary=None, etag='"e1"', body=b"x"):
    headers = {"ETag": etag, "Cache-Control": "max-age=60"}
    if vary is not None:
        headers["Vary"] = vary
    return Response(200, headers, body, "http://x/a")


class VaryUnitTests(unittest.TestCase):
    def test_vary_names(self):
        self.assertEqual(vary_names(Headers({"Vary": "Accept, Accept-Language"})), ["accept", "accept-language"])
        self.assertEqual(vary_names(Headers({})), [])
        self.assertIsNone(vary_names(Headers({"Vary": "Accept, *"})))

    def test_entry_is_only_reused_for_the_same_values(self):
        cache = ResponseCache()
        cache.store("k", resp("Accept"), {"Accept": "application/json"})
        self.assertIsNotNone(cache.fresh("k", {"accept": "application/json"}))        # header case differs
        self.assertIsNone(cache.fresh("k", {"Accept": "text/plain"}))
        self.assertIsNone(cache.fresh("k", {}))
        self.assertEqual(cache.conditional_headers("k", {"Accept": "text/plain"}), {})
        self.assertEqual(cache.conditional_headers("k", {"Accept": "application/json"}), {"If-None-Match": '"e1"'})

    def test_whitespace_differences_do_not_matter(self):
        cache = ResponseCache()
        cache.store("k", resp("Accept"), {"Accept": "text/html,  application/json"})
        self.assertIsNotNone(cache.fresh("k", {"Accept": " text/html, application/json "}))

    def test_no_vary_header_means_any_request_matches(self):
        cache = ResponseCache()
        cache.store("k", resp(), {"Accept": "a"})
        self.assertIsNotNone(cache.fresh("k", {"Accept": "b"}))

    def test_a_header_missing_from_both_requests_matches(self):
        cache = ResponseCache()
        cache.store("k", resp("Accept-Language"), {})
        self.assertIsNotNone(cache.fresh("k", {}))
        self.assertIsNone(cache.fresh("k", {"Accept-Language": "fr"}))

    def test_vary_star_is_never_stored(self):
        cache = ResponseCache()
        self.assertFalse(cache.store("k", resp("*"), {}))
        self.assertEqual(len(cache), 0)

    def test_vary_star_drops_an_older_entry_for_the_key(self):
        cache = ResponseCache()
        cache.store("k", resp(), {})
        cache.store("k", resp("*"), {})
        self.assertNotIn("k", cache)

    def test_multiple_varying_headers(self):
        cache = ResponseCache()
        cache.store("k", resp("Accept, Accept-Language"), {"Accept": "a", "Accept-Language": "en"})
        self.assertIsNone(cache.fresh("k", {"Accept": "a", "Accept-Language": "fr"}))
        self.assertIsNotNone(cache.fresh("k", {"Accept": "a", "Accept-Language": "en"}))


class VaryAgainstServerTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.client = UrllibClient(base_url=self.server.url, cache=ResponseCache())

    def test_a_different_accept_header_never_gets_the_other_representation(self):
        as_json = self.client.get("/vary", headers={"Accept": "application/json"})
        as_text = self.client.get("/vary", headers={"Accept": "text/plain"})
        self.assertEqual(as_json.json(), {"representation": "json"})     # the bug returned this for both
        self.assertEqual(as_text.text, "plain text representation")
        self.assertFalse(hasattr(as_text, "from_cache"))

    def test_same_accept_is_served_from_the_cache(self):
        self.client.get("/vary", headers={"Accept": "text/plain"})
        again = self.client.get("/vary", headers={"Accept": "text/plain"})
        self.assertTrue(again.from_cache)
        self.assertEqual(self.server.counters["vary-200"], 1)

    def test_revalidation_uses_the_etag_of_the_matching_representation(self):
        self.client.get("/vary", params={"max_age": 0}, headers={"Accept": "text/plain"})
        again = self.client.get("/vary", params={"max_age": 0}, headers={"Accept": "text/plain"})
        sent = [h for m, p, h in self.server.requests if p.startswith("/vary")][1]
        self.assertEqual(sent["If-None-Match"], '"vary-text-1"')
        self.assertEqual(again.text, "plain text representation")
        self.assertEqual(self.server.counters["vary-304"], 1)

    def test_switching_representation_does_not_send_the_wrong_validator(self):
        self.client.get("/vary", params={"max_age": 0}, headers={"Accept": "application/json"})
        self.client.get("/vary", params={"max_age": 0}, headers={"Accept": "text/plain"})
        sent = [h for m, p, h in self.server.requests if p.startswith("/vary")][1]
        self.assertNotIn("If-None-Match", sent)

    def test_vary_star_responses_are_not_cached(self):
        self.client.get("/vary", params={"vary": "*"})
        self.client.get("/vary", params={"vary": "*"})
        self.assertEqual(self.server.counters["vary-200"], 2)


if __name__ == "__main__":
    unittest.main()
