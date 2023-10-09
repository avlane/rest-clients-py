"""Features that arrived after the oldest supported Python, with fallbacks."""
try:
    from itertools import batched          # Python 3.12+
except ImportError:                          # pragma: no cover - exercised on older interpreters only
    from itertools import islice

    def batched(iterable, n):
        """Yield tuples of up to ``n`` items (same behaviour as itertools.batched)."""
        if n < 1:
            raise ValueError("n must be at least one")
        iterator = iter(iterable)
        while True:
            chunk = tuple(islice(iterator, n))
            if not chunk:
                return
            yield chunk

__all__ = ["batched"]
