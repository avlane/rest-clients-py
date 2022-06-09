import io
import json
import logging
import unittest

from restclients.auth import BearerAuth
from restclients.logging_utils import JsonFormatter, correlation_id, redact_headers, redact_url
from restclients.retry import RetryPolicy
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class RedactionTests(unittest.TestCase):
    def test_headers(self):
        shown = redact_headers({"Authorization": "Bearer abc", "Accept": "x", "X-Api-Key": "k"})
        self.assertEqual(shown, {"Authorization": "***", "Accept": "x", "X-Api-Key": "***"})

    def test_url_query_secrets(self):
        self.assertEqual(redact_url("http://h/p?page=2&access_token=abc&q=a%20b"),
                         "http://h/p?page=2&access_token=***&q=a+b")

    def test_url_password(self):
        self.assertEqual(redact_url("http://bob:hunter2@h/p"), "http://bob:***@h/p")

    def test_clean_url_untouched(self):
        self.assertEqual(redact_url("http://h/p?page=2"), "http://h/p?page=2")


class JsonFormatterTests(unittest.TestCase):
    def format(self, **extra):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger("test.jsonfmt.%d" % id(stream))
        logger.propagate = False
        logger.addHandler(handler)
        logger.warning("hello %s", "world", extra=extra)
        return json.loads(stream.getvalue())

    def test_fields(self):
        record = self.format(status=503, attempt=2)
        self.assertEqual((record["level"], record["message"]), ("WARNING", "hello world"))
        self.assertEqual((record["status"], record["attempt"]), (503, 2))
        self.assertTrue(record["ts"].endswith("+00:00"))

    def test_unserialisable_extra_does_not_crash(self):
        self.assertIn("object", self.format(thing=object())["thing"])


class ClientLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def test_success_is_logged_with_duration_and_no_secrets(self):
        client = UrllibClient(base_url=self.server.url, auth=BearerAuth("super-secret"))
        with self.assertLogs("restclients.http", "INFO") as logs:
            client.get("/items/1", params={"access_token": "super-secret"})
        record = logs.records[0]
        self.assertEqual((record.method, record.status, record.attempt), ("GET", 200, 1))
        self.assertGreaterEqual(record.duration_ms, 0)
        self.assertNotIn("super-secret", logs.output[0])
        self.assertNotIn("super-secret", record.url)

    def test_each_retry_attempt_is_logged(self):
        client = UrllibClient(base_url=self.server.url, sleep=lambda s: None,
                              retry=RetryPolicy(jitter=False))
        with self.assertLogs("restclients.http", "INFO") as logs:
            client.get("/flaky", params={"key": "logtest", "fail": 2})
        self.assertEqual([(r.levelname, r.status, r.attempt) for r in logs.records],
                         [("WARNING", 503, 1), ("WARNING", 503, 2), ("INFO", 200, 3)])

    def test_transport_failure_is_logged_as_error(self):
        with ApiServer() as dead:
            url = dead.url
        client = UrllibClient(base_url=url)
        with self.assertLogs("restclients.http", "ERROR") as logs:
            with self.assertRaises(Exception):
                client.get("/items/1")
        self.assertIsNone(logs.records[0].status)
        self.assertIn("failed", logs.output[0])

    def test_request_id_is_sent_logged_and_shared_across_retries(self):
        client = UrllibClient(base_url=self.server.url, sleep=lambda s: None,
                              retry=RetryPolicy(jitter=False))
        with self.assertLogs("restclients.http", "INFO") as logs:
            client.get("/flaky", params={"key": "rid", "fail": 1})
        ids = {r.request_id for r in logs.records}
        self.assertEqual(len(ids), 1)
        sent = [h["X-Request-Id"] for m, p, h in self.server.requests if "key=rid" in p]
        self.assertEqual(sent, [ids.pop()] * 2)
        self.assertEqual(logs.records[-1].server_request_id, sent[0])

    def test_caller_supplied_request_id_wins(self):
        client = UrllibClient(base_url=self.server.url)
        with self.assertLogs("restclients.http", "INFO") as logs:
            client.get("/items/1", headers={"X-Request-ID": "mine-1"})
        self.assertEqual(logs.records[0].request_id, "mine-1")

    def test_correlation_id_context(self):
        client = UrllibClient(base_url=self.server.url)
        token = correlation_id.set("job-42")
        try:
            with self.assertLogs("restclients.http", "INFO") as logs:
                client.get("/items/1")
                client.get("/items/2")
        finally:
            correlation_id.reset(token)
        self.assertEqual([r.request_id for r in logs.records], ["job-42", "job-42"])

    def test_request_id_can_be_disabled(self):
        client = UrllibClient(base_url=self.server.url, request_id_header=None)
        client.get("/echo")
        self.assertNotIn("X-Request-Id", self.server.requests[-1][2])

    def test_custom_logger(self):
        client = UrllibClient(base_url=self.server.url, logger=logging.getLogger("my.app.http"))
        with self.assertLogs("my.app.http", "INFO"):
            client.get("/items/1")


if __name__ == "__main__":
    unittest.main()
