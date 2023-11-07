"""Retry policy: which failures are worth another attempt, and how long to wait.

This module is pure decision-making. It never sleeps or sends anything, so it
is easy to test; the client owns the loop (see ``HttpClient.request``).
"""
import random
import re
import time
from datetime import timezone
from email.utils import parsedate_to_datetime

IDEMPOTENT_METHODS = frozenset(["GET", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"])
RETRY_STATUSES = frozenset([429, 500, 502, 503, 504])


_DECIMAL = re.compile(r"\d+(\.\d+)?$")


def parse_retry_after(value, now=None):
    """Seconds to wait according to a ``Retry-After`` header, or None.

    The header is either delta-seconds (``120``) or an HTTP-date
    (``Wed, 21 Oct 2015 07:28:00 GMT``). Dates in the past give 0. A few servers
    send fractional seconds (``1.5``), which is accepted. Anything else is None.
    ``now`` is a timestamp, injectable for tests.
    """
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    if _DECIMAL.match(value):
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        # "-0000" means UTC with an unknown local zone; email.utils then returns a naive
        # datetime, and naive.timestamp() would silently use this machine's timezone.
        when = when.replace(tzinfo=timezone.utc)
    current = now if now is not None else time.time()
    return max(0.0, when.timestamp() - current)


class RetryPolicy:
    """Exponential backoff with optional jitter.

    ``max_attempts`` counts the first try, so 3 means one try and two retries.
    The wait before retry ``n`` (starting at 1) is
    ``min(max_delay, backoff_base * 2 ** (n - 1))``. With ``jitter=True`` it is
    drawn uniformly from ``[0, that]`` ("full jitter"), which spreads out
    clients that all failed at the same moment.
    """

    def __init__(self, max_attempts=3, backoff_base=0.5, max_delay=30.0, jitter=True,
                 statuses=RETRY_STATUSES, methods=IDEMPOTENT_METHODS, rng=None,
                 max_retry_after=60.0):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.max_delay = max_delay
        self.jitter = jitter
        self.statuses = frozenset(statuses)
        self.methods = frozenset(m.upper() for m in methods)
        self.rng = rng or random.Random()
        self.max_retry_after = max_retry_after

    def backoff(self, retry_number):
        """Seconds to wait before retry number ``retry_number`` (1-based)."""
        ceiling = min(self.max_delay, self.backoff_base * (2 ** (retry_number - 1)))
        return self.rng.uniform(0, ceiling) if self.jitter else ceiling

    def wait_seconds(self, retry_number, retry_after=None):
        """How long to sleep before a retry, or None to give up instead.

        A server's ``Retry-After`` is a floor under our own backoff. If the
        server asks for longer than ``max_retry_after`` we would rather fail
        than block the caller that long.
        """
        wait = self.backoff(retry_number)
        if retry_after is not None:
            if retry_after > self.max_retry_after:
                return None
            wait = max(wait, retry_after)
        return wait

    def should_retry_method(self, method):
        return method.upper() in self.methods

    def should_retry_status(self, status):
        return status in self.statuses

    def attempts_left(self, attempt):
        """``attempt`` is the number of tries made so far."""
        return attempt < self.max_attempts
