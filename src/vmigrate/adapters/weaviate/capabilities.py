"""Server-version gated features."""

from __future__ import annotations

from vmigrate.domain.models import SchemaPlan

MULTIVECTOR_MIN = (1, 29)
NAMED_VECTORS_MIN = (1, 24)


def parse_version(version: str) -> tuple[int, int]:
    major, minor, *_ = (int(p) for p in version.split("-")[0].split("."))
    return major, minor


def check_plan(plan: SchemaPlan, server_version: str) -> list[str]:
    version = parse_version(server_version)
    warnings = []
    if version < NAMED_VECTORS_MIN:
        warnings.append(f"Weaviate {server_version} does not support named vectors (need 1.24+)")
    if any(v.multivector for v in plan.vectors) and version < MULTIVECTOR_MIN:
        warnings.append(f"Weaviate {server_version} does not support multivectors (need 1.29+)")
    return warnings
