from __future__ import annotations

from typing import Protocol, runtime_checkable

from vmigrate.domain.models import Hit, Query, Record, SchemaPlan, WriteResult


@runtime_checkable
class Sink(Protocol):
    def check(self, plan: SchemaPlan) -> list[str]:
        """Target-specific warnings (e.g. a feature unsupported by the server version)."""
        ...

    def ensure_collection(self, plan: SchemaPlan) -> None:
        """Create the collection if missing. Must be safe to call on every run."""
        ...

    def write(self, collection: str, records: list[Record]) -> WriteResult:
        """Upsert by record id. Per-record failures go in the result; raise for whole-batch errors."""
        ...

    def count(self, collection: str) -> int: ...

    def fetch(self, collection: str, ids: list[str]) -> list[Record]: ...

    def search(self, collection: str, query: Query) -> list[Hit]: ...

    def close(self) -> None: ...
