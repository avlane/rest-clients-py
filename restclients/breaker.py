"""Circuit breaker: stop calling a dependency that is clearly down.

                 failures >= threshold
      CLOSED ------------------------------> OPEN
        ^                                      |
        | probe succeeds                       | recovery_timeout elapsed
        |                                      v
        +------------- HALF_OPEN <-------------+
                         |  probe fails
                         +------------------> OPEN (timer restarts)

While OPEN every call fails immediately with :class:`CircuitOpen`, which spares
the failing service the extra load and the caller the wait. After
``recovery_timeout`` a limited number of probe calls is let through (HALF_OPEN);
one success closes the circuit again.
"""
import threading
import time

from restclients.errors import ApiError

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half-open"


class CircuitOpen(ApiError):
    """The breaker refused the call without trying it."""

    def __init__(self, name, retry_in):
        super().__init__("circuit %r is open; next probe in %.1fs" % (name, retry_in))
        self.name = name
        self.retry_in = retry_in


class CircuitBreaker:
    def __init__(self, name="default", failure_threshold=5, recovery_timeout=30.0,
                 half_open_max_calls=1, clock=time.monotonic, on_state_change=None):
        if failure_threshold < 1 or half_open_max_calls < 1:
            raise ValueError("failure_threshold and half_open_max_calls must be at least 1")
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.on_state_change = on_state_change
        self._clock = clock
        self._lock = threading.Lock()
        self._state = CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._probes_in_flight = 0
        self.rejected = 0                   # calls refused while open

    @property
    def state(self):
        with self._lock:
            self._maybe_half_open()
            return self._state

    def _set_state(self, state):
        if state != self._state:
            previous, self._state = self._state, state
            if self.on_state_change is not None:
                self.on_state_change(self.name, previous, state)

    def _maybe_half_open(self):
        if self._state == OPEN and self._clock() - self._opened_at >= self.recovery_timeout:
            self._probes_in_flight = 0
            self._set_state(HALF_OPEN)

    def allow(self):
        """Raise :class:`CircuitOpen` unless a call may go ahead. Pair with record_*()."""
        with self._lock:
            self._maybe_half_open()
            if self._state == OPEN:
                self.rejected += 1
                raise CircuitOpen(self.name, self.recovery_timeout - (self._clock() - self._opened_at))
            if self._state == HALF_OPEN:
                if self._probes_in_flight >= self.half_open_max_calls:
                    self.rejected += 1
                    raise CircuitOpen(self.name, 0.0)
                self._probes_in_flight += 1

    def record_success(self):
        with self._lock:
            if self._state == HALF_OPEN:
                self._probes_in_flight = max(0, self._probes_in_flight - 1)
                self._set_state(CLOSED)
            self._failures = 0

    def record_failure(self):
        with self._lock:
            if self._state == HALF_OPEN:
                self._probes_in_flight = max(0, self._probes_in_flight - 1)
                self._trip()
                return
            self._failures += 1
            if self._state == CLOSED and self._failures >= self.failure_threshold:
                self._trip()

    def _trip(self):
        self._opened_at = self._clock()
        self._set_state(OPEN)

    def call(self, func, *args, is_failure=lambda exc: True, **kwargs):
        """Run ``func`` under the breaker. Exceptions for which ``is_failure`` is false
        (e.g. a 404) do not count against the circuit."""
        self.allow()
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            if is_failure(exc):
                self.record_failure()
            else:
                self.record_success()
            raise
        self.record_success()
        return result

    def reset(self):
        with self._lock:
            self._failures = 0
            self._probes_in_flight = 0
            self._set_state(CLOSED)
