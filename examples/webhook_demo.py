"""Run a webhook receiver and send it signed events, all on localhost.

    python3 -m examples.webhook_demo

Prints what the receiver accepted and what it rejected, so you can see signature
checks, duplicate suppression and timestamp tolerance working.
"""
from restclients.errors import Unauthorized
from restclients.signatures import HmacVerifier, sign
from restclients.urllib_client import UrllibClient
from restclients.webhook_sender import WebhookSender
from restclients.webhooks import WebhookReceiver

SECRET = "demo-secret"


def main():
    with WebhookReceiver(verifier=HmacVerifier(SECRET)) as receiver:
        sender = WebhookSender(SECRET)
        sender.send(receiver.url, {"type": "item.created", "id": 1}, event_id="evt-1")
        sender.send(receiver.url, {"type": "item.created", "id": 1}, event_id="evt-1")   # a retry
        sender.send(receiver.url, {"type": "item.deleted", "id": 1}, event_id="evt-2")

        body = b'{"type":"item.created","id":99}'
        forged = {"X-Signature": sign("not-the-secret", body)}
        try:
            UrllibClient().post(receiver.url, data=body, headers=forged)
        except Unauthorized as exc:
            print("forged delivery refused:", exc.message)
        stale = {"X-Signature": sign(SECRET, body, timestamp=1_000_000)}
        try:
            UrllibClient().post(receiver.url, data=body, headers=stale)
        except Unauthorized as exc:
            print("stale delivery refused:", exc.message)

        for event in receiver.wait_for(2):
            print("accepted:", event.payload, "id", event.headers["X-Event-Id"])
        print("duplicates dropped:", receiver.duplicates)


if __name__ == "__main__":
    main()
