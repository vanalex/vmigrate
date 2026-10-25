from __future__ import annotations

from typing import Protocol

from vmigrate.domain.models import Record


class DeadLetterSink(Protocol):
    def put(self, run_id: str, collection: str, record: Record, error: str) -> None: ...

    def close(self) -> None: ...
