"""Send signed webhooks with retries (the provider side of ``restclients.webhooks``)."""
import json
import time
import uuid

from restclients.errors import TransportError
from restclients.retry import RetryPolicy, parse_retry_after
from restclients.signatures import DEFAULT_HEADER, sign
from restclients.urllib_client import UrllibClient


class DeliveryFailed(Exception):
    """Gave up on a delivery. ``attempts`` holds the status (or None) of each try."""

    def __init__(self, event_id, attempts):
        super().__init__("delivery of %s failed after %d attempt(s): %s" % (
            event_id, len(attempts), ", ".join(str(a) for a in attempts)))
        self.event_id = event_id
        self.attempts = attempts


class WebhookSender:
    """POST JSON events with an HMAC signature and an ``X-Event-Id``.

    The signature is recomputed for every attempt, so a delivery that is retried
    for longer than the receiver's timestamp tolerance still verifies. Retrying a
    POST is safe only because the event id lets the receiver drop duplicates.
    """

    def __init__(self, secret, http=None, retry=None, header=DEFAULT_HEADER, clock=time.time,
                 sleep=time.sleep):
        self.secret = secret
        self.http = http or UrllibClient()
        self.retry = retry or RetryPolicy(max_attempts=5, backoff_base=1.0, max_delay=60.0)
        self.header = header
        self._clock = clock
        self._sleep = sleep

    def send(self, url, payload, event_id=None):
        """Deliver ``payload``; returns the successful Response or raises DeliveryFailed."""
        event_id = event_id or uuid.uuid4().hex
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        attempts = []
        while True:
            headers = {"Content-Type": "application/json", "X-Event-Id": event_id,
                       self.header: sign(self.secret, body, self._clock())}
            retry_after = None
            try:
                response = self.http.request("POST", url, data=body, headers=headers,
                                             raise_for_status=False)
            except TransportError:
                attempts.append(None)
            else:
                attempts.append(response.status)
                if 200 <= response.status < 300:
                    return response
                if response.status < 500 and response.status not in (408, 425, 429):
                    raise DeliveryFailed(event_id, attempts)          # our request is wrong; retrying won't fix it
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
            if not self.retry.attempts_left(len(attempts)):
                raise DeliveryFailed(event_id, attempts)
            wait = self.retry.wait_seconds(len(attempts), retry_after)
            if wait is None:
                raise DeliveryFailed(event_id, attempts)
            self._sleep(wait)
