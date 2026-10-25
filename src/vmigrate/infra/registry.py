"""Adapter discovery via entry points, with built-ins as a fallback for non-installed runs."""

from __future__ import annotations

import importlib
from importlib.metadata import entry_points
from typing import Any

SOURCES_GROUP = "vmigrate.sources"
SINKS_GROUP = "vmigrate.sinks"

_BUILTIN = {
    SOURCES_GROUP: {
        "qdrant": "vmigrate.adapters.qdrant.source:QdrantSource",
        "memory": "vmigrate.adapters.memory:MemorySource",
    },
    SINKS_GROUP: {
        "weaviate": "vmigrate.adapters.weaviate.sink:WeaviateSink",
        "memory": "vmigrate.adapters.memory:MemorySink",
    },
}


def _load(target: str) -> type:
    module_name, _, attr = target.partition(":")
    return getattr(importlib.import_module(module_name), attr)


def available(group: str) -> dict[str, str]:
    found = {ep.name: ep.value for ep in entry_points(group=group)}
    return {**_BUILTIN[group], **found}


def create(group: str, kind: str, options: dict[str, Any]) -> Any:
    adapters = available(group)
    if kind not in adapters:
        raise ValueError(f"unknown {group} adapter '{kind}'; available: {sorted(adapters)}")
    return _load(adapters[kind])(**options)


def create_source(kind: str, options: dict[str, Any]) -> Any:
    return create(SOURCES_GROUP, kind, options)


def create_sink(kind: str, options: dict[str, Any]) -> Any:
    return create(SINKS_GROUP, kind, options)
