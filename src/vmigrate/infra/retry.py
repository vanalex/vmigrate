from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

R = TypeVar("R")
log = logging.getLogger(__name__)


def retry(
    fn: Callable[[], R],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
) -> R:
    """Call `fn` with exponential backoff and jitter; re-raise after the last attempt."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retry_on as exc:
            if attempt == attempts:
                raise
            delay = min(max_delay, base_delay * 2 ** (attempt - 1)) * random.uniform(0.5, 1.0)
            log.warning("attempt %d/%d failed: %s; retrying in %.2fs", attempt, attempts, exc, delay)
            sleep(delay)
    raise AssertionError("unreachable")
