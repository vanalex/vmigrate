"""End-to-end Qdrant -> Weaviate. Needs `docker compose up -d`; run with `pytest -m integration`."""

import uuid

import pytest
from qdrant_client import QdrantClient, models

from vmigrate.adapters.qdrant.source import QdrantSource
from vmigrate.adapters.weaviate.sink import WeaviateSink
from vmigrate.bootstrap import build
from vmigrate.domain.models import Query

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded_qdrant():
    name = f"it_{uuid.uuid4().hex[:8]}"
    client = QdrantClient(url="http://localhost:6333")
    client.create_collection(
        name, vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE)
    )
    client.upsert(
        name,
        points=[
            models.PointStruct(
                id=i,
                vector=[float(i % 7), 1.0, float(i % 3), 0.5],
                payload={"title": f"doc {i}", "n": i, "geo": {"lat": 40.0, "lon": -3.0}},
            )
            for i in range(1, 501)
        ],
    )
    yield client, name
    client.delete_collection(name)


def test_qdrant_to_weaviate(seeded_qdrant, config):
    client, name = seeded_qdrant
    target = "It" + name[3:]
    config.collections[0].source = name
    config.collections[0].target = target
    config.collections[0].rename = {}

    sink = WeaviateSink(url="http://localhost:8080", grpc_port=50051)
    try:
        with build(config, source=QdrantSource(client=client), sink=sink) as c:
            report = c.run.execute(config.mappings(), config.fingerprint())
            assert report.collections[0].stats.written == 500

            golden = [Query([float(i % 7), 1.0, float(i % 3), 0.5], limit=5) for i in range(10)]
            result = c.validate.execute(config.mappings()[0], golden)
            assert result.source_count == result.target_count == 500
            assert result.fidelity.ok, result.fidelity
    finally:
        # Separate client: `build` closed the sink above.
        cleanup = WeaviateSink(url="http://localhost:8080", grpc_port=50051)
        cleanup._client.collections.delete(target)
        cleanup.close()
