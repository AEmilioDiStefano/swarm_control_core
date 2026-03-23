#!/usr/bin/env python3

"""
Optional ExecutePlaybook action compatibility.

This module isolates the optional external action dependency so the execution
substrate can use neutral "playbook action" naming internally while remaining
compatible with existing ROS action packages when they are installed.
"""

from __future__ import annotations

from typing import List


try:
    from fleet_orchestrator_interfaces.action import ExecutePlaybook

    HAS_PLAYBOOK_ACTION = True
except Exception:
    HAS_PLAYBOOK_ACTION = False

    class ExecutePlaybook:  # type: ignore[override]
        class Goal:
            def __init__(self):
                self.intent_id = ""
                self.command_id = ""
                self.vehicle_ids: List[str] = []
                self.parameters_json = ""
                self.north_m = 0.0
                self.east_m = 0.0


PLAYBOOK_ACTION_TYPE = "fleet_orchestrator_interfaces/action/ExecutePlaybook"
PLAYBOOK_ACTION_SEND_GOAL_TYPE = (
    "fleet_orchestrator_interfaces/action/ExecutePlaybook_SendGoal"
)
