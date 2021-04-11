import asyncio
import unittest

from restclients import errors
from restclients.aiohttp_client import AiohttpClient
from restclients.testing import FakeAiohttpSession, FakeResponse


class ClientConnectorError(Exception):  # shaped like aiohttp.ClientConnectorError
    pass


ClientConnectorError.__module__ = "aiohttp.client_exceptions"


def make(session, **kwargs):
    return AiohttpClient(session, timeout_factory=lambda seconds: ("timeout", seconds), **kwargs)


class AiohttpClientTests(unittest.TestCase):
    def test_get_json(self):
        session = FakeAiohttpSession([FakeResponse(json={"id": 1})])
        client = make(session, base_url="http://api.test", timeout=4)
        self.assertEqual(asyncio.run(client.get_json("/items/1")), {"id": 1})
        self.assertEqual(session.calls[0]["timeout"], ("timeout", 4))
        self.assertEqual(session.calls[0]["url"], "http://api.test/items/1")

    def test_status_error(self):
        session = FakeAiohttpSession([FakeResponse(429, json={"error": "slow"}, headers={"Retry-After": "2"})])
        with self.assertRaises(errors.RateLimited) as ctx:
            asyncio.run(make(session).get("http://api.test/x"))
        self.assertEqual(ctx.exception.retry_after, 2.0)

    def test_body_sent_as_data(self):
        session = FakeAiohttpSession()
        asyncio.run(make(session).post("http://api.test/x", json={"a": 1}))
        self.assertEqual(session.sent_json(), {"a": 1})

    def test_connection_error(self):
        session = FakeAiohttpSession([ClientConnectorError("refused")])
        with self.assertRaises(errors.TransportError):
            asyncio.run(make(session).get("http://api.test/x"))

    def test_asyncio_timeout_is_a_transport_error(self):
        session = FakeAiohttpSession([asyncio.TimeoutError()])
        with self.assertRaises(errors.TransportError) as ctx:
            asyncio.run(make(session).get("http://api.test/x"))
        self.assertIn("timed out", ctx.exception.message)

    def test_unrelated_exception_propagates(self):
        session = FakeAiohttpSession([RuntimeError("bug")])
        with self.assertRaises(RuntimeError):
            asyncio.run(make(session).get("http://api.test/x"))

    def test_aclose(self):
        session = FakeAiohttpSession()

        async def main():
            async with make(session):
                pass
        asyncio.run(main())
        self.assertTrue(session.closed)


if __name__ == "__main__":
    unittest.main()
