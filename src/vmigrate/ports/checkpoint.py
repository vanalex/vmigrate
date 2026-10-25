from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from vmigrate.domain.models import Cursor, RunStats


@dataclass
class ShardProgress:
    cursor: Cursor
    stats: RunStats


@dataclass
class RunInfo:
    run_id: str
    status: str
    config_hash: str
    created_at: str


class CheckpointStore(Protocol):
    def start_run(self, run_id: str, config_hash: str) -> None:
        """Create the run, or mark an existing one as running again."""
        ...

    def finish_run(self, run_id: str, status: str) -> None: ...

    def get_run(self, run_id: str) -> RunInfo | None: ...

    def load(self, run_id: str, collection: str) -> dict[str, ShardProgress]: ...

    def commit(self, run_id: str, collection: str, cursor: Cursor, delta: RunStats) -> None:
        """Persist the new cursor and add `delta` to the shard's counters atomically."""
        ...

    def close(self) -> None: ...
