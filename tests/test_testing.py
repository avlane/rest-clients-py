import unittest

from restclients.errors import NotFound
from restclients.requests_client import RequestsClient
from restclients.testing import FakeResponse, FakeSession


class FakeSessionTests(unittest.TestCase):
    def test_routes_by_method_and_url(self):
        session = FakeSession()
        session.respond("GET", "http://api.test/a", FakeResponse(json={"a": 1}))
        session.respond("GET", "http://api.test/b", FakeResponse(404, json={"error": "gone"}))
        client = RequestsClient(session)
        self.assertEqual(client.get_json("http://api.test/a"), {"a": 1})
        with self.assertRaises(NotFound):
            client.get("http://api.test/b")

    def test_sequence_then_last_repeats(self):
        session = FakeSession().respond("GET", "http://api.test/s", FakeResponse(500), FakeResponse(200))
        statuses = [session.request("GET", "http://api.test/s").status_code for _ in range(4)]
        self.assertEqual(statuses, [500, 200, 200, 200])

    def test_queue_fallback_and_default(self):
        session = FakeSession([FakeResponse(201)])
        self.assertEqual(session.request("POST", "http://x").status_code, 201)
        self.assertEqual(session.request("POST", "http://x").status_code, 200)

    def test_exceptions_are_raised(self):
        session = FakeSession([TimeoutError("slow")])
        with self.assertRaises(TimeoutError):
            session.request("GET", "http://x")

    def test_recording_helpers(self):
        session = FakeSession()
        RequestsClient(session).post("http://api.test/items", json={"n": 1})
        self.assertEqual(session.sent_json(), {"n": 1})
        self.assertEqual(len(session.calls_to("post", "http://api.test/items")), 1)
        self.assertEqual(session.calls_to("GET", "http://api.test/items"), [])

    def test_fake_response_helpers(self):
        resp = FakeResponse(200, "héllo")
        self.assertEqual(resp.text, "héllo")
        self.assertEqual(FakeResponse(json={"k": 1}).headers["Content-Type"], "application/json")
        self.assertEqual(FakeResponse(json={"k": 1}).json(), {"k": 1})


if __name__ == "__main__":
    unittest.main()
