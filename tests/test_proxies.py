import os
import unittest
from unittest import mock

from restclients import errors
from restclients.keepalive_client import KeepAliveClient
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer

PROXY_VARS = ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy",
              "ALL_PROXY", "all_proxy")


def clean_env(**extra):
    """An environment without the developer's own proxy settings, plus ``extra``."""
    env = {k: v for k, v in os.environ.items() if k not in PROXY_VARS}
    env.update(extra)
    return mock.patch.dict(os.environ, env, clear=True)


class UrllibProxyTests(unittest.TestCase):
    """The test server doubles as a forward proxy: it receives absolute-form request targets."""

    def setUp(self):
        self.proxy = ApiServer().__enter__()
        self.addCleanup(self.proxy.__exit__, None, None, None)

    def test_explicit_proxies(self):
        client = UrllibClient(proxies={"http": self.proxy.url})
        echo = client.get_json("http://upstream.test/echo")
        self.assertEqual(echo["headers"]["host"], "upstream.test")      # addressed to the origin...
        self.assertEqual(self.proxy.requests[-1][1], "http://upstream.test/echo")   # ...sent to the proxy

    def dead_url(self):
        """A loopback address nothing listens on: direct connections are refused at once."""
        with ApiServer() as dead:
            return dead.url + "/echo"

    def test_environment_proxy_is_honoured_by_default(self):
        with clean_env(HTTP_PROXY=self.proxy.url):
            client = UrllibClient()
            echo = client.get_json("http://upstream.test/echo")
        self.assertEqual(echo["headers"]["host"], "upstream.test")

    def test_no_proxy_bypasses_it(self):
        url = self.dead_url()
        with clean_env(HTTP_PROXY=self.proxy.url):
            self.assertEqual(UrllibClient().get(url).status, 200)         # no NO_PROXY: via the proxy
        before = len(self.proxy.requests)
        with clean_env(HTTP_PROXY=self.proxy.url, NO_PROXY="127.0.0.1"):
            with self.assertRaises(errors.TransportError):                # direct, and refused
                UrllibClient().get(url)
        self.assertEqual(len(self.proxy.requests), before)

    def test_trust_env_false_ignores_the_environment(self):
        url = self.dead_url()
        with clean_env(HTTP_PROXY=self.proxy.url):
            client = UrllibClient(trust_env=False)
            with self.assertRaises(errors.TransportError):
                client.get(url)
        self.assertEqual(self.proxy.requests, [])

    def test_explicit_proxies_beat_the_environment(self):
        other = ApiServer().__enter__()
        self.addCleanup(other.__exit__, None, None, None)
        with clean_env(HTTP_PROXY=other.url):
            client = UrllibClient(proxies={"http": self.proxy.url})
            client.get("http://upstream.test/echo")
        self.assertEqual((len(self.proxy.requests), len(other.requests)), (1, 0))

    def test_loopback_is_not_proxied_in_these_tests(self):
        with ApiServer() as server, clean_env(HTTP_PROXY="http://127.0.0.1:9", NO_PROXY="127.0.0.1"):
            self.assertEqual(UrllibClient(base_url=server.url).get_json("/items/1")["id"], 1)


class KeepAliveProxyTests(unittest.TestCase):
    def test_refuses_instead_of_silently_bypassing_a_proxy(self):
        with clean_env(HTTP_PROXY="http://proxy.corp.test:3128"):
            with self.assertRaisesRegex(errors.TransportError, "cannot use"):
                KeepAliveClient().get("http://upstream.test/x")

    def test_no_proxy_entry_lets_it_through(self):
        with ApiServer() as server, clean_env(HTTP_PROXY="http://proxy.corp.test:3128",
                                              NO_PROXY="127.0.0.1"):
            client = KeepAliveClient(base_url=server.url)
            self.assertEqual(client.get_json("/items/2")["id"], 2)
            client.close()

    def test_trust_env_false(self):
        with ApiServer() as server, clean_env(HTTP_PROXY="http://proxy.corp.test:3128"):
            client = KeepAliveClient(base_url=server.url, trust_env=False)
            self.assertEqual(client.get_json("/items/2")["id"], 2)
            client.close()


if __name__ == "__main__":
    unittest.main()
