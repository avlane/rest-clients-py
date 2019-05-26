import unittest

from restclients import basics
from tests.server import ApiServer


class GetJsonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def test_single_object(self):
        item = basics.get_json(self.server.url + "/items/3")
        self.assertEqual(item, {"id": 3, "name": "item-03", "price": 15})

    def test_list(self):
        items = basics.get_json(self.server.url + "/items")
        self.assertEqual(len(items), 23)
        self.assertEqual(items[0]["name"], "item-01")


if __name__ == "__main__":
    unittest.main()
