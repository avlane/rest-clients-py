"""Client-side rate limiting with a token bucket.

The bucket holds up to ``capacity`` tokens and refills at ``rate`` tokens per
second. Each request takes one. A full bucket allows a burst; after that
requests are spaced ``1 / rate`` seconds apart.
"""
import threading
import time


class TokenBucket:
    def __init__(self, rate, capacity=1, clock=time.monotonic, sleep=time.sleep):
        if rate <= 0:
            raise ValueError("rate must be positive")
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.rate = float(rate)
        self.capacity = float(capacity)
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(capacity)
        self._updated = clock()
        self._lock = threading.Lock()

    def _refill(self):
        now = self._clock()
        elapsed = max(0.0, now - self._updated)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._updated = now

    def try_acquire(self, tokens=1):
        """Take tokens if available right now; never waits."""
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def reserve(self, tokens=1):
        """Take tokens now and return how long the caller must wait before using them."""
        with self._lock:
            self._refill()
            self._tokens -= tokens
            if self._tokens >= 0:
                return 0.0
            return -self._tokens / self.rate

    def acquire(self, tokens=1):
        """Block until ``tokens`` are available. Returns the seconds slept."""
        wait = self.reserve(tokens)
        if wait > 0:
            self._sleep(wait)
        return wait


class RateLimitInfo:
    """What the server says about its own rate limit.

    Understands the IETF draft names (``RateLimit-Limit``, ``RateLimit-Remaining`` and
    ``RateLimit-Reset``, the last a number of seconds) and the common ``X-RateLimit-*`` forms,
    where ``X-RateLimit-Reset`` is usually a Unix timestamp (GitHub) but sometimes seconds.
    """

    def __init__(self, limit, remaining, reset_at):
        self.limit = limit
        self.remaining = remaining
        self.reset_at = reset_at          # Unix timestamp when the window renews, or None

    @classmethod
    def from_headers(cls, headers, now=None):
        """Parse a ``Headers`` (or mapping); returns None if the response says nothing useful."""
        now = time.time() if now is None else now

        def number(*names):
            for name in names:
                value = headers.get(name) if hasattr(headers, "get") else None
                if value is None:
                    continue
                try:
                    return float(str(value).strip().split(",")[0].split(";")[0])
                except ValueError:
                    continue
            return None

        limit = number("RateLimit-Limit", "X-RateLimit-Limit")
        remaining = number("RateLimit-Remaining", "X-RateLimit-Remaining")
        if remaining is None:
            return None
        reset = number("RateLimit-Reset", "X-RateLimit-Reset", "X-Rate-Limit-Reset")
        reset_at = None
        if reset is not None:
            reset_at = reset if reset > 1e9 else now + reset      # a timestamp, or seconds from now
        return cls(None if limit is None else int(limit), int(remaining), reset_at)

    def wait_needed(self, now=None):
        """Seconds until the window renews if no requests remain, else 0."""
        now = time.time() if now is None else now
        if self.remaining > 0 or self.reset_at is None:
            return 0.0
        return max(0.0, self.reset_at - now)

    def __repr__(self):
        return "RateLimitInfo(limit=%r, remaining=%r, reset_at=%r)" % (self.limit, self.remaining, self.reset_at)
