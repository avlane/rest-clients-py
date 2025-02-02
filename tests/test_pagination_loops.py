import asyncio
import unittest
from unittest import mock

from restclients import pagination
from restclients.async_pagination import alist, apaginate_cursor, apaginate_links, apaginate_pages
from restclients.async_streams_client import AsyncStreamsClient
from restclients.errors import PaginationLoop
from restclients.pagination import paginate_cursor, paginate_links, paginate_pages
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class LoopDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()
        cls.client = UrllibClient(base_url=cls.server.url)
        cls.async_client = AsyncStreamsClient(base_url=cls.server.url)

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def test_link_pointing_at_itself(self):
        with self.assertRaisesRegex(PaginationLoop, "links back"):
            list(paginate_links(self.client, "/broken_pages/links"))

    def test_link_cycle_across_several_pages(self):
        seen = []
        with self.assertRaises(PaginationLoop):
            for item in paginate_links(self.client, "/broken_pages/links-cycle", params={"page": 1}):
                seen.append(item["id"])
        self.assertEqual(len(seen), 6)               # three pages were fetched before the cycle closed

    def test_repeated_cursor(self):
        with self.assertRaisesRegex(PaginationLoop, "same-every-time"):
            list(paginate_cursor(self.client, "/broken_pages/cursor"))

    def test_server_that_ignores_the_page_parameter(self):
        with self.assertRaisesRegex(PaginationLoop, "ignoring 'page'"):
            list(paginate_pages(self.client, "/broken_pages/ignores-page", limit=3))

    def test_async_versions_detect_the_same_problems(self):
        for factory, path in ((lambda: apaginate_links(self.async_client, "/broken_pages/links"), "links"),
                              (lambda: apaginate_cursor(self.async_client, "/broken_pages/cursor"), "cursor"),
                              (lambda: apaginate_pages(self.async_client, "/broken_pages/ignores-page", limit=3), "pages")):
            with self.subTest(kind=path):
                with self.assertRaises(PaginationLoop):
                    asyncio.run(alist(factory()))

    def test_legitimate_listings_are_unaffected(self):
        self.assertEqual(len(list(paginate_links(self.client, "/linked", params={"per_page": 10}))), 23)
        self.assertEqual(len(list(paginate_cursor(self.client, "/cursor", params={"limit": 10}))), 23)
        self.assertEqual(len(list(paginate_pages(self.client, "/pages", limit=10))), 23)

    def test_hard_page_limit_stops_an_endless_but_changing_listing(self):
        class Endless:
            """Every page is new and has a next cursor, so only the hard limit can end it."""
            def __init__(self):
                self.calls = 0

            def get_json(self, path, params=None):
                self.calls += 1
                return {"data": [self.calls], "meta": {"next_cursor": "c%d" % self.calls}}

        client = Endless()
        with mock.patch.object(pagination, "HARD_PAGE_LIMIT", 50):
            with self.assertRaisesRegex(PaginationLoop, "after 50 pages"):
                list(paginate_cursor(client, "/x"))
        self.assertEqual(client.calls, 50)

    def test_pagination_loop_is_an_api_error(self):
        from restclients.errors import ApiError
        self.assertTrue(issubclass(PaginationLoop, ApiError))


if __name__ == "__main__":
    unittest.main()
