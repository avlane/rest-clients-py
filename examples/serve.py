"""Run the test API server for manual experiments.

    python3 -m examples.serve [--port 8080]

Then try, from another terminal:

    curl -s localhost:8080/                     # lists the routes
    curl -si 'localhost:8080/flaky?fail=2'      # 503, 503, then 200
    curl -si localhost:8080/limited             # 429 with Retry-After
    curl -si -H 'If-None-Match: "v1"' localhost:8080/etag
    curl -s 'localhost:8080/linked?per_page=5' -D -   # Link header pagination

Everything it serves is fictional test data and it binds to 127.0.0.1 only.
"""
import argparse
import threading

from tests.server import ApiServer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=0, help="port to listen on (default: any free port)")
    args = parser.parse_args(argv)
    with ApiServer(port=args.port) as server:
        print("listening on %s" % server.url, flush=True)
        try:
            threading.Event().wait()            # sleep until interrupted
        except KeyboardInterrupt:
            print("\nbye", flush=True)


if __name__ == "__main__":
    main()
