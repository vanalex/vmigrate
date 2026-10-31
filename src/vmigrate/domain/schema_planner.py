"""Turn a source CollectionSpec + mapping + samples into a target SchemaPlan."""

from __future__ import annotations

from vmigrate.domain.mapping import CollectionMapping, SparsePolicy
from vmigrate.domain.models import (
    CollectionSpec,
    Distance,
    PropertySpec,
    PropertyType,
    Record,
    SchemaPlan,
    VectorSpec,
)
from vmigrate.domain.transforms.renamer import FieldRenamer
from vmigrate.domain.type_inference import infer_properties

# Source index types whose fields get a range index on the target.
_RANGE_INDEX_TYPES = {"integer", "float", "datetime"}
_RANGE_CAPABLE = {PropertyType.INT, PropertyType.NUMBER, PropertyType.DATE}


def plan_schema(
    spec: CollectionSpec, mapping: CollectionMapping, samples: list[Record]
) -> SchemaPlan:
    """`samples` must already have gone through the transform chain."""
    warnings: list[str] = []
    gaps: list[str] = []

    target = mapping.target
    if not target[:1].isupper():
        target = target[:1].upper() + target[1:]
        warnings.append(f"collection names must start uppercase, using '{target}'")

    vectors: list[VectorSpec] = []
    for v in spec.vectors:
        vectors.append(VectorSpec(mapping.target_vector(v.name), v.size, v.distance, v.multivector))
        if v.distance is Distance.EUCLID:
            warnings.append(
                f"vector '{v.name or 'default'}': euclid -> l2-squared, scores change scale "
                "(ranking identical); recalibrate score thresholds"
            )

    for s in spec.sparse_vectors:
        label = s.name or "default"
        if mapping.sparse is SparsePolicy.FAIL:
            gaps.append(f"sparse vector '{label}' cannot be migrated (sparse policy = fail)")
        elif mapping.sparse is SparsePolicy.DROP:
            warnings.append(f"sparse vector '{label}' dropped; consider BM25 hybrid search")
        else:
            warnings.append(f"sparse vector '{label}' stored as a JSON property (not searchable)")

    properties, inference_warnings = infer_properties(r.payload for r in samples)
    warnings.extend(inference_warnings)
    if spec.count and not samples:
        warnings.append("no sample points read; schema contains overrides only")

    by_name = {p.name: p for p in properties}
    for name, forced in mapping.property_types.items():
        if name in by_name:
            by_name[name].type = forced
        else:
            by_name[name] = PropertySpec(name=name, type=forced)

    renamer = FieldRenamer(mapping.rename)
    for field, index_type in spec.indexed_fields.items():
        prop = by_name.get(renamer.name(field))
        if prop and index_type in _RANGE_INDEX_TYPES and prop.type in _RANGE_CAPABLE:
            prop.range_filter = True

    return SchemaPlan(
        source=spec.name,
        target=target,
        vectors=vectors,
        properties=list(by_name.values()),
        warnings=warnings,
        gaps=gaps,
    )
