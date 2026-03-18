#!/usr/bin/env python3
"""
swarm_camera_node.py

Canonical camera node entrypoint for swarm_control_core.

This delegates to the adapter-backed camera pipeline in `camera_adapter.py`.
"""

from .camera_adapter import main


if __name__ == '__main__':
    main()
