---
name: trial-migration
description: End-to-end smoke test of the vmigrate CLI on realistic data. Seeds local Qdrant with a synthetic collection full of edge cases (named, multi and sparse vectors, reserved keys, geo, dates, fields that only appear late), then runs plan, run, status and validate, and inspects the dead-letter output. Use to check a change against the real CLI, reproduce a migration bug, measure throughput, or demo the tool.
---

# Trial migration

Needs the Docker stack. Start it and wait for readiness as in the `integration-test` skill
(steps 1–2). All paths below are relative to the repo root. Scratch files go in `.vmigrate/`,
which is gitignored state.

## 1. Seed Qdrant

```bash
uv run python .claude/skills/trial-migration/scripts/seed_qdrant.py \
  --collection trial_docs --points 1000 --golden .vmigrate/trial/golden.jsonl
```

This recreates `trial_docs` with:

- named dense vector `text` (dim 8, cosine), multivector `colbert`, and sparse vector `bm25`
- integer ids `1..N`
- payload: `title`, `lang`, `id` (reserved in Weaviate), `user-id` (invalid name), `score`
  (float with a range index), `created_at` (RFC 3339), `tags` (list), `meta` (nested object),
  `location` (lat/lon)
- `late_note` only on the last 50 points. Sampling reads the first `sample_size` points in ID
  order, so the planner never sees it.

It also writes golden queries for `validate`, some with a `lang` filter. Flags:
`--points`, `--late 0` (no late field), `--no-sparse`, `--no-multivector`, `--dim`, `--seed`.

## 2. Run the CLI

```bash
cp .claude/skills/trial-migration/migrate.trial.yaml .vmigrate/trial/migrate.yaml
C=.vmigrate/trial/migrate.yaml

uv run vmigrate plan -c $C            # exit code 2 = blocking gaps
uv run vmigrate run -c $C             # prints the run id; exit code 1 = migration failed
uv run vmigrate status -c $C          # recent runs
uv run vmigrate status -c $C <RUN_ID> # per-shard progress
uv run vmigrate validate -c $C --golden .vmigrate/trial/golden.jsonl   # exit code 1 = FAIL
```

Add `--json` to `plan`, `run` and `validate` for machine-readable output.

The trial config keeps its state in `.vmigrate/trial/`, separate from any real
`migrate.yaml` state. Re-running `run` is safe (upserts by deterministic UUID). To start from
scratch, delete the target and the state:

```bash
curl -s -X DELETE localhost:8080/v1/schema/TrialDocs; rm -rf .vmigrate/trial/state.db .vmigrate/trial/deadletter
```

## 3. What you should see with the defaults

- **plan:** a warning that sparse vector `bm25` is dropped. `id` and `user-id` become
  `id_` / `user_id` (or whatever `rename:` says). `score` gets `indexRangeFilters`. `location`
  becomes `geo`. `created_at` is overridden to `date`. No gaps.
- **run:** `read=1000`, `written=950`, `failed=50`. The 50 records with `late_note` are rejected
  because the property isn't in the schema and auto-schema is off.
- **dead letter:** `.vmigrate/trial/deadletter/<RUN_ID>/trial_docs.jsonl` holds 50 lines. Each
  has an `error` that mentions `late_note` and the full transformed `record`:
  ```bash
  wc -l .vmigrate/trial/deadletter/*/trial_docs.jsonl
  head -1 .vmigrate/trial/deadletter/*/trial_docs.jsonl | python -m json.tool | head -20
  ```
- **validate:** FAIL. Count is `1000 -> 950`. Fidelity samples up to 1000 records (the
  `Validate` default, independent of `sample_size`), so with 1000 points it reports
  `missing=50`. Parity drops too (some top-10 results are among the missing records).

With `--late 0` everything should pass: `written=1000 failed=0`, then validate PASS with count
`1000 -> 1000`, no fidelity diffs, and parity `mean@k=1.000`. When a change (e.g. better
sampling, schema evolution or dead-letter replay) is supposed to fix the late-field case, the
default seed is the check: it should end with `failed=0` and validate PASS.

Noise you can ignore: a qdrant-client vs. server version `UserWarning`, and the Weaviate
client logging each failed batch at ERROR level with the full objects (very long lines). Use
`--log-level WARNING` and filter long lines when reading the output.

## 4. Throughput

For rough numbers, seed more points and time the run:

```bash
uv run python .claude/skills/trial-migration/scripts/seed_qdrant.py --points 100000 --late 0 --golden .vmigrate/trial/golden.jsonl
time uv run vmigrate --log-level WARNING run -c .vmigrate/trial/migrate.yaml
```

Report points/second = written ÷ wall-clock time. Note `batch_size` and `workers` from the
config. Seeding 100k points takes a while; it isn't part of the measurement.

## Reporting

Summarise what each step printed, highlight anything that differs from section 3, and include
the run id. Clean up only if the user asks.
