"""YAML config -> validated pydantic models -> domain mappings."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from vmigrate.domain.mapping import DEFAULT_UUID_NAMESPACE, CollectionMapping, SparsePolicy
from vmigrate.domain.models import PropertyType

# ${VAR} or ${VAR:-default}
_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class EndpointConfig(BaseModel):
    """`type` selects the adapter; every other key is passed to its constructor."""

    model_config = ConfigDict(extra="allow")
    type: str

    def options(self) -> dict[str, Any]:
        return {k: v for k, v in (self.model_extra or {}).items() if v not in (None, "")}


class Defaults(BaseModel):
    batch_size: int = Field(500, gt=0)
    workers: int = Field(4, gt=0)
    max_retries: int = Field(3, gt=0)
    on_error: Literal["deadletter", "fail"] = "deadletter"
    sample_size: int = Field(200, gt=0)


class StateConfig(BaseModel):
    checkpoint_path: Path = Path(".vmigrate/state.db")
    deadletter_dir: Path = Path(".vmigrate/deadletter")


class ObservabilityConfig(BaseModel):
    prometheus_port: int | None = None


class IdsConfig(BaseModel):
    keep_source_id_as: str | None = "source_id"
    uuid_namespace: uuid.UUID = DEFAULT_UUID_NAMESPACE


class PropertyOverride(BaseModel):
    type: PropertyType


class CollectionConfig(BaseModel):
    source: str
    target: str
    ids: IdsConfig = IdsConfig()
    vectors: dict[str, str] = {}
    sparse: SparsePolicy = SparsePolicy.DROP
    properties: dict[str, PropertyOverride] = {}
    rename: dict[str, str] = {}
    transforms: list[str] = []

    def to_mapping(self) -> CollectionMapping:
        return CollectionMapping(
            source=self.source,
            target=self.target,
            vectors=dict(self.vectors),
            sparse=self.sparse,
            keep_source_id_as=self.ids.keep_source_id_as,
            uuid_namespace=self.ids.uuid_namespace,
            rename=dict(self.rename),
            property_types={k: v.type for k, v in self.properties.items()},
            hooks=list(self.transforms),
        )


class MigrationConfig(BaseModel):
    source: EndpointConfig
    target: EndpointConfig
    defaults: Defaults = Defaults()
    state: StateConfig = StateConfig()
    observability: ObservabilityConfig = ObservabilityConfig()
    collections: list[CollectionConfig] = Field(min_length=1)

    def mappings(self, only: list[str] | None = None) -> list[CollectionMapping]:
        selected = [c for c in self.collections if not only or c.source in only]
        if only and len(selected) != len(set(only)):
            missing = set(only) - {c.source for c in selected}
            raise ValueError(f"collections not in config: {sorted(missing)}")
        return [c.to_mapping() for c in selected]

    def fingerprint(self) -> str:
        """Hash of what changes migrated data or shard layout. Credentials are excluded."""
        relevant = self.model_dump_json(include={"collections": True, "defaults": {"workers"}})
        return hashlib.sha256(relevant.encode()).hexdigest()[:16]


def _interpolate(text: str) -> str:
    def sub(m: re.Match[str]) -> str:
        name, default = m.group(1), m.group(2)
        value = os.environ.get(name, default)
        if value is None:
            raise ValueError(f"environment variable {name} is not set")
        return value

    return _ENV.sub(sub, text)


def load_config(path: str | Path) -> MigrationConfig:
    raw = yaml.safe_load(_interpolate(Path(path).read_text()))
    return MigrationConfig.model_validate(raw)
