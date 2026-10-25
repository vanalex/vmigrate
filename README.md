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

## Roadmap / TODOs

- Parallel Qdrant scroll by id range (`QdrantSource.shards`)
- Random sampling across the collection for schema inference and validation
- Carry HNSW params and quantization over to Weaviate
- Native Weaviate multi-tenancy from a payload field
- Dead-letter replay command
