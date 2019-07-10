import unittest

from restclients import basics, errors
from tests.server import ApiServer


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


if __name__ == "__main__":
    unittest.main()
