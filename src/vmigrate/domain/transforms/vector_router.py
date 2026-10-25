from __future__ import annotations

from vmigrate.domain.mapping import CollectionMapping, SparsePolicy
from vmigrate.domain.models import Record
from vmigrate.domain.transforms.renamer import safe_name


class SparseVectorUnsupported(ValueError):
    pass


class VectorRouter:
    """Renames vectors to their target names and applies the sparse-vector policy."""

    def __init__(self, mapping: CollectionMapping):
        self._mapping = mapping

    def __call__(self, record: Record) -> Record:
        target = self._mapping.target_vector
        record.vectors = {target(k): v for k, v in record.vectors.items()}
        record.multivectors = {target(k): v for k, v in record.multivectors.items()}

        if record.sparse:
            policy = self._mapping.sparse
            if policy is SparsePolicy.FAIL:
                raise SparseVectorUnsupported(f"point {record.source_id} has sparse vectors")
            if policy is SparsePolicy.JSON_PROPERTY:
                for name, sv in record.sparse.items():
                    key = f"sparse_{safe_name(name) if name else 'default'}"
                    record.payload[key] = {"indices": sv.indices, "values": sv.values}
            record.sparse = {}
        return record
