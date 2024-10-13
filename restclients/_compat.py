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

try:
    from warnings import deprecated         # Python 3.13+
except ImportError:                          # pragma: no cover - exercised on older interpreters only
    import functools
    import warnings

    def deprecated(message, *, category=DeprecationWarning, stacklevel=1):
        """Decorator marking a function deprecated; calling it warns (like warnings.deprecated)."""
        def decorate(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                warnings.warn(message, category, stacklevel=stacklevel + 1)
                return func(*args, **kwargs)
            return wrapper
        return decorate

__all__ = ["batched", "deprecated"]
