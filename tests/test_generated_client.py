"""Generate the client from the spec, exec it, and use it against the real test server."""
import os
import unittest

from restclients import errors
from restclients.openapi import load_spec, parse_spec
from restclients.openapi_gen import generate_client
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "items-openapi.json")


def build(source, name):
    namespace = {}
    exec(compile(source, "<generated>", "exec"), namespace)
    return namespace[name]


class GeneratedClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_class = build(generate_client(load_spec(FIXTURE)), "ItemsAPIClient")

    def setUp(self):
        self.server = ApiServer().__enter__()
        self.api = self.client_class(UrllibClient(base_url=self.server.url))

    def tearDown(self):
        self.server.__exit__(None, None, None)

    def test_list_and_get(self):
        self.assertEqual(len(self.api.list_items()), 23)
        self.assertEqual(self.api.get_item(3), {"id": 3, "name": "item-03", "price": 15})

    def test_create_update_delete(self):
        created = self.api.create_item({"name": "generated", "price": 4})
        self.assertEqual(created["id"], 24)
        self.assertEqual(self.api.update_item(24, {"name": "renamed"})["name"], "renamed")
        self.assertIsNone(self.api.delete_item(24))      # 204: empty body
        with self.assertRaises(errors.NotFound):
            self.api.get_item(24)

    def test_optional_query_parameters_are_only_sent_when_given(self):
        self.api.get_pages()
        self.assertEqual(self.server.requests[-1][1], "/pages")
        page = self.api.get_pages(page=3, limit=5)
        self.assertEqual([i["id"] for i in page["items"]], [11, 12, 13, 14, 15])
        self.assertIn("page=3", self.server.requests[-1][1])
        self.assertIn("limit=5", self.server.requests[-1][1])

    def test_header_parameter(self):
        self.api.get_order(1, x_trace="trace-9")
        self.assertEqual(self.server.requests[-1][2]["X-Trace"], "trace-9")
        self.api.get_order(1)
        self.assertNotIn("X-Trace", self.server.requests[-1][2])

    def test_validation_error_from_the_server(self):
        with self.assertRaises(errors.BadRequest):
            self.api.create_item({"price": 3})

    def test_path_parameters_are_percent_encoded(self):
        spec = parse_spec({"openapi": "3.0.0", "info": {"title": "Echo", "version": "1"}, "paths": {
            "/echo/{name}/{other}": {"get": {
                "operationId": "echoPath",
                "parameters": [{"name": "name", "in": "path", "required": True},
                               {"name": "other", "in": "path", "required": True}],
                "responses": {}}}}})
        api = build(generate_client(spec), "EchoClient")(UrllibClient(base_url=self.server.url))
        echo = api.echo_path("a b/c", "100%")
        # the slash inside a value stays inside its segment instead of adding a path level
        self.assertEqual(echo["path"], "/echo/a%20b%2Fc/100%25")
        self.assertEqual(self.server.requests[-1][1], "/echo/a%20b%2Fc/100%25")

    def test_literal_percent_signs_in_the_path_template_survive(self):
        spec = parse_spec({"openapi": "3.0.0", "info": {"title": "Pct", "version": "1"}, "paths": {
            "/100%25/{x}": {"get": {"operationId": "pct",
                                    "parameters": [{"name": "x", "in": "path", "required": True}],
                                    "responses": {}}}}})
        source = generate_client(spec)
        self.assertIn("/100%%25/%s", source)
        api = build(source, "PctClient")(UrllibClient(base_url=self.server.url))
        with self.assertRaises(errors.NotFound):
            api.pct("v")
        self.assertEqual(self.server.requests[-1][1], "/100%25/v")


if __name__ == "__main__":
    unittest.main()
