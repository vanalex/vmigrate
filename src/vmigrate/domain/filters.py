"""Database-neutral filter AST. Adapters translate it to their native filter types."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Match:
    field: str
    value: Any


@dataclass(frozen=True)
class MatchAny:
    field: str
    values: tuple[Any, ...]


@dataclass(frozen=True)
class Range:
    field: str
    gt: Any = None
    gte: Any = None
    lt: Any = None
    lte: Any = None


@dataclass(frozen=True)
class And:
    items: tuple[FilterExpr, ...]


@dataclass(frozen=True)
class Or:
    items: tuple[FilterExpr, ...]


@dataclass(frozen=True)
class Not:
    item: FilterExpr


FilterExpr = Match | MatchAny | Range | And | Or | Not


def parse_filter(obj: dict[str, Any]) -> FilterExpr:
    """Parse the JSON form used in golden-query files.

    {"and": [...]}, {"or": [...]}, {"not": {...}},
    {"match": {"field": "f", "value": 1}}, {"match_any": {"field": "f", "values": [1, 2]}},
    {"range": {"field": "f", "gte": 1, "lt": 5}}
    """
    if len(obj) != 1:
        raise ValueError(f"filter node must have exactly one key, got {sorted(obj)}")
    ((kind, body),) = obj.items()
    if kind == "and":
        return And(tuple(parse_filter(i) for i in body))
    if kind == "or":
        return Or(tuple(parse_filter(i) for i in body))
    if kind == "not":
        return Not(parse_filter(body))
    if kind == "match":
        return Match(body["field"], body["value"])
    if kind == "match_any":
        return MatchAny(body["field"], tuple(body["values"]))
    if kind == "range":
        return Range(**body)
    raise ValueError(f"unknown filter node: {kind}")


def rename_fields(expr: FilterExpr, rename: Callable[[str], str]) -> FilterExpr:
    """Rewrite field names, e.g. to apply the payload renames done during migration."""
    match expr:
        case Match(field, value):
            return Match(rename(field), value)
        case MatchAny(field, values):
            return MatchAny(rename(field), values)
        case Range(field, gt, gte, lt, lte):
            return Range(rename(field), gt, gte, lt, lte)
        case And(items):
            return And(tuple(rename_fields(i, rename) for i in items))
        case Or(items):
            return Or(tuple(rename_fields(i, rename) for i in items))
        case Not(item):
            return Not(rename_fields(item, rename))
    raise TypeError(f"not a filter expression: {expr!r}")
