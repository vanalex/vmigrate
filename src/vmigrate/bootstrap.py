"""Composition root: the one place that picks concrete adapters and wires the use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

from vmigrate.adapters.checkpoint import SqliteCheckpointStore
from vmigrate.adapters.observability import JsonlDeadLetter, NoopMetrics, PrometheusMetrics
from vmigrate.app import (
    EngineSettings,
    PipelineEngine,
    PlanMigration,
    ResumeMigration,
    RunMigration,
    Validate,
)
from vmigrate.infra import registry
from vmigrate.infra.config import MigrationConfig
from vmigrate.ports import DeadLetterSink, Metrics, Sink, Source


@dataclass
class Container:
    config: MigrationConfig
    source: Source
    sink: Sink
    checkpoints: SqliteCheckpointStore
    deadletter: DeadLetterSink
    metrics: Metrics
    planner: PlanMigration = field(init=False)
    run: RunMigration = field(init=False)
    resume: ResumeMigration = field(init=False)
    validate: Validate = field(init=False)

    def __post_init__(self) -> None:
        d = self.config.defaults
        engine = PipelineEngine(
            self.source,
            self.sink,
            self.checkpoints,
            self.deadletter,
            self.metrics,
            EngineSettings(d.batch_size, d.workers, d.max_retries, d.on_error),
        )
        self.planner = PlanMigration(self.source, self.sink, d.sample_size)
        self.run = RunMigration(self.planner, self.sink, engine, self.checkpoints)
        self.resume = ResumeMigration(self.run, self.checkpoints)
        self.validate = Validate(self.source, self.sink, self.planner)

    def close(self) -> None:
        for closable in (self.source, self.sink, self.checkpoints, self.deadletter):
            closable.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def build(
    config: MigrationConfig,
    *,
    source: Source | None = None,
    sink: Sink | None = None,
    metrics: Metrics | None = None,
) -> Container:
    """Explicit `source`/`sink`/`metrics` override the config (used by tests and embedders)."""
    if metrics is None:
        port = config.observability.prometheus_port
        metrics = PrometheusMetrics(port) if port else NoopMetrics()
    return Container(
        config=config,
        source=source or registry.create_source(config.source.type, config.source.options()),
        sink=sink or registry.create_sink(config.target.type, config.target.options()),
        checkpoints=SqliteCheckpointStore(config.state.checkpoint_path),
        deadletter=JsonlDeadLetter(config.state.deadletter_dir),
        metrics=metrics,
    )
