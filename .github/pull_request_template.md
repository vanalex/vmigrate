## What and why

<!-- What does this change, and why? Link the issue or roadmap item if there is one. -->

## How it was tested

- [ ] Unit tests (`uv run pytest`)
- [ ] Integration tests (`uv run pytest -m integration`), needed for adapter, engine or validation changes
- [ ] Trial migration (`.claude/skills/trial-migration/SKILL.md`), if the CLI behaviour changed

## Checklist

- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] Bug fixes include a test that fails without the fix
- [ ] README updated for user-facing changes (config keys, mapping rules, CLI), roadmap items ticked
- [ ] Layering rules respected (see CONTRIBUTING.md): only `adapters/` import database clients
