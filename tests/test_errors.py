import unittest
import warnings

from restclients import basics, errors
from tests.server import ApiServer


_saved_filters = []


def setUpModule():
    # basics.get_json is deprecated; these tests are about its behaviour, not the warning
    _saved_filters[:] = warnings.filters
    warnings.filterwarnings("ignore", message=r"restclients\.basics\.get_json", category=DeprecationWarning)


def tearDownModule():
    warnings.filters[:] = _saved_filters


class ErrorMappingTests(unittest.TestCase):
    def test_known_statuses(self):
        cases = {
            400: errors.BadRequest, 401: errors.Unauthorized, 403: errors.Forbidden,
            404: errors.NotFound, 409: errors.Conflict, 429: errors.RateLimited,
        }
        for status, cls in cases.items():
            with self.subTest(status=status):
                self.assertIs(type(errors.error_for_status(status)), cls)

    def test_other_ranges(self):
        self.assertIs(type(errors.error_for_status(418)), errors.ClientError)
        self.assertIs(type(errors.error_for_status(503)), errors.ServerError)
        self.assertIsInstance(errors.error_for_status(404), errors.HttpStatusError)

    def test_message_from_json_body(self):
        err = errors.error_for_status(404, "http://x/y", b'{"error": "no such item"}')
        self.assertEqual(err.message, "no such item")
        self.assertEqual(str(err), "HTTP 404: no such item")

    def test_message_from_plain_body(self):
        err = errors.error_for_status(500, None, b"  kaboom \n")
        self.assertEqual(err.message, "kaboom")


class GetJsonErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def test_404_becomes_not_found(self):
        with self.assertRaises(errors.NotFound) as ctx:
            basics.get_json(self.server.url + "/items/999")
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(ctx.exception.message, "not found")

    def test_503_becomes_server_error(self):
        with self.assertRaises(errors.ServerError) as ctx:
            basics.get_json(self.server.url + "/status/503")
        self.assertIn("503", ctx.exception.message)

    def test_catch_all_base_class(self):
        with self.assertRaises(errors.ApiError):
            basics.get_json(self.server.url + "/status/401")

    def get_error(self, **params):
        with self.assertRaises(errors.ApiError) as ctx:
            basics.get_json(self.server.url + "/errors", params)
        return ctx.exception

    def test_message_shapes(self):
        cases = [
            ("nested", "nested message"),
            ("list", "name is too short; price must be positive"),
            ("oauth", "missing parameter"),
            ("problem", "quantity must be positive"),
            ("text", "plain text failure"),
        ]
        for shape, expected in cases:
            with self.subTest(shape=shape):
                self.assertEqual(self.get_error(shape=shape).message, expected)

    def test_error_data_property(self):
        err = self.get_error(shape="problem")
        self.assertEqual(err.data["status"], 422)
        self.assertEqual(err.status, 422)
        self.assertIsNone(self.get_error(shape="text").data)

    def test_non_json_body(self):
        with self.assertRaises(errors.ApiError) as ctx:
            basics.get_json(self.server.url + "/html")
        self.assertIn("not valid JSON", ctx.exception.message)
        self.assertTrue(ctx.exception.body.startswith(b"<html>"))


class TransportFailureTests(unittest.TestCase):
    def test_read_timeout(self):
        with ApiServer() as server:
            with self.assertRaises(errors.TransportError):
                basics.get_json(server.url + "/slow", {"delay": 1}, timeout=0.2)

    def test_connection_refused(self):
        with ApiServer() as server:
            dead_url = server.url
        # the server is shut down again, so nothing is listening on that port
        with self.assertRaises(errors.TransportError) as ctx:
            basics.get_json(dead_url + "/items", timeout=1)
        self.assertIsNone(ctx.exception.status)


if __name__ == "__main__":
    unittest.main()
