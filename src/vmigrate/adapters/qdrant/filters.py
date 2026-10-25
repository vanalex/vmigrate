from __future__ import annotations

from qdrant_client import models

from vmigrate.domain.filters import And, FilterExpr, Match, MatchAny, Not, Or, Range


def _condition(expr: FilterExpr) -> models.Condition:
    match expr:
        case Match(field, value):
            return models.FieldCondition(key=field, match=models.MatchValue(value=value))
        case MatchAny(field, values):
            return models.FieldCondition(key=field, match=models.MatchAny(any=list(values)))
        case Range(field, gt, gte, lt, lte):
            return models.FieldCondition(
                key=field, range=models.Range(gt=gt, gte=gte, lt=lt, lte=lte)
            )
    return to_qdrant(expr)  # nested boolean expression


def to_qdrant(expr: FilterExpr) -> models.Filter:
    match expr:
        case And(items):
            return models.Filter(must=[_condition(i) for i in items])
        case Or(items):
            return models.Filter(should=[_condition(i) for i in items])
        case Not(item):
            return models.Filter(must_not=[_condition(item)])
    return models.Filter(must=[_condition(expr)])
