"""Regenerate tests/fixtures/*.json by recording against the local test server.

    python3 -m tools.record_fixtures

The server listens on a random port, so every ``http://127.0.0.1:PORT`` in the
output is rewritten to ``https://api.example.test`` and volatile headers are
dropped. That keeps the fixtures stable, so re-recording gives a clean diff.
"""
import json
import os
import re
import sys

from restclients.pagination import paginate_links
from restclients.recorder import Cassette, RecordingClient
from restclients.retry import RetryPolicy
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "tests", "fixtures")
FAKE_HOST = "https://api.example.test"
VOLATILE_HEADERS = {"date", "server", "x-request-id"}


def walkthrough(client):
    """The calls made while recording ``items_walkthrough.json``."""
    list(paginate_links(client, "/linked", params={"per_page": 10}))
    client.get_json("/orders/1")
    client.get_json("/items/7")
    try:
        client.get("/items/999")
    except Exception:  # the 404 is the point; it is recorded before it raises
        pass
    client.get_json("/flaky", params={"key": "fixture", "fail": 1})


def stabilise(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r"http://127\.0\.0\.1:\d+", FAKE_HOST, text)
    data = json.loads(text)
    for interaction in data["interactions"]:
        interaction["response"]["headers"] = [
            h for h in interaction["response"]["headers"] if h[0].lower() not in VOLATILE_HEADERS]
        interaction["request"]["headers"].pop("X-Request-ID", None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def main():
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    path = os.path.join(FIXTURE_DIR, "items_walkthrough.json")
    with ApiServer() as server:
        cassette = Cassette(path)
        client = RecordingClient(UrllibClient(), cassette, base_url=server.url,
                                 retry=RetryPolicy(jitter=False), sleep=lambda s: None)
        walkthrough(client)
        client.close()
    stabilise(path)
    print("wrote %s (%d interactions)" % (path, len(cassette)))


if __name__ == "__main__":
    sys.exit(main())
