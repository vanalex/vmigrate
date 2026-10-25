from datetime import UTC, datetime

import pytest

from vmigrate.adapters.checkpoint import SqliteCheckpointStore
from vmigrate.domain.filters import And, Match, Range, parse_filter, rename_fields
from vmigrate.domain.models import Cursor, RunStats
from vmigrate.domain.parity import overlap_at_k, payload_diff
from vmigrate.infra.config import load_config
from vmigrate.infra.retry import retry


def test_checkpoint_commit_accumulates_and_resumes(tmp_path):
    store = SqliteCheckpointStore(tmp_path / "s.db")
    store.start_run("r", "h")
    store.commit("r", "docs", Cursor("all", "abc"), RunStats(read=10, written=9, failed=1))
    store.commit("r", "docs", Cursor("all", None, done=True), RunStats(read=5, written=5))
    progress = store.load("r", "docs")["all"]
    assert progress.cursor == Cursor("all", None, True)
    assert progress.stats == RunStats(read=15, written=14, failed=1, skipped=0)
    store.finish_run("r", "completed")
    assert store.get_run("r").status == "completed"


def test_retry_backs_off_then_succeeds():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError
        return "ok"

    assert retry(flaky, attempts=3, sleep=lambda _: None) == "ok"
    with pytest.raises(ConnectionError):
        retry(lambda: (_ for _ in ()).throw(ConnectionError()), attempts=2, sleep=lambda _: None)


def test_filter_parse_and_rename():
    expr = parse_filter({"and": [{"match": {"field": "user-id", "value": 1}},
                                 {"range": {"field": "score", "gte": 0.5}}]})
    assert expr == And((Match("user-id", 1), Range("score", gte=0.5)))
    renamed = rename_fields(expr, lambda f: f.replace("-", "_"))
    assert renamed.items[0] == Match("user_id", 1)


def test_parity_helpers():
    assert overlap_at_k(["a", "b", "c"], ["c", "a", "x"], 3) == pytest.approx(2 / 3)
    expected = {"d": "2024-01-01T00:00:00+00:00", "x": 1.0, "o": {"k": [1, 2]}}
    actual = {"d": datetime(2024, 1, 1, tzinfo=UTC), "x": 1.0000000001, "o": {"k": [1, 3]}}
    assert payload_diff(expected, actual) == ["o.k[1]: 2 != 3"]


def test_config_env_interpolation(tmp_path, monkeypatch):
    monkeypatch.setenv("QKEY", "secret")
    path = tmp_path / "m.yaml"
    path.write_text(
        "source: {type: qdrant, url: 'http://q:6333', api_key: '${QKEY}'}\n"
        "target: {type: weaviate, url: 'http://w:8080', api_key: '${WKEY:-}'}\n"
        "collections: [{source: docs, target: Docs}]\n"
    )
    cfg = load_config(path)
    assert cfg.source.options() == {"url": "http://q:6333", "api_key": "secret"}
    assert cfg.target.options() == {"url": "http://w:8080"}  # empty values dropped
    assert cfg.mappings()[0].target == "Docs"
    with pytest.raises(ValueError, match="not in config"):
        cfg.mappings(["nope"])


def test_example_config_is_valid(monkeypatch):
    from pathlib import Path

    cfg = load_config(Path(__file__).parent.parent / "migrate.example.yaml")
    assert cfg.collections[0].rename == {"user-id": "userId"}
