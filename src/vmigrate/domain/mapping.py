"""User-declared mapping from one source collection to one target collection."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

from vmigrate.domain.models import DEFAULT_VECTOR, PropertyType

DEFAULT_TARGET_VECTOR = "default"
# Fixed namespace so integer ids always map to the same UUID across runs (idempotent upserts).
DEFAULT_UUID_NAMESPACE = uuid.UUID("6f1c2f3e-6a8b-4d55-9a3c-2b0e7c1d9f10")


class SparsePolicy(str, Enum):
    DROP = "drop"
    JSON_PROPERTY = "json_property"
    FAIL = "fail"


@dataclass
class CollectionMapping:
    source: str
    target: str
    # source vector name -> target named vector
    vectors: dict[str, str] = field(default_factory=dict)
    sparse: SparsePolicy = SparsePolicy.DROP
    keep_source_id_as: str | None = "source_id"
    uuid_namespace: uuid.UUID = DEFAULT_UUID_NAMESPACE
    # source payload key -> target property name (top level only)
    rename: dict[str, str] = field(default_factory=dict)
    # target property name -> forced type
    property_types: dict[str, PropertyType] = field(default_factory=dict)
    # "module:function" transforms, run after the built-in ones
    hooks: list[str] = field(default_factory=list)

    def target_vector(self, source_name: str) -> str:
        if source_name in self.vectors:
            return self.vectors[source_name]
        return DEFAULT_TARGET_VECTOR if source_name == DEFAULT_VECTOR else source_name
