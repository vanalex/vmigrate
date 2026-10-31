from __future__ import annotations

import logging
import uuid
from typing import Any
from urllib.parse import urlparse

import weaviate
from weaviate.classes.data import DataObject
from weaviate.classes.init import Auth
from weaviate.classes.query import MetadataQuery
from weaviate.exceptions import WeaviateInsertManyAllFailedError

from vmigrate.adapters.weaviate.capabilities import check_plan
from vmigrate.adapters.weaviate.filters import to_weaviate
from vmigrate.adapters.weaviate.schema import collection_kwargs
from vmigrate.domain.models import Hit, Query, Record, SchemaPlan, WriteResult

log = logging.getLogger(__name__)


def _plain(value: Any) -> Any:
    """Weaviate client types -> plain Python, so payloads compare against the source."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "latitude") and hasattr(value, "longitude"):
        return {"latitude": value.latitude, "longitude": value.longitude}
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


class WeaviateSink:
    def __init__(
        self,
        url: str = "http://localhost:8080",
        grpc_port: int = 50051,
        grpc_host: str | None = None,
        grpc_secure: bool | None = None,
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        u = urlparse(url)
        secure = u.scheme == "https"
        self._client = weaviate.connect_to_custom(
            http_host=u.hostname or "localhost",
            http_port=u.port or (443 if secure else 80),
            http_secure=secure,
            grpc_host=grpc_host or u.hostname or "localhost",
            grpc_port=grpc_port,
            grpc_secure=secure if grpc_secure is None else grpc_secure,
            headers=headers,
            auth_credentials=Auth.api_key(api_key) if api_key else None,
        )

    def check(self, plan: SchemaPlan) -> list[str]:
        warnings = check_plan(plan, self._client.get_meta()["version"])
        if self._client.collections.exists(plan.target):
            warnings.append(
                f"collection '{plan.target}' already exists; its schema is reused as is"
            )
        return warnings

    def ensure_collection(self, plan: SchemaPlan) -> None:
        if self._client.collections.exists(plan.target):
            return
        self._client.collections.create(**collection_kwargs(plan))
        log.info("created collection %s", plan.target)

    def write(self, collection: str, records: list[Record]) -> WriteResult:
        objects = [
            DataObject(
                properties=r.payload,
                uuid=r.id,
                vector={**r.vectors, **r.multivectors} or None,
            )
            for r in records
        ]
        # insert_many goes through gRPC batch, which upserts by uuid -> reruns are idempotent.
        try:
            result = self._client.collections.use(collection).data.insert_many(objects)
        except WeaviateInsertManyAllFailedError as exc:
            # Raised instead of a result when every object fails (e.g. retrying only the bad
            # records). These are per-record errors, not a batch error: report them as such so
            # the engine dead-letters them. The client keeps only the distinct messages.
            return WriteResult(written=0, failures=[(r, str(exc)) for r in records])
        failures = [(records[i], err.message) for i, err in result.errors.items()]
        return WriteResult(written=len(records) - len(failures), failures=failures)

    def count(self, collection: str) -> int:
        agg = self._client.collections.use(collection).aggregate.over_all(total_count=True)
        return agg.total_count or 0

    def fetch(self, collection: str, ids: list[str]) -> list[Record]:
        if not ids:
            return []
        response = self._client.collections.use(collection).query.fetch_objects_by_ids(
            ids, limit=len(ids), include_vector=True
        )
        records = []
        for obj in response.objects:
            vectors, multivectors = {}, {}
            for name, vec in (obj.vector or {}).items():
                if vec and isinstance(vec[0], list):
                    multivectors[name] = vec
                else:
                    vectors[name] = vec
            records.append(
                Record(
                    id=str(obj.uuid),
                    source_id=str(obj.uuid),
                    vectors=vectors,
                    multivectors=multivectors,
                    payload=_plain(dict(obj.properties)),
                )
            )
        return records

    def search(self, collection: str, query: Query) -> list[Hit]:
        response = self._client.collections.use(collection).query.near_vector(
            near_vector=query.vector,
            target_vector=query.vector_name or None,
            limit=query.limit,
            filters=to_weaviate(query.filter) if query.filter else None,
            return_metadata=MetadataQuery(distance=True),
        )
        # Weaviate returns distance (lower is better); negate so higher is better like Qdrant.
        return [Hit(id=str(o.uuid), score=-(o.metadata.distance or 0.0)) for o in response.objects]

    def close(self) -> None:
        self._client.close()
