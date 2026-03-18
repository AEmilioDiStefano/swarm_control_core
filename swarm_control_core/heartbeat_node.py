#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .drive_profiles import load_profile_registry, resolve_robot_profile
from .path_defaults import default_robot_name
from .runtime_env import ensure_ros_domain_id


class HeartbeatNode(Node):
    def __init__(self):
        super().__init__("heartbeat_node")

        self.declare_parameter("robot_name", "")
        self.declare_parameter("profiles_path", "")

        # Allow override parameters so a robot can start with explicit drive/hardware
        # without requiring a central registry entry.
        self.declare_parameter("drive_type", "")
        self.declare_parameter("hardware", "")

        configured_robot_name = str(self.get_parameter("robot_name").value).strip()
        self.robot = configured_robot_name or default_robot_name()
        profiles_path = str(self.get_parameter("profiles_path").value).strip() or None

        self.drive_type = None
        self.hardware = None
        self.profile_name = None

        try:
            reg = load_profile_registry(profiles_path)
            prof = resolve_robot_profile(reg, self.robot)
            self.drive_type = prof["drive_type"]
            self.hardware = prof["hardware"]
            self.profile_name = prof["profile_name"]
        except FileNotFoundError as ex:
            self.get_logger().error(f"[{self.robot}] Required profile registry missing: {ex}")
            raise
        except Exception:
            # Fall back to explicit parameters or reasonable defaults
            dt = str(self.get_parameter("drive_type").value).strip()
            hw = str(self.get_parameter("hardware").value).strip()
            if dt:
                self.drive_type = dt
            else:
                self.drive_type = "diff_drive"
            if hw:
                self.hardware = hw
            else:
                self.hardware = "L298N_diff"
            self.profile_name = None
            self.get_logger().warning(f"[{self.robot}] profile not found in registry; publishing heartbeat with drive_type={self.drive_type} hardware={self.hardware}")

        self.topic = f"/{self.robot}/heartbeat"
        self.pub = self.create_publisher(String, self.topic, 10)
        self.create_timer(0.5, self._tick)  # 2 Hz

        self.get_logger().info(f"[{self.robot}] Heartbeat publishing on {self.topic}")
        self.get_logger().info(f"[{self.robot}] drive_type={self.drive_type} hardware={self.hardware} profile={self.profile_name}")

    def _tick(self):
        payload = {
            "robot": self.robot,
            "t": time.time(),
            "drive_type": self.drive_type,
            "hardware": self.hardware,
            "profile": self.profile_name,
        }
        msg = String()
        msg.data = json.dumps(payload, separators=(",", ":"))
        self.pub.publish(msg)


def main(args=None):
    ensure_ros_domain_id()
    rclpy.init(args=args)
    node = HeartbeatNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
