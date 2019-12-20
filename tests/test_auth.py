import unittest

from restclients import errors
from restclients.auth import ApiKeyAuth, BasicAuth, BearerAuth
from restclients.requests_client import RequestsClient
from restclients.urllib_client import UrllibClient
from tests.fakes import FakeSession
from tests.server import ApiServer


class AuthHeaderTests(unittest.TestCase):
    def test_basic_encoding(self):
        headers = {}
        BasicAuth("Aladdin", "open sesame").apply(headers)
        self.assertEqual(headers["Authorization"], "Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==")  # RFC 7617

    def test_basic_non_ascii_is_utf8(self):
        headers = {}
        BasicAuth("josé", "p").apply(headers)
        self.assertEqual(headers["Authorization"], "Basic am9zw6k6cA==")

    def test_bearer_callable_is_called_each_time(self):
        tokens = iter(["a", "b"])
        auth = BearerAuth(lambda: next(tokens))
        first, second = {}, {}
        auth.apply(first)
        auth.apply(second)
        self.assertEqual((first["Authorization"], second["Authorization"]), ("Bearer a", "Bearer b"))

    def test_secrets_are_not_in_repr(self):
        self.assertNotIn("s3cret", repr(BasicAuth("u", "s3cret")))
        self.assertNotIn("tok", repr(BearerAuth("tok-123")))


class AuthAgainstServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def client(self, auth=None):
        return UrllibClient(base_url=self.server.url, auth=auth)

    def test_basic_ok(self):
        self.assertEqual(self.client(BasicAuth("avery", "s3cret")).get_json("/basic"), {"user": "avery"})

    def test_basic_wrong_password(self):
        with self.assertRaises(errors.Unauthorized) as ctx:
            self.client(BasicAuth("avery", "nope")).get("/basic")
        self.assertEqual(ctx.exception.headers["WWW-Authenticate"], 'Basic realm="test"')

    def test_missing_credentials(self):
        with self.assertRaises(errors.Unauthorized):
            self.client().get("/bearer")

    def test_bearer_ok(self):
        self.assertEqual(self.client(BearerAuth("tok-123")).get_json("/bearer")["scope"], "read")

    def test_per_call_auth_overrides_client_default(self):
        client = self.client(BearerAuth("wrong"))
        self.assertEqual(client.get_json("/bearer", auth=BearerAuth("tok-123"))["user"], "avery")

    def test_api_key(self):
        self.assertTrue(self.client(ApiKeyAuth("key-abc")).get_json("/apikey")["ok"])
        with self.assertRaises(errors.Forbidden):
            self.client(ApiKeyAuth("other")).get("/apikey")


class AuthWithRequestsClientTests(unittest.TestCase):
    def test_auth_header_reaches_session(self):
        session = FakeSession()
        RequestsClient(session, auth=BearerAuth("tok")).get("http://api.test/me")
        self.assertEqual(session.calls[0]["headers"]["Authorization"], "Bearer tok")


if __name__ == "__main__":
    unittest.main()
