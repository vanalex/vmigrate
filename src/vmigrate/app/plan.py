from __future__ import annotations

from vmigrate.domain.mapping import CollectionMapping
from vmigrate.domain.models import Record, SchemaPlan
from vmigrate.domain.schema_planner import plan_schema
from vmigrate.domain.transforms import apply_chain, build_chain
from vmigrate.ports import Sink, Source


class PlanMigration:
    """Describe the source, sample it, and produce the target schema plus warnings/gaps."""

    def __init__(self, source: Source, sink: Sink, sample_size: int = 200):
        self._source = source
        self._sink = sink
        self._sample_size = sample_size

    def execute(self, mapping: CollectionMapping) -> SchemaPlan:
        spec = self._source.describe(mapping.source)
        samples = apply_chain(build_chain(mapping), self.sample(mapping.source))
        plan = plan_schema(spec, mapping, samples)
        plan.warnings.extend(self._sink.check(plan))
        return plan

    def sample(self, collection: str, size: int | None = None) -> list[Record]:
        # TODO: random sampling across shards; the first batch can miss late-appearing fields.
        first = self._source.shards(collection, 1)[0]
        for records, _ in self._source.read(collection, first, size or self._sample_size):
            return records
        return []
