"""Seed a local Qdrant collection with edge-case data for vmigrate trial migrations.

Usage: uv run python .claude/skills/trial-migration/scripts/seed_qdrant.py --help
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

from qdrant_client import QdrantClient, models

LANGS = ["en", "es", "de", "fr"]


def vec(rng: random.Random, dim: int) -> list[float]:
    return [rng.uniform(-1, 1) for _ in range(dim)]


def payload(i: int, n: int, late: int, rng: random.Random) -> dict:
    p = {
        "title": f"document {i}",
        "lang": LANGS[i % len(LANGS)],
        "id": f"ext-{i}",  # reserved in Weaviate
        "user-id": i % 25,  # invalid Weaviate property name
        "score": round(rng.uniform(0, 100), 3),
        "created_at": (datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i)).isoformat(),
        "tags": rng.sample(["a", "b", "c", "d"], k=1 + i % 3),
        "meta": {"pages": 1 + i % 40, "source": "trial"},
        "location": {"lat": round(40 + rng.uniform(-1, 1), 5),
                     "lon": round(-3.7 + rng.uniform(-1, 1), 5)},
    }
    if i > n - late:
        p["late_note"] = f"only on late points ({i})"
    return p


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://localhost:6333")
    ap.add_argument("--collection", default="trial_docs")
    ap.add_argument("--points", type=int, default=1000)
    ap.add_argument("--dim", type=int, default=8)
    ap.add_argument("--late", type=int, default=50,
                    help="number of final points that carry the late-appearing field")
    ap.add_argument("--no-sparse", action="store_true")
    ap.add_argument("--no-multivector", action="store_true")
    ap.add_argument("--golden", type=Path, help="write golden queries JSONL here")
    ap.add_argument("--queries", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    client = QdrantClient(url=args.url, timeout=60)

    vectors = {"text": models.VectorParams(size=args.dim, distance=models.Distance.COSINE)}
    if not args.no_multivector:
        vectors["colbert"] = models.VectorParams(
            size=args.dim,
            distance=models.Distance.COSINE,
            multivector_config=models.MultiVectorConfig(
                comparator=models.MultiVectorComparator.MAX_SIM
            ),
        )
    sparse = None if args.no_sparse else {"bm25": models.SparseVectorParams()}

    if client.collection_exists(args.collection):
        client.delete_collection(args.collection)
    client.create_collection(args.collection, vectors_config=vectors,
                             sparse_vectors_config=sparse)
    client.create_payload_index(args.collection, "score", models.PayloadSchemaType.FLOAT)
    client.create_payload_index(args.collection, "lang", models.PayloadSchemaType.KEYWORD)

    batch: list[models.PointStruct] = []
    for i in range(1, args.points + 1):
        v: dict = {"text": vec(rng, args.dim)}
        if not args.no_multivector:
            v["colbert"] = [vec(rng, args.dim) for _ in range(1 + i % 3)]
        if not args.no_sparse:
            idx = sorted(rng.sample(range(1000), k=5))
            v["bm25"] = models.SparseVector(indices=idx, values=[rng.random() for _ in idx])
        batch.append(models.PointStruct(id=i, vector=v,
                                        payload=payload(i, args.points, args.late, rng)))
        if len(batch) == 500:
            client.upsert(args.collection, batch, wait=True)
            batch = []
    if batch:
        client.upsert(args.collection, batch, wait=True)

    count = client.count(args.collection, exact=True).count
    print(f"seeded {args.collection}: {count} points "
          f"(late field on last {min(args.late, args.points)})")

    if args.golden:
        args.golden.parent.mkdir(parents=True, exist_ok=True)
        with args.golden.open("w") as f:
            for q in range(args.queries):
                query = {"vector": vec(rng, args.dim), "vector_name": "text", "limit": 10}
                if q % 2:
                    query["filter"] = {"match": {"field": "lang", "value": LANGS[q % len(LANGS)]}}
                f.write(json.dumps(query) + "\n")
        print(f"wrote {args.queries} golden queries to {args.golden}")


if __name__ == "__main__":
    main()
