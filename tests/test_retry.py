import random
import unittest

from restclients import errors
from restclients.retry import RetryPolicy, parse_retry_after


class RetryPolicyTests(unittest.TestCase):
    def test_backoff_doubles_without_jitter(self):
        policy = RetryPolicy(backoff_base=0.5, jitter=False)
        self.assertEqual([policy.backoff(n) for n in (1, 2, 3, 4)], [0.5, 1.0, 2.0, 4.0])

    def test_backoff_is_capped(self):
        policy = RetryPolicy(backoff_base=1, max_delay=5, jitter=False)
        self.assertEqual(policy.backoff(10), 5)

    def test_jitter_stays_within_ceiling(self):
        policy = RetryPolicy(backoff_base=1, jitter=True, rng=random.Random(42))
        samples = [policy.backoff(3) for _ in range(200)]
        self.assertTrue(all(0 <= s <= 4 for s in samples))
        self.assertGreater(len(set(samples)), 100)

    def test_attempts_left(self):
        policy = RetryPolicy(max_attempts=3)
        self.assertEqual([policy.attempts_left(n) for n in (1, 2, 3)], [True, True, False])

    def test_only_idempotent_methods_by_default(self):
        policy = RetryPolicy()
        self.assertTrue(policy.should_retry_method("get"))
        self.assertTrue(policy.should_retry_method("PUT"))
        self.assertFalse(policy.should_retry_method("POST"))

    def test_statuses(self):
        policy = RetryPolicy()
        self.assertTrue(policy.should_retry_status(503))
        self.assertFalse(policy.should_retry_status(404))
        self.assertTrue(policy.should_retry_status(429))

    def test_zero_attempts_rejected(self):
        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=0)

    def test_retry_after_is_a_floor(self):
        policy = RetryPolicy(backoff_base=1, jitter=False)
        self.assertEqual(policy.wait_seconds(1, retry_after=10), 10)
        self.assertEqual(policy.wait_seconds(3, retry_after=1), 4)
        self.assertEqual(policy.wait_seconds(1), 1)

    def test_retry_after_beyond_cap_gives_up(self):
        policy = RetryPolicy(jitter=False, max_retry_after=30)
        self.assertIsNone(policy.wait_seconds(1, retry_after=31))
        self.assertEqual(policy.wait_seconds(1, retry_after=30), 30)


class ParseRetryAfterTests(unittest.TestCase):
    def test_delta_seconds(self):
        self.assertEqual(parse_retry_after("120"), 120.0)
        self.assertEqual(parse_retry_after(" 0 "), 0.0)

    def test_http_date(self):
        # Wed, 21 Oct 2015 07:28:00 GMT is 1445412480
        self.assertEqual(parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412470), 10.0)

    def test_http_date_in_the_past_is_zero(self):
        self.assertEqual(parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412999), 0.0)

    def test_unknown_local_offset_means_utc_whatever_the_machine_timezone(self):
        # "-0000" is RFC 2822 for "UTC, local zone unknown"; email.utils returns a *naive*
        # datetime for it, and .timestamp() on a naive value assumes the machine's own zone.
        import os
        import time
        if not hasattr(time, "tzset"):
            self.skipTest("time.tzset is not available on this platform")
        old = os.environ.get("TZ")
        self.addCleanup(self._restore_tz, old)
        os.environ["TZ"] = "America/Los_Angeles"
        time.tzset()
        # 1445412480 is Wed, 21 Oct 2015 07:28:00 UTC
        self.assertEqual(parse_retry_after("Wed, 21 Oct 2015 07:28:00 -0000", now=1445412470), 10.0)
        self.assertEqual(parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412470), 10.0)

    @staticmethod
    def _restore_tz(old):
        import os
        import time
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()

    def test_numeric_forms(self):
        self.assertEqual(parse_retry_after("1.5"), 1.5)
        self.assertEqual(parse_retry_after("007"), 7.0)
        self.assertIsNone(parse_retry_after("-5"))
        self.assertIsNone(parse_retry_after("1e3"))
        self.assertIsNone(parse_retry_after("nan"))
        self.assertIsNone(parse_retry_after("inf"))

    def test_offset_dates(self):
        # 09:28:00 +0200 is 07:28:00 UTC
        self.assertEqual(parse_retry_after("Wed, 21 Oct 2015 09:28:00 +0200", now=1445412470), 10.0)

    def test_garbage_and_missing(self):
        self.assertIsNone(parse_retry_after(None))
        self.assertIsNone(parse_retry_after(""))
        self.assertIsNone(parse_retry_after("soon"))


class RateLimitedErrorTests(unittest.TestCase):
    def test_retry_after_property(self):
        err = errors.error_for_status(429, headers={"retry-after": "7"})
        self.assertIsInstance(err, errors.RateLimited)
        self.assertEqual(err.retry_after, 7.0)

    def test_retry_after_absent(self):
        self.assertIsNone(errors.error_for_status(429).retry_after)


if __name__ == "__main__":
    unittest.main()
