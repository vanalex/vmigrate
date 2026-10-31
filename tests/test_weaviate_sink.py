"""WeaviateSink.write error handling, with a fake client (no server needed)."""

from types import SimpleNamespace

import pytest
from weaviate.exceptions import WeaviateInsertManyAllFailedError

from vmigrate.adapters.weaviate.sink import WeaviateSink
from vmigrate.domain.models import Record


class FakeData:
    def __init__(self, fail: set[int], all_failed: bool = False):
        self.fail = fail
        self.all_failed = all_failed

    def insert_many(self, objects):
        if self.all_failed:
            raise WeaviateInsertManyAllFailedError("Here is the set of all errors: no such prop")
        errors = {i: SimpleNamespace(message=f"bad {i}") for i in self.fail if i < len(objects)}
        return SimpleNamespace(errors=errors)


def make_sink(data: FakeData) -> WeaviateSink:
    sink = WeaviateSink.__new__(WeaviateSink)  # skip __init__: it connects to a server
    collection = SimpleNamespace(data=data)
    sink._client = SimpleNamespace(collections=SimpleNamespace(use=lambda name: collection))
    return sink


def records(n: int) -> list[Record]:
    return [
        Record(id=f"00000000-0000-0000-0000-{i:012d}", source_id=i, payload={"n": i})
        for i in range(n)
    ]


def test_partial_failures_are_reported_per_record():
    recs = records(4)
    result = make_sink(FakeData(fail={1, 3})).write("C", recs)
    assert result.written == 2
    assert [(r.source_id, msg) for r, msg in result.failures] == [(1, "bad 1"), (3, "bad 3")]


def test_all_failed_batch_returns_failures_instead_of_raising():
    recs = records(3)
    result = make_sink(FakeData(fail=set(), all_failed=True)).write("C", recs)
    assert result.written == 0
    assert [r.source_id for r, _ in result.failures] == [0, 1, 2]
    assert all("no such prop" in msg for _, msg in result.failures)


def test_other_errors_still_raise():
    class Broken:
        def insert_many(self, objects):
            raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        make_sink(Broken()).write("C", records(1))
