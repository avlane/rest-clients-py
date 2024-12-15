# Benchmarks: sequential vs threads vs asyncio

Produced with `python3 -m restclients.bench` on one laptop (Apple silicon, macOS,
Python 3.14), against the in-process test server on localhost. The server is a
pure-Python `ThreadingHTTPServer` and shares the interpreter's CPU with the
client, so treat the numbers as a comparison between strategies, not as what any
real API would deliver. They vary run to run by tens of percent.

## Latency-bound: 20 ms of server-side delay per request

200 requests.

| scenario | concurrency | seconds | req/s | p95 ms |
|---|---:|---:|---:|---:|
| urllib, sequential | 1 | 5.24 | 38 | 30.7 |
| keep-alive pool, threads | 4 | 1.25 | 160 | 26.7 |
| urllib, threads | 4 | 1.27 | 157 | 27.7 |
| asyncio + urllib in threads | 4 | 1.33 | 150 | 28.4 |
| keep-alive pool, threads | 16 | 0.35 | 571 | 29.3 |
| asyncio + urllib in threads | 16 | 0.40 | 506 | 55.2 |
| urllib, threads | 16 | 0.43 | 463 | 58.3 |

When requests mostly wait, overlapping them is what matters: sequential is
bounded by `n * latency` (200 x 25 ms is about 5 s), and concurrency 4 and 16
divide that by roughly 4 and 14. The three concurrent strategies are close to
each other. The event loop adds nothing here because each request still occupies
a thread; its advantage would only show with natively async I/O and thousands of
connections.

## Overhead-bound: no server delay

500 requests, concurrency 8.

| scenario | seconds | req/s | p50 ms | p95 ms |
|---|---:|---:|---:|---:|
| keep-alive pool, threads | 0.13 | 3720 | 1.65 | 4.4 |
| urllib, threads | 0.33 | 1508 | 3.04 | 16.8 |
| urllib, sequential | 0.39 | 1290 | 0.70 | 1.4 |
| asyncio + urllib in threads | 0.41 | 1229 | 4.34 | 8.9 |

Without latency to hide, per-request cost dominates. Reusing connections is the
only thing that helped (about 2.5-3x over opening a new connection per request),
and the threads made the other strategies no faster than the sequential loop:
the GIL, thread hand-offs and a server competing for the same CPU eat the gain.
Sequential urllib even has the best single-request latency (0.7 ms p50).

## Takeaways

1. For latency-bound work, bound the concurrency (`gather_bounded`, or a thread
   pool) rather than going sequential. Going from 4 to 16 helped until the server
   itself became the limit.
2. Reuse connections. The keep-alive pool won both tables. `requests.Session`,
   `httpx.Client` and `aiohttp.ClientSession` exist for this reason.
3. Do not expect an event loop to speed up blocking code. It organises waiting;
   it does not remove it.
4. p95 latency rises faster than p50 once threads contend. If tail latency
   matters, measure it rather than looking at throughput alone.

Re-run on your own machine and API before deciding anything.

## Addendum: the native asyncio client (December)

`AsyncStreamsClient` (asyncio streams, one connection per request, one thread)
was added to the harness after the tables above were produced. This second run
was taken while the machine was busy with other work, and the same scenarios came
out several times slower than in the first run (sequential urllib, 500 requests,
no delay: 0.39 s then, 1.50 s now). Compare rows *within* a table only.

200 requests, 20 ms server delay, concurrency 16:

| scenario | seconds | req/s | p50 ms | p95 ms |
|---|---:|---:|---:|---:|
| keep-alive pool, threads | 0.33 | 607 | 25.2 | 28.0 |
| urllib, threads | 0.35 | 565 | 26.2 | 29.2 |
| asyncio + urllib in threads | 0.45 | 444 | 27.7 | 59.4 |
| asyncio native streams | 0.50 | 401 | 33.5 | 68.7 |
| urllib, sequential (concurrency 1) | 5.10 | 39 | 25.8 | 29.5 |

500 requests, no delay, concurrency 8:

| scenario | seconds | req/s | p50 ms | p95 ms |
|---|---:|---:|---:|---:|
| keep-alive pool, threads | 0.29 | 1737 | 3.1 | 10.7 |
| urllib, threads | 0.89 | 564 | 8.5 | 45.4 |
| asyncio + urllib in threads | 0.90 | 557 | 8.6 | 41.7 |
| asyncio native streams | 1.00 | 501 | 10.2 | 46.0 |
| urllib, sequential | 1.50 | 334 | 2.2 | 8.1 |

The hand-written asyncio client lands with the other connection-per-request
strategies: it overlaps the waiting as well as threads do, with no thread pool,
but it does not make the per-request work cheaper. The one thing that stands out
in both tables is again connection reuse.
