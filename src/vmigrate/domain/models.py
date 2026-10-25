"""Canonical data model shared by every adapter. No database imports allowed here."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from vmigrate.domain.filters import FilterExpr

# Name used for a collection's unnamed (single) vector.
DEFAULT_VECTOR = ""


class Distance(str, Enum):
    COSINE = "cosine"
    DOT = "dot"
    EUCLID = "euclid"
    MANHATTAN = "manhattan"


class PropertyType(str, Enum):
    TEXT = "text"
    INT = "int"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    UUID = "uuid"
    GEO = "geo"
    OBJECT = "object"
    TEXT_ARRAY = "text[]"
    INT_ARRAY = "int[]"
    NUMBER_ARRAY = "number[]"
    BOOLEAN_ARRAY = "boolean[]"
    DATE_ARRAY = "date[]"
    UUID_ARRAY = "uuid[]"
    OBJECT_ARRAY = "object[]"


@dataclass(frozen=True)
class SparseVector:
    indices: list[int]
    values: list[float]


@dataclass
class Record:
    id: str
    source_id: str | int
    vectors: dict[str, list[float]] = field(default_factory=dict)
    multivectors: dict[str, list[list[float]]] = field(default_factory=dict)
    sparse: dict[str, SparseVector] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorSpec:
    name: str
    size: int
    distance: Distance
    multivector: bool = False


@dataclass(frozen=True)
class SparseVectorSpec:
    name: str


@dataclass
class CollectionSpec:
    name: str
    vectors: list[VectorSpec]
    sparse_vectors: list[SparseVectorSpec] = field(default_factory=list)
    count: int = 0
    # payload field -> source index type (e.g. "keyword", "integer")
    indexed_fields: dict[str, str] = field(default_factory=dict)


@dataclass
class PropertySpec:
    name: str
    type: PropertyType
    range_filter: bool = False
    nested: list[PropertySpec] = field(default_factory=list)


@dataclass
class SchemaPlan:
    source: str
    target: str
    vectors: list[VectorSpec]
    properties: list[PropertySpec]
    warnings: list[str] = field(default_factory=list)
    # Gaps block a run: the mapping cannot be applied without data loss the user did not accept.
    gaps: list[str] = field(default_factory=list)

    def property_types(self) -> dict[str, PropertyType]:
        return {p.name: p.type for p in self.properties}


@dataclass(frozen=True)
class Cursor:
    """Resumable read position for one shard of a source collection."""

    shard: str
    value: Any = None
    done: bool = False


@dataclass
class RunStats:
    read: int = 0
    written: int = 0
    failed: int = 0
    skipped: int = 0

    def __iadd__(self, other: RunStats) -> RunStats:
        self.read += other.read
        self.written += other.written
        self.failed += other.failed
        self.skipped += other.skipped
        return self


@dataclass
class WriteResult:
    written: int
    failures: list[tuple[Record, str]] = field(default_factory=list)


@dataclass
class Query:
    vector: list[float]
    vector_name: str = DEFAULT_VECTOR
    limit: int = 10
    filter: FilterExpr | None = None


@dataclass(frozen=True)
class Hit:
    id: str
    score: float
