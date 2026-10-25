from __future__ import annotations

from typing import Protocol


class Metrics(Protocol):
    def inc(self, name: str, value: float = 1, **labels: str) -> None: ...
