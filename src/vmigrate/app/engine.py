"""Pipeline engine: shard readers -> transform chain -> sink writer, with checkpoints."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from vmigrate.domain.mapping import CollectionMapping
from vmigrate.domain.models import Cursor, Record, RunStats
from vmigrate.domain.transforms import Transform, apply_chain
from vmigrate.infra.concurrency import run_parallel
from vmigrate.infra.retry import retry
from vmigrate.ports import CheckpointStore, DeadLetterSink, Metrics, Sink, Source

log = logging.getLogger(__name__)


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class EngineSettings:
    batch_size: int = 500
    workers: int = 4
    max_retries: int = 3
    on_error: str = "deadletter"  # or "fail"


class PipelineEngine:
    def __init__(
        self,
        source: Source,
        sink: Sink,
        checkpoints: CheckpointStore,
        deadletter: DeadLetterSink,
        metrics: Metrics,
        settings: EngineSettings,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._source = source
        self._sink = sink
        self._checkpoints = checkpoints
        self._deadletter = deadletter
        self._metrics = metrics
        self._settings = settings
        self._sleep = sleep

    def migrate(
        self, run_id: str, mapping: CollectionMapping, target: str, chain: list[Transform]
    ) -> RunStats:
        progress = self._checkpoints.load(run_id, mapping.source)
        pending: list[Cursor] = []
        for initial in self._source.shards(mapping.source, self._settings.workers):
            saved = progress.get(initial.shard)
            if saved is None:
                pending.append(initial)
            elif not saved.cursor.done:
                pending.append(saved.cursor)

        done = sum(1 for p in progress.values() if p.cursor.done)
        log.info("%s -> %s: %d shard(s) pending, %d done", mapping.source, target,
                 len(pending), done)
        run_parallel(
            lambda cursor: self._run_shard(run_id, mapping, target, chain, cursor),
            pending,
            self._settings.workers,
        )

        total = RunStats()
        for shard in self._checkpoints.load(run_id, mapping.source).values():
            total += shard.stats
        return total

    def _run_shard(
        self,
        run_id: str,
        mapping: CollectionMapping,
        target: str,
        chain: list[Transform],
        cursor: Cursor,
    ) -> None:
        batches = self._source.read(mapping.source, cursor, self._settings.batch_size)
        for records, next_cursor in batches:
            kept = apply_chain(chain, records)
            delta = RunStats(read=len(records), skipped=len(records) - len(kept))
            if kept:
                written, failed = self._write(run_id, mapping.source, target, kept)
                delta.written, delta.failed = written, failed
            # Commit only after the write: a crash replays at most one batch (idempotent upserts).
            self._checkpoints.commit(run_id, mapping.source, next_cursor, delta)
            self._emit(mapping.source, delta)

    def _write(
        self, run_id: str, collection: str, target: str, records: list[Record]
    ) -> tuple[int, int]:
        attempts = self._settings.max_retries
        result = retry(lambda: self._sink.write(target, records), attempts=attempts,
                       sleep=self._sleep)
        written, failures = result.written, result.failures

        # Per-record failures are often transient too (e.g. timeouts); retry just those.
        for _ in range(attempts - 1):
            if not failures:
                break
            again = self._sink.write(target, [r for r, _ in failures])
            written += again.written
            failures = again.failures

        if failures:
            if self._settings.on_error == "fail":
                record, error = failures[0]
                raise MigrationError(
                    f"{len(failures)} record(s) failed in {collection}; first: "
                    f"{record.source_id}: {error}"
                )
            for record, error in failures:
                self._deadletter.put(run_id, collection, record, error)
        return written, len(failures)

    def _emit(self, collection: str, delta: RunStats) -> None:
        for name in ("read", "written", "failed", "skipped"):
            value = getattr(delta, name)
            if value:
                self._metrics.inc(f"records_{name}", value, collection=collection)
