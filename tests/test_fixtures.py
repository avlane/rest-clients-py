"""Replay the committed cassette: no server, no network, deterministic."""
import os
import unittest

from examples.items_client import ItemsClient
from restclients import errors
from restclients.pagination import paginate_links
from restclients.recorder import Cassette, ReplayClient
from restclients.retry import RetryPolicy

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "items_walkthrough.json")
BASE = "https://api.example.test"


class WalkthroughFixtureTests(unittest.TestCase):
    def client(self, **kwargs):
        return ReplayClient(Cassette.load(FIXTURE), base_url=BASE, **kwargs)

    def test_fixture_has_no_local_addresses_or_secrets(self):
        with open(FIXTURE, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("127.0.0.1", text)
        self.assertNotIn("Bearer ", text)

    def test_pagination_follows_recorded_link_headers(self):
        items = list(paginate_links(self.client(), "/linked", params={"per_page": 10}))
        self.assertEqual([i["id"] for i in items], list(range(1, 24)))

    def test_typed_client_over_the_fixture(self):
        replay = self.client(allow_playback_repeats=True)
        api = ItemsClient(replay)
        self.assertEqual(api.get_item(7).name, "item-07")
        self.assertEqual(api.get_order(1).total, 15)
        self.assertIsNone(api.find_item(999))

    def test_recorded_503_then_200_with_retry(self):
        sleeps = []
        replay = self.client(retry=RetryPolicy(jitter=False), sleep=sleeps.append)
        self.assertTrue(replay.get_json("/flaky", params={"key": "fixture", "fail": 1})["ok"])
        self.assertEqual(sleeps, [0.5])

    def test_everything_recorded_is_replayable_once(self):
        replay = self.client(retry=RetryPolicy(jitter=False), sleep=lambda s: None)
        list(paginate_links(replay, "/linked", params={"per_page": 10}))
        replay.get_json("/orders/1")
        replay.get_json("/items/7")
        with self.assertRaises(errors.NotFound):
            replay.get("/items/999")
        replay.get_json("/flaky", params={"key": "fixture", "fail": 1})
        replay.assert_all_used()


if __name__ == "__main__":
    unittest.main()
