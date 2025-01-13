import asyncio
import unittest

from restclients.async_client import ThreadedAsyncClient
from restclients.async_pagination import alist, apaginate_cursor, apaginate_links, apaginate_pages
from restclients.async_streams_client import AsyncStreamsClient
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer

IDS = list(range(1, 24))


class AsyncPaginationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()
        cls.native = AsyncStreamsClient(base_url=cls.server.url)
        cls.threaded = ThreadedAsyncClient(UrllibClient(base_url=cls.server.url))

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def run_(self, coro):
        return asyncio.run(coro)

    def ids(self, iterator):
        return [item["id"] for item in self.run_(alist(iterator))]

    def test_pages_with_both_async_transports(self):
        for client in (self.native, self.threaded):
            with self.subTest(client=type(client).__name__):
                self.assertEqual(self.ids(apaginate_pages(client, "/pages", limit=10)), IDS)

    def test_links(self):
        self.assertEqual(self.ids(apaginate_links(self.native, "/linked", params={"per_page": 10})), IDS)

    def test_cursor(self):
        self.assertEqual(self.ids(apaginate_cursor(self.native, "/cursor", params={"limit": 8})), IDS)

    def test_max_pages(self):
        self.assertEqual(len(self.ids(apaginate_pages(self.native, "/pages", limit=5, max_pages=2))), 10)
        self.assertEqual(len(self.ids(apaginate_links(self.native, "/linked", {"per_page": 5}, max_pages=2))), 10)
        self.assertEqual(len(self.ids(apaginate_cursor(self.native, "/cursor", {"limit": 5}, max_pages=3))), 15)

    def test_breaking_out_stops_requesting(self):
        async def first_three():
            got = []
            async for item in apaginate_pages(self.native, "/pages", limit=3):
                got.append(item["id"])
                if len(got) == 3:
                    break
            return got

        before = len(self.server.requests)
        self.assertEqual(self.run_(first_three()), [1, 2, 3])
        self.assertEqual(len(self.server.requests) - before, 1)

    def test_pages_can_be_consumed_concurrently_with_other_work(self):
        order = []

        async def consume():
            async for item in apaginate_pages(self.native, "/pages", limit=10):
                order.append(("item", item["id"]))

        async def other():
            await asyncio.sleep(0)
            order.append(("other", 0))

        async def main():
            await asyncio.gather(consume(), other())

        self.run_(main())
        self.assertLess(order.index(("other", 0)), order.index(("item", 23)))


if __name__ == "__main__":
    unittest.main()
