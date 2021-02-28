"""Run many requests concurrently without opening hundreds of connections at once."""
import asyncio


async def gather_bounded(factories, limit=10, return_exceptions=False):
    """Await ``factory()`` for each zero-argument callable, at most ``limit`` at a time.

    Taking callables (not coroutine objects) means a coroutine is only created
    when its turn comes, so a long list does not allocate thousands of pending
    coroutines. Results come back in the order of ``factories``.

    With ``return_exceptions=False`` the first failure cancels everything still
    running and is re-raised.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    semaphore = asyncio.Semaphore(limit)

    async def run(factory):
        async with semaphore:
            return await factory()

    tasks = [asyncio.ensure_future(run(f)) for f in factories]
    try:
        return await asyncio.gather(*tasks, return_exceptions=return_exceptions)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def map_bounded(func, items, limit=10, return_exceptions=False):
    """``await func(item)`` for every item with bounded concurrency; ordered results."""
    return await gather_bounded([lambda item=item: func(item) for item in items],
                                limit, return_exceptions)
