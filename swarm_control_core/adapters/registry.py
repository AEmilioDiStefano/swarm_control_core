#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

"""
Adapter registry for compatibility modules.
"""

from __future__ import annotations

from typing import Dict, Iterable

from .base import AdapterContract
from .passthrough import PassthroughAdapter


class AdapterRegistry:
    """In-memory adapter registry."""

    def __init__(self):
        self._adapters: Dict[str, AdapterContract] = {}

    def register(self, adapter: AdapterContract, *, replace: bool = False) -> None:
        name = str(adapter.name).strip()
        if not name:
            raise ValueError("Adapter name must be non-empty")
        if name in self._adapters and not replace:
            raise ValueError(f"Adapter '{name}' already registered")
        self._adapters[name] = adapter

    def get(self, name: str) -> AdapterContract:
        key = str(name or "").strip()
        if key not in self._adapters:
            known = ", ".join(sorted(self._adapters.keys())) or "<none>"
            raise KeyError(f"Unknown adapter '{key}'. Known adapters: {known}")
        return self._adapters[key]

    def list_names(self) -> Iterable[str]:
        return tuple(sorted(self._adapters.keys()))


default_adapter_registry = AdapterRegistry()
default_adapter_registry.register(PassthroughAdapter(), replace=True)


def register_adapter(adapter: AdapterContract, *, replace: bool = False) -> None:
    default_adapter_registry.register(adapter, replace=replace)


def get_adapter(name: str) -> AdapterContract:
    return default_adapter_registry.get(name)


def list_adapters() -> tuple[str, ...]:
    return tuple(default_adapter_registry.list_names())
