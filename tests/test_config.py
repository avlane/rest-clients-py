import os
import tempfile
import unittest

from restclients.auth import ApiKeyAuth, BasicAuth, BearerAuth
from restclients import config as config_module
from restclients.config import ConfigError, build_auth, build_client, load_config, parse_config
from restclients.keepalive_client import KeepAliveClient
from restclients.testing import FakeSession
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "client.toml")


needs_toml = unittest.skipIf(config_module.tomllib is None,
                             "reading TOML needs Python 3.11+ or the tomli package")


@needs_toml
class LoadTests(unittest.TestCase):
    def test_fixture_file(self):
        config = load_config(FIXTURE)
        self.assertEqual(config.client.base_url, "https://api.example.test")
        self.assertEqual(config.client.timeout, [2.5, 8.0])
        self.assertEqual(config.retry.max_attempts, 4)
        self.assertEqual(config.rate_limit.burst, 5)
        self.assertEqual(config.auth.token_env, "EXAMPLE_API_TOKEN")

    def test_build_client_from_fixture(self):
        client = build_client(load_config(FIXTURE), environ={"EXAMPLE_API_TOKEN": "tok"})
        self.assertIsInstance(client, KeepAliveClient)
        self.assertEqual(client.timeout, (2.5, 8.0))
        self.assertEqual(client.headers["X-Team"], "docs")
        self.assertEqual(client.retry.max_attempts, 4)
        self.assertEqual(client.rate_limiter.rate, 20)
        headers = {}
        client.auth.apply(headers)
        self.assertEqual(headers["Authorization"], "Bearer tok")

    def test_minimal_config_uses_defaults(self):
        config = parse_config({"client": {"base_url": "http://x"}})
        client = build_client(config)
        self.assertIsInstance(client, UrllibClient)
        self.assertIsNone(client.retry)
        self.assertEqual(client.timeout, 10.0)

    def test_missing_file(self):
        with self.assertRaisesRegex(ConfigError, "cannot read"):
            load_config("/no/such/file.toml")

    def test_invalid_toml(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write("[client\nbase_url =")
        self.addCleanup(os.remove, f.name)
        with self.assertRaisesRegex(ConfigError, "not valid TOML"):
            load_config(f.name)

    def test_typos_are_rejected(self):
        with self.assertRaisesRegex(ConfigError, r"\$\.retry\.max_attemps: unexpected field"):
            parse_config({"client": {"base_url": "http://x"}, "retry": {"max_attemps": 5}})

    def test_wrong_types_and_missing_fields(self):
        with self.assertRaises(ConfigError) as ctx:
            parse_config({"client": {"timeout": "fast"}})
        self.assertIn("$.client.base_url", str(ctx.exception))

    def test_bad_transport_and_timeout_pair(self):
        with self.assertRaisesRegex(ConfigError, "transport"):
            parse_config({"client": {"base_url": "http://x", "transport": "carrier-pigeon"}})
        with self.assertRaisesRegex(ConfigError, "pair"):
            parse_config({"client": {"base_url": "http://x", "timeout": [1, 2, 3]}})


class AuthTests(unittest.TestCase):
    def section(self, **kwargs):
        return parse_config({"client": {"base_url": "http://x"}, "auth": kwargs}).auth

    def test_each_type(self):
        env = {"T": "tok", "P": "pw"}
        self.assertIsInstance(build_auth(self.section(type="bearer", token_env="T"), env), BearerAuth)
        key = build_auth(self.section(type="api_key", token_env="T", header="X-Key"), env)
        self.assertIsInstance(key, ApiKeyAuth)
        self.assertEqual(key.header, "X-Key")
        basic = build_auth(self.section(type="basic", username="avery", password_env="P"), env)
        self.assertIsInstance(basic, BasicAuth)

    def test_secret_must_come_from_the_environment(self):
        with self.assertRaisesRegex(ConfigError, "NOPE .* is not set"):
            build_auth(self.section(type="bearer", token_env="NOPE"), {})
        with self.assertRaisesRegex(ConfigError, "token_env is required"):
            build_auth(self.section(type="bearer"), {})

    def test_unknown_type(self):
        with self.assertRaisesRegex(ConfigError, "auth.type"):
            build_auth(self.section(type="kerberos"), {})

    def test_no_auth_section(self):
        self.assertIsNone(build_auth(None))


class TransportChoiceTests(unittest.TestCase):
    def test_requests_transport_gets_the_injected_session(self):
        config = parse_config({"client": {"base_url": "http://api.test", "transport": "requests"}})
        session = FakeSession()
        client = build_client(config, session=session)
        client.get("/x")
        self.assertEqual(session.calls[0]["url"], "http://api.test/x")

    def test_httpx_transport(self):
        config = parse_config({"client": {"base_url": "http://api.test", "transport": "httpx"}})
        session = FakeSession()
        build_client(config, session=session).get("/y")
        self.assertEqual(session.calls[0]["url"], "http://api.test/y")

    def test_configured_client_talks_to_a_real_server(self):
        with ApiServer() as server:
            config = parse_config({
                "client": {"base_url": server.url, "timeout": 5},
                "retry": {"max_attempts": 3, "backoff_base": 0.01},
                "auth": {"type": "bearer", "token_env": "T"},
            })
            client = build_client(config, environ={"T": "tok-123"})
            self.assertEqual(client.get_json("/bearer")["user"], "avery")
            self.assertTrue(client.get_json("/flaky", {"key": "cfg", "fail": 1})["ok"])


if __name__ == "__main__":
    unittest.main()
