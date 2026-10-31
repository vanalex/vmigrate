---
name: new-adapter
description: Add a new vector database Source or Sink adapter to vmigrate (e.g. pgvector, Pinecone or Milvus as a source; Qdrant as a sink). Covers the port contract, registration, filter translation, optional dependencies and tests. Use when asked to support a new database, add a source or sink, or implement the Source/Sink protocol.
---

# Adding a Source or Sink adapter

Read these first; they are the contract and the reference implementations:

- `src/vmigrate/ports/source.py`, `src/vmigrate/ports/sink.py`: the protocols.
- `src/vmigrate/domain/models.py`: `Record`, `Cursor`, `CollectionSpec`, `SchemaPlan`,
  `WriteResult`, `Query`, `Hit`.
- `src/vmigrate/adapters/qdrant/source.py`: reference Source.
- `src/vmigrate/adapters/weaviate/`: reference Sink (`sink.py`, `schema.py`,
  `capabilities.py`, `filters.py`).
- `src/vmigrate/adapters/memory.py`: smallest complete Source and Sink, including real sharding.

## Layering rules

- Only files under `src/vmigrate/adapters/<db>/` may import the database's client library.
  Nothing in `domain/`, `ports/` or `app/` changes to support a specific database.
- Convert to and from domain types at the adapter boundary. Client types (UUID objects, geo
  structs, protobuf ids) must not leak out. See `_plain()` in the Weaviate sink.
- The constructor takes keyword arguments only. Every key in the YAML `source:`/`target:` block
  except `type` is passed straight through, with empty values dropped. Also accept an optional
  `client=` argument so tests can inject an in-process or fake client (as `QdrantSource` does).

## Source contract

| Method | Requirements |
|---|---|
| `describe` | Return a `CollectionSpec`: every dense/multi vector as a `VectorSpec` (size, `Distance`, `multivector`), sparse vectors, exact `count`, and payload index types in `indexed_fields`. Map the database's unnamed vector to `DEFAULT_VECTOR` (`""`). |
| `shards(collection, parallelism)` | At most `parallelism` initial `Cursor`s. The `shard` name must be stable across processes, because resume matches saved progress by shard name. Returning one cursor is correct; split only if each shard's range can be resumed. |
| `read(collection, cursor, batch_size)` | Yield `(records, cursor_after_this_batch)`. `cursor.value` must be JSON-serialisable (it's stored in SQLite). The last batch's cursor has `done=True`; an empty collection yields exactly one `([], Cursor(..., done=True))`. Starting from a saved cursor must continue right after that batch. |
| `to Record` | `id = str(native id)`, `source_id` = native id (int or str). Put dense vectors in `vectors`, multivectors (list of lists) in `multivectors`, sparse ones in `sparse`, and the raw payload dict in `payload`. Don't rename or coerce here; the transform chain does that. |
| `fetch(collection, source_ids)` | Look up by *source* id (strings; convert numeric ids back). Used by validation. |
| `search(collection, query)` | Translate `query.filter` (domain AST in `domain/filters.py`) with a `<db>/filters.py` module. Higher `Hit.score` = better. |

## Sink contract

| Method | Requirements |
|---|---|
| `check(plan)` | Return warnings for features the server/version can't handle (see `weaviate/capabilities.py`). Also warn if the target already exists. |
| `ensure_collection(plan)` | Create the target from the `SchemaPlan` if missing. It's called on every run and must be safe to repeat. Map `PropertyType` and `Distance` in a `schema.py`. |
| `write(collection, records)` | **Upsert by `Record.id`**, which is already a UUID string from `IdMapper`. Re-runs and crash replays depend on this. Return per-record errors in `WriteResult.failures`; raise only when the whole batch failed, so the engine's retry handles it. |
| `count`, `fetch(collection, ids)` | `fetch` takes *target* ids and returns `Record`s with plain Python payload values, so `payload_diff` compares like with like. |
| `search` | Same score direction as sources (negate distances). |

Adapters must be thread-safe: the engine calls `read` and `write` from several worker threads.

## Registration (both places)

1. `pyproject.toml` entry point:
   ```toml
   [project.entry-points."vmigrate.sinks"]      # or "vmigrate.sources"
   mydb = "vmigrate.adapters.mydb.sink:MyDbSink"
   ```
2. `_BUILTIN` in `src/vmigrate/infra/registry.py`, so it works without reinstalling.
3. The client library as an optional extra under `[project.optional-dependencies]` (a `mydb`
   extra, and add it to `all`), plus the `dev` dependency group. Then run `uv sync`.
4. Add an `adapters/mydb/__init__.py` exporting the class.

Third-party adapters only need step 1, in their own package.

## Tests

- **Unit tests:** `tests/test_<db>_<source|sink>.py` using an in-process or fake client. Cover:
  record conversion (named, unnamed, multi and sparse vectors; integer and UUID ids), `describe`
  mapping, the empty-collection `done=True` batch, resuming from a mid-collection cursor, and
  filter translation for every AST node.
- **Engine tests with the adapter:** swap it into `build(config, source=..., sink=...)` and
  check that a re-run is idempotent (count unchanged) and that resuming continues from
  checkpoints. Copy the patterns in `tests/test_engine.py`.
- **Integration test:** if the database runs in Docker, add a service to `docker-compose.yml`
  (pinned version) and a `@pytest.mark.integration` test. Run it with the `integration-test`
  skill.

## Finish

- Add the mapping rules and quirks to the README's mapping table, and a line under the Extending
  section if the setup is unusual.
- `uv run ruff check . && uv run pytest -q` must pass.
- Run `vmigrate plan` with the new adapter to check that the inferred schema and warnings make
  sense.
