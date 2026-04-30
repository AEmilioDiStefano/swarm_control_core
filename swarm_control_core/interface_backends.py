#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Set


@dataclass(frozen=True)
class InterfaceBackendSchema:
    name: str
    gpio_layouts: Dict[str, Set[str]]


_INTERFACE_BACKENDS: Dict[str, InterfaceBackendSchema] = {}


def register_interface_backend(name: str, gpio_layouts: Dict[str, Iterable[str]]) -> None:
    key = str(name or "").strip()
    if not key:
        raise ValueError("Interface backend name cannot be empty")
    _INTERFACE_BACKENDS[key] = InterfaceBackendSchema(
        name=key,
        gpio_layouts={layout: set(keys) for layout, keys in gpio_layouts.items()},
    )


def get_interface_backend(name: str) -> InterfaceBackendSchema | None:
    return _INTERFACE_BACKENDS.get(str(name or "").strip())


def registered_backend_names() -> tuple[str, ...]:
    return tuple(sorted(_INTERFACE_BACKENDS))


register_interface_backend(
    "gpio_hbridge",
    {
        "side_pair": {
            "en_left",
            "in1_left",
            "in2_left",
            "en_right",
            "in1_right",
            "in2_right",
        },
        "front_pair": {
            "fl_pwm",
            "fl_in1",
            "fl_in2",
            "fr_pwm",
            "fr_in1",
            "fr_in2",
        },
        "four_wheel": {
            "fl_pwm",
            "fl_in1",
            "fl_in2",
            "fr_pwm",
            "fr_in1",
            "fr_in2",
            "rl_pwm",
            "rl_in1",
            "rl_in2",
            "rr_pwm",
            "rr_in1",
            "rr_in2",
        },
    },
)
