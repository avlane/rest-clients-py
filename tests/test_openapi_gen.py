import inspect
import os
import unittest

from restclients.base import ApiClient
from restclients.openapi import load_spec, parse_spec
from restclients.openapi_gen import class_name, generate_client, snake_case

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "items-openapi.json")


def build(source):
    namespace = {}
    exec(compile(source, "<generated>", "exec"), namespace)
    return namespace


class NamingTests(unittest.TestCase):
    def test_snake_case(self):
        cases = {"getOrderById": "get_order_by_id", "listItems": "list_items", "get_pages": "get_pages",
                 "HTTPStatusCheck": "http_status_check", "X-Trace": "x_trace", "class": "class_",
                 "2fa": "_2fa", "self": "self_", "body": "body_"}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(snake_case(raw), expected)

    def test_class_name(self):
        self.assertEqual(class_name("Items API"), "ItemsAPIClient")
        self.assertEqual(class_name("pet-store v2"), "PetStoreV2Client")
        self.assertEqual(class_name(""), "ApiClientImpl")


class GeneratedSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = generate_client(load_spec(FIXTURE))
        cls.namespace = build(cls.source)
        cls.client_class = cls.namespace["ItemsAPIClient"]

    def signature(self, name):
        return str(inspect.signature(getattr(self.client_class, name)))

    def test_it_compiles_and_subclasses_apiclient(self):
        self.assertTrue(issubclass(self.client_class, ApiClient))
        self.assertEqual(self.client_class.default_base_url, "https://api.example.test")

    def test_one_method_per_operation(self):
        methods = sorted(n for n, v in vars(self.client_class).items()
                         if inspect.isfunction(v) and not n.startswith("_"))
        self.assertEqual(methods, ["create_item", "delete_item", "get_item", "get_order", "get_pages",
                                   "list_items", "update_item"])

    def test_signatures(self):
        self.assertEqual(self.signature("list_items"), "(self)")
        self.assertEqual(self.signature("get_item"), "(self, item_id)")
        self.assertEqual(self.signature("create_item"), "(self, body)")
        self.assertEqual(self.signature("update_item"), "(self, item_id, body)")
        self.assertEqual(self.signature("get_pages"), "(self, page=None, limit=None)")
        self.assertEqual(self.signature("get_order"), "(self, order_id, x_trace=None)")

    def test_docstrings_come_from_summaries(self):
        self.assertEqual(self.client_class.get_item.__doc__, "Fetch one item")
        self.assertEqual(self.client_class.get_pages.__doc__, "Items, one page at a time")

    def test_header_names_the_spec(self):
        self.assertIn("Client for Items API 1.2.0", self.source)

    def test_generation_is_deterministic(self):
        self.assertEqual(self.source, generate_client(load_spec(FIXTURE)))


class EdgeCaseTests(unittest.TestCase):
    def test_optional_body_and_clashing_names(self):
        spec = parse_spec({"openapi": "3.0.0", "info": {"title": "Edge", "version": "1"}, "paths": {
            "/a/{id}": {"put": {
                "operationId": "putA",
                "parameters": [{"name": "id", "in": "path", "required": True},
                               {"name": "id", "in": "query"},
                               {"name": "class", "in": "query"}],
                "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
                "responses": {}}}}})
        namespace = build(generate_client(spec))
        signature = str(inspect.signature(namespace["EdgeClient"].put_a))
        self.assertEqual(signature, "(self, id, id_2=None, class_=None, body=None)")

    def test_empty_api(self):
        spec = parse_spec({"openapi": "3.0.0", "info": {"title": "Nothing", "version": "1"}})
        self.assertIn("pass", generate_client(spec))
        build(generate_client(spec))

    def test_duplicate_snake_case_names_are_made_unique(self):
        spec = parse_spec({"openapi": "3.0.0", "info": {"title": "Dup", "version": "1"}, "paths": {
            "/a": {"get": {"operationId": "getA", "responses": {}}},
            "/b": {"get": {"operationId": "get_a", "responses": {}}}}})
        namespace = build(generate_client(spec))
        self.assertTrue(hasattr(namespace["DupClient"], "get_a"))
        self.assertTrue(hasattr(namespace["DupClient"], "get_a_2"))


if __name__ == "__main__":
    unittest.main()
