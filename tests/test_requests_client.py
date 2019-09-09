import unittest

from restclients import errors
from restclients.requests_client import RequestsClient
from tests.fakes import FakeRequestsResponse, FakeSession


class ConnectionError(Exception):  # shaped like requests.exceptions.ConnectionError
    pass


ConnectionError.__module__ = "requests.exceptions"


class RequestsClientTests(unittest.TestCase):
    def test_request_is_forwarded_to_session(self):
        session = FakeSession([FakeRequestsResponse(200, b'{"id": 1}', {"X-A": "b"})])
        client = RequestsClient(session, base_url="http://api.test", timeout=3)
        resp = client.get("/items", params={"page": 2})
        self.assertEqual(resp.json(), {"id": 1})
        self.assertEqual(resp.headers["x-a"], "b")
        call = session.calls[0]
        self.assertEqual((call["method"], call["url"]), ("GET", "http://api.test/items?page=2"))
        self.assertEqual(call["timeout"], 3)
        self.assertEqual(call["headers"]["Accept"], "application/json")

    def test_json_body(self):
        session = FakeSession()
        RequestsClient(session).post("http://api.test/items", json={"name": "x"})
        self.assertEqual(session.calls[0]["data"], b'{"name": "x"}')
        self.assertEqual(session.calls[0]["headers"]["Content-Type"], "application/json")

    def test_error_status_uses_shared_exceptions(self):
        session = FakeSession([FakeRequestsResponse(404, b'{"error": "nope"}')])
        with self.assertRaises(errors.NotFound) as ctx:
            RequestsClient(session).get("http://api.test/x")
        self.assertEqual(ctx.exception.message, "nope")

    def test_requests_exceptions_become_transport_errors(self):
        session = FakeSession([ConnectionError("refused")])
        with self.assertRaises(errors.TransportError):
            RequestsClient(session).get("http://api.test/x")

    def test_other_exceptions_pass_through(self):
        session = FakeSession([KeyError("bug")])
        with self.assertRaises(KeyError):
            RequestsClient(session).get("http://api.test/x")

    def test_close_closes_session(self):
        session = FakeSession()
        RequestsClient(session).close()
        self.assertTrue(session.closed)


if __name__ == "__main__":
    unittest.main()
