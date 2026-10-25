from __future__ import annotations

import uuid

from vmigrate.domain.models import Record


def map_id(source_id: str | int, namespace: uuid.UUID) -> str:
    """UUIDs pass through unchanged; anything else maps to a deterministic uuid5."""
    raw = str(source_id)
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return str(uuid.uuid5(namespace, raw))


class IdMapper:
    def __init__(self, namespace: uuid.UUID, keep_source_id_as: str | None):
        self._namespace = namespace
        self._keep_as = keep_source_id_as

    def __call__(self, record: Record) -> Record:
        record.id = map_id(record.source_id, self._namespace)
        if self._keep_as:
            record.payload[self._keep_as] = str(record.source_id)
        return record
