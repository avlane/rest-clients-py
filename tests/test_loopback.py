import threading
import unittest

from restclients import pkce
from restclients.errors import NotFound
from restclients.loopback import CallbackServer
from restclients.oauth2 import exchange_code
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class CallbackServerTests(unittest.TestCase):
    def test_captures_code_and_state(self):
        with CallbackServer() as cb:
            threading.Timer(0.05, lambda: UrllibClient().get(
                cb.redirect_uri + "?code=abc&state=xyz")).start()
            self.assertEqual(cb.wait(timeout=5, expected_state="xyz"), {"code": "abc", "state": "xyz"})

    def test_state_mismatch(self):
        with CallbackServer() as cb:
            UrllibClient().get(cb.redirect_uri + "?code=abc&state=evil")
            with self.assertRaises(ValueError):
                cb.wait(timeout=5, expected_state="mine")

    def test_error_redirect(self):
        with CallbackServer() as cb:
            UrllibClient().get(cb.redirect_uri + "?error=access_denied&error_description=No+thanks")
            with self.assertRaisesRegex(ValueError, "No thanks"):
                cb.wait(timeout=5)

    def test_timeout(self):
        with CallbackServer() as cb:
            with self.assertRaises(TimeoutError):
                cb.wait(timeout=0.1)

    def test_other_paths_are_ignored(self):
        with CallbackServer() as cb:
            with self.assertRaises(NotFound):
                UrllibClient().get(cb.redirect_uri.replace("/callback", "/favicon.ico"))
            with self.assertRaises(TimeoutError):
                cb.wait(timeout=0.1)


class LoginSimulationTests(unittest.TestCase):
    def test_cli_login_end_to_end(self):
        """What a command line tool does: listener, authorize URL, redirect, code exchange."""
        with ApiServer() as server, CallbackServer() as cb:
            http = UrllibClient(base_url=server.url)
            verifier, state = pkce.generate_code_verifier(), pkce.generate_state()
            url = pkce.authorization_url(server.url + "/oauth/authorize", "cli-app",
                                         cb.redirect_uri, "read", state, verifier)
            granted = http.get_json(url)                     # the "browser" visit
            http.get(cb.redirect_uri, params=granted)        # ...and its redirect to us
            params = cb.wait(timeout=5, expected_state=state)
            token = exchange_code(server.url + "/oauth/token", "cli-app", params["code"],
                                  cb.redirect_uri, verifier, http=http)
            me = UrllibClient(base_url=server.url).get_json(
                "/oauth/me", headers={"Authorization": "Bearer " + token.access_token})
        self.assertEqual(me, {"client": "cli-app"})


if __name__ == "__main__":
    unittest.main()
