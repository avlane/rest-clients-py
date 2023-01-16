import json
import os
import unittest

from restclients.openapi import SpecError, load_spec, parse_spec, resolve_ref

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "items-openapi.json")


class LoadSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load_spec(FIXTURE)

    def test_basics(self):
        self.assertEqual((self.spec.title, self.spec.version), ("Items API", "1.2.0"))
        self.assertEqual(self.spec.base_url, "https://api.example.test")

    def test_operations(self):
        ids = sorted(op.operation_id for op in self.spec.operations)
        self.assertEqual(ids, ["createItem", "deleteItem", "getItem", "getOrder", "get_pages",
                               "listItems", "updateItem"])

    def test_missing_operation_id_is_derived(self):
        op = [o for o in self.spec.operations if o.path == "/pages"][0]
        self.assertEqual(op.operation_id, "get_pages")

    def test_path_level_parameter_ref_is_shared_by_each_method(self):
        for name in ("getItem", "updateItem", "deleteItem"):
            params = self.spec.operation(name).parameters
            self.assertEqual([(p.name, p.location, p.required) for p in params],
                             [("itemId", "path", True)])

    def test_query_and_header_parameters(self):
        pages = self.spec.operation("get_pages")
        self.assertEqual([(p.name, p.required) for p in pages.parameters],
                         [("page", False), ("limit", False)])
        order = self.spec.operation("getOrder")
        self.assertEqual([(p.name, p.location) for p in order.parameters],
                         [("orderId", "path"), ("X-Trace", "header")])

    def test_request_body_and_responses(self):
        create = self.spec.operation("createItem")
        self.assertTrue(create.request_body["required"])
        self.assertEqual(create.request_body["schema"], {"$ref": "#/components/schemas/ItemInput"})
        self.assertEqual(create.success_schema, {"$ref": "#/components/schemas/Item"})
        self.assertEqual(create.responses["400"], {"$ref": "#/components/schemas/Error"})
        self.assertIsNone(self.spec.operation("deleteItem").success_schema)

    def test_schemas(self):
        self.assertEqual(sorted(self.spec.schemas), ["Error", "Item", "ItemInput", "ItemPage", "Order"])


class ErrorTests(unittest.TestCase):
    def test_not_openapi(self):
        with self.assertRaises(SpecError):
            parse_spec({"swagger": "2.0"})

    def test_invalid_json_and_missing_file(self):
        with self.assertRaisesRegex(SpecError, "YAML"):
            load_spec("{ nope")
        with self.assertRaisesRegex(SpecError, "cannot read"):
            load_spec("/no/such/spec.json")

    def test_duplicate_operation_ids(self):
        doc = {"openapi": "3.0.0", "paths": {
            "/a": {"get": {"operationId": "same", "responses": {}}},
            "/b": {"get": {"operationId": "same", "responses": {}}}}}
        with self.assertRaisesRegex(SpecError, "duplicate operationId: same"):
            parse_spec(doc)

    def test_resolve_ref(self):
        doc = {"a": {"b/c": {"d": 1}}}
        self.assertEqual(resolve_ref(doc, "#/a/b~1c/d"), 1)
        with self.assertRaises(SpecError):
            resolve_ref(doc, "#/a/missing")
        with self.assertRaises(SpecError):
            resolve_ref(doc, "other.json#/a")

    def test_reference_loop(self):
        doc = {"openapi": "3.0.0", "paths": {"/a": {"$ref": "#/x"}}, "x": {"$ref": "#/x"}}
        with self.assertRaisesRegex(SpecError, "loop"):
            parse_spec(doc)

    def test_accepts_a_json_string(self):
        spec = load_spec(json.dumps({"openapi": "3.1.0", "info": {"title": "T", "version": "1"}}))
        self.assertEqual(spec.operations, [])


if __name__ == "__main__":
    unittest.main()
