from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from vmigrate.app.plan import PlanMigration
from vmigrate.domain.filters import parse_filter, rename_fields
from vmigrate.domain.mapping import CollectionMapping
from vmigrate.domain.models import Query, SchemaPlan
from vmigrate.domain.parity import cosine, overlap_at_k, payload_diff
from vmigrate.domain.transforms import FieldRenamer, apply_chain, build_chain, map_id
from vmigrate.ports import Sink, Source


@dataclass
class FidelityResult:
    sampled: int = 0
    missing: list[str] = field(default_factory=list)
    payload_mismatches: dict[str, list[str]] = field(default_factory=dict)
    vector_mismatches: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing or self.payload_mismatches or self.vector_mismatches)


@dataclass
class ParityResult:
    queries: int = 0
    mean_overlap: float = 1.0
    min_overlap: float = 1.0
    below_threshold: int = 0


@dataclass
class CollectionValidation:
    source: str
    target: str
    source_count: int
    target_count: int
    fidelity: FidelityResult
    parity: ParityResult

    @property
    def passed(self) -> bool:
        return (
            self.source_count == self.target_count
            and self.fidelity.ok
            and self.parity.below_threshold == 0
        )


def load_golden(path: str | Path) -> list[Query]:
    """JSONL: {"vector": [...], "vector_name": "", "limit": 10, "filter": {...}}"""
    queries = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        queries.append(
            Query(
                vector=obj["vector"],
                vector_name=obj.get("vector_name", ""),
                limit=obj.get("limit", 10),
                filter=parse_filter(obj["filter"]) if obj.get("filter") else None,
            )
        )
    return queries


class Validate:
    def __init__(
        self,
        source: Source,
        sink: Sink,
        planner: PlanMigration,
        sample_size: int = 1000,
        overlap_threshold: float = 0.95,
        vector_tolerance: float = 1e-4,
    ):
        self._source = source
        self._sink = sink
        self._planner = planner
        self._sample_size = sample_size
        self._threshold = overlap_threshold
        self._tolerance = vector_tolerance

    def execute(
        self, mapping: CollectionMapping, golden: list[Query] | None = None
    ) -> CollectionValidation:
        plan = self._planner.execute(mapping)
        return CollectionValidation(
            source=mapping.source,
            target=plan.target,
            source_count=self._source.count(mapping.source),
            target_count=self._sink.count(plan.target),
            fidelity=self._fidelity(mapping, plan),
            parity=self._parity(mapping, plan.target, golden or []),
        )

    def _fidelity(self, mapping: CollectionMapping, plan: SchemaPlan) -> FidelityResult:
        sample = self._planner.sample(mapping.source, self._sample_size)
        expected = apply_chain(build_chain(mapping, plan), copy.deepcopy(sample))
        actual = {r.id: r for r in self._sink.fetch(plan.target, [r.id for r in expected])}

        result = FidelityResult(sampled=len(expected))
        for exp in expected:
            got = actual.get(exp.id)
            if got is None:
                result.missing.append(str(exp.source_id))
                continue
            diffs = payload_diff(exp.payload, got.payload)
            if diffs:
                result.payload_mismatches[str(exp.source_id)] = diffs
            for name, vec in exp.vectors.items():
                other = got.vectors.get(name)
                if other is None or cosine(vec, other) < 1 - self._tolerance:
                    result.vector_mismatches.append(f"{exp.source_id}:{name or 'default'}")
        return result

    def _parity(self, mapping: CollectionMapping, target: str, golden: list[Query]) -> ParityResult:
        if not golden:
            return ParityResult()
        renamer = FieldRenamer(mapping.rename)
        overlaps = []
        for q in golden:
            expected = [
                map_id(h.id, mapping.uuid_namespace) for h in self._source.search(mapping.source, q)
            ]
            target_query = Query(
                vector=q.vector,
                vector_name=mapping.target_vector(q.vector_name),
                limit=q.limit,
                filter=rename_fields(q.filter, renamer.name) if q.filter else None,
            )
            actual = [h.id for h in self._sink.search(target, target_query)]
            overlaps.append(overlap_at_k(expected, actual, q.limit))
        return ParityResult(
            queries=len(overlaps),
            mean_overlap=sum(overlaps) / len(overlaps),
            min_overlap=min(overlaps),
            below_threshold=sum(1 for o in overlaps if o < self._threshold),
        )
