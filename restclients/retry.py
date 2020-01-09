"""Retry policy: which failures are worth another attempt, and how long to wait.

This module is pure decision-making. It never sleeps or sends anything, so it
is easy to test; the client owns the loop (see ``HttpClient.request``).
"""
import random

IDEMPOTENT_METHODS = frozenset(["GET", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"])
RETRY_STATUSES = frozenset([500, 502, 503, 504])


class RetryPolicy:
    """Exponential backoff with optional jitter.

    ``max_attempts`` counts the first try, so 3 means one try and two retries.
    The wait before retry ``n`` (starting at 1) is
    ``min(max_delay, backoff_base * 2 ** (n - 1))``. With ``jitter=True`` it is
    drawn uniformly from ``[0, that]`` ("full jitter"), which spreads out
    clients that all failed at the same moment.
    """

    def __init__(self, max_attempts=3, backoff_base=0.5, max_delay=30.0, jitter=True,
                 statuses=RETRY_STATUSES, methods=IDEMPOTENT_METHODS, rng=None):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.max_delay = max_delay
        self.jitter = jitter
        self.statuses = frozenset(statuses)
        self.methods = frozenset(m.upper() for m in methods)
        self.rng = rng or random.Random()

    def backoff(self, retry_number):
        """Seconds to wait before retry number ``retry_number`` (1-based)."""
        ceiling = min(self.max_delay, self.backoff_base * (2 ** (retry_number - 1)))
        return self.rng.uniform(0, ceiling) if self.jitter else ceiling

    def should_retry_method(self, method):
        return method.upper() in self.methods

    def should_retry_status(self, status):
        return status in self.statuses

    def attempts_left(self, attempt):
        """``attempt`` is the number of tries made so far."""
        return attempt < self.max_attempts
