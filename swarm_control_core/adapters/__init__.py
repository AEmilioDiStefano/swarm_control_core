#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

"""
Adapter boundary package.

Adapters provide compatibility translation between external systems and
runtime/playbook contract payloads.
"""

from .base import AdapterContract, AdapterError
from .passthrough import PassthroughAdapter
from .registry import default_adapter_registry, get_adapter, list_adapters, register_adapter

__all__ = [
    "AdapterContract",
    "AdapterError",
    "PassthroughAdapter",
    "default_adapter_registry",
    "register_adapter",
    "get_adapter",
    "list_adapters",
]
