"""Sender and receiver talking over real sockets."""
import unittest

from restclients.retry import RetryPolicy
from restclients.signatures import HmacVerifier
from restclients.webhook_sender import DeliveryFailed, WebhookSender
from restclients.webhooks import WebhookReceiver, WebhookRejected


class Flaky:
    """Verifier wrapper that answers with failures for the first ``fail`` deliveries."""

    def __init__(self, inner, fail, status=503):
        self.inner, self.fail, self.status, self.calls = inner, fail, status, 0

    def __call__(self, headers, body):
        self.calls += 1
        if self.calls <= self.fail:
            raise WebhookRejected("try again later", self.status)
        self.inner(headers, body)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.sleeps = []
        self.clock = [1_700_000_000.0]

    def sender(self, **kwargs):
        kwargs.setdefault("retry", RetryPolicy(max_attempts=4, backoff_base=2, jitter=False))
        kwargs.setdefault("sleep", self.sleeps.append)
        return WebhookSender("s3cret", clock=lambda: self.clock[0], **kwargs)

    def verifier(self):
        return HmacVerifier("s3cret", clock=lambda: self.clock[0])

    def test_signed_delivery_is_accepted(self):
        with WebhookReceiver(verifier=self.verifier()) as receiver:
            response = self.sender().send(receiver.url, {"type": "item.created", "id": 9}, event_id="evt-1")
            (event,) = receiver.wait_for(1)
        self.assertEqual(response.json(), {"received": True})
        self.assertEqual(event.payload, {"type": "item.created", "id": 9})
        self.assertEqual(event.headers["X-Event-Id"], "evt-1")

    def test_wrong_secret_is_a_permanent_failure(self):
        with WebhookReceiver(verifier=HmacVerifier("other", clock=lambda: self.clock[0])) as receiver:
            with self.assertRaises(DeliveryFailed) as ctx:
                self.sender().send(receiver.url, {"a": 1})
        self.assertEqual(ctx.exception.attempts, [401])          # no retries for a 4xx
        self.assertEqual(self.sleeps, [])

    def test_retries_5xx_with_backoff_and_resigns_each_attempt(self):
        signatures = []

        def record_then_check(headers, body):
            signatures.append(headers["X-Signature"])
            flaky(headers, body)

        flaky = Flaky(self.verifier(), fail=2)

        def sleep(seconds):                 # time really passes while the sender waits
            self.sleeps.append(seconds)
            self.clock[0] += 400            # more than the 300 s tolerance per wait

        with WebhookReceiver(verifier=record_then_check) as receiver:
            response = self.sender(sleep=sleep).send(receiver.url, {"n": 1}, event_id="evt-2")
            receiver.wait_for(1)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.sleeps, [2, 4])
        # accepted on the third try although 800 s have passed: every attempt was signed afresh
        self.assertEqual(len({sig.split(",")[0] for sig in signatures}), 3)

    def test_gives_up_after_max_attempts(self):
        with WebhookReceiver(verifier=Flaky(self.verifier(), fail=99)) as receiver:
            with self.assertRaises(DeliveryFailed) as ctx:
                self.sender().send(receiver.url, {"n": 1})
        self.assertEqual(ctx.exception.attempts, [503] * 4)
        self.assertEqual(len(self.sleeps), 3)

    def test_receiver_drops_duplicate_event_ids(self):
        with WebhookReceiver(verifier=self.verifier()) as receiver:
            sender = self.sender()
            sender.send(receiver.url, {"n": 1}, event_id="same")
            again = sender.send(receiver.url, {"n": 1}, event_id="same")
            sender.send(receiver.url, {"n": 2}, event_id="different")
            events = receiver.wait_for(2)
        self.assertEqual(again.json(), {"received": True, "duplicate": True})
        self.assertEqual([e.payload["n"] for e in events], [1, 2])
        self.assertEqual(receiver.duplicates, 1)

    def test_429_is_retried(self):
        flaky = Flaky(self.verifier(), fail=1, status=429)
        with WebhookReceiver(verifier=flaky) as receiver:
            # the receiver cannot set headers here, so no Retry-After: plain backoff is used
            self.sender().send(receiver.url, {"n": 1})
        self.assertEqual(self.sleeps, [2])

    def test_unreachable_receiver_counts_as_a_failed_attempt(self):
        with WebhookReceiver() as receiver:
            url = receiver.url
        with self.assertRaises(DeliveryFailed) as ctx:
            self.sender().send(url, {"n": 1})
        self.assertEqual(ctx.exception.attempts, [None] * 4)

    def test_generated_event_ids_are_unique(self):
        with WebhookReceiver(verifier=self.verifier()) as receiver:
            sender = self.sender()
            sender.send(receiver.url, {"n": 1})
            sender.send(receiver.url, {"n": 1})
            self.assertEqual(len(receiver.wait_for(2)), 2)


if __name__ == "__main__":
    unittest.main()
