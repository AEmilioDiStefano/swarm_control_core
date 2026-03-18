#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""
Default non-destructive adapter used as a baseline compatibility boundary.
"""

from __future__ import annotations

from typing import Any, Mapping

from .base import AdapterContract


class PassthroughAdapter(AdapterContract):
    """
    No-op adapter that forwards payload shape as-is.
    """

    @property
    def name(self) -> str:
        return "passthrough"

    def supported_schema_versions(self) -> set[str]:
        return {"v1", "v1alpha1", "unknown"}

    def adapter_capabilities(self) -> Mapping[str, Any]:
        return {
            "task_translation": True,
            "state_translation": True,
            "mode": "passthrough",
        }

    def translate_external_task(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return dict(payload or {})

    def translate_external_state(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return dict(payload or {})
