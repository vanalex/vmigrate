# Contributing to vmigrate

Thanks for helping! vmigrate is early: Qdrant → Weaviate works, and much of what's left is
listed in the [Roadmap](README.md#roadmap). Please follow the
[code of conduct](CODE_OF_CONDUCT.md). Issues and pull requests are welcome, especially
for roadmap items and new database adapters.

## Setup

You need [uv](https://docs.astral.sh/uv/) and, for integration tests, Docker.

```bash
git clone git@github.com:vanalex/vmigrate.git
cd vmigrate
uv sync                    # Python 3.12 (see .python-version), runtime + dev dependencies
```

## Checks

CI runs all of these on every pull request, and they must pass before merging into `main`.
Run them locally before opening a pull request:

```bash
uv run ruff check .        # lint (line length 100)
uv run ruff format .       # format
uv run pytest -q           # unit tests: in-memory adapters, no Docker needed

docker compose up -d       # local Qdrant + Weaviate
uv run pytest -m integration
```

Integration tests are skipped unless you pass `-m integration`. Run them whenever you touch
an adapter, the engine or validation.

To try the CLI end to end on synthetic data full of edge cases, seed Qdrant and run a trial
migration as described in
[.claude/skills/trial-migration/SKILL.md](.claude/skills/trial-migration/SKILL.md).

## Architecture rules

The code uses a ports-and-adapters layout (see
[Architecture](README.md#architecture-ports--adapters)). Reviews check these rules:

- `domain/` is pure logic. It doesn't import database clients or any other vmigrate layer.
- `app/` depends only on `domain/`, `ports/` and `infra/` helpers.
- Only `adapters/` import database client libraries.
- Concrete adapters are chosen only in `bootstrap.py`.

The pipeline relies on a few rules that are easy to break without noticing:

- **Re-runs must stay safe.** Sinks upsert by `Record.id`, which comes from a deterministic
  UUID mapping, and checkpoints are committed only after a write succeeds.
- **Sinks report failures per record.** `Sink.write` returns them in `WriteResult.failures`
  and raises only when the whole batch failed, so the engine can retry and dead-letter.
- **The Weaviate test stack runs with `AUTOSCHEMA_ENABLED=false`.** Don't turn it on to make a
  test pass; the planner owns the schema.

## Adding a database adapter

1. Implement the `Source` or `Sink` protocol (`src/vmigrate/ports/`) under
   `src/vmigrate/adapters/<db>/`. The Qdrant source, Weaviate sink and in-memory adapters are
   the reference implementations.
2. Register it as an entry point in `pyproject.toml` and in `_BUILTIN` in
   `src/vmigrate/infra/registry.py`.
3. Add the client library as an optional extra (and to `all` and the `dev` group).
4. Add unit tests with an in-process or fake client and, if the database runs in Docker, a
   pinned service in `docker-compose.yml` plus a `@pytest.mark.integration` test.
5. Add its mapping rules to the README.

The full checklist, including the rules each protocol method must follow, is in
[.claude/skills/new-adapter/SKILL.md](.claude/skills/new-adapter/SKILL.md).

## Pull requests

- Keep each PR to one change. Open an issue first for large changes or new adapters.
- Add or update tests for behaviour changes; bug fixes should include a test that fails
  without the fix.
- Update the README when you change user-facing behaviour, config keys or mapping rules, and
  tick off roadmap items you complete.
- Describe how you tested the change (unit, integration, trial migration).

## Using Claude Code

The repo includes project guidance for [Claude Code](https://claude.com/claude-code) in
`.claude/`: `CLAUDE.md` with architecture notes, and skills for running integration tests,
trial migrations and adding adapters. You don't need Claude Code to contribute; the skill
files are plain Markdown and work as documentation too.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
