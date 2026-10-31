"""Exercises the real Qdrant adapter against qdrant-client's in-process (local) mode."""

import uuid

import pytest
from qdrant_client import QdrantClient, models

from vmigrate.adapters.memory import MemorySink
from vmigrate.adapters.qdrant.source import QdrantSource
from vmigrate.bootstrap import build
from vmigrate.domain.filters import Match
from vmigrate.domain.models import Distance, Query


@pytest.fixture
def qdrant() -> QdrantClient:
    client = QdrantClient(":memory:")
    client.create_collection(
        "docs",
        vectors_config={
            "dense": models.VectorParams(size=4, distance=models.Distance.EUCLID),
            "colbert": models.VectorParams(
                size=2,
                distance=models.Distance.COSINE,
                multivector_config=models.MultiVectorConfig(
                    comparator=models.MultiVectorComparator.MAX_SIM
                ),
            ),
        },
        sparse_vectors_config={"bm25": models.SparseVectorParams()},
    )
    client.upsert(
        "docs",
        points=[
            models.PointStruct(
                id=i if i % 2 else str(uuid.UUID(int=i)),
                vector={
                    "dense": [float(i), 1.0, 0.0, 0.5],
                    "colbert": [[1.0, 0.0], [0.0, float(i + 1)]],
                    "bm25": models.SparseVector(indices=[i], values=[1.0]),
                },
                payload={"kind": "odd" if i % 2 else "even", "n": i},
            )
            for i in range(25)
        ],
    )
    return client


def test_describe(qdrant):
    spec = QdrantSource(client=qdrant).describe("docs")
    by = {v.name: v for v in spec.vectors}
    assert by["dense"].distance is Distance.EUCLID and by["dense"].size == 4
    assert by["colbert"].multivector
    assert [s.name for s in spec.sparse_vectors] == ["bm25"]
    assert spec.count == 25


def test_read_pages_through_everything_and_resumes(qdrant):
    src = QdrantSource(client=qdrant)
    [cursor] = src.shards("docs", 4)
    batches = list(src.read("docs", cursor, batch_size=10))
    assert [len(b) for b, _ in batches] == [10, 10, 5]
    assert batches[-1][1].done and not batches[0][1].done

    first = batches[0][0][0]
    assert set(first.vectors) == {"dense"}
    assert set(first.multivectors) == {"colbert"}
    assert set(first.sparse) == {"bm25"}

    resumed = list(src.read("docs", batches[0][1], batch_size=10))
    assert sum(len(b) for b, _ in resumed) == 15


def test_fetch_and_search(qdrant):
    src = QdrantSource(client=qdrant)
    assert {str(r.source_id) for r in src.fetch("docs", ["3", str(uuid.UUID(int=4))])} == {
        "3",
        str(uuid.UUID(int=4)),
    }
    hits = src.search("docs", Query([3.0, 1.0, 0.0, 0.5], "dense", 3, Match("kind", "odd")))
    assert hits[0].id == "3" and len(hits) == 3


def test_full_run_from_qdrant(qdrant, config):
    config.collections[0].ids.keep_source_id_as = "qdrant_id"
    config.collections[0].rename = {}
    sink = MemorySink()
    with build(config, source=QdrantSource(client=qdrant), sink=sink) as c:
        plan = c.planner.execute(config.mappings()[0])
        report = c.run.execute(config.mappings(), config.fingerprint())

    assert {v.name for v in plan.vectors} == {"dense", "colbert"}
    assert any("l2-squared" in w for w in plan.warnings)
    assert any("bm25" in w for w in plan.warnings)
    assert report.collections[0].stats.written == 25
    stored = list(sink.data["Docs"].values())
    assert all(uuid.UUID(r.id) for r in stored)  # int ids became uuid5
    assert all(not r.sparse for r in stored)
