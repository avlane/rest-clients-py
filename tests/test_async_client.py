import asyncio
import unittest

from restclients import errors
from restclients.async_client import AsyncHttpxClient, ThreadedAsyncClient
from restclients.retry import RetryPolicy
from restclients.testing import FakeAsyncSession, FakeResponse
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class ConnectError(Exception):  # shaped like httpx.ConnectError
    pass


ConnectError.__module__ = "httpx"


class ThreadedAsyncClientTests(unittest.TestCase):
    """The blocking urllib client driven from an event loop, against the real server."""

    def setUp(self):
        self.server = ApiServer().__enter__()
        self.client = ThreadedAsyncClient(UrllibClient(base_url=self.server.url))

    def tearDown(self):
        self.server.__exit__(None, None, None)

    def test_get_json(self):
        item = asyncio.run(self.client.get_json("/items/5"))
        self.assertEqual(item["name"], "item-05")

    def test_error_status_raises_shared_exception(self):
        with self.assertRaises(errors.NotFound):
            asyncio.run(self.client.get("/items/999"))

    def test_post_json(self):
        resp = asyncio.run(self.client.post("/echo", json={"k": "v"}))
        self.assertEqual(resp.json()["method"], "POST")

    def test_wrapped_client_retries_apply(self):
        sync = UrllibClient(base_url=self.server.url, sleep=lambda s: None,
                            retry=RetryPolicy(jitter=False))
        body = asyncio.run(ThreadedAsyncClient(sync).get_json("/flaky", {"key": "async", "fail": 2}))
        self.assertEqual(body["call"], 3)

    def test_async_context_manager(self):
        async def main():
            async with self.client as client:
                return await client.get_json("/items/1")
        self.assertEqual(asyncio.run(main())["id"], 1)


class AsyncHttpxClientTests(unittest.TestCase):
    def test_request_shape_and_json(self):
        fake = FakeAsyncSession([FakeResponse(json={"id": 3})])
        client = AsyncHttpxClient(fake, base_url="http://api.test")
        self.assertEqual(asyncio.run(client.get_json("/items/3")), {"id": 3})
        self.assertEqual(fake.calls[0]["url"], "http://api.test/items/3")

    def test_post_body(self):
        fake = FakeAsyncSession()
        asyncio.run(AsyncHttpxClient(fake).post("http://api.test/x", json={"a": 1}))
        self.assertEqual(fake.sent_json(), {"a": 1})

    def test_httpx_error_is_transport_error(self):
        fake = FakeAsyncSession([ConnectError("refused")])
        with self.assertRaises(errors.TransportError):
            asyncio.run(AsyncHttpxClient(fake).get("http://api.test/x"))

    def test_aclose(self):
        fake = FakeAsyncSession()

        async def main():
            async with AsyncHttpxClient(fake):
                pass
        asyncio.run(main())
        self.assertTrue(fake.closed)


if __name__ == "__main__":
    unittest.main()
