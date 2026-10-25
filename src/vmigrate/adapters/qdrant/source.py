from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from qdrant_client import QdrantClient, models

from vmigrate.adapters.qdrant.filters import to_qdrant
from vmigrate.domain.models import (
    DEFAULT_VECTOR,
    CollectionSpec,
    Cursor,
    Distance,
    Hit,
    Query,
    Record,
    SparseVector,
    SparseVectorSpec,
    VectorSpec,
)

_DISTANCE = {
    models.Distance.COSINE: Distance.COSINE,
    models.Distance.DOT: Distance.DOT,
    models.Distance.EUCLID: Distance.EUCLID,
    models.Distance.MANHATTAN: Distance.MANHATTAN,
}


def _parse_id(source_id: str) -> int | str:
    return int(source_id) if source_id.isdigit() else source_id


def to_record(point: models.Record) -> Record:
    vectors: dict[str, list[float]] = {}
    multivectors: dict[str, list[list[float]]] = {}
    sparse: dict[str, SparseVector] = {}

    raw = point.vector
    items: list[tuple[str, Any]]
    if raw is None:
        items = []
    elif isinstance(raw, dict):
        items = list(raw.items())
    else:
        items = [(DEFAULT_VECTOR, raw)]

    for name, value in items:
        if isinstance(value, models.SparseVector):
            sparse[name] = SparseVector(list(value.indices), list(value.values))
        elif value and isinstance(value[0], list):
            multivectors[name] = value
        else:
            vectors[name] = value

    return Record(
        id=str(point.id),
        source_id=point.id,
        vectors=vectors,
        multivectors=multivectors,
        sparse=sparse,
        payload=dict(point.payload or {}),
    )


class QdrantSource:
    def __init__(
        self,
        url: str = "http://localhost:6333",
        api_key: str | None = None,
        timeout: int = 60,
        prefer_grpc: bool = False,
        client: QdrantClient | None = None,
    ):
        # `client` lets tests and embedders pass e.g. QdrantClient(":memory:").
        self._client = client or QdrantClient(
            url=url, api_key=api_key, timeout=timeout, prefer_grpc=prefer_grpc
        )

    def describe(self, collection: str) -> CollectionSpec:
        info = self._client.get_collection(collection)
        params = info.config.params

        raw = params.vectors
        if raw is None:
            vector_items: list[tuple[str, models.VectorParams]] = []
        elif isinstance(raw, dict):
            vector_items = list(raw.items())
        else:
            vector_items = [(DEFAULT_VECTOR, raw)]

        return CollectionSpec(
            name=collection,
            vectors=[
                VectorSpec(
                    name=name,
                    size=p.size,
                    distance=_DISTANCE[p.distance],
                    multivector=p.multivector_config is not None,
                )
                for name, p in vector_items
            ],
            sparse_vectors=[SparseVectorSpec(n) for n in (params.sparse_vectors or {})],
            count=self.count(collection),
            indexed_fields={
                field: getattr(index.data_type, "value", str(index.data_type))
                for field, index in (info.payload_schema or {}).items()
            },
        )

    def count(self, collection: str) -> int:
        return self._client.count(collection, exact=True).count

    def shards(self, collection: str, parallelism: int) -> list[Cursor]:
        # TODO(M2): split by id range / shard key for parallel scrolls. Scroll pagination is
        # ordered by id, so ranges need a filter per worker; one stream is correct and simple.
        return [Cursor(shard="all")]

    def read(
        self, collection: str, cursor: Cursor, batch_size: int
    ) -> Iterator[tuple[list[Record], Cursor]]:
        offset = cursor.value
        while True:
            points, next_offset = self._client.scroll(
                collection_name=collection,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            if isinstance(next_offset, (int, str)) or next_offset is None:
                resume = next_offset
            else:  # uuid.UUID / grpc PointId
                resume = str(next_offset)
            yield [to_record(p) for p in points], Cursor(cursor.shard, resume, resume is None)
            if resume is None:
                return
            offset = resume

    def fetch(self, collection: str, source_ids: list[str]) -> list[Record]:
        points = self._client.retrieve(
            collection_name=collection,
            ids=[_parse_id(i) for i in source_ids],
            with_payload=True,
            with_vectors=True,
        )
        return [to_record(p) for p in points]

    def search(self, collection: str, query: Query) -> list[Hit]:
        response = self._client.query_points(
            collection_name=collection,
            query=query.vector,
            using=query.vector_name or None,
            limit=query.limit,
            query_filter=to_qdrant(query.filter) if query.filter else None,
            with_payload=False,
        )
        return [Hit(id=str(p.id), score=p.score) for p in response.points]

    def close(self) -> None:
        self._client.close()
