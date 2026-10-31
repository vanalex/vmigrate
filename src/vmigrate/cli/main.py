from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Annotated

import typer

from vmigrate.app import MigrationError, load_golden
from vmigrate.bootstrap import build
from vmigrate.domain.models import SchemaPlan
from vmigrate.infra.config import load_config
from vmigrate.infra.logging import configure_logging

app = typer.Typer(no_args_is_help=True, help="Migrate vector collections between databases.")

ConfigOpt = Annotated[
    Path, typer.Option("--config", "-c", exists=True, dir_okay=False, help="Migration YAML")
]
CollectionsOpt = Annotated[
    str | None, typer.Option("--collections", help="Comma-separated source collection names")
]
JsonOpt = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON")]


def _split(value: str | None) -> list[str] | None:
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


def _dump(obj: object) -> str:
    return json.dumps(dataclasses.asdict(obj), indent=2, default=str)  # type: ignore[arg-type]


def _print_plan(plan: SchemaPlan) -> None:
    typer.secho(f"\n{plan.source} -> {plan.target}", bold=True)
    for v in plan.vectors:
        kind = "multivector" if v.multivector else "vector"
        typer.echo(f"  {kind:11} {v.name:20} dim={v.size:<6} distance={v.distance.value}")
    for p in plan.properties:
        flags = " [range]" if p.range_filter else ""
        nested = f" {{{', '.join(n.name for n in p.nested)}}}" if p.nested else ""
        typer.echo(f"  property    {p.name:20} {p.type.value}{flags}{nested}")
    for w in plan.warnings:
        typer.secho(f"  ! {w}", fg=typer.colors.YELLOW)
    for g in plan.gaps:
        typer.secho(f"  x {g}", fg=typer.colors.RED)


@app.callback()
def main(
    log_level: Annotated[str, typer.Option(help="DEBUG, INFO, WARNING")] = "INFO",
    json_logs: Annotated[bool, typer.Option(help="Structured JSON logs")] = False,
) -> None:
    configure_logging(log_level, json_logs)


@app.command()
def plan(config: ConfigOpt, collections: CollectionsOpt = None, as_json: JsonOpt = False) -> None:
    """Show the inferred target schema, warnings and blocking gaps. Writes nothing."""
    cfg = load_config(config)
    with build(cfg) as c:
        plans = [c.planner.execute(m) for m in cfg.mappings(_split(collections))]
    if as_json:
        typer.echo(json.dumps([dataclasses.asdict(p) for p in plans], indent=2, default=str))
    else:
        for p in plans:
            _print_plan(p)
    if any(p.gaps for p in plans):
        raise typer.Exit(2)


@app.command()
def run(
    config: ConfigOpt,
    collections: CollectionsOpt = None,
    resume: Annotated[str | None, typer.Option(help="Run id to resume")] = None,
    as_json: JsonOpt = False,
) -> None:
    """Migrate collections. Safe to rerun; use --resume to continue a failed run."""
    cfg = load_config(config)
    mappings = cfg.mappings(_split(collections))
    with build(cfg) as c:
        try:
            if resume:
                report = c.resume.execute(mappings, cfg.fingerprint(), resume)
            else:
                report = c.run.execute(mappings, cfg.fingerprint())
        except MigrationError as exc:
            typer.secho(f"migration failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from exc
    if as_json:
        typer.echo(_dump(report))
        return
    typer.secho(f"run {report.run_id}: {report.status}", bold=True)
    for col in report.collections:
        s = col.stats
        typer.echo(
            f"  {col.source} -> {col.target}: read={s.read} written={s.written} "
            f"failed={s.failed} skipped={s.skipped}"
        )
    if any(col.stats.failed for col in report.collections):
        typer.secho(
            f"  failed records in {cfg.state.deadletter_dir / report.run_id}",
            fg=typer.colors.YELLOW,
        )


@app.command()
def validate(
    config: ConfigOpt,
    collections: CollectionsOpt = None,
    golden: Annotated[Path | None, typer.Option(help="Golden queries JSONL")] = None,
    as_json: JsonOpt = False,
) -> None:
    """Compare source and target: counts, sampled records, and search parity."""
    cfg = load_config(config)
    queries = load_golden(golden) if golden else None
    with build(cfg) as c:
        results = [c.validate.execute(m, queries) for m in cfg.mappings(_split(collections))]
    if as_json:
        typer.echo(
            json.dumps(
                [{**dataclasses.asdict(r), "passed": r.passed} for r in results],
                indent=2,
                default=str,
            )
        )
    else:
        for r in results:
            color = typer.colors.GREEN if r.passed else typer.colors.RED
            typer.secho(
                f"\n{r.source} -> {r.target}: {'PASS' if r.passed else 'FAIL'}", fg=color, bold=True
            )
            typer.echo(f"  count        {r.source_count} -> {r.target_count}")
            f = r.fidelity
            typer.echo(
                f"  fidelity     sampled={f.sampled} missing={len(f.missing)} "
                f"payload_diffs={len(f.payload_mismatches)} vector_diffs={len(f.vector_mismatches)}"
            )
            for sid, diffs in list(f.payload_mismatches.items())[:5]:
                typer.echo(f"    {sid}: {'; '.join(diffs[:3])}")
            p = r.parity
            if p.queries:
                typer.echo(
                    f"  parity       queries={p.queries} mean@k={p.mean_overlap:.3f} "
                    f"min@k={p.min_overlap:.3f} below_threshold={p.below_threshold}"
                )
    if not all(r.passed for r in results):
        raise typer.Exit(1)


@app.command()
def status(
    config: ConfigOpt,
    run_id: Annotated[str | None, typer.Argument(help="Run id; omit to list recent runs")] = None,
) -> None:
    """Show recent runs, or per-shard progress for one run."""
    cfg = load_config(config)
    from vmigrate.adapters.checkpoint import SqliteCheckpointStore

    store = SqliteCheckpointStore(cfg.state.checkpoint_path)
    try:
        if run_id is None:
            for r in store.list_runs():
                typer.echo(f"{r.run_id}  {r.status:10} {r.created_at}")
            return
        info = store.get_run(run_id)
        if info is None:
            typer.secho(f"run {run_id} not found", fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
        typer.secho(f"{info.run_id}: {info.status} (started {info.created_at})", bold=True)
        for collection, shard, p in store.shards(run_id):
            state = "done" if p.cursor.done else f"at {p.cursor.value}"
            s = p.stats
            typer.echo(
                f"  {collection}/{shard}: {state}  read={s.read} written={s.written} "
                f"failed={s.failed} skipped={s.skipped}"
            )
    finally:
        store.close()


if __name__ == "__main__":
    app()
