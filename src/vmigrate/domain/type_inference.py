"""Infer target property types from sampled (already transformed) payloads."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from vmigrate.domain.models import PropertySpec
from vmigrate.domain.models import PropertyType as T

_ARRAY_OF = {
    T.TEXT: T.TEXT_ARRAY,
    T.INT: T.INT_ARRAY,
    T.NUMBER: T.NUMBER_ARRAY,
    T.BOOLEAN: T.BOOLEAN_ARRAY,
    T.DATE: T.DATE_ARRAY,
    T.UUID: T.UUID_ARRAY,
    T.OBJECT: T.OBJECT_ARRAY,
}
# Lossless widenings; anything else that conflicts falls back to TEXT.
_WIDEN = {
    frozenset({T.INT, T.NUMBER}): T.NUMBER,
    frozenset({T.INT_ARRAY, T.NUMBER_ARRAY}): T.NUMBER_ARRAY,
}

GEO_KEYS = frozenset({"latitude", "longitude"})


def _scalar(value: Any) -> T | None:
    if isinstance(value, bool):  # before int: bool is an int subclass
        return T.BOOLEAN
    if isinstance(value, int):
        return T.INT
    if isinstance(value, float):
        return T.NUMBER
    if isinstance(value, (datetime, date)):
        return T.DATE
    if isinstance(value, uuid.UUID):
        return T.UUID
    if isinstance(value, str):
        return T.TEXT
    return None


def _classify(value: Any) -> tuple[T | None, list[dict[str, Any]]]:
    """Return the value's type and, for objects, the nested dicts to recurse into."""
    if value is None:
        return None, []
    if isinstance(value, dict):
        if set(value) == GEO_KEYS:
            return T.GEO, []
        return T.OBJECT, [value]
    if isinstance(value, list):
        items = [v for v in value if v is not None]
        if not items:
            return None, []
        if all(isinstance(v, dict) for v in items):
            return T.OBJECT_ARRAY, items
        merged: T | None = None
        for item in items:
            t = _scalar(item)
            if t is None:
                return T.TEXT, []
            merged = t if merged is None else merge_types(merged, t)
        return _ARRAY_OF.get(merged, T.TEXT_ARRAY), []
    return _scalar(value), []


def merge_types(a: T, b: T) -> T:
    if a == b:
        return a
    return _WIDEN.get(frozenset({a, b}), T.TEXT)


def infer_properties(
    payloads: Iterable[dict[str, Any]], path: str = ""
) -> tuple[list[PropertySpec], list[str]]:
    types: dict[str, T] = {}
    nested_samples: dict[str, list[dict[str, Any]]] = {}
    warnings: list[str] = []

    for payload in payloads:
        for key, value in payload.items():
            t, nested = _classify(value)
            if t is None:
                continue
            if key in types and types[key] != t:
                merged = merge_types(types[key], t)
                if merged == T.TEXT:
                    warnings.append(
                        f"{path}{key}: conflicting types {types[key].value}/{t.value}, using text"
                    )
                t = merged
            types[key] = t
            nested_samples.setdefault(key, []).extend(nested)

    specs: list[PropertySpec] = []
    for key, t in types.items():
        spec = PropertySpec(name=key, type=t)
        if t in (T.OBJECT, T.OBJECT_ARRAY):
            spec.nested, nested_warnings = infer_properties(nested_samples[key], f"{path}{key}.")
            warnings.extend(nested_warnings)
            if not spec.nested:
                warnings.append(f"{path}{key}: object has no typed fields, property dropped")
                continue
        specs.append(spec)
    return specs, warnings
