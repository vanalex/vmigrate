# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

vmigrate is a pluggable vector database migration CLI (Python 3.11+, managed with `uv`). The only
pair implemented so far is Qdrant → Weaviate.

## Commands

```bash
uv sync                                               # install, including dev deps
uv run ruff check . && uv run ruff format .           # lint / format (line length 100)
uv run pytest                                         # unit tests (integration excluded by default)
uv run pytest tests/test_engine.py::test_rerun_is_idempotent -q   # a single test
docker compose up -d && uv run pytest -m integration  # real Qdrant 1.13 + Weaviate 1.30

uv run vmigrate plan -c migrate.yaml                  # schema plan, warnings, gaps (no writes)
uv run vmigrate run -c migrate.yaml [--resume RUN_ID]
uv run vmigrate status -c migrate.yaml [RUN_ID]
uv run vmigrate validate -c migrate.yaml --golden queries.jsonl
```

pytest's `addopts` adds `-m 'not integration'`. Unit tests use the in-memory adapters, plus an
in-process `QdrantClient(":memory:")` passed through the `client=` argument of `QdrantSource`.

## Architecture

Ports and adapters. Dependencies point inward, so keep these boundaries:

- `domain/`: pure logic (models, mapping, type inference, schema planner, transforms, filter
  AST, parity math). It imports no database clients and nothing from `app`, `ports`, `adapters`
  or `infra`.
- `ports/`: `typing.Protocol` interfaces (`Source`, `Sink`, `CheckpointStore`, `DeadLetterSink`,
  `Metrics`) built only on domain types.
- `app/`: use cases (`PlanMigration`, `RunMigration`, `ResumeMigration`, `Validate`) and
  `PipelineEngine`. Imports only `domain`, `ports` and `infra` helpers.
- `adapters/`: the only code that imports `qdrant_client` or `weaviate`.
- `bootstrap.py`: the composition root and the only place concrete adapters are chosen.
  `build(config, source=..., sink=...)` lets tests and embedders inject adapters.
- `infra/registry.py`: resolves `source.type` / `target.type` from the `vmigrate.sources` and
  `vmigrate.sinks` entry points, with a built-in fallback table. A new adapter needs entries in
  both `pyproject.toml` and `_BUILTIN`. All config keys except `type` are passed to the
  adapter's constructor.

### Data flow

`PlanMigration` describes the source collection and samples records. It then runs the transform
chain without a plan, so only the user's type overrides apply. From that it builds a
`SchemaPlan` with `warnings` and `gaps`. Gaps stop a run (`PlanGapError`).

`RunMigration` → `sink.ensure_collection(plan)` → `PipelineEngine.migrate`. For each shard
cursor, the engine:

1. Calls `Source.read`, which yields `(records, cursor_after_batch)`.
2. Runs `apply_chain`: `FieldRenamer` → `TypeCoercer` → `IdMapper` → `VectorRouter` → user hooks
   (`"module:function"`; returning `None` drops the record).
3. Calls `Sink.write`, then `CheckpointStore.commit`.

Failed records are retried, then dead-lettered to JSONL, or the run raises if
`on_error: fail`.

### Invariants that the design relies on

- **Safe re-runs.** `map_id` passes UUIDs through and maps every other ID to `uuid5(namespace,
  id)`. Sinks must upsert by `Record.id`. The checkpoint is committed only after the write, so a
  crash replays at most one batch.
- **Source contract.** The last batch's cursor has `done=True`, and an empty collection yields
  one empty batch with `done=True`. `Sink.write` returns per-record failures in `WriteResult`
  and raises only for whole-batch errors.
- **The unnamed vector** is `DEFAULT_VECTOR = ""` in the domain model. The mapping turns it into
  a named target vector (`default` unless configured otherwise).
- **Resume compatibility.** `--resume` refuses to continue if `MigrationConfig.fingerprint()`
  has changed. The fingerprint covers `collections` and `defaults.workers`, so changing
  `workers` also blocks resume.
- **Weaviate's auto-schema must be off** (`AUTOSCHEMA_ENABLED=false`, as in
  `docker-compose.yml`). The planner owns the schema, so properties it didn't infer fail into
  the dead-letter file instead of being added silently.
- **Validation.** `Validate` re-plans, recomputes the expected records through the same chain,
  and compares them with `Sink.fetch`. Golden-query parity compares top-k ID overlap. Weaviate
  distances are negated so that higher scores are better on both sides.

## Status

`QdrantSource.shards` returns a single cursor, so `workers` currently has no effect for Qdrant.
Sampling reads only the first batch. The phased plan and known limitations are in the
README's "Roadmap" section.
