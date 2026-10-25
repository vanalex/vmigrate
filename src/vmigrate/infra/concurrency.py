from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


def run_parallel(fn: Callable[[T], R], items: Iterable[T], workers: int) -> list[R]:
    """Run `fn` over `items` in threads; the first failure cancels pending work and is raised."""
    items = list(items)
    if not items:
        return []
    if workers <= 1 or len(items) == 1:
        return [fn(i) for i in items]
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        futures = [pool.submit(fn, i) for i in items]
        done, pending = wait(futures, return_when=FIRST_EXCEPTION)
        for f in pending:
            f.cancel()
        for f in done:
            if f.exception() is not None:
                raise f.exception()
        return [f.result() for f in futures]
