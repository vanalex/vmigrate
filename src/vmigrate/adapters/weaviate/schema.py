"""SchemaPlan -> Weaviate collection config."""

from __future__ import annotations

from typing import Any

from weaviate.classes.config import Configure, DataType, Property, VectorDistances

from vmigrate.domain.models import Distance, PropertySpec, PropertyType, SchemaPlan, VectorSpec

DISTANCES = {
    Distance.COSINE: VectorDistances.COSINE,
    Distance.DOT: VectorDistances.DOT,
    Distance.EUCLID: VectorDistances.L2_SQUARED,
    Distance.MANHATTAN: VectorDistances.MANHATTAN,
}

DATA_TYPES = {
    PropertyType.TEXT: DataType.TEXT,
    PropertyType.INT: DataType.INT,
    PropertyType.NUMBER: DataType.NUMBER,
    PropertyType.BOOLEAN: DataType.BOOL,
    PropertyType.DATE: DataType.DATE,
    PropertyType.UUID: DataType.UUID,
    PropertyType.GEO: DataType.GEO_COORDINATES,
    PropertyType.OBJECT: DataType.OBJECT,
    PropertyType.TEXT_ARRAY: DataType.TEXT_ARRAY,
    PropertyType.INT_ARRAY: DataType.INT_ARRAY,
    PropertyType.NUMBER_ARRAY: DataType.NUMBER_ARRAY,
    PropertyType.BOOLEAN_ARRAY: DataType.BOOL_ARRAY,
    PropertyType.DATE_ARRAY: DataType.DATE_ARRAY,
    PropertyType.UUID_ARRAY: DataType.UUID_ARRAY,
    PropertyType.OBJECT_ARRAY: DataType.OBJECT_ARRAY,
}


def to_property(spec: PropertySpec) -> Property:
    kwargs: dict[str, Any] = {"name": spec.name, "data_type": DATA_TYPES[spec.type]}
    if spec.range_filter:
        kwargs["index_range_filters"] = True
    if spec.nested:
        kwargs["nested_properties"] = [to_property(n) for n in spec.nested]
    return Property(**kwargs)


def to_vector_config(spec: VectorSpec) -> Any:
    # TODO(M4): carry over HNSW params and quantization from the source collection.
    index = Configure.VectorIndex.hnsw(distance_metric=DISTANCES[spec.distance])
    if spec.multivector:
        return Configure.MultiVectors.self_provided(name=spec.name, vector_index_config=index)
    return Configure.Vectors.self_provided(name=spec.name, vector_index_config=index)


def collection_kwargs(plan: SchemaPlan) -> dict[str, Any]:
    return {
        "name": plan.target,
        "properties": [to_property(p) for p in plan.properties],
        "vector_config": [to_vector_config(v) for v in plan.vectors],
    }
