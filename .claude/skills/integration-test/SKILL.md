---
name: integration-test
description: Run vmigrate's integration tests against real Qdrant and Weaviate in Docker. Starts the docker compose stack, waits until both services are ready, runs `pytest -m integration`, and reports results. Use when asked to run integration tests, test against real databases, or check that a change to the Qdrant/Weaviate adapters, the engine, or validation works end to end.
---

# Integration tests (real Qdrant + Weaviate)

Unit tests (`uv run pytest`) use the in-memory adapters and never touch Docker. Integration
tests are marked `@pytest.mark.integration`. pytest's `addopts` (`-m 'not integration'`) skips
them unless you pass `-m integration` explicitly.

## 1. Start the stack

```bash
docker info >/dev/null 2>&1 || echo "Docker is not running"
docker compose ps --status running --services   # already up? then skip `up`
docker compose up -d
```

If Docker isn't running, stop and ask the user to start it. Don't try to install or start the
Docker daemon yourself.

`docker-compose.yml` pins Qdrant `v1.13.4` (6333 HTTP, 6334 gRPC) and Weaviate `1.30.0` (8080
HTTP, 50051 gRPC) with `AUTOSCHEMA_ENABLED=false`. If a port is taken by something else, report
it rather than changing the compose file.

## 2. Wait until both services are ready

The containers report "running" before the databases accept requests. Poll both readiness
endpoints (up to ~60 s):

```bash
for i in $(seq 1 30); do
  curl -fsS localhost:6333/readyz >/dev/null 2>&1 \
    && curl -fsS localhost:8080/v1/.well-known/ready >/dev/null 2>&1 \
    && echo ready && break
  sleep 2
done
```

If it never prints `ready`, check `docker compose logs --tail 50 qdrant weaviate` before
running any tests.

## 3. Run the tests

```bash
uv run pytest -m integration -v                      # all integration tests
uv run pytest -m integration tests/test_integration.py::test_qdrant_to_weaviate -v
```

Run the unit tests too (`uv run pytest -q`). A change that breaks them usually explains an
integration failure faster.

## 4. When a test fails

- **Connection refused or timeouts:** the stack isn't ready. Go back to step 2.
- **`collection '...' already exists`, or wrong counts:** a previous run was interrupted before
  its cleanup ran. Tests use random `it_<hex>` / `It<hex>` names, so leftovers are harmless,
  but they can be listed and removed:
  ```bash
  curl -s localhost:6333/collections | python -m json.tool
  curl -s localhost:8080/v1/schema | python -c "import json,sys; print([c['class'] for c in json.load(sys.stdin)['classes']])"
  ```
- **Records failing with "no such prop":** this is auto-schema off doing its job. A payload
  field wasn't in the planner's sample. Fix the planner or the test data; don't enable
  auto-schema.
- **Weaviate feature errors (e.g. multivector):** check `adapters/weaviate/capabilities.py`
  against the pinned Weaviate version.

## 5. Tear down

Leave the stack running unless the user asks otherwise. It's reused across runs.

```bash
docker compose down        # stop; the containers' data is discarded
```

## Reporting

Give the pass/fail counts and, for each failure, the assertion or error plus your diagnosis.
State plainly if tests were skipped or the stack couldn't start.
