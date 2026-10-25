"""Python API for embedding vmigrate in orchestrators (Airflow, Dagster, scripts)."""

from __future__ import annotations

from pathlib import Path

from vmigrate.app import CollectionValidation, RunReport, load_golden
from vmigrate.bootstrap import build
from vmigrate.domain.models import SchemaPlan
from vmigrate.infra.config import load_config


def plan(config_path: str | Path, collections: list[str] | None = None) -> list[SchemaPlan]:
    config = load_config(config_path)
    with build(config) as c:
        return [c.planner.execute(m) for m in config.mappings(collections)]


def run(
    config_path: str | Path,
    collections: list[str] | None = None,
    resume_run_id: str | None = None,
) -> RunReport:
    config = load_config(config_path)
    mappings = config.mappings(collections)
    with build(config) as c:
        if resume_run_id:
            return c.resume.execute(mappings, config.fingerprint(), resume_run_id)
        return c.run.execute(mappings, config.fingerprint())


def validate(
    config_path: str | Path,
    collections: list[str] | None = None,
    golden_path: str | Path | None = None,
) -> list[CollectionValidation]:
    config = load_config(config_path)
    golden = load_golden(golden_path) if golden_path else None
    with build(config) as c:
        return [c.validate.execute(m, golden) for m in config.mappings(collections)]
