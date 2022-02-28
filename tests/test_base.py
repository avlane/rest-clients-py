import unittest

from examples.items_client import ItemsClient
from restclients.models import Item
from restclients.validation import ValidationError
from restclients.base import ApiClient
from restclients.errors import BadRequest, NotFound
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class ItemsClientTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.api = ItemsClient(UrllibClient(base_url=self.server.url))

    def tearDown(self):
        self.server.__exit__(None, None, None)

    def test_get_and_list(self):
        self.assertEqual(self.api.get_item(4), Item(4, "item-04", 20))
        items = list(self.api.list_items())
        self.assertEqual(len(items), 23)
        self.assertIsInstance(items[0], Item)

    def test_find_item_returns_none_when_missing(self):
        self.assertIsNone(self.api.find_item(1000))
        self.assertEqual(self.api.find_item(1).id, 1)

    def test_create_rename_delete(self):
        created = self.api.create_item("widget", 9)
        self.assertEqual((created.id, created.price), (24, 9))
        renamed = self.api.rename_item(24, "gadget")
        self.assertEqual(renamed.name, "gadget")
        self.assertEqual(self.api.get_item(24).name, "gadget")
        self.api.delete_item(24)
        with self.assertRaises(NotFound):
            self.api.get_item(24)

    def test_validation_error_from_server(self):
        with self.assertRaises(BadRequest) as ctx:
            self.api.create_item("")
        self.assertEqual(ctx.exception.message, "name is required")

    def test_nested_order_is_decoded(self):
        order = self.api.get_order(1)
        self.assertEqual([i.name for i in order.items], ["item-01", "item-02"])
        self.assertEqual(order.total, 15)

    def test_invalid_payload_raises_validation_error_with_paths(self):
        with self.assertRaises(ValidationError) as ctx:
            self.api.get_order(2)
        self.assertEqual([p for p, _ in ctx.exception.problems],
                         ["$.id", "$.items[0].name"])

    def test_extra_fields_from_the_server_are_tolerated(self):
        self.assertEqual(self.api.get_order(3).customer, "Mina Park")

    def test_context_manager_closes_transport(self):
        closed = []

        class Http(UrllibClient):
            def close(self):
                closed.append(True)

        with ApiClient(Http(base_url=self.server.url)):
            pass
        self.assertEqual(closed, [True])


class PaginationStrategyTests(unittest.TestCase):
    def test_strategy_selection(self):
        with ApiServer() as server:
            http = UrllibClient(base_url=server.url)

            class Pages(ApiClient):
                pagination = "pages"
                page_size = 10

            class Links(ApiClient):
                pagination = "links"

            class Cursor(ApiClient):
                pagination = "cursor"

            self.assertEqual(len(list(Pages(http)._iterate("/pages"))), 23)
            self.assertEqual(len(list(Links(http)._iterate("/linked", {"per_page": 10}))), 23)
            self.assertEqual(len(list(Cursor(http)._iterate("/cursor", {"limit": 10}))), 23)
            self.assertEqual(len(list(ApiClient(http)._iterate("/items"))), 23)


if __name__ == "__main__":
    unittest.main()
