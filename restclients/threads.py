"""Bounded concurrency for the synchronous clients (the thread counterpart of ``gather_bounded``)."""
import contextvars
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_EXCEPTION


def map_concurrent(func, items, workers=8, return_exceptions=False):
    """``[func(item) for item in items]`` using up to ``workers`` threads; results keep input order.

    * The caller's context variables are copied into each task, so a
      ``restclients.logging_utils.correlation_id`` set around the call reaches the requests
      made by the workers (plain thread pools do not do this).
    * With ``return_exceptions=False`` the first failure cancels tasks that have not started
      and is re-raised once the running ones finish; with True, each failure is returned in
      its slot instead.
    * Share one thread-safe client between workers (``UrllibClient``, ``KeepAliveClient``);
      a ``requests.Session`` is *mostly* safe but not guaranteed to be.
    """
    if workers < 1:
        raise ValueError("workers must be at least 1")
    items = list(items)
    context = contextvars.copy_context()

    def run(item):
        return context.copy().run(func, item)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, item) for item in items]
        if not return_exceptions:
            done, _ = wait(futures, return_when=FIRST_EXCEPTION)
            if any(f.exception() is not None for f in done if not f.cancelled()):
                for future in futures:
                    future.cancel()           # only affects tasks that have not started
        results = []
        for future in futures:
            if future.cancelled():
                continue
            try:
                results.append(future.result())
            except Exception as exc:
                if not return_exceptions:
                    raise
                results.append(exc)
        return results


def get_many(client, paths, workers=8, return_exceptions=False, **kwargs):
    """GET each of ``paths`` concurrently and return the decoded JSON bodies in order."""
    return map_concurrent(lambda path: client.get_json(path, **kwargs), paths, workers, return_exceptions)
