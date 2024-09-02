import io
import json
import unittest

from restclients.bench import SCENARIOS, Result, format_table, main, run_benchmark
from tests.server import ApiServer


class ResultTests(unittest.TestCase):
    def test_statistics(self):
        r = Result("x", 5, 2, 2.0, [0.01, 0.02, 0.03, 0.04, 0.10], 0)
        self.assertEqual(r.rps, 2.5)
        self.assertEqual(r.percentile(50), 0.03)
        self.assertEqual(r.percentile(100), 0.10)
        d = r.as_dict()
        self.assertEqual((d["p50_ms"], d["p95_ms"], d["mean_ms"]), (30.0, 100.0, 40.0))

    def test_empty_latencies(self):
        r = Result("x", 3, 1, 1.0, [], 3)
        self.assertEqual(r.percentile(95), 0.0)
        self.assertEqual(r.as_dict()["mean_ms"], 0.0)


class RunBenchmarkTests(unittest.TestCase):
    def test_every_scenario_completes_all_requests_without_errors(self):
        with ApiServer() as server:
            results = run_benchmark(server.url, requests=24, concurrency=4, delay=0.0)
            seen = len(server.requests)
        self.assertEqual([r.name for r in results], [
            "urllib, sequential", "urllib, threads", "keep-alive pool, threads",
            "asyncio + urllib in threads", "asyncio native streams"])
        for r in results:
            self.assertEqual((r.requests, r.errors), (24, 0))
            self.assertEqual(len(r.latencies), 24)
        self.assertEqual(seen, 5 + 5 * 24)               # warm-up plus every scenario

    def test_overlapping_waits_beats_doing_them_one_at_a_time(self):
        with ApiServer() as server:
            results = {r.name: r for r in run_benchmark(
                server.url, requests=16, concurrency=8, delay=0.05, warmup=1)}
        sequential = results["urllib, sequential"].seconds
        self.assertGreater(sequential, 16 * 0.05)         # at least the sum of the delays
        for name in ("urllib, threads", "keep-alive pool, threads", "asyncio + urllib in threads",
                     "asyncio native streams"):
            self.assertLess(results[name].seconds, sequential / 2, name)

    def test_keepalive_opens_few_connections(self):
        with ApiServer() as server:
            run_benchmark(server.url, requests=40, concurrency=4, delay=0.0,
                          scenarios=["keepalive"], warmup=0)
            self.assertLessEqual(server.connections, 4)

    def test_errors_are_counted_not_raised(self):
        with ApiServer() as server:
            url = server.url
            warm_ok = run_benchmark(url, requests=2, concurrency=1, scenarios=["sequential"], warmup=1)
        self.assertEqual(warm_ok[0].errors, 0)
        from restclients.bench import run_urllib_sequential
        with ApiServer() as dead:
            dead_url = dead.url
        result = run_urllib_sequential(dead_url, "/items/1", None, 3, 1)
        self.assertEqual((result.errors, result.latencies), (3, []))

    def test_unknown_scenario(self):
        with self.assertRaisesRegex(ValueError, "nope"):
            run_benchmark("http://127.0.0.1:9", scenarios=["nope"])
        self.assertEqual(sorted(SCENARIOS), ["asyncio", "asyncio-native", "keepalive", "sequential", "threads"])


class ReportTests(unittest.TestCase):
    def test_table_is_sorted_by_time_and_aligned(self):
        slow = Result("slow one", 10, 1, 5.0, [0.5] * 10, 0)
        fast = Result("fast", 10, 4, 1.0, [0.1] * 10, 1)
        lines = format_table([slow, fast]).splitlines()
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[0].startswith("scenario"))
        self.assertTrue(lines[2].startswith("fast"))
        self.assertTrue(lines[3].startswith("slow one"))
        self.assertEqual(len({len(line) for line in lines}), 1)       # columns line up

    def test_cli_table_and_json(self):
        out = io.StringIO()
        self.assertEqual(main(["-n", "6", "-c", "2", "--scenario", "sequential", "--scenario", "threads"], out), 0)
        text = out.getvalue()
        self.assertIn("urllib, sequential", text)
        self.assertIn("urllib, threads", text)
        self.assertNotIn("asyncio", text)
        out = io.StringIO()
        main(["-n", "4", "-c", "2", "--scenario", "keepalive", "--json"], out)
        (row,) = json.loads(out.getvalue())
        self.assertEqual((row["name"], row["requests"], row["errors"]), ("keep-alive pool, threads", 4, 0))

    def test_cli_against_an_explicit_url(self):
        with ApiServer() as server:
            out = io.StringIO()
            main(["--url", server.url, "-n", "3", "--scenario", "sequential", "--json"], out)
            self.assertGreaterEqual(len(server.requests), 3 + 5)
        self.assertEqual(json.loads(out.getvalue())[0]["requests"], 3)


if __name__ == "__main__":
    unittest.main()
