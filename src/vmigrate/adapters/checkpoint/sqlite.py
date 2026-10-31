from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from vmigrate.domain.models import Cursor, RunStats
from vmigrate.ports import RunInfo, ShardProgress

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shards (
    run_id      TEXT NOT NULL,
    collection  TEXT NOT NULL,
    shard       TEXT NOT NULL,
    cursor      TEXT,
    done        INTEGER NOT NULL DEFAULT 0,
    read        INTEGER NOT NULL DEFAULT 0,
    written     INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    skipped     INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, collection, shard)
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SqliteCheckpointStore:
    """Single-file checkpoint store; safe for the engine's worker threads."""

    def __init__(self, path: str | Path):
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def start_run(self, run_id: str, config_hash: str) -> None:
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO runs VALUES (?, 'running', ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET status='running', updated_at=excluded.updated_at",
                (run_id, config_hash, now, now),
            )

    def finish_run(self, run_id: str, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET status=?, updated_at=? WHERE run_id=?", (status, _now(), run_id)
            )

    def get_run(self, run_id: str) -> RunInfo | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT run_id, status, config_hash, created_at FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
        return RunInfo(*row) if row else None

    def list_runs(self, limit: int = 20) -> list[RunInfo]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id, status, config_hash, created_at FROM runs "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [RunInfo(*r) for r in rows]

    def load(self, run_id: str, collection: str) -> dict[str, ShardProgress]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT shard, cursor, done, read, written, failed, skipped FROM shards "
                "WHERE run_id=? AND collection=?",
                (run_id, collection),
            ).fetchall()
        return {
            shard: ShardProgress(
                cursor=Cursor(shard, json.loads(cursor) if cursor else None, bool(done)),
                stats=RunStats(read, written, failed, skipped),
            )
            for shard, cursor, done, read, written, failed, skipped in rows
        }

    def shards(self, run_id: str) -> list[tuple[str, str, ShardProgress]]:
        """(collection, shard, progress) for every shard of a run, for status reporting."""
        with self._lock:
            collections = [
                r[0]
                for r in self._conn.execute(
                    "SELECT DISTINCT collection FROM shards WHERE run_id=?", (run_id,)
                )
            ]
        return [
            (c, shard, progress)
            for c in collections
            for shard, progress in self.load(run_id, c).items()
        ]

    def commit(self, run_id: str, collection: str, cursor: Cursor, delta: RunStats) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO shards VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, collection, shard) DO UPDATE SET
                    cursor=excluded.cursor, done=excluded.done,
                    read=read+excluded.read, written=written+excluded.written,
                    failed=failed+excluded.failed, skipped=skipped+excluded.skipped,
                    updated_at=excluded.updated_at
                """,
                (
                    run_id,
                    collection,
                    cursor.shard,
                    json.dumps(cursor.value),
                    int(cursor.done),
                    delta.read,
                    delta.written,
                    delta.failed,
                    delta.skipped,
                    _now(),
                ),
            )

    def close(self) -> None:
        self._conn.close()
