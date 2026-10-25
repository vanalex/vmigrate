"""In-memory Source/Sink. Used by tests and handy for trying mappings without databases."""

from __future__ import annotations

import copy
import threading
from collections.abc import Iterator

from vmigrate.domain.models import (
    CollectionSpec,
    Cursor,
    Hit,
    Query,
    Record,
    SchemaPlan,
    WriteResult,
)
from vmigrate.domain.parity import cosine


class MemorySource:
    def __init__(self, collections: dict[str, tuple[CollectionSpec, list[Record]]] | None = None,
                 **_: object):
        self.collections = collections or {}

    def describe(self, collection: str) -> CollectionSpec:
        return self.collections[collection][0]

    def count(self, collection: str) -> int:
        return len(self.collections[collection][1])

    def shards(self, collection: str, parallelism: int) -> list[Cursor]:
        total = self.count(collection)
        n = max(1, min(parallelism, total))
        step = -(-total // n)  # ceil
        # Shard name encodes its [start, end) range so a resume reads the same slice.
        return [Cursor(shard=f"{s}-{min(s + step, total)}", value=s) for s in range(0, total, step)] \
            or [Cursor(shard="0-0", value=0)]

    def read(self, collection: str, cursor: Cursor, batch_size: int
             ) -> Iterator[tuple[list[Record], Cursor]]:
        records = self.collections[collection][1]
        start, end = (int(x) for x in cursor.shard.split("-"))
        pos = start if cursor.value is None else cursor.value
        if pos >= end:
            yield [], Cursor(cursor.shard, end, done=True)
            return
        while pos < end:
            nxt = min(pos + batch_size, end)
            yield copy.deepcopy(records[pos:nxt]), Cursor(cursor.shard, nxt, done=nxt >= end)
            pos = nxt

    def fetch(self, collection: str, source_ids: list[str]) -> list[Record]:
        wanted = set(source_ids)
        return [copy.deepcopy(r) for r in self.collections[collection][1]
                if str(r.source_id) in wanted]

    def search(self, collection: str, query: Query) -> list[Hit]:
        return _brute_force(self.collections[collection][1], query, lambda r: str(r.source_id))

    def close(self) -> None:
        pass


class MemorySink:
    def __init__(self, **_: object):
        self.plans: dict[str, SchemaPlan] = {}
        self.data: dict[str, dict[str, Record]] = {}
        self._lock = threading.Lock()

    def check(self, plan: SchemaPlan) -> list[str]:
        return []

    def ensure_collection(self, plan: SchemaPlan) -> None:
        with self._lock:
            self.plans.setdefault(plan.target, plan)
            self.data.setdefault(plan.target, {})

    def write(self, collection: str, records: list[Record]) -> WriteResult:
        with self._lock:
            store = self.data[collection]
            for r in records:
                store[r.id] = copy.deepcopy(r)
        return WriteResult(written=len(records))

    def count(self, collection: str) -> int:
        return len(self.data.get(collection, {}))

    def fetch(self, collection: str, ids: list[str]) -> list[Record]:
        store = self.data.get(collection, {})
        return [copy.deepcopy(store[i]) for i in ids if i in store]

    def search(self, collection: str, query: Query) -> list[Hit]:
        return _brute_force(list(self.data.get(collection, {}).values()), query, lambda r: r.id)

    def close(self) -> None:
        pass


def _brute_force(records: list[Record], query: Query, key) -> list[Hit]:
    # Filters are not evaluated here; tests that need them should use real databases.
    scored = [
        Hit(key(r), cosine(query.vector, r.vectors[query.vector_name]))
        for r in records
        if query.vector_name in r.vectors
    ]
    scored.sort(key=lambda h: h.score, reverse=True)
    return scored[: query.limit]
