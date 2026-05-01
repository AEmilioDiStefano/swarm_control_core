#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

from __future__ import annotations

import argparse
from typing import List, Optional

from .configure_robot_profile import main as configure_robot_profile_main


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Add or update one robot from the canonical robot_instances.yaml entry, "
            "then sync runtime core profiles and camera profile state."
        )
    )
    parser.add_argument("--workspace", default="", help="Workspace root containing src/swarm_control_core")
    parser.add_argument("--name", "--robot", dest="robot", default="", help="Robot name, e.g. robot4")
    parser.add_argument("--host", default="", help="SSH target host, e.g. legion4.local or robot4@legion4.local")
    parser.add_argument("--control-type", default="", help="Control type, e.g. diff_drive")
    parser.add_argument("--control-interface", default="", help="Hardware/control interface, e.g. dual_l298n_diff")
    parser.add_argument(
        "--skip-camera",
        action="store_true",
        help="Skip interactive camera discovery; run save_camera_profile_core later.",
    )
    parser.add_argument(
        "--no-update-existing",
        action="store_true",
        help="Do not update an existing robot entry even if explicit type/interface args are provided.",
    )
    parser.add_argument(
        "--update-source-baseline",
        action="store_true",
        help=(
            "Also write src/swarm_control_core/config/robot_instances.yaml. "
            "Default writes runtime config only so robot git checkouts stay clean."
        ),
    )
    args = parser.parse_args(argv)

    linux_username = ""
    hostname = ""
    host = str(args.host or "").strip()
    if host:
        if "@" in host:
            linux_username, hostname = host.split("@", 1)
        else:
            hostname = host
        if hostname.endswith(".local"):
            hostname = hostname[:-6]

    forwarded = [
        "--workspace",
        str(args.workspace or ""),
        "--robot",
        str(args.robot or ""),
        "--control-type",
        str(args.control_type or ""),
        "--control-interface",
        str(args.control_interface or ""),
        "--linux-username",
        linux_username,
        "--hostname",
        hostname,
    ]
    if not args.no_update_existing:
        forwarded.append("--update-existing")
    if args.update_source_baseline:
        forwarded.append("--update-source-baseline")
    if args.skip_camera:
        forwarded.append("--skip-camera-profile")

    return configure_robot_profile_main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
