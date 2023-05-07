import unittest

from restclients import errors
from restclients.urllib_client import UrllibClient
from restclients.webhooks import WebhookReceiver, WebhookRejected


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.receiver = WebhookReceiver().__enter__()
        self.addCleanup(self.receiver.__exit__, None, None, None)
        self.client = UrllibClient()

    def test_collects_json_events(self):
        resp = self.client.post(self.receiver.url, json={"type": "item.created", "id": 5})
        self.assertEqual(resp.json(), {"received": True})
        (event,) = self.receiver.wait_for(1)
        self.assertEqual(event.payload, {"type": "item.created", "id": 5})
        self.assertEqual(event.headers["Content-Type"], "application/json")

    def test_on_event_callback(self):
        seen = []
        receiver = WebhookReceiver(on_event=seen.append).__enter__()
        try:
            self.client.post(receiver.url, json={"n": 1})
            receiver.wait_for(1)
        finally:
            receiver.__exit__(None, None, None)
        self.assertEqual([e.payload for e in seen], [{"n": 1}])

    def test_invalid_json_is_a_400_and_not_stored(self):
        with self.assertRaises(errors.BadRequest):
            self.client.post(self.receiver.url, data=b"{nope", headers={"Content-Type": "application/json"})
        self.assertEqual(self.receiver.wait_for_rejections(1), [(400, "body is not valid JSON")])
        self.assertEqual(self.receiver.events, [])

    def test_wrong_path_and_method(self):
        base = self.receiver.url.rsplit("/", 1)[0]
        with self.assertRaises(errors.NotFound):
            self.client.post(base + "/elsewhere", json={})
        with self.assertRaises(errors.ClientError) as ctx:
            self.client.get(self.receiver.url)
        self.assertEqual(ctx.exception.status, 405)
        self.assertEqual(ctx.exception.headers["Allow"], "POST")

    def test_oversized_body_is_refused(self):
        receiver = WebhookReceiver(max_body=100).__enter__()
        try:
            with self.assertRaises(errors.ClientError) as ctx:
                self.client.post(receiver.url, json={"blob": "x" * 500})
            self.assertEqual(ctx.exception.status, 413)
        finally:
            receiver.__exit__(None, None, None)

    def test_verifier_can_reject(self):
        def deny(headers, body):
            raise WebhookRejected("nope", 403)

        receiver = WebhookReceiver(verifier=deny).__enter__()
        try:
            with self.assertRaises(errors.Forbidden):
                self.client.post(receiver.url, json={"a": 1})
            self.assertEqual(receiver.wait_for_rejections(1), [(403, "nope")])
            self.assertEqual(receiver.events, [])
        finally:
            receiver.__exit__(None, None, None)

    def test_wait_for_times_out(self):
        with self.assertRaisesRegex(TimeoutError, "0 of 1"):
            self.receiver.wait_for(1, timeout=0.05)

    def test_many_deliveries_in_parallel(self):
        import threading
        threads = [threading.Thread(target=lambda n=n: UrllibClient().post(self.receiver.url, json={"n": n}))
                   for n in range(20)]
        for t in threads:
            t.start()
        events = self.receiver.wait_for(20, timeout=10)
        for t in threads:
            t.join()
        self.assertEqual(sorted(e.payload["n"] for e in events), list(range(20)))


if __name__ == "__main__":
    unittest.main()
