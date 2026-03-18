#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""
Base adapter contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping


class AdapterError(RuntimeError):
    """Raised when an adapter cannot translate an external payload."""


class AdapterContract(ABC):
    """
    Stable adapter interface for third-party integration boundaries.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique adapter name."""

    @abstractmethod
    def supported_schema_versions(self) -> set[str]:
        """Return accepted schema versions."""

    @abstractmethod
    def adapter_capabilities(self) -> Mapping[str, Any]:
        """Return adapter metadata and translation capabilities."""

    @abstractmethod
    def translate_external_task(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Translate external task payload into fleet-contract task assignment."""

    @abstractmethod
    def translate_external_state(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Translate external robot state payload into fleet-contract state."""
