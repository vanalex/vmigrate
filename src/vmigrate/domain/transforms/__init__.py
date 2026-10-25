"""Record transforms. Each one is a callable `Record -> Record | None` (None drops the record)."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable

from vmigrate.domain.mapping import CollectionMapping
from vmigrate.domain.models import Record, SchemaPlan
from vmigrate.domain.transforms.coercer import TypeCoercer
from vmigrate.domain.transforms.id_mapper import IdMapper, map_id
from vmigrate.domain.transforms.renamer import FieldRenamer, safe_name
from vmigrate.domain.transforms.vector_router import SparseVectorUnsupported, VectorRouter

Transform = Callable[[Record], Record | None]

__all__ = [
    "FieldRenamer",
    "IdMapper",
    "SparseVectorUnsupported",
    "Transform",
    "TypeCoercer",
    "VectorRouter",
    "apply_chain",
    "build_chain",
    "load_hook",
    "map_id",
    "safe_name",
]


def load_hook(spec: str) -> Transform:
    module_name, _, func_name = spec.partition(":")
    if not func_name:
        raise ValueError(f"hook must look like 'module:function', got '{spec}'")
    return getattr(importlib.import_module(module_name), func_name)


def build_chain(mapping: CollectionMapping, plan: SchemaPlan | None = None) -> list[Transform]:
    """Without a plan only the user's type overrides are applied (used while planning)."""
    types = plan.property_types() if plan else mapping.property_types
    return [
        FieldRenamer(mapping.rename),
        TypeCoercer(types),
        IdMapper(mapping.uuid_namespace, mapping.keep_source_id_as),
        VectorRouter(mapping),
        *(load_hook(h) for h in mapping.hooks),
    ]


def apply_chain(chain: list[Transform], records: Iterable[Record]) -> list[Record]:
    out: list[Record] = []
    for record in records:
        current: Record | None = record
        for transform in chain:
            current = transform(current)
            if current is None:
                break
        if current is not None:
            out.append(current)
    return out
