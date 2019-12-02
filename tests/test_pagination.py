import unittest

from restclients.pagination import (paginate_cursor, paginate_links, paginate_pages,
                                  parse_link_header)
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class PageLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()
        cls.client = UrllibClient(base_url=cls.server.url)

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def test_walks_every_page(self):
        items = list(paginate_pages(self.client, "/pages", limit=10))
        self.assertEqual([i["id"] for i in items], list(range(1, 24)))

    def test_exact_multiple_of_limit_stops_on_total(self):
        before = len(self.server.requests)
        items = list(paginate_pages(self.client, "/pages", limit=23))
        self.assertEqual(len(items), 23)
        self.assertEqual(len(self.server.requests) - before, 1)

    def test_is_lazy(self):
        before = len(self.server.requests)
        first = next(paginate_pages(self.client, "/pages", limit=5))
        self.assertEqual(first["id"], 1)
        self.assertEqual(len(self.server.requests) - before, 1)

    def test_max_pages(self):
        items = list(paginate_pages(self.client, "/pages", limit=5, max_pages=2))
        self.assertEqual(len(items), 10)

    def test_extra_params_are_kept(self):
        list(paginate_pages(self.client, "/pages", params={"q": "x"}, limit=50))
        self.assertIn("q=x", self.server.requests[-1][1])


class LinkHeaderTests(unittest.TestCase):
    def test_parse(self):
        header = ('<https://api.test/items?page=2>; rel="next", '
                  '<https://api.test/items?page=9>; rel="last"')
        self.assertEqual(parse_link_header(header), {
            "next": "https://api.test/items?page=2", "last": "https://api.test/items?page=9"})

    def test_parse_unquoted_and_extra_params(self):
        header = '<http://x/a?b=1,2>; title="Next page"; rel=next'
        self.assertEqual(parse_link_header(header), {"next": "http://x/a?b=1,2"})

    def test_empty(self):
        self.assertEqual(parse_link_header(None), {})
        self.assertEqual(parse_link_header(""), {})
        self.assertEqual(parse_link_header("garbage"), {})


class LinkPaginationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()
        cls.client = UrllibClient(base_url=cls.server.url)

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def test_follows_next_links(self):
        before = len(self.server.requests)
        items = list(paginate_links(self.client, "/linked", params={"per_page": 10}))
        self.assertEqual([i["id"] for i in items], list(range(1, 24)))
        self.assertEqual(len(self.server.requests) - before, 3)

    def test_max_pages(self):
        items = list(paginate_links(self.client, "/linked", params={"per_page": 5}, max_pages=2))
        self.assertEqual(len(items), 10)

    def test_single_page_has_no_link_header(self):
        items = list(paginate_links(self.client, "/linked", params={"per_page": 50}))
        self.assertEqual(len(items), 23)


class CursorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()
        cls.client = UrllibClient(base_url=cls.server.url)

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def test_walks_to_the_end(self):
        items = list(paginate_cursor(self.client, "/cursor", params={"limit": 8}))
        self.assertEqual([i["id"] for i in items], list(range(1, 24)))

    def test_stops_early(self):
        before = len(self.server.requests)
        items = list(paginate_cursor(self.client, "/cursor", params={"limit": 5}, max_pages=2))
        self.assertEqual(len(items), 10)
        self.assertEqual(len(self.server.requests) - before, 2)

    def test_second_request_carries_cursor(self):
        list(paginate_cursor(self.client, "/cursor", params={"limit": 20}))
        self.assertIn("cursor=", self.server.requests[-1][1])


if __name__ == "__main__":
    unittest.main()
