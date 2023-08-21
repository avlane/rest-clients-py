import threading
import unittest

from restclients.breaker import CLOSED, HALF_OPEN, OPEN, CircuitBreaker, CircuitOpen


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class BreakerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.changes = []
        self.breaker = CircuitBreaker("svc", failure_threshold=3, recovery_timeout=30,
                                      clock=self.clock,
                                      on_state_change=lambda n, a, b: self.changes.append((a, b)))

    def failures(self, times=1):
        for _ in range(times):
            self.breaker.allow()
            self.breaker.record_failure()

    def test_opens_after_consecutive_failures(self):
        self.failures(2)
        self.assertEqual(self.breaker.state, CLOSED)
        self.failures()
        self.assertEqual(self.breaker.state, OPEN)
        self.assertEqual(self.changes, [(CLOSED, OPEN)])

    def test_success_resets_the_failure_count(self):
        self.failures(2)
        self.breaker.allow()
        self.breaker.record_success()
        self.failures(2)
        self.assertEqual(self.breaker.state, CLOSED)

    def test_open_circuit_rejects_immediately_and_says_when_to_retry(self):
        self.failures(3)
        self.clock.now = 10
        with self.assertRaises(CircuitOpen) as ctx:
            self.breaker.allow()
        self.assertAlmostEqual(ctx.exception.retry_in, 20)
        self.assertEqual(self.breaker.rejected, 1)

    def test_half_open_after_the_timeout_and_success_closes(self):
        self.failures(3)
        self.clock.now = 30
        self.assertEqual(self.breaker.state, HALF_OPEN)
        self.breaker.allow()
        self.breaker.record_success()
        self.assertEqual(self.breaker.state, CLOSED)
        self.assertEqual(self.changes, [(CLOSED, OPEN), (OPEN, HALF_OPEN), (HALF_OPEN, CLOSED)])

    def test_failed_probe_reopens_and_restarts_the_timer(self):
        self.failures(3)
        self.clock.now = 30
        self.breaker.allow()
        self.breaker.record_failure()
        self.assertEqual(self.breaker.state, OPEN)
        self.clock.now = 59
        with self.assertRaises(CircuitOpen):
            self.breaker.allow()
        self.clock.now = 60
        self.breaker.allow()           # the next probe window

    def test_only_a_limited_number_of_probes_run_at_once(self):
        self.failures(3)
        self.clock.now = 30
        self.breaker.allow()           # the one allowed probe is in flight
        with self.assertRaises(CircuitOpen):
            self.breaker.allow()

    def test_call_helper_and_failure_classification(self):
        def boom():
            raise KeyError("x")

        for _ in range(2):
            with self.assertRaises(KeyError):
                self.breaker.call(boom)
        for _ in range(5):             # "expected" errors are not failures; the service did answer
            with self.assertRaises(KeyError):
                self.breaker.call(boom, is_failure=lambda exc: False)
        # ...and an answer counts as a sign of health, so the earlier failures were forgotten
        for _ in range(2):
            with self.assertRaises(KeyError):
                self.breaker.call(boom)
        self.assertEqual(self.breaker.state, CLOSED)
        with self.assertRaises(KeyError):
            self.breaker.call(boom)
        self.assertEqual(self.breaker.state, OPEN)

    def test_call_returns_the_result(self):
        self.assertEqual(self.breaker.call(lambda a, b=1: a + b, 2, b=3), 5)

    def test_reset(self):
        self.failures(3)
        self.breaker.reset()
        self.assertEqual(self.breaker.state, CLOSED)
        self.failures(2)
        self.assertEqual(self.breaker.state, CLOSED)

    def test_invalid_configuration(self):
        with self.assertRaises(ValueError):
            CircuitBreaker(failure_threshold=0)

    def test_thread_safety_smoke(self):
        breaker = CircuitBreaker(failure_threshold=50, recovery_timeout=1000)

        def hammer():
            for _ in range(100):
                try:
                    breaker.allow()
                    breaker.record_failure()
                except CircuitOpen:
                    pass

        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(breaker.state, OPEN)
        self.assertEqual(breaker.rejected, 800 - 50)


if __name__ == "__main__":
    unittest.main()
