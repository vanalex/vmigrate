import uuid

import pytest

from vmigrate.domain.mapping import CollectionMapping, SparsePolicy
from vmigrate.domain.models import PropertyType, Record, SparseVector
from vmigrate.domain.transforms import (
    FieldRenamer,
    SparseVectorUnsupported,
    TypeCoercer,
    VectorRouter,
    apply_chain,
    build_chain,
    map_id,
    safe_name,
)
from vmigrate.domain.transforms.id_mapper import IdMapper

NS = uuid.UUID("6f1c2f3e-6a8b-4d55-9a3c-2b0e7c1d9f10")


def test_map_id_keeps_uuids_and_is_deterministic_for_ints():
    u = str(uuid.uuid4())
    assert map_id(u, NS) == u
    assert map_id(42, NS) == map_id("42", NS) == str(uuid.uuid5(NS, "42"))


def test_id_mapper_keeps_source_id():
    r = IdMapper(NS, "qdrant_id")(Record(id="7", source_id=7))
    assert r.id == str(uuid.uuid5(NS, "7"))
    assert r.payload["qdrant_id"] == "7"


@pytest.mark.parametrize(
    "raw,expected",
    [("user-id", "user_id"), ("1st", "_1st"), ("id", "id_"), ("ok_name", "ok_name"), ("", "_")],
)
def test_safe_name(raw, expected):
    assert safe_name(raw) == expected


def test_renamer_applies_explicit_renames_and_sanitizes_nested_keys():
    r = Record(id="1", source_id=1, payload={"user-id": 1, "meta": {"a-b": [{"c d": 1}]}})
    out = FieldRenamer({"user-id": "userId"})(r)
    assert out.payload == {"userId": 1, "meta": {"a_b": [{"c_d": 1}]}}


def test_renamer_rejects_collisions():
    with pytest.raises(ValueError, match="collide"):
        FieldRenamer()(Record(id="1", source_id=1, payload={"a-b": 1, "a_b": 2}))


def test_coercer_drops_nulls_converts_geo_and_casts():
    r = Record(
        id="1",
        source_id=1,
        payload={"n": None, "loc": {"lat": 1.0, "lon": 2.0}, "x": 3, "tags": "solo"},
    )
    out = TypeCoercer({"x": PropertyType.NUMBER, "tags": PropertyType.TEXT_ARRAY})(r)
    assert out.payload == {
        "loc": {"latitude": 1.0, "longitude": 2.0},
        "x": 3.0,
        "tags": ["solo"],
    }


def test_vector_router_renames_and_applies_sparse_policies():
    def rec():
        return Record(
            id="1",
            source_id=1,
            vectors={"": [1.0], "title": [2.0]},
            sparse={"bm25": SparseVector([1], [0.5])},
        )

    m = CollectionMapping("a", "A", vectors={"title": "title_vec"})
    out = VectorRouter(m)(rec())
    assert out.vectors == {"default": [1.0], "title_vec": [2.0]}
    assert out.sparse == {}

    m.sparse = SparsePolicy.JSON_PROPERTY
    assert VectorRouter(m)(rec()).payload["sparse_bm25"] == {"indices": [1], "values": [0.5]}

    m.sparse = SparsePolicy.FAIL
    with pytest.raises(SparseVectorUnsupported):
        VectorRouter(m)(rec())


def drop_odd(record):
    return None if record.source_id % 2 else record


def test_chain_runs_hooks_last_and_can_drop_records():
    m = CollectionMapping("a", "A", hooks=[f"{__name__}:drop_odd"])
    out = apply_chain(build_chain(m), [Record(id=str(i), source_id=i) for i in range(4)])
    assert [r.source_id for r in out] == [0, 2]
