#!/usr/bin/env python3
"""Critical flake8 gate: syntax errors and undefined names fail the suite.

Scoped to runtime-breaking findings only (see flake8_critical.ini). An
undefined-name check (F821) in CI would have caught the HAS_FLEET_ACTION
NameError on the unit executor action path the day it was introduced.
"""

from pathlib import Path

import pytest
from ament_flake8.main import main_with_errors


@pytest.mark.flake8
@pytest.mark.linter
def test_flake8_critical():
    """Run the critical-only flake8 profile over all Python surfaces."""
    config_file = Path(__file__).with_name("flake8_critical.ini")
    rc, errors = main_with_errors(
        argv=[
            "--config",
            str(config_file),
            "setup.py",
            "swarm_control_core",
            "swarm_launch",
            "test",
        ]
    )
    assert rc == 0, (
        "Found %d critical code errors:\n" % len(errors) + "\n".join(errors)
    )
