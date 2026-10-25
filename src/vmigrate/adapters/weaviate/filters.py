from __future__ import annotations

from typing import Any

from weaviate.classes.query import Filter

from vmigrate.domain.filters import And, FilterExpr, Match, MatchAny, Not, Or, Range


def to_weaviate(expr: FilterExpr) -> Any:
    match expr:
        case Match(field, value):
            return Filter.by_property(field).equal(value)
        case MatchAny(field, values):
            return Filter.by_property(field).contains_any(list(values))
        case Range(field, gt, gte, lt, lte):
            prop = Filter.by_property(field)
            parts = [
                op(v)
                for op, v in (
                    (prop.greater_than, gt),
                    (prop.greater_or_equal, gte),
                    (prop.less_than, lt),
                    (prop.less_or_equal, lte),
                )
                if v is not None
            ]
            return parts[0] if len(parts) == 1 else Filter.all_of(parts)
        case And(items):
            return Filter.all_of([to_weaviate(i) for i in items])
        case Or(items):
            return Filter.any_of([to_weaviate(i) for i in items])
        case Not(item):
            return Filter.not_(to_weaviate(item))
    raise TypeError(f"not a filter expression: {expr!r}")
