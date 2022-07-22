import os
import tempfile
import unittest

from restclients import errors
from restclients.recorder import (Cassette, NoMatchingInteraction, RecordingClient, ReplayClient,
                                  cassette_client)
from restclients.retry import RetryPolicy
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class RecordThenReplayTests(unittest.TestCase):
    def record(self, calls):
        """Run ``calls(client)`` against a live server and return the cassette."""
        cassette = Cassette()
        with ApiServer() as server:
            client = RecordingClient(UrllibClient(), cassette, base_url=server.url,
                                     retry=RetryPolicy(jitter=False), sleep=lambda s: None)
            calls(client)
            self.base = server.url
        return cassette

    def test_replay_without_a_server(self):
        cassette = self.record(lambda c: (c.get("/items/3"), c.get("/items/4")))
        # the server is gone now: replay has to come from the cassette alone
        replay = ReplayClient(cassette, base_url=self.base)
        self.assertEqual(replay.get_json("/items/4")["name"], "item-04")
        self.assertEqual(replay.get_json("/items/3")["name"], "item-03")

    def test_unrecorded_request_raises(self):
        cassette = self.record(lambda c: c.get("/items/1"))
        replay = ReplayClient(cassette, base_url=self.base)
        with self.assertRaises(NoMatchingInteraction) as ctx:
            replay.get("/items/2")
        self.assertIn("/items/2", ctx.exception.message)

    def test_miss_is_not_retried(self):
        cassette = self.record(lambda c: c.get("/items/1"))
        sleeps = []
        replay = ReplayClient(cassette, base_url=self.base, sleep=sleeps.append,
                              retry=RetryPolicy(jitter=False))
        with self.assertRaises(NoMatchingInteraction):
            replay.get("/items/2")
        self.assertEqual(sleeps, [])

    def test_recorded_failure_sequence_replays_in_order_with_retries(self):
        cassette = self.record(lambda c: c.get("/flaky", params={"key": "seq", "fail": 2}))
        self.assertEqual([i.status for i in cassette.interactions], [503, 503, 200])
        sleeps = []
        replay = ReplayClient(cassette, base_url=self.base, sleep=sleeps.append,
                              retry=RetryPolicy(jitter=False))
        self.assertEqual(replay.get_json("/flaky", params={"key": "seq", "fail": 2})["ok"], True)
        self.assertEqual(sleeps, [0.5, 1.0])
        replay.assert_all_used()

    def test_interactions_are_single_use_by_default(self):
        cassette = self.record(lambda c: c.get("/items/1"))
        replay = ReplayClient(cassette, base_url=self.base)
        replay.get("/items/1")
        with self.assertRaises(NoMatchingInteraction):
            replay.get("/items/1")

    def test_playback_repeats(self):
        cassette = self.record(lambda c: c.get("/items/1"))
        replay = ReplayClient(cassette, base_url=self.base, allow_playback_repeats=True)
        for _ in range(3):
            self.assertEqual(replay.get_json("/items/1")["id"], 1)

    def test_assert_all_used_reports_leftovers(self):
        cassette = self.record(lambda c: (c.get("/items/1"), c.get("/items/2")))
        replay = ReplayClient(cassette, base_url=self.base)
        replay.get("/items/1")
        with self.assertRaisesRegex(AssertionError, "items/2"):
            replay.assert_all_used()

    def test_recorded_error_status_replays_as_the_same_exception(self):
        def calls(c):
            with self.assertRaises(errors.NotFound):
                c.get("/items/999")
        cassette = self.record(calls)
        with self.assertRaises(errors.NotFound):
            ReplayClient(cassette, base_url=self.base).get("/items/999")

    def test_body_matching_distinguishes_posts(self):
        cassette = self.record(lambda c: (c.post("/items", json={"name": "a", "price": 1}),
                                          c.post("/items", json={"name": "b", "price": 2})))
        replay = ReplayClient(cassette, base_url=self.base, match_on=("method", "url", "body"))
        created = replay.post("/items", json={"price": 2, "name": "b"}).json()  # key order differs
        self.assertEqual(created["name"], "b")
        with self.assertRaises(NoMatchingInteraction):
            replay.post("/items", json={"name": "c"})

    def test_cannot_match_on_unknown_field(self):
        replay = ReplayClient(Cassette([]), match_on=("colour",))
        with self.assertRaises(ValueError):
            replay.get("http://x/y")


class CassetteClientModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "c.json")

    def test_once_records_first_then_replays(self):
        with ApiServer() as server:
            with cassette_client(self.path, UrllibClient(), base_url=server.url) as client:
                self.assertIsInstance(client, RecordingClient)
                client.get("/items/5")
            base = server.url
        # server stopped; the second run must replay
        with cassette_client(self.path, UrllibClient(), base_url=base) as client:
            self.assertIsInstance(client, ReplayClient)
            self.assertEqual(client.get_json("/items/5")["id"], 5)

    def test_none_mode_requires_existing_cassette(self):
        with self.assertRaises(FileNotFoundError):
            cassette_client(self.path, mode="none")

    def test_all_mode_re_records(self):
        Cassette(self.path).save()
        with ApiServer() as server:
            with cassette_client(self.path, UrllibClient(), mode="all", base_url=server.url) as c:
                self.assertIsInstance(c, RecordingClient)
                c.get("/items/1")
        self.assertEqual(len(Cassette.load(self.path)), 1)

    def test_recording_needs_an_inner_client(self):
        with self.assertRaises(ValueError):
            cassette_client(self.path)

    def test_unknown_mode(self):
        with self.assertRaises(ValueError):
            cassette_client(self.path, mode="sometimes")


if __name__ == "__main__":
    unittest.main()
