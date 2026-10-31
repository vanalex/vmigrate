"""Comparison helpers used by validation: search overlap, vector and payload equality."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any


def overlap_at_k(expected: list[str], actual: list[str], k: int) -> float:
    exp = expected[:k]
    if not exp:
        return 1.0
    return len(set(exp) & set(actual[:k])) / len(exp)


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def cosine(u: list[float], v: list[float]) -> float:
    dot = sum(x * y for x, y in zip(u, v, strict=True))
    nu = math.sqrt(sum(x * x for x in u))
    nv = math.sqrt(sum(y * y for y in v))
    if nu == 0 or nv == 0:
        return 1.0 if nu == nv else 0.0
    return dot / (nu * nv)


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)  # accepts a trailing "Z" since Python 3.11
        except ValueError:
            return None
    return None


def values_equal(a: Any, b: Any) -> bool:
    if (
        (isinstance(a, float) or isinstance(b, float))
        and isinstance(a, (int, float))
        and isinstance(b, (int, float))
    ):
        return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)
    if isinstance(a, (datetime, date)) or isinstance(b, (datetime, date)):
        da, db = _as_datetime(a), _as_datetime(b)
        if da is not None and db is not None:
            if (da.tzinfo is None) != (db.tzinfo is None):
                da, db = da.replace(tzinfo=None), db.replace(tzinfo=None)
            return da == db
    return a == b


def payload_diff(expected: dict[str, Any], actual: dict[str, Any], path: str = "") -> list[str]:
    diffs: list[str] = []
    for key, exp in expected.items():
        here = f"{path}{key}"
        if key not in actual or actual[key] is None:
            if exp is not None:
                diffs.append(f"{here}: missing")
            continue
        act = actual[key]
        if isinstance(exp, dict) and isinstance(act, dict):
            diffs.extend(payload_diff(exp, act, f"{here}."))
        elif isinstance(exp, list) and isinstance(act, list):
            if len(exp) != len(act):
                diffs.append(f"{here}: length {len(exp)} != {len(act)}")
                continue
            for i, (e, a) in enumerate(zip(exp, act)):
                if isinstance(e, dict) and isinstance(a, dict):
                    diffs.extend(payload_diff(e, a, f"{here}[{i}]."))
                elif not values_equal(e, a):
                    diffs.append(f"{here}[{i}]: {e!r} != {a!r}")
        elif not values_equal(exp, act):
            diffs.append(f"{here}: {exp!r} != {act!r}")
    return diffs
