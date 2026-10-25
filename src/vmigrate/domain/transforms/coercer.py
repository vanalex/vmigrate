from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from vmigrate.domain.models import PropertyType as T
from vmigrate.domain.models import Record

_ELEMENT_OF = {
    T.TEXT_ARRAY: T.TEXT,
    T.INT_ARRAY: T.INT,
    T.NUMBER_ARRAY: T.NUMBER,
    T.BOOLEAN_ARRAY: T.BOOLEAN,
    T.DATE_ARRAY: T.DATE,
    T.UUID_ARRAY: T.UUID,
}


def _to_rfc3339(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC).isoformat()
    return value


def coerce(value: Any, t: T) -> Any:
    if value is None:
        return None
    if t in _ELEMENT_OF:
        items = value if isinstance(value, list) else [value]
        return [coerce(v, _ELEMENT_OF[t]) for v in items if v is not None]
    if t is T.TEXT:
        return value if isinstance(value, str) else json.dumps(value, default=str)
    if t is T.INT:
        return int(value)
    if t is T.NUMBER:
        return float(value)
    if t is T.BOOLEAN:
        return bool(value)
    if t is T.DATE:
        return _to_rfc3339(value)
    if t is T.UUID:
        return str(value)
    return value


def _geo(value: Any) -> Any:
    # Qdrant geo payloads use lat/lon; Weaviate geoCoordinates use latitude/longitude.
    if isinstance(value, dict) and set(value) == {"lat", "lon"}:
        return {"latitude": value["lat"], "longitude": value["lon"]}
    return value


class TypeCoercer:
    """Drops nulls, normalizes geo points and casts values to the planned property types."""

    def __init__(self, types: dict[str, T] | None = None):
        self._types = types or {}

    def __call__(self, record: Record) -> Record:
        payload = {k: _geo(v) for k, v in record.payload.items() if v is not None}
        for name, t in self._types.items():
            if name in payload:
                payload[name] = coerce(payload[name], t)
        record.payload = payload
        return record
