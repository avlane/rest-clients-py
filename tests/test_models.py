import unittest

from restclients.models import Item, Order


class ModelTests(unittest.TestCase):
    def test_item_round_trip(self):
        item = Item.from_dict({"id": 3, "name": "item-03", "price": 15})
        self.assertEqual(item, Item(3, "item-03", 15))
        self.assertEqual(item.to_dict(), {"id": 3, "name": "item-03", "price": 15})

    def test_default_price(self):
        self.assertEqual(Item.from_dict({"id": 1, "name": "x"}).price, 0)

    def test_order_with_nested_items(self):
        order = Order.from_dict({"id": 9, "customer": "Rowan Hale",
                                 "items": [{"id": 1, "name": "a", "price": 5},
                                           {"id": 2, "name": "b", "price": 7}]})
        self.assertEqual(order.total, 12)
        self.assertIsNone(order.note)
        self.assertEqual(order.to_dict()["items"][1]["name"], "b")

    def test_missing_field_is_a_bare_key_error(self):
        # the weakness the next step fixes: no path, no friendly message
        with self.assertRaises(KeyError):
            Item.from_dict({"id": 1})


if __name__ == "__main__":
    unittest.main()
