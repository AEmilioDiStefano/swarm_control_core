#!/usr/bin/env python3
"""
camera_autonomy_node.py

Camera-driven autonomy primitives for ground robots:
- detect: run lightweight perception and publish status only
- follow: follow the largest detected person/blob in frame
- patrol: forward motion with camera-reactive obstacle avoidance
- manual: autonomy disabled (holds still)

This node is intentionally conservative and preemptible:
- Human override (/robot/human_override) always wins.
- If camera frames go stale, robot is stopped immediately.
"""

from __future__ import annotations

import json
import math
import random
import time
from typing import Dict, Optional, Tuple

import cv2
import numpy as np
import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String

from .drive_profiles import load_profile_registry, resolve_robot_profile
from .path_defaults import default_robot_name
from .runtime_env import ensure_ros_domain_id


class CameraAutonomyNode(Node):
    def __init__(self):
        super().__init__("camera_autonomy_node")

        self.declare_parameter("robot_name", "")
        self.declare_parameter("profiles_path", "")
        self.declare_parameter("control_hz", 10.0)
        self.declare_parameter("frame_stale_timeout_s", 1.2)

        self.declare_parameter("follow_target_area_ratio", 0.10)
        self.declare_parameter("follow_kp_yaw", 1.5)
        self.declare_parameter("follow_kp_lin", 1.2)
        self.declare_parameter("follow_search_yaw", 0.5)

        self.declare_parameter("patrol_forward_mps", 0.20)
        self.declare_parameter("patrol_turn_yaw_rps", 0.8)
        self.declare_parameter("patrol_obstacle_edge_ratio", 0.11)
        self.declare_parameter("patrol_turn_sec", 0.9)

        configured_robot_name = str(self.get_parameter("robot_name").value).strip()
        self.robot = configured_robot_name or default_robot_name()
        profiles_path = str(self.get_parameter("profiles_path").value).strip() or None

        self.control_hz = float(self.get_parameter("control_hz").value)
        self.frame_stale_timeout_s = float(self.get_parameter("frame_stale_timeout_s").value)
        self.follow_target_area_ratio = float(self.get_parameter("follow_target_area_ratio").value)
        self.follow_kp_yaw = float(self.get_parameter("follow_kp_yaw").value)
        self.follow_kp_lin = float(self.get_parameter("follow_kp_lin").value)
        self.follow_search_yaw = float(self.get_parameter("follow_search_yaw").value)

        self.patrol_forward_mps = float(self.get_parameter("patrol_forward_mps").value)
        self.patrol_turn_yaw_rps = float(self.get_parameter("patrol_turn_yaw_rps").value)
        self.patrol_obstacle_edge_ratio = float(self.get_parameter("patrol_obstacle_edge_ratio").value)
        self.patrol_turn_sec = float(self.get_parameter("patrol_turn_sec").value)

        # Robot profile metadata is used only for safe defaults and status.
        self.drive_type = "diff_drive"
        self.hardware = "unknown"
        self.profile_name = ""
        try:
            reg = load_profile_registry(profiles_path)
            prof = resolve_robot_profile(reg, self.robot)
            self.drive_type = str(prof.get("drive_type") or self.drive_type)
            self.hardware = str(prof.get("hardware") or self.hardware)
            self.profile_name = str(prof.get("profile_name") or "")
        except FileNotFoundError as ex:
            self.get_logger().error(f"[{self.robot}] Required profile registry missing: {ex}")
            raise
        except Exception:
            pass

        self.image_topic = f"/{self.robot}/camera/image_raw"
        self.cmd_topic = f"/{self.robot}/cmd_vel"
        self.mode_topic = f"/{self.robot}/autonomy/mode"
        self.status_topic = f"/{self.robot}/autonomy/status"
        self.detect_topic = f"/{self.robot}/autonomy/detections"
        self.override_topic = f"/{self.robot}/human_override"

        self.cmd_pub = self.create_publisher(Twist, self.cmd_topic, 10)
        self.status_pub = self.create_publisher(String, self.status_topic, 10)
        self.detect_pub = self.create_publisher(String, self.detect_topic, 10)
        self.create_subscription(Image, self.image_topic, self._on_image, qos_profile_sensor_data)
        self.create_subscription(String, self.mode_topic, self._on_mode, 10)
        self.create_subscription(String, self.override_topic, self._on_override, 20)

        # Autonomy mode state
        self.mode = "manual"
        self._human_override_active = False
        self._latest_frame: Optional[np.ndarray] = None  # BGR
        self._latest_frame_stamp = 0.0
        self._last_detection: Dict[str, float] = {}
        self._turn_until_s = 0.0
        self._turn_sign = 1.0

        # Lightweight person detector (can be CPU-heavy at high resolution).
        self._hog = cv2.HOGDescriptor()
        self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

        self.create_timer(1.0 / max(1.0, self.control_hz), self._control_tick)
        self.create_timer(0.5, self._status_tick)

        self.get_logger().info(
            f"[{self.robot}] camera autonomy ready mode={self.mode} "
            f"image={self.image_topic} cmd={self.cmd_topic} drive={self.drive_type}"
        )

    def _on_mode(self, msg: String):
        raw = str(msg.data or "").strip()
        mode = raw
        if raw.startswith("{"):
            try:
                payload = json.loads(raw)
                mode = str(payload.get("mode", raw))
            except Exception:
                mode = raw
        mode = mode.strip().lower()
        if mode not in ("manual", "follow", "patrol", "detect"):
            return
        self.mode = mode
        # Reset transient patrol state on mode switch.
        self._turn_until_s = 0.0
        self._publish_zero()
        self.get_logger().info(f"[{self.robot}] autonomy mode -> {self.mode}")

    def _on_override(self, msg: String):
        raw = str(msg.data or "").strip().lower()
        active = raw in ("1", "true", "active", "yes")
        if not active and raw.startswith("{"):
            try:
                payload = json.loads(raw)
                active = bool(payload.get("active", False))
            except Exception:
                active = False
        self._human_override_active = bool(active)
        if self._human_override_active:
            self._publish_zero()

    def _on_image(self, msg: Image):
        bgr = self._to_bgr(msg)
        if bgr is None:
            return
        self._latest_frame = bgr
        self._latest_frame_stamp = time.monotonic()

    def _to_bgr(self, msg: Image) -> Optional[np.ndarray]:
        h, w = int(msg.height), int(msg.width)
        if h <= 0 or w <= 0:
            return None
        enc = str(msg.encoding or "").lower().strip()
        data = msg.data

        try:
            if enc == "bgr8":
                return np.frombuffer(data, dtype=np.uint8).reshape((h, w, 3))
            if enc == "rgb8":
                arr = np.frombuffer(data, dtype=np.uint8).reshape((h, w, 3))
                return arr[:, :, ::-1]
            if enc == "mono8":
                g = np.frombuffer(data, dtype=np.uint8).reshape((h, w))
                return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)

            expected = h * w * 3
            if len(data) >= expected:
                return np.frombuffer(data[:expected], dtype=np.uint8).reshape((h, w, 3))
        except Exception:
            return None
        return None

    def _publish_zero(self):
        self.cmd_pub.publish(Twist())

    def _clip(self, v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, float(v)))

    def _person_detection(self, frame_bgr: np.ndarray) -> Optional[Tuple[float, float, float]]:
        """
        Return normalized detection summary:
          (center_x_norm, center_y_norm, area_ratio)
        """
        # Resize for CPU stability and consistent detector behavior.
        frame = cv2.resize(frame_bgr, (640, 360))
        rects, _weights = self._hog.detectMultiScale(
            frame,
            winStride=(8, 8),
            padding=(8, 8),
            scale=1.05,
        )
        if len(rects) == 0:
            return None
        # Largest box heuristic.
        x, y, w, h = max(rects, key=lambda r: r[2] * r[3])
        fw, fh = frame.shape[1], frame.shape[0]
        cx = (x + 0.5 * w) / max(1.0, float(fw))
        cy = (y + 0.5 * h) / max(1.0, float(fh))
        area_ratio = (w * h) / max(1.0, float(fw * fh))
        return (cx, cy, area_ratio)

    def _edge_obstacle_metrics(self, frame_bgr: np.ndarray) -> Tuple[float, float, float]:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        roi = gray[int(h * 0.45):, :]
        edges = cv2.Canny(roi, 80, 160)
        # Global and side-specific edge occupancy ratios.
        edge_ratio = float(np.count_nonzero(edges)) / max(1.0, float(edges.size))
        left = edges[:, : w // 2]
        right = edges[:, w // 2 :]
        left_ratio = float(np.count_nonzero(left)) / max(1.0, float(left.size))
        right_ratio = float(np.count_nonzero(right)) / max(1.0, float(right.size))
        return edge_ratio, left_ratio, right_ratio

    def _detect_tick(self, frame_bgr: np.ndarray):
        det = self._person_detection(frame_bgr)
        if det is None:
            self._last_detection = {"found": 0.0}
            msg = String()
            msg.data = json.dumps(
                {"robot": self.robot, "found": False, "ts": time.time()},
                separators=(",", ":"),
            )
            self.detect_pub.publish(msg)
            return
        cx, cy, area = det
        self._last_detection = {"found": 1.0, "cx": cx, "cy": cy, "area": area}
        msg = String()
        msg.data = json.dumps(
            {
                "robot": self.robot,
                "found": True,
                "cx_norm": cx,
                "cy_norm": cy,
                "area_ratio": area,
                "ts": time.time(),
            },
            separators=(",", ":"),
        )
        self.detect_pub.publish(msg)

    def _follow_tick(self, frame_bgr: np.ndarray):
        det = self._person_detection(frame_bgr)
        if det is None:
            # Search behavior: rotate slowly to reacquire target.
            t = Twist()
            t.angular.z = self._clip(self.follow_search_yaw, -1.2, 1.2)
            self.cmd_pub.publish(t)
            self._last_detection = {"found": 0.0}
            return

        cx, _cy, area = det
        err_x = (cx - 0.5) / 0.5
        err_area = float(self.follow_target_area_ratio - area)

        yaw = self._clip(-self.follow_kp_yaw * err_x, -1.5, 1.5)
        lin = self._clip(self.follow_kp_lin * err_area, -0.25, 0.35)
        # If target is far from center, prioritize alignment over forward motion.
        if abs(err_x) > 0.25:
            lin *= 0.35

        t = Twist()
        t.linear.x = lin
        t.angular.z = yaw
        self.cmd_pub.publish(t)
        self._last_detection = {"found": 1.0, "cx": cx, "area": area, "lin": lin, "yaw": yaw}

    def _patrol_tick(self, frame_bgr: np.ndarray):
        edge_ratio, left_ratio, right_ratio = self._edge_obstacle_metrics(frame_bgr)
        now_mono = time.monotonic()

        if now_mono < self._turn_until_s:
            t = Twist()
            t.angular.z = self._turn_sign * self.patrol_turn_yaw_rps
            self.cmd_pub.publish(t)
            self._last_detection = {
                "mode": "patrol_turn",
                "edge_ratio": edge_ratio,
                "left": left_ratio,
                "right": right_ratio,
            }
            return

        if edge_ratio > self.patrol_obstacle_edge_ratio:
            # Turn toward lower edge density side (simple free-space heuristic).
            # Positive angular.z is left turn in ROS.
            if right_ratio < left_ratio:
                self._turn_sign = -1.0  # turn right
            elif left_ratio < right_ratio:
                self._turn_sign = 1.0  # turn left
            else:
                self._turn_sign = random.choice([-1.0, 1.0])
            self._turn_until_s = now_mono + self.patrol_turn_sec

            t = Twist()
            t.angular.z = self._turn_sign * self.patrol_turn_yaw_rps
            self.cmd_pub.publish(t)
            self._last_detection = {
                "mode": "patrol_avoid",
                "edge_ratio": edge_ratio,
                "left": left_ratio,
                "right": right_ratio,
                "turn_sign": self._turn_sign,
            }
            return

        t = Twist()
        t.linear.x = self.patrol_forward_mps
        self.cmd_pub.publish(t)
        self._last_detection = {
            "mode": "patrol_forward",
            "edge_ratio": edge_ratio,
            "left": left_ratio,
            "right": right_ratio,
        }

    def _control_tick(self):
        if self._human_override_active:
            self._publish_zero()
            return

        if self.mode == "manual":
            self._publish_zero()
            return

        frame = self._latest_frame
        age = time.monotonic() - float(self._latest_frame_stamp)
        if frame is None or age > self.frame_stale_timeout_s:
            self._publish_zero()
            return

        if self.mode == "detect":
            self._detect_tick(frame)
            self._publish_zero()
            return
        if self.mode == "follow":
            self._follow_tick(frame)
            return
        if self.mode == "patrol":
            self._patrol_tick(frame)
            return

        self._publish_zero()

    def _status_tick(self):
        payload = {
            "robot": self.robot,
            "mode": self.mode,
            "human_override": bool(self._human_override_active),
            "drive_type": self.drive_type,
            "hardware": self.hardware,
            "profile": self.profile_name,
            "frame_age_s": max(0.0, time.monotonic() - float(self._latest_frame_stamp)),
            "last_detection": self._last_detection,
            "ts": time.time(),
        }
        msg = String()
        msg.data = json.dumps(payload, separators=(",", ":"))
        self.status_pub.publish(msg)


def main(args=None):
    ensure_ros_domain_id()
    rclpy.init(args=args)
    node = CameraAutonomyNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
