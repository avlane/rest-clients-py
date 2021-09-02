"""Wiring tests: stand-in modules replace the real libraries in sys.modules.

These show the factories pass the right arguments to the right constructors.
"""
import sys
import types
import unittest
from unittest import mock

from restclients import factories


class Recorder:
    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.mounted = {}

    def mount(self, prefix, adapter):
        self.mounted[prefix] = adapter


def fake_module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


class FactoryTests(unittest.TestCase):
    def test_requests_session_mounts_a_sized_adapter(self):
        requests = fake_module("requests", Session=Recorder)
        adapters = fake_module("requests.adapters", HTTPAdapter=Recorder)
        requests.adapters = adapters
        with mock.patch.dict(sys.modules, {"requests": requests, "requests.adapters": adapters}):
            session = factories.make_requests_session(pool_connections=4, pool_maxsize=16, max_retries=2)
        adapter = session.mounted["https://"]
        self.assertIs(adapter, session.mounted["http://"])
        self.assertEqual(adapter.kwargs, {"pool_connections": 4, "pool_maxsize": 16, "max_retries": 2})

    def test_httpx_client_gets_limits(self):
        httpx = fake_module("httpx", Limits=Recorder, Client=Recorder)
        with mock.patch.dict(sys.modules, {"httpx": httpx}):
            client = factories.make_httpx_client(max_connections=50, max_keepalive_connections=5,
                                                 timeout=3)
        self.assertEqual(client.kwargs["limits"].kwargs,
                         {"max_connections": 50, "max_keepalive_connections": 5})
        self.assertEqual(client.kwargs["timeout"], 3)

    def test_aiohttp_session_gets_connector(self):
        aiohttp = fake_module("aiohttp", TCPConnector=Recorder, ClientSession=Recorder)
        with mock.patch.dict(sys.modules, {"aiohttp": aiohttp}):
            session = factories.make_aiohttp_session(limit=30, limit_per_host=6)
        self.assertEqual(session.kwargs["connector"].kwargs, {"limit": 30, "limit_per_host": 6})

    def test_missing_library_raises_import_error(self):
        with mock.patch.dict(sys.modules, {"httpx": None}):
            with self.assertRaises(ImportError):
                factories.make_httpx_client()


if __name__ == "__main__":
    unittest.main()
