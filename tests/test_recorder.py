import json
import os
import tempfile
import unittest

from restclients.auth import BearerAuth
from restclients.recorder import (Cassette, Interaction, RecordingClient, Scrubber, decode_body,
                                  encode_body)
from restclients.retry import RetryPolicy
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class BodyEncodingTests(unittest.TestCase):
    def test_text_and_binary(self):
        self.assertEqual(encode_body("café".encode("utf-8")), {"text": "café"})
        self.assertEqual(encode_body(b"\xff\x00"), {"base64": "/wA="})
        self.assertEqual(encode_body(b""), {"text": ""})
        for raw in (b"", b"plain", b"\xff\x00\x10", "café".encode("utf-8")):
            self.assertEqual(decode_body(encode_body(raw)), raw)


class CassetteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "nested", "c.json")

    def interaction(self):
        return Interaction("GET", "http://h/x", {"Accept": "a"}, b"", 200,
                           [["Content-Type", "application/json"]], b'{"a": 1}')

    def test_round_trip(self):
        cassette = Cassette(self.path)
        cassette.append(self.interaction())
        cassette.save()
        loaded = Cassette.load(self.path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded.interactions[0].to_dict(), self.interaction().to_dict())

    def test_missing_file_is_empty(self):
        self.assertEqual(len(Cassette.load(self.path)), 0)

    def test_unknown_version_is_rejected(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            json.dump({"version": 99, "interactions": []}, f)
        with self.assertRaises(ValueError):
            Cassette.load(self.path)

    def test_save_without_path(self):
        with self.assertRaises(ValueError):
            Cassette().save()

    def test_no_temp_files_left_behind(self):
        cassette = Cassette(self.path, [self.interaction()])
        cassette.save()
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["c.json"])


class RecordingClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def test_records_requests_and_responses_from_the_real_server(self):
        cassette = Cassette()
        client = RecordingClient(UrllibClient(), cassette, base_url=self.server.url)
        client.get("/items/2")
        client.post("/items", json={"name": "recorded"})
        first, second = cassette.interactions
        self.assertEqual((first.method, first.status), ("GET", 200))
        self.assertEqual(json.loads(first.response_body)["name"], "item-02")
        self.assertEqual((second.method, second.status), ("POST", 201))
        self.assertEqual(json.loads(second.request_body), {"name": "recorded"})

    def test_secrets_are_not_stored(self):
        cassette = Cassette()
        client = RecordingClient(UrllibClient(), cassette, base_url=self.server.url,
                                 auth=BearerAuth("top-secret-token"))
        client.get("/echo", params={"access_token": "top-secret-token", "q": "x"})
        # /echo reflects the token back in its response body, so that must be scrubbed too
        stored = json.dumps(cassette.interactions[0].to_dict())
        self.assertNotIn("top-secret-token", stored)
        self.assertEqual(cassette.interactions[0].request_headers["Authorization"], "***")
        self.assertIn("access_token=***", cassette.interactions[0].url)

    def test_each_retry_attempt_is_recorded(self):
        cassette = Cassette()
        client = RecordingClient(UrllibClient(), cassette, base_url=self.server.url,
                                 retry=RetryPolicy(jitter=False), sleep=lambda s: None)
        client.get("/flaky", params={"key": "rec", "fail": 1})
        self.assertEqual([i.status for i in cassette.interactions], [503, 200])

    def test_error_responses_are_recorded_before_raising(self):
        cassette = Cassette()
        client = RecordingClient(UrllibClient(), cassette, base_url=self.server.url)
        with self.assertRaises(Exception):
            client.get("/items/999")
        self.assertEqual(cassette.interactions[0].status, 404)

    def test_close_saves_the_cassette(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.json")
            with RecordingClient(UrllibClient(), Cassette(path), base_url=self.server.url) as client:
                client.get("/items/1")
            self.assertEqual(len(Cassette.load(path)), 1)


class ScrubberTests(unittest.TestCase):
    def test_json_keys_are_replaced_at_any_depth(self):
        body = json.dumps({"user": "a", "password": "pw", "nested": [{"refresh_token": "r", "ok": 1}]})
        cleaned = json.loads(Scrubber().body(body.encode()))
        self.assertEqual(cleaned, {"user": "a", "password": "***",
                                   "nested": [{"refresh_token": "***", "ok": 1}]})

    def test_untouched_json_is_returned_byte_for_byte(self):
        original = b'{"a":   1,\n "b": [true]}'
        self.assertEqual(Scrubber().body(original), original)

    def test_regexes_apply_to_text_and_json_strings(self):
        scrubber = Scrubber(regexes=[(r"\b\d{3}-\d{2}-\d{4}\b", "XXX-XX-XXXX")])
        self.assertEqual(scrubber.body(b"id 123-45-6789 end"), b"id XXX-XX-XXXX end")
        self.assertEqual(json.loads(scrubber.body(b'{"note": "ssn 123-45-6789"}')),
                         {"note": "ssn XXX-XX-XXXX"})

    def test_binary_bodies_pass_through(self):
        self.assertEqual(Scrubber(regexes=[("a", "b")]).body(b"\xff\xfe"), b"\xff\xfe")

    def test_custom_header_and_param_lists(self):
        scrubber = Scrubber(headers=["X-Tenant"], params=["sig"], json_keys=["tenant"])
        self.assertEqual(scrubber.request_headers({"x-tenant": "t1", "Authorization": "keep"}),
                         {"x-tenant": "***", "Authorization": "keep"})
        self.assertEqual(scrubber.url("http://h/p?sig=abc&access_token=keep"),
                         "http://h/p?sig=***&access_token=keep")
        self.assertEqual(json.loads(scrubber.body(b'{"tenant": "t1", "password": "kept"}')),
                         {"tenant": "***", "password": "kept"})

    def test_response_headers_like_set_cookie(self):
        self.assertEqual(Scrubber().response_headers([("Set-Cookie", "sid=1"), ("ETag", "x")]),
                         [["Set-Cookie", "***"], ["ETag", "x"]])


if __name__ == "__main__":
    unittest.main()
