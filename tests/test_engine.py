import json

import pytest

from vmigrate.adapters.memory import MemorySink
from vmigrate.app import MigrationError
from vmigrate.bootstrap import build
from vmigrate.domain.models import WriteResult


def test_run_migrates_everything(container, config, sink, records):
    report = container.run.execute(config.mappings(), config.fingerprint())

    assert report.status == "completed"
    stats = report.collections[0].stats
    assert (stats.read, stats.written, stats.failed) == (len(records), len(records), 0)
    stored = sink.data["Docs"]
    assert len(stored) == len(records)
    sample = next(iter(stored.values()))
    assert "userId" in sample.payload and "user-id" not in sample.payload
    assert sample.payload["location"] == {"latitude": 40.4, "longitude": -3.7}
    assert set(sample.vectors) == {"default"}


def test_rerun_is_idempotent(container, config, sink, records):
    container.run.execute(config.mappings(), config.fingerprint())
    container.run.execute(config.mappings(), config.fingerprint())
    assert len(sink.data["Docs"]) == len(records)


class CrashingSink(MemorySink):
    """Raises on every write after `crash_after` successful batches."""

    def __init__(self, crash_after: int):
        super().__init__()
        self.crash_after = crash_after
        self.batches = 0

    def write(self, collection, records):
        if self.batches >= self.crash_after:
            raise ConnectionError("target went away")
        self.batches += 1
        return super().write(collection, records)


def test_resume_continues_from_checkpoints(config, source, records):
    crashing = CrashingSink(crash_after=3)
    with build(config, source=source, sink=crashing) as c:
        c.run._engine._sleep = lambda _: None
        with pytest.raises(ConnectionError):
            c.run.execute(config.mappings(), config.fingerprint(), run_id="r1")
        assert c.checkpoints.get_run("r1").status == "failed"

    crashing.crash_after = 10**9
    before = crashing.batches
    with build(config, source=source, sink=crashing) as c:
        report = c.resume.execute(config.mappings(), config.fingerprint(), "r1")

    assert report.status == "completed"
    assert len(crashing.data["Docs"]) == len(records)
    total_batches = -(-len(records) // config.defaults.batch_size) + 2  # 3 shards -> up to +2
    # Resumed run must not redo the batches committed before the crash.
    assert crashing.batches - before <= total_batches - 3
    assert report.collections[0].stats.read == len(records)


def test_resume_refuses_changed_config(container, config):
    container.run.execute(config.mappings(), config.fingerprint(), run_id="r2")
    with pytest.raises(MigrationError, match="different collection config"):
        container.resume.execute(config.mappings(), "other-hash", "r2")


class RejectingSink(MemorySink):
    """Rejects records whose source id is divisible by 50."""

    def write(self, collection, records):
        ok = [r for r in records if int(r.payload["qdrant_id"]) % 50]
        bad = [(r, "invalid") for r in records if not int(r.payload["qdrant_id"]) % 50]
        super().write(collection, ok)
        return WriteResult(written=len(ok), failures=bad)


def test_failed_records_go_to_deadletter(config, source, records, tmp_path):
    with build(config, source=source, sink=RejectingSink()) as c:
        report = c.run.execute(config.mappings(), config.fingerprint(), run_id="r3")

    stats = report.collections[0].stats
    assert stats.failed == 5 and stats.written == len(records) - 5
    lines = (tmp_path / "deadletter" / "r3" / "docs.jsonl").read_text().splitlines()
    assert len(lines) == 5
    assert json.loads(lines[0])["error"] == "invalid"


def test_on_error_fail_aborts(config, source):
    config.defaults.on_error = "fail"
    with (
        build(config, source=source, sink=RejectingSink()) as c,
        pytest.raises(MigrationError, match="failed"),
    ):
        c.run.execute(config.mappings(), config.fingerprint())


def test_validate_passes_after_run(container, config, records):
    from vmigrate.domain.models import Query

    container.run.execute(config.mappings(), config.fingerprint())
    golden = [Query(vector=r.vectors[""], limit=5) for r in records[:10]]
    result = container.validate.execute(config.mappings()[0], golden)

    assert result.source_count == result.target_count == len(records)
    assert result.fidelity.ok, result.fidelity
    assert result.parity.queries == 10 and result.parity.min_overlap == 1.0
    assert result.passed
