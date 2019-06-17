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

    def test_query_string_is_encoded(self):
        echo = basics.get_json(self.server.url + "/echo", params={"q": "a b&c", "n": 2})
        self.assertEqual(echo["query"], {"q": ["a b&c"], "n": ["2"]})

    def test_headers_are_sent(self):
        echo = basics.get_json(self.server.url + "/echo", headers={"X-Trace": "abc"})
        self.assertEqual(echo["headers"]["x-trace"], "abc")
        self.assertEqual(echo["headers"]["accept"], "application/json")
        self.assertTrue(echo["headers"]["user-agent"].startswith("rest-clients-py/"))


class BuildUrlTests(unittest.TestCase):
    def test_keeps_existing_query(self):
        self.assertEqual(basics.build_url("http://x/y?a=1", {"b": 2}), "http://x/y?a=1&b=2")

    def test_none_dropped_lists_repeated_bools_lowercase(self):
        url = basics.build_url("http://x/y", {"a": None, "tag": ["p", "q"], "on": True})
        self.assertEqual(url, "http://x/y?tag=p&tag=q&on=true")

    def test_no_params_is_identity(self):
        self.assertEqual(basics.build_url("http://x/y"), "http://x/y")


if __name__ == "__main__":
    unittest.main()
