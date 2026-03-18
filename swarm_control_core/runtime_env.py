#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""
Runtime environment defaults for community stack entrypoints.
"""

from __future__ import annotations

import os
from typing import Tuple

DEFAULT_ROS_DOMAIN_ID = "17"


def ensure_ros_domain_id(default_value: str = DEFAULT_ROS_DOMAIN_ID) -> Tuple[str, bool]:
    """
    Ensure ROS_DOMAIN_ID is set for this process.

    Returns:
      (domain_id_value, was_defaulted)
    """
    current = str(os.environ.get("ROS_DOMAIN_ID", "")).strip()
    if current:
        return current, False
    value = str(default_value).strip() or DEFAULT_ROS_DOMAIN_ID
    os.environ["ROS_DOMAIN_ID"] = value
    return value, True

