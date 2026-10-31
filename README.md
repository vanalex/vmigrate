# vmigrate

Pluggable vector database migration tool. First pair: **Qdrant → Weaviate**.

- Idempotent and resumable: deterministic UUIDs + upserts, SQLite checkpoints per shard
- Declarative YAML mapping with schema inference from sampled points
- Built-in validation: counts, record fidelity, search parity on golden queries
- New databases = new adapters, discovered via Python entry points

## Architecture (ports & adapters)

```
1. Interface       cli/, api.py                 parse input, format output
2. Application     app/                         use cases + pipeline engine
3. Domain          domain/                      pure logic: models, mapping, transforms, planner
4. Ports           ports/                       Source, Sink, CheckpointStore, DeadLetterSink, Metrics
5. Adapters        adapters/                    qdrant, weaviate, memory, sqlite, jsonl, prometheus
6. Infrastructure  infra/                       config, registry, retry, concurrency, logging
                   bootstrap.py                 composition root (the only place adapters are chosen)
```

Dependencies point inward: `domain` imports nothing else; `app` imports `domain` + `ports`;
only `adapters/` import database clients.

Pipeline: `Source.read` (per shard) → transform chain (rename → coerce → id map → vector
route → user hooks) → `Sink.write` → checkpoint commit. Failed records are retried, then
dead-lettered (or abort the run with `on_error: fail`).

## Quickstart

```bash
uv sync
docker compose up -d                          # local Qdrant + Weaviate
cp migrate.example.yaml migrate.yaml          # edit collections

uv run vmigrate plan -c migrate.yaml          # inferred schema, warnings, gaps (no writes)
uv run vmigrate run -c migrate.yaml           # migrate
uv run vmigrate status -c migrate.yaml [RUN]  # runs / per-shard progress
uv run vmigrate run -c migrate.yaml --resume RUN_ID
uv run vmigrate validate -c migrate.yaml --golden queries.jsonl
```

Golden queries (JSONL), run against both sides and compared by top-k overlap:

```json
{"vector": [0.1, 0.2, 0.3], "vector_name": "", "limit": 10, "filter": {"match": {"field": "lang", "value": "en"}}}
```

## Mapping rules

| Qdrant | Weaviate |
|---|---|
| Cosine / Dot / Euclid / Manhattan | `cosine` / `dot` / `l2-squared` / `manhattan` |
| unnamed vector | named vector `default` (configurable) |
| named vectors | named vectors (`self_provided`) |
| multivector | multivector (Weaviate ≥ 1.29) |
| sparse vectors | `drop` (default) / `json_property` / `fail` |
| integer ids | `uuid5(namespace, id)`; original kept in `keep_source_id_as` |
| `{"lat","lon"}` payload | `geoCoordinates` |
| `integer`/`float`/`datetime` payload index | `indexRangeFilters: true` |
| invalid / reserved keys (`id`, `user-id`) | sanitized (`id_`, `user_id`) or `rename:` |

Run Weaviate with `AUTOSCHEMA_ENABLED=false` so writes can't silently add properties the planner
did not declare (fields missing from the sample then land in the dead-letter file instead).

## Extending

Implement `vmigrate.ports.Source` or `Sink` and register it in your package:

```toml
[project.entry-points."vmigrate.sinks"]
mydb = "my_pkg.sink:MyDbSink"
```

Then use `target: {type: mydb, ...}`; extra keys are passed to the constructor.

## Tests

```bash
uv run pytest                    # unit + engine + Qdrant adapter (in-process Qdrant)
docker compose up -d && uv run pytest -m integration   # real Qdrant -> Weaviate
```

## Roadmap

### Known limitations

- **Single read stream.** `QdrantSource.shards` always returns one cursor, so `workers` has no
  effect for Qdrant. Inside a shard, reads and writes take turns: the next batch isn't read until
  the current write finishes.
- **First-batch sampling.** `PlanMigration.sample` reads the first `sample_size` points in ID
  order. With auto-schema off, fields that first appear later in the collection send those
  records to the dead-letter file.
