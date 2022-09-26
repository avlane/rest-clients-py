import unittest
from urllib.parse import quote

from restclients.auth import BearerAuth
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class RedirectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()
        cls.url = cls.server.url
        cls.other_origin = cls.url.replace("127.0.0.1", "localhost")

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def setUp(self):
        self.client = UrllibClient(base_url=self.url)

    def seen(self, path):
        return [(m, h) for m, p, h in self.server.requests if p == path]

    def test_get_follows_redirect_and_reports_final_url(self):
        resp = self.client.get("/redirect", params={"to": "/items/3"})
        self.assertEqual(resp.json()["id"], 3)
        self.assertEqual(resp.url, self.url + "/items/3")

    def test_follow_can_be_disabled(self):
        client = UrllibClient(base_url=self.url, follow_redirects=False)
        resp = client.get("/redirect", params={"to": "/items/3"})
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.headers["Location"], "/items/3")

    def test_302_turns_post_into_get_without_body(self):
        self.client.post("/redirect", params={"to": "/echo?via=302"}, json={"secret": "body"})
        method, headers = self.seen("/echo?via=302")[-1]
        self.assertEqual(method, "GET")
        self.assertNotIn("Content-Type", headers)

    def test_303_always_becomes_get(self):
        self.client.put("/redirect", params={"to": "/echo?via=303", "code": 303}, json={"a": 1})
        self.assertEqual(self.seen("/echo?via=303")[-1][0], "GET")

    def test_307_and_308_keep_method_and_body(self):
        for code in (307, 308):
            with self.subTest(code=code):
                target = "/echo?via=%d" % code
                resp = self.client.post("/redirect", params={"to": target, "code": code},
                                        json={"keep": code})
                echo = resp.json()
                self.assertEqual(echo["method"], "POST")
                self.assertEqual(echo["headers"]["content-type"], "application/json")
                self.assertEqual(echo["headers"]["content-length"], str(len('{"keep": %d}' % code)))

    def test_credentials_are_forwarded_within_the_same_origin(self):
        client = UrllibClient(base_url=self.url, auth=BearerAuth("tok-123"))
        client.get("/redirect", params={"to": "/echo?same=1"})
        self.assertEqual(self.seen("/echo?same=1")[-1][1]["Authorization"], "Bearer tok-123")

    def test_credentials_are_dropped_when_the_host_changes(self):
        client = UrllibClient(base_url=self.url, auth=BearerAuth("tok-123"))
        target = self.other_origin + "/echo?cross=1"
        resp = client.get("/redirect", params={"to": target})
        echo = resp.json()
        self.assertEqual(echo["path"], "/echo")
        self.assertNotIn("authorization", echo["headers"])
        self.assertTrue(echo["headers"]["host"].startswith("localhost"))
        self.assertEqual(client.get("/echo").json()["headers"]["authorization"], "Bearer tok-123")

    def test_redirect_loop_gives_up(self):
        resp = self.client.get("/redirect/loop", raise_for_status=False)
        self.assertEqual(resp.status, 302)   # urllib stops after 10 hops and reports the last 3xx
        hops = [r for r in self.server.requests if r[1] == "/redirect/loop"]
        self.assertLessEqual(len(hops), 12)


if __name__ == "__main__":
    unittest.main()
