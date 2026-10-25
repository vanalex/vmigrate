from __future__ import annotations

import re
from typing import Any

from vmigrate.domain.models import Record

_INVALID = re.compile(r"[^_0-9A-Za-z]")
# Property names Weaviate reserves for itself.
RESERVED = frozenset({"id", "_id", "_additional"})


def safe_name(name: str) -> str:
    """Make a payload key a valid GraphQL/Weaviate property name."""
    out = _INVALID.sub("_", name)
    if not out or out[0].isdigit():
        out = "_" + out
    if out in RESERVED:
        out += "_"
    return out


class FieldRenamer:
    """Applies explicit renames at the top level and sanitizes every key, recursively."""

    def __init__(self, rename: dict[str, str] | None = None):
        self._rename = rename or {}

    def name(self, key: str) -> str:
        return self._rename.get(key) or safe_name(key)

    def __call__(self, record: Record) -> Record:
        record.payload = self._rename_dict(record.payload, top=True)
        return record

    def _rename_dict(self, obj: dict[str, Any], top: bool) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in obj.items():
            new = self.name(key) if top else safe_name(key)
            if new in out:
                raise ValueError(f"payload keys collide after renaming: '{key}' -> '{new}'")
            out[new] = self._rename_value(value)
        return out

    def _rename_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return self._rename_dict(value, top=False)
        if isinstance(value, list):
            return [self._rename_value(v) for v in value]
        return value
