"""Benchmark harness: the same N requests issued sequentially, with threads, and with asyncio.

Everything runs against a server you point it at. With an artificial
``delay`` on the server the interesting question is how well each strategy
overlaps waiting; with ``delay=0`` it measures per-request overhead instead.

Only transports that can run without third-party packages are included
(``urllib``, the pooled ``http.client`` client, and asyncio driving urllib in
threads).
"""
import asyncio
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from restclients.async_client import ThreadedAsyncClient
from restclients.concurrency import map_bounded
from restclients.keepalive_client import KeepAliveClient
from restclients.urllib_client import UrllibClient


class Result:
    def __init__(self, name, requests, concurrency, seconds, latencies, errors):
        self.name = name
        self.requests = requests
        self.concurrency = concurrency
        self.seconds = seconds
        self.errors = errors
        self.latencies = sorted(latencies)

    @property
    def rps(self):
        return self.requests / self.seconds if self.seconds > 0 else float("inf")

    def percentile(self, p):
        if not self.latencies:
            return 0.0
        index = min(len(self.latencies) - 1, int(round(p / 100.0 * (len(self.latencies) - 1))))
        return self.latencies[index]

    def as_dict(self):
        return {"name": self.name, "requests": self.requests, "concurrency": self.concurrency,
                "seconds": round(self.seconds, 4), "rps": round(self.rps, 1), "errors": self.errors,
                "p50_ms": round(self.percentile(50) * 1000, 2),
                "p95_ms": round(self.percentile(95) * 1000, 2),
                "mean_ms": round(statistics.mean(self.latencies) * 1000, 2) if self.latencies else 0.0}


def _timed(call):
    """Run ``call()``; return (seconds, error_or_None)."""
    started = time.perf_counter()
    try:
        call()
        return time.perf_counter() - started, None
    except Exception as exc:    # a failed request is data, not a crash
        return time.perf_counter() - started, exc


def _collect(name, requests, concurrency, wall, outcomes):
    latencies = [seconds for seconds, error in outcomes if error is None]
    errors = len([1 for _, error in outcomes if error is not None])
    return Result(name, requests, concurrency, wall, latencies, errors)


def run_urllib_sequential(base_url, path, params, requests, concurrency):
    client = UrllibClient(base_url=base_url)
    started = time.perf_counter()
    outcomes = [_timed(lambda: client.get(path, params=params)) for _ in range(requests)]
    return _collect("urllib, sequential", requests, 1, time.perf_counter() - started, outcomes)


def run_urllib_threads(base_url, path, params, requests, concurrency):
    client = UrllibClient(base_url=base_url)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        outcomes = list(pool.map(lambda _: _timed(lambda: client.get(path, params=params)),
                                 range(requests)))
    return _collect("urllib, threads", requests, concurrency, time.perf_counter() - started, outcomes)


def run_keepalive_threads(base_url, path, params, requests, concurrency):
    client = KeepAliveClient(base_url=base_url, max_connections=concurrency)
    try:
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            outcomes = list(pool.map(lambda _: _timed(lambda: client.get(path, params=params)),
                                     range(requests)))
        return _collect("keep-alive pool, threads", requests, concurrency,
                        time.perf_counter() - started, outcomes)
    finally:
        client.close()


def run_asyncio_threaded(base_url, path, params, requests, concurrency):
    executor = ThreadPoolExecutor(max_workers=concurrency)
    client = ThreadedAsyncClient(UrllibClient(base_url=base_url), executor=executor)

    async def one(_):
        started = time.perf_counter()
        try:
            await client.get(path, params=params)
            return time.perf_counter() - started, None
        except Exception as exc:
            return time.perf_counter() - started, exc

    async def main():
        return await map_bounded(one, range(requests), limit=concurrency)

    try:
        started = time.perf_counter()
        outcomes = asyncio.run(main())
        return _collect("asyncio + urllib in threads", requests, concurrency,
                        time.perf_counter() - started, outcomes)
    finally:
        executor.shutdown(wait=True)


SCENARIOS = {
    "sequential": run_urllib_sequential,
    "threads": run_urllib_threads,
    "keepalive": run_keepalive_threads,
    "asyncio": run_asyncio_threaded,
}


def run_benchmark(base_url, requests=100, concurrency=10, delay=0.0, scenarios=None, warmup=5):
    """Run each scenario once and return a list of :class:`Result`.

    ``delay`` is passed to the server's ``/slow`` endpoint; with ``delay == 0`` the cheap
    ``/items/1`` endpoint is used. A short warm-up request run happens first so the first
    scenario does not pay for starting the server's worker threads.
    """
    names = list(scenarios or SCENARIOS)
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        raise ValueError("unknown scenario(s): %s" % ", ".join(unknown))
    path, params = ("/slow", {"delay": delay}) if delay > 0 else ("/items/1", None)
    warm = UrllibClient(base_url=base_url)
    for _ in range(warmup):
        warm.get(path, params=params)
    return [SCENARIOS[name](base_url, path, params, requests, concurrency) for name in names]
