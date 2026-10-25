from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from vmigrate.app.engine import MigrationError, PipelineEngine
from vmigrate.app.plan import PlanMigration
from vmigrate.domain.mapping import CollectionMapping
from vmigrate.domain.models import RunStats, SchemaPlan
from vmigrate.domain.transforms import build_chain
from vmigrate.ports import CheckpointStore, Sink

log = logging.getLogger(__name__)


class PlanGapError(MigrationError):
    def __init__(self, collection: str, gaps: list[str]):
        super().__init__(f"{collection}: cannot migrate without data loss: {'; '.join(gaps)}")
        self.gaps = gaps


@dataclass
class CollectionReport:
    source: str
    target: str
    plan: SchemaPlan
    stats: RunStats


@dataclass
class RunReport:
    run_id: str
    status: str = "running"
    collections: list[CollectionReport] = field(default_factory=list)


def new_run_id() -> str:
    return f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


class RunMigration:
    def __init__(
        self,
        planner: PlanMigration,
        sink: Sink,
        engine: PipelineEngine,
        checkpoints: CheckpointStore,
    ):
        self._planner = planner
        self._sink = sink
        self._engine = engine
        self._checkpoints = checkpoints

    def execute(
        self, mappings: list[CollectionMapping], config_hash: str, run_id: str | None = None
    ) -> RunReport:
        report = RunReport(run_id=run_id or new_run_id())
        self._checkpoints.start_run(report.run_id, config_hash)
        try:
            for mapping in mappings:
                plan = self._planner.execute(mapping)
                for warning in plan.warnings:
                    log.warning("%s: %s", mapping.source, warning)
                if plan.gaps:
                    raise PlanGapError(mapping.source, plan.gaps)
                self._sink.ensure_collection(plan)
                stats = self._engine.migrate(
                    report.run_id, mapping, plan.target, build_chain(mapping, plan)
                )
                report.collections.append(
                    CollectionReport(mapping.source, plan.target, plan, stats)
                )
                log.info("%s -> %s done: %s", mapping.source, plan.target, stats)
        except BaseException:
            report.status = "failed"
            self._checkpoints.finish_run(report.run_id, report.status)
            raise
        report.status = "completed"
        self._checkpoints.finish_run(report.run_id, report.status)
        return report
