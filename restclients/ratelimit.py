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