- **Validation blind spots.**
  - Fidelity checks reuse that same first batch.
  - Record counts must match exactly, so records dropped on purpose by a transform hook count
    as a failure.
  - Multivectors aren't compared.
- **Existing target collections are used as-is**, with only a warning. If their schema doesn't
  match the plan, records fail one by one into the dead-letter file.
- **One-shot copy only.** Points deleted or updated in the source during or after a run are not
  brought across.

### Phase 0: Foundation

- [ ] CI (GitHub Actions): ruff, unit tests, and an integration job with Qdrant and Weaviate as
      service containers.
- [ ] Validation fixes:
  - [ ] Compare counts as `target == source - skipped`, using checkpoint stats. Dead-lettered
        records still fail validation.
  - [ ] Compare multivectors.
  - [ ] Report results per check, not just one pass/fail.
- [ ] Check existing collections: compare an existing target's properties and vector configs with
      the plan. Missing properties or incompatible types become gaps that stop the run.
- [ ] `--json` output for `run`, `validate` and `status`, so CI pipelines can gate a cutover on
      the result.

### Phase 1: No quiet data loss

- [ ] Sample from spread-out ID positions across the collection for planning and validation.
      Add `sample: full` to scan the whole collection when complete coverage matters more than
      speed.
- [ ] Optional `schema_evolution: add`: when a write fails because a property is missing, infer
      its type, add it to the target collection, and retry. Off by default.
- [ ] `vmigrate replay RUN_ID`: re-run dead-lettered records through the current mapping, for
      example after fixing a rename or type override.

### Phase 2: Throughput

- [ ] Parallel Qdrant reads. Qdrant can't filter scrolls by ID range, but scroll results come
      back in ID order. So:
  - Pick N-1 split IDs by sampling.
  - Start worker *i* at `offset = split[i]`.
  - Have it stop when it reaches `split[i+1]`.

  The existing per-shard checkpoints handle resume without changes. Collections that use custom
  shard keys can use `shard_key_selector` instead.
- [ ] Overlap reads and writes: a bounded queue between the reader and writer in each shard.
- [ ] Back-pressure: shrink batch size on 429s or timeouts, and grow it again when writes succeed.
- [ ] Benchmark script (1M synthetic points) that records points per second for each change.

### Phase 3: Migrating while the source keeps changing

- [ ] `vmigrate sync --since TS`: re-migrate only points changed since the last run, using an
      `updated_at`-style payload field. Upserts make this safe to repeat.
- [ ] Deletion check: compare source and target ID sets and delete orphaned target objects.
      `--dry-run` only reports them.
- [ ] Cutover runbook: full copy, then catch-up passes, then freeze writes, then a final sync,
      `validate` and switching reads over. Also document writing to both databases during the
      switch as an alternative.

### Phase 4: Index settings and tenancy

- [ ] Copy HNSW settings: Qdrant `m` / `ef_construct` → Weaviate `maxConnections` /
      `efConstruction`.
- [ ] Map Qdrant quantization to Weaviate: scalar → SQ, product → PQ, binary → BQ. Add a planner
      warning where there's no exact match.
- [ ] Multi-tenancy: `tenant_from: <payload field>` creates Weaviate tenants and routes each
      record to its tenant.

### Phase 5: More adapters

- [ ] Shared adapter test suite that every Source and Sink must pass: resume after a crash, the
      empty-collection contract, idempotent upserts.
- [ ] Qdrant as a target, which allows Qdrant → Weaviate → Qdrant round-trip tests.
- [ ] Sources: pgvector, Pinecone, Milvus.

### Throughout: running it in practice

- [ ] Progress bar with an ETA (the total is known from `count`).
- [ ] JSON logs.
- [ ] Prometheus gauges for each shard's progress and for retries.
- [ ] Docker image, and PyPI releases with the optional database extras.

### Order

Phase 0 → 1 → 2 is the critical path: trustworthy validation first, then no quiet data loss,
then speed. Phase 3 is only needed when the source has to stay live during the migration.
Otherwise go to Phase 4.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, checks,
architecture rules and how to add an adapter.

## License

MIT. See [LICENSE](LICENSE).
