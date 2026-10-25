from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from vmigrate.domain.models import CollectionSpec, Cursor, Hit, Query, Record


@runtime_checkable
class Source(Protocol):
    def describe(self, collection: str) -> CollectionSpec: ...

    def count(self, collection: str) -> int: ...

    def shards(self, collection: str, parallelism: int) -> list[Cursor]:
        """Initial cursors for independent read streams (at most `parallelism`)."""
        ...

    def read(
        self, collection: str, cursor: Cursor, batch_size: int
    ) -> Iterator[tuple[list[Record], Cursor]]:
        """Yield batches with the cursor to resume *after* that batch.

        The last batch's cursor must have done=True (an empty collection yields one
        empty batch with done=True).
        """
        ...

    def fetch(self, collection: str, source_ids: list[str]) -> list[Record]: ...

    def search(self, collection: str, query: Query) -> list[Hit]: ...

    def close(self) -> None: ...
