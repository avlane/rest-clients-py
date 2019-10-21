import unittest

from restclients.pagination import paginate_pages
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


if __name__ == "__main__":
    unittest.main()
