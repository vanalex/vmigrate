from __future__ import annotations

import random

import pytest

from vmigrate.adapters.memory import MemorySink, MemorySource
from vmigrate.bootstrap import build
from vmigrate.domain.models import CollectionSpec, Distance, Record, SparseVectorSpec, VectorSpec
from vmigrate.infra.config import MigrationConfig

DIM = 8


def make_records(n: int, seed: int = 7) -> list[Record]:
    rng = random.Random(seed)
    return [
        Record(
            id=str(i),
            source_id=i,
            vectors={"": [rng.uniform(-1, 1) for _ in range(DIM)]},
            payload={
                "title": f"doc {i}",
                "user-id": i % 10,
                "score": i / 10,
                "tags": ["a", "b"] if i % 2 else ["c"],
                "meta": {"lang": "en", "pages": i},
                "location": {"lat": 40.4, "lon": -3.7},
                "id": f"ext-{i}",
            },
        )
        for i in range(n)
    ]


def make_spec(name: str = "docs", count: int = 0, sparse: bool = False) -> CollectionSpec:
    return CollectionSpec(
        name=name,
        vectors=[VectorSpec("", DIM, Distance.COSINE)],
        sparse_vectors=[SparseVectorSpec("bm25")] if sparse else [],
        count=count,
        indexed_fields={"score": "float", "user-id": "integer"},
    )


@pytest.fixture
def records() -> list[Record]:
    return make_records(250)


@pytest.fixture
def source(records) -> MemorySource:
    return MemorySource({"docs": (make_spec(count=len(records)), records)})


@pytest.fixture
def sink() -> MemorySink:
    return MemorySink()


@pytest.fixture
def config(tmp_path) -> MigrationConfig:
    return MigrationConfig.model_validate(
        {
            "source": {"type": "memory"},
            "target": {"type": "memory"},
            "defaults": {"batch_size": 40, "workers": 3, "max_retries": 2},
            "state": {
                "checkpoint_path": str(tmp_path / "state.db"),
                "deadletter_dir": str(tmp_path / "deadletter"),
            },
            "collections": [
                {
                    "source": "docs",
                    "target": "docs",
                    "rename": {"user-id": "userId"},
                    "ids": {"keep_source_id_as": "qdrant_id"},
                }
            ],
        }
    )


@pytest.fixture
def container(config, source, sink):
    c = build(config, source=source, sink=sink)
    yield c
    c.close()
