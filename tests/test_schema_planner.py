from datetime import datetime

from tests.conftest import make_records, make_spec
from vmigrate.domain.mapping import CollectionMapping, SparsePolicy
from vmigrate.domain.models import Distance, VectorSpec
from vmigrate.domain.models import PropertyType as T
from vmigrate.domain.schema_planner import plan_schema
from vmigrate.domain.transforms import apply_chain, build_chain
from vmigrate.domain.type_inference import infer_properties


def test_infer_scalars_arrays_objects_geo_and_widening():
    props, warnings = infer_properties(
        [
            {"i": 1, "f": 1, "b": True, "d": datetime(2024, 1, 1), "tags": ["x"],
             "geo": {"latitude": 1.0, "longitude": 2.0}, "obj": {"a": 1}, "objs": [{"k": "v"}]},
            {"f": 2.5, "mixed": 1},
            {"mixed": "s", "empty": {}},
        ]
    )
    by = {p.name: p for p in props}
    assert by["i"].type is T.INT
    assert by["f"].type is T.NUMBER  # int + float widens
    assert by["b"].type is T.BOOLEAN
    assert by["d"].type is T.DATE
    assert by["tags"].type is T.TEXT_ARRAY
    assert by["geo"].type is T.GEO
    assert by["obj"].type is T.OBJECT and by["obj"].nested[0].type is T.INT
    assert by["objs"].type is T.OBJECT_ARRAY
    assert by["mixed"].type is T.TEXT
    assert "empty" not in by
    assert any("mixed" in w for w in warnings) and any("empty" in w for w in warnings)


def test_plan_schema_end_to_end():
    mapping = CollectionMapping(
        "docs", "docs", rename={"user-id": "userId"}, property_types={"title": T.TEXT},
        sparse=SparsePolicy.DROP, keep_source_id_as="qdrant_id",
    )
    spec = make_spec(count=10, sparse=True)
    samples = apply_chain(build_chain(mapping), make_records(10))
    plan = plan_schema(spec, mapping, samples)

    assert plan.target == "Docs"
    assert plan.vectors == [VectorSpec("default", 8, Distance.COSINE)]
    by = {p.name: p for p in plan.properties}
    assert by["userId"].type is T.INT and by["userId"].range_filter
    assert by["score"].type is T.NUMBER and by["score"].range_filter
    assert by["location"].type is T.GEO
    assert by["id_"].type is T.TEXT  # reserved name renamed
    assert by["qdrant_id"].type is T.TEXT
    assert not plan.gaps
    assert any("sparse" in w for w in plan.warnings)


def test_sparse_fail_policy_is_a_gap():
    mapping = CollectionMapping("docs", "Docs", sparse=SparsePolicy.FAIL)
    plan = plan_schema(make_spec(sparse=True), mapping, [])
    assert plan.gaps
