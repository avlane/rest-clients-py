import random
import unittest

from restclients.retry import RetryPolicy


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
        self.assertFalse(policy.should_retry_status(429))  # handled with Retry-After later

    def test_zero_attempts_rejected(self):
        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=0)


if __name__ == "__main__":
    unittest.main()
