#!/usr/bin/env python3
import time
import logging
import os
import json

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from geometry_msgs.msg import Twist
from std_msgs.msg import String

from .drive_profiles import load_profile_registry, resolve_robot_profile
from .hardware_interface import HardwareInterface
from .drive_types import get_drive_type
from .audit_logger import AuditLogger
from .path_defaults import default_robot_name
from .runtime_env import ensure_ros_domain_id

LOG = logging.getLogger("motor_driver_node")

CMD_VEL_QOS = QoSProfile(
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
)


class MotorDriverNode(Node):
    def __init__(self):
        super().__init__("motor_driver_node")

        # Robot naming
        self.declare_parameter("robot_name", "")
        configured_robot_name = str(self.get_parameter("robot_name").value).strip()
        self.robot_name = configured_robot_name or default_robot_name()

        # Profile registry path (optional)
        self.declare_parameter("profiles_path", "")
        profiles_path = str(self.get_parameter("profiles_path").value).strip() or None

        gpio_map = {}
        drive_params = {}
        hw_params = {}
        self.drive_type = "diff_drive"
        self.hardware_profile = "unknown"
        try:
            reg = load_profile_registry(profiles_path)
            prof = resolve_robot_profile(reg, self.robot_name)
            gpio_map = prof.get("gpio", {}) or {}
            drive_params = prof.get("drive_params", {}) or {}
            hw_params = prof.get("hardware_params", {}) or {}
            self.drive_type = str(prof.get("drive_type") or "diff_drive").lower()
            self.hardware_profile = str(prof.get("hardware") or "unknown")
            self.get_logger().info(f"[{self.robot_name}] Loaded GPIO map from profile: {list(gpio_map.keys())}")
        except FileNotFoundError as ex:
            self.get_logger().error(f"[{self.robot_name}] Required profile registry missing: {ex}")
            raise
        except Exception as ex:
            # Log the exception; drive_profiles.py should have already tried fallbacks.
            self.get_logger().warning(f"[{self.robot_name}] Failed to load profile registry: {ex}")
            self.get_logger().warning(f"[{self.robot_name}] Will run in mock hardware mode. To fix, pass profiles_path parameter or rebuild package.")

        # Parameters (YAML defaults, ROS params override)
        wheel_sep_default = (
            drive_params.get("wheel_separation_m")
            or drive_params.get("wheel_base_m")
            or 0.18
        )
        wheel_base_default = drive_params.get("wheel_base_m") or wheel_sep_default
        track_width_default = drive_params.get("track_width_m") or wheel_sep_default
        max_lin_default = drive_params.get("max_linear_mps") or 0.4
        max_ang_default = drive_params.get("max_angular_rps") or 2.0
        max_pwm_default = hw_params.get("max_pwm") or 100
        pwm_hz_default = hw_params.get("pwm_hz") or 1000
        pwm_ramp_ms_default = hw_params.get("pwm_ramp_ms") or 0
        pwm_deadband_default = hw_params.get("pwm_deadband_pct") or 0
        cmd_rate_hz_default = hw_params.get("cmd_rate_hz") or 0
        pwm_slew_default = hw_params.get("pwm_slew_pct_per_s") or 0
        timeout_default = drive_params.get("watchdog_timeout_s") or 0.5
        spin_mult_default = drive_params.get("spin_speed_mult") or 0.7
        stall_timeout_default = drive_params.get("stall_timeout_s") or 0.0
        stall_duty_default = drive_params.get("stall_duty_pct") or 0.0
        # Optional open-loop left/right trim for diff-drive straightness tuning.
        left_speed_scale_default = drive_params.get("left_speed_scale") or 1.0
        right_speed_scale_default = drive_params.get("right_speed_scale") or 1.0
        strict_single_pub_default = bool(hw_params.get("strict_single_cmd_vel_publisher") or False)
        strict_exempt_default_raw = hw_params.get("strict_cmd_vel_exempt_publishers")
        strict_exempt_default = ["unit_executor_action_server"]
        if isinstance(strict_exempt_default_raw, list):
            cleaned = [str(x).strip() for x in strict_exempt_default_raw if str(x).strip()]
            if cleaned:
                strict_exempt_default = cleaned
        elif isinstance(strict_exempt_default_raw, str):
            cleaned = [x.strip() for x in strict_exempt_default_raw.split(",") if x.strip()]
            if cleaned:
                strict_exempt_default = cleaned
        rotate_bypass_default_raw = hw_params.get("allow_rotate_bypass_safety")
        if rotate_bypass_default_raw is None:
            rotate_bypass_default = True
        else:
            rotate_bypass_default = bool(rotate_bypass_default_raw)
        motor_diag_hz_default = hw_params.get("motor_diagnostics_hz") or 2.0

        self.declare_parameter("wheel_separation", float(wheel_sep_default))   # meters
        self.declare_parameter("wheel_base", float(wheel_base_default))       # meters (mecanum)
        self.declare_parameter("track_width", float(track_width_default))     # meters (mecanum)
        self.declare_parameter("max_linear_speed", float(max_lin_default))    # m/s
        self.declare_parameter("max_angular_speed", float(max_ang_default))   # rad/s
        self.declare_parameter("max_pwm", int(max_pwm_default))               # percent
        self.declare_parameter("pwm_hz", int(pwm_hz_default))                 # Hz
        self.declare_parameter("pwm_ramp_ms", float(pwm_ramp_ms_default))
        self.declare_parameter("pwm_deadband_pct", float(pwm_deadband_default))
        self.declare_parameter("cmd_rate_hz", float(cmd_rate_hz_default))
        self.declare_parameter("pwm_slew_pct_per_s", float(pwm_slew_default))
        self.declare_parameter("watchdog_timeout_s", float(timeout_default))
        self.declare_parameter("spin_speed_mult", float(spin_mult_default))
        self.declare_parameter("stall_timeout_s", float(stall_timeout_default))
        self.declare_parameter("stall_duty_pct", float(stall_duty_default))
        self.declare_parameter("left_speed_scale", float(left_speed_scale_default))
        self.declare_parameter("right_speed_scale", float(right_speed_scale_default))
        self.declare_parameter("strict_single_cmd_vel_publisher", bool(strict_single_pub_default))
        self.declare_parameter("strict_cmd_vel_exempt_publishers", list(strict_exempt_default))
        self.declare_parameter("allow_rotate_bypass_safety", bool(rotate_bypass_default))
        self.declare_parameter("motor_diagnostics_hz", float(motor_diag_hz_default))

        # Topic this robot listens to
        self.declare_parameter("cmd_vel_topic", f"/{self.robot_name}/cmd_vel")
        self.cmd_vel_topic = self.get_parameter("cmd_vel_topic").value.strip() or f"/{self.robot_name}/cmd_vel"

        # Normalize common profile naming and initialize hardware interface.
        # For mecanum/omni we keep 4-channel names intact (fl/fr/rl/rr).
        gpio_map = self._normalize_gpio_map(gpio_map, drive_type=self.drive_type)
        # Pass PWM frequency through the gpio_map for HardwareInterface
        gpio_map["pwm_hz"] = int(self.get_parameter("pwm_hz").value)
        gpio_map["pwm_ramp_ms"] = float(self.get_parameter("pwm_ramp_ms").value)
        gpio_map["pwm_slew_pct_per_s"] = float(self.get_parameter("pwm_slew_pct_per_s").value)
        self.hw = HardwareInterface(gpio_map)
        self.drive = get_drive_type(self.drive_type)

        # Subscriber
        self.subscription = self.create_subscription(
            Twist,
            self.cmd_vel_topic,
            self.cmd_vel_callback,
            CMD_VEL_QOS,
        )

        # Watchdog
        self.last_cmd_time = time.time()
        self.last_output_time = 0.0
        self._last_commanded = None  # (left_duty, left_dir, right_duty, right_dir)
        # Stall protection: time-based limiter to avoid grinding motors under load.
        self._stall_start_time = None
        self._stall_active = False
        self._stall_timeout_s = float(self.get_parameter("stall_timeout_s").value)
        self._stall_duty_pct = float(self.get_parameter("stall_duty_pct").value)
        self.cmd_rate_hz = float(self.get_parameter("cmd_rate_hz").value)
        self.min_cmd_period = (1.0 / self.cmd_rate_hz) if self.cmd_rate_hz > 0 else 0.0
        self.timeout_sec = float(self.get_parameter("watchdog_timeout_s").value)
        self.strict_single_cmd_vel_publisher = bool(
            self.get_parameter("strict_single_cmd_vel_publisher").value
        )
        self.strict_cmd_vel_exempt_publishers = tuple(
            str(x).strip()
            for x in (self.get_parameter("strict_cmd_vel_exempt_publishers").value or [])
            if str(x).strip()
        )
        self.allow_rotate_bypass_safety = bool(
            self.get_parameter("allow_rotate_bypass_safety").value
        )
        self._strict_multi_pub_blocked = False
        self._strict_multi_pub_block_count = 0
        self._last_multi_pub_block_log_s = 0.0

        # Command-source/saturation diagnostics.
        self._cmd_vel_pub_count = 0
        self._cmd_vel_pub_nodes = []
        self._cmd_vel_pub_count_total = 0
        self._cmd_vel_pub_nodes_total = []
        self._last_left_clipped = False
        self._last_right_clipped = False
        self._clip_events_total = 0
        self._last_left_duty = 0.0
        self._last_right_duty = 0.0

        self.create_timer(0.1, self._watchdog)
        # Detect command contention (multiple publishers on /<robot>/cmd_vel).
        # This is a common real-world source of "slow", "jerky", or under-rotating
        # behavior because stop/override messages can interleave with motion commands.
        self._last_cmd_pub_signature = None
        self.create_timer(2.0, self._monitor_cmd_vel_publishers)

        # Publish motor command diagnostics for field tuning/safety visibility.
        self.motor_diag_hz = max(0.2, float(self.get_parameter("motor_diagnostics_hz").value))
        self.motor_diag_topic = f"/{self.robot_name}/motor/diagnostics"
        self.motor_diag_pub = self.create_publisher(String, self.motor_diag_topic, 10)
        self.create_timer(1.0 / self.motor_diag_hz, self._publish_motor_diag)

        # Audit logging for DIU compliance
        audit_log_path = os.environ.get("ROBOT_AUDIT_LOG_PATH") or f"/tmp/robot_{self.robot_name}_audit.jsonl"
        self.audit = AuditLogger(self, "motor_driver", audit_log_path)
        # High-rate cmd_vel can flood logs and add latency on constrained robots.
        # Keep audit traceability but throttle repetitive "received" events.
        try:
            self.audit_cmd_vel_min_period_s = max(
                0.0,
                float(os.environ.get("SWARM_CORE_AUDIT_CMD_VEL_MIN_PERIOD_S", "2.0")),
            )
        except Exception:
            self.audit_cmd_vel_min_period_s = 2.0
        self._last_cmd_vel_audit_s = 0.0
        self._suppressed_cmd_vel_audit_count = 0

        self.get_logger().info(f"[{self.robot_name}] Motor driver listening on {self.cmd_vel_topic}")
        self.get_logger().info(
            f"[{self.robot_name}] limits drive_type={self.drive_type} hardware={self.hardware_profile} "
            f"max_linear={float(self.get_parameter('max_linear_speed').value):.3f}mps "
            f"max_angular={float(self.get_parameter('max_angular_speed').value):.3f}radps "
            f"max_pwm={float(self.get_parameter('max_pwm').value):.1f}% "
            f"ramp_ms={float(self.get_parameter('pwm_ramp_ms').value):.1f} "
            f"slew_pct_per_s={float(self.get_parameter('pwm_slew_pct_per_s').value):.1f} "
            f"deadband_pct={float(self.get_parameter('pwm_deadband_pct').value):.1f} "
            f"left_speed_scale={float(self.get_parameter('left_speed_scale').value):.3f} "
            f"right_speed_scale={float(self.get_parameter('right_speed_scale').value):.3f} "
            f"cmd_rate_hz={self.cmd_rate_hz:.1f} "
            f"strict_single_cmd_vel_publisher={self.strict_single_cmd_vel_publisher} "
            f"strict_cmd_vel_exempt_publishers={list(self.strict_cmd_vel_exempt_publishers)} "
            f"allow_rotate_bypass_safety={self.allow_rotate_bypass_safety}"
        )
        self.get_logger().info(
            f"[{self.robot_name}] diagnostics topic={self.motor_diag_topic} "
            f"hz={self.motor_diag_hz:.1f}"
        )
        self.get_logger().info(f"[{self.robot_name}] Audit log: {audit_log_path}")
        self.get_logger().info(
            f"[{self.robot_name}] cmd_vel audit throttle min_period_s={self.audit_cmd_vel_min_period_s:.3f}"
        )

    # --------------------------------------------------

    def _normalize_gpio_map(self, gpio_map: dict, drive_type: str = "diff_drive") -> dict:
        """Normalize different hardware profile key names into a common
        mapping consumed by HardwareInterface (en_left,in1_left,in2_left,en_right,...).

        This keeps motor mixing logic independent of exact profile naming.
        """
        if not gpio_map:
            return {}

        # If mecanum/omni, keep 4-channel map intact
        if str(drive_type).lower() in ("mecanum", "omni", "omnidirectional", "mecanum_drive"):
            return gpio_map

        if all(k in gpio_map for k in ("en_left", "in1_left", "in2_left", "en_right", "in1_right", "in2_right")):
            return dict(gpio_map)

        if all(k in gpio_map for k in ("fl_pwm", "fl_in1", "fl_in2", "fr_pwm", "fr_in1", "fr_in2")):
            return dict(gpio_map)

        mapped = {}
        if "fl_pwm" in gpio_map and "fr_pwm" in gpio_map:
            mapped["en_left"] = gpio_map.get("fl_pwm")
            mapped["in1_left"] = gpio_map.get("fl_in1")
            mapped["in2_left"] = gpio_map.get("fl_in2")

            mapped["en_right"] = gpio_map.get("fr_pwm")
            mapped["in1_right"] = gpio_map.get("fr_in1")
            mapped["in2_right"] = gpio_map.get("fr_in2")
            return mapped

        # L298N_diff (hbridge_2ch) style mapping
        if "en_left" in gpio_map or "in1_left" in gpio_map:
            mapped.update(gpio_map)
            return mapped

        # older-style keys (en_left/en_right names may vary)
        # try common alternative keys
        if "ena" in gpio_map and "enb" in gpio_map:
            mapped["en_left"] = gpio_map.get("ena")
            mapped["en_right"] = gpio_map.get("enb")
            mapped["in1_left"] = gpio_map.get("in1_left")
            mapped["in2_left"] = gpio_map.get("in2_left")
            mapped["in1_right"] = gpio_map.get("in1_right")
            mapped["in2_right"] = gpio_map.get("in2_right")
            return mapped

        # fallback: return original map, HardwareInterface will mock if keys absent
        return gpio_map

    # --------------------------------------------------

    def cmd_vel_callback(self, msg: Twist):
        self.last_cmd_time = time.time()
        start_time = time.time()

        wheel_sep = float(self.get_parameter("wheel_separation").value)
        max_lin = float(self.get_parameter("max_linear_speed").value)
        max_ang = float(self.get_parameter("max_angular_speed").value)
        is_stop_cmd = (
            abs(float(msg.linear.x)) < 1e-6
            and abs(float(msg.linear.y)) < 1e-6
            and abs(float(msg.angular.z)) < 1e-6
        )

        if self.strict_single_cmd_vel_publisher and self._cmd_vel_pub_count > 1:
            self._strict_multi_pub_blocked = not is_stop_cmd
            if not is_stop_cmd:
                self._strict_multi_pub_block_count += 1
                now = time.time()
                if (now - self._last_multi_pub_block_log_s) >= 1.0:
                    self._last_multi_pub_block_log_s = now
                    self.get_logger().error(
                        f"[{self.robot_name}] strict mode blocking non-stop cmd_vel while "
                        f"{self._cmd_vel_pub_count} publishers are active"
                    )
                self._set_motor_outputs(0.0, 0.0, force=True)
                return
        else:
            self._strict_multi_pub_blocked = False

        # Log motor command for audit trail (throttled to avoid high-rate log/IO overhead).
        t_now = time.time()
        do_audit = (
            self.audit_cmd_vel_min_period_s <= 0.0
            or (t_now - self._last_cmd_vel_audit_s) >= self.audit_cmd_vel_min_period_s
        )
        if do_audit:
            details = None
            if self._suppressed_cmd_vel_audit_count > 0:
                details = f"suppressed_cmd_vel_events={self._suppressed_cmd_vel_audit_count}"
            self.audit.log_command(
                robot=self.robot_name,
                source="cmd_vel",
                command_id="twist",
                parameters={"linear_x": float(msg.linear.x), "angular_z": float(msg.angular.z)},
                status="received",
                details=details,
                duration_s=t_now - start_time,
            )
            self._last_cmd_vel_audit_s = t_now
            self._suppressed_cmd_vel_audit_count = 0
        else:
            self._suppressed_cmd_vel_audit_count += 1

        # Centralized drive-type mixing
        params = {
            "wheel_separation": wheel_sep,
            "wheel_base": float(self.get_parameter("wheel_base").value),
            "track_width": float(self.get_parameter("track_width").value),
            "max_linear_speed": max_lin,
            "max_angular_speed": max_ang,
            "spin_speed_mult": float(self.get_parameter("spin_speed_mult").value),
        }
        cmd = self.drive.mix(msg, params)
        if cmd.left is not None and cmd.right is not None:
            # Optional legacy behavior: bypass ramp/deadband on in-place rotate.
            # Keep this configurable so safety-first robots can disable it.
            is_rotate = abs(cmd.left) > 1e-6 and abs(cmd.right) > 1e-6 and (cmd.left * cmd.right) < 0
            self._set_motor_outputs(
                cmd.left,
                cmd.right,
                bypass_safety=(is_rotate and self.allow_rotate_bypass_safety),
            )
        else:
            self._set_mecanum_outputs(cmd)

    # --------------------------------------------------

    def _watchdog(self):
        if time.time() - self.last_cmd_time > self.timeout_sec:
            if str(self.drive_type).lower() in ("mecanum", "omni", "omnidirectional", "mecanum_drive"):
                self._set_mecanum_stop(force=True)
            else:
                self._set_motor_outputs(0.0, 0.0, force=True)

    def _is_exempt_cmd_vel_publisher(self, node_name: str) -> bool:
        """
        True if publisher should be ignored by strict cmd_vel gating.
        Match either full node path (/ns/name) or base node name (name).
        """
        full = str(node_name or "").strip()
        if not full:
            return False
        base = full.split("/")[-1]
        for token in self.strict_cmd_vel_exempt_publishers:
            t = str(token or "").strip()
            if not t:
                continue
            if full == t or base == t:
                return True
        return False

    def _is_unknown_cmd_vel_publisher(self, node_name: str) -> bool:
        full = str(node_name or "").strip()
        if not full:
            return True
        if full == "unknown_node":
            return True
        upper = full.upper()
        return ("_NODE_NAMESPACE_UNKNOWN_" in upper) or ("_NODE_NAME_UNKNOWN_" in upper)

    def _monitor_cmd_vel_publishers(self):
        """
        Warn when multiple nodes publish to this robot's cmd_vel topic.

        Why this matters:
        - Teleop, playbook execution, FPV UI, or autonomy can all publish Twist.
        - If more than one publishes concurrently, motion gets clobbered and can
          look extremely slow or inconsistent (many quick stop/move alternations).
        """
        try:
            infos = self.get_publishers_info_by_topic(self.cmd_vel_topic)
        except Exception:
            return

        pub_nodes = []
        for info in infos:
            try:
                ns = str(getattr(info, "node_namespace", "") or "").rstrip("/")
                nm = str(getattr(info, "node_name", "") or "")
                full = f"{ns}/{nm}" if ns else nm
            except Exception:
                full = "unknown_node"
            pub_nodes.append(full)
        # Deduplicate endpoint rows from ROS graph introspection. Some stacks can
        # expose multiple writers under the same node identity.
        all_pub_nodes = sorted({p for p in pub_nodes if p})
        known_pub_nodes = sorted({p for p in all_pub_nodes if not self._is_unknown_cmd_vel_publisher(p)})
        if known_pub_nodes:
            all_pub_nodes = known_pub_nodes
        effective_pub_nodes = sorted({p for p in all_pub_nodes if not self._is_exempt_cmd_vel_publisher(p)})
        display_nodes = effective_pub_nodes or ["none"]
        self._cmd_vel_pub_count_total = len(all_pub_nodes)
        self._cmd_vel_pub_nodes_total = list(all_pub_nodes)
        self._cmd_vel_pub_count = len(effective_pub_nodes)
        self._cmd_vel_pub_nodes = list(effective_pub_nodes)

        signature = (
            len(all_pub_nodes),
            tuple(all_pub_nodes),
            len(effective_pub_nodes),
            tuple(effective_pub_nodes),
        )
        if signature == self._last_cmd_pub_signature:
            return
        self._last_cmd_pub_signature = signature

        if self._cmd_vel_pub_count > 1:
            self.get_logger().warning(
                f"[{self.robot_name}] Multiple effective cmd_vel publishers on {self.cmd_vel_topic}: "
                f"{', '.join(display_nodes)}"
            )
            self.get_logger().warning(
                f"[{self.robot_name}] Motion may be clobbered; keep only one active controller. "
                f"strict_single_cmd_vel_publisher={self.strict_single_cmd_vel_publisher}"
            )
        else:
            self.get_logger().info(
                f"[{self.robot_name}] cmd_vel effective publisher set: {', '.join(display_nodes)}"
            )
        if len(all_pub_nodes) != len(effective_pub_nodes):
            ignored = sorted({p for p in all_pub_nodes if p not in effective_pub_nodes})
            self.get_logger().info(
                f"[{self.robot_name}] cmd_vel strict-exempt publishers ignored: {', '.join(ignored)}"
            )

    def _publish_motor_diag(self):
        payload = {
            "robot": self.robot_name,
            "drive_type": self.drive_type,
            "hardware_profile": self.hardware_profile,
            "cmd_vel_topic": self.cmd_vel_topic,
            "cmd_vel_publishers_count_total": int(self._cmd_vel_pub_count_total),
            "cmd_vel_publishers_total": list(self._cmd_vel_pub_nodes_total),
            "cmd_vel_publishers_count": int(self._cmd_vel_pub_count),
            "cmd_vel_publishers": list(self._cmd_vel_pub_nodes),
            "strict_single_cmd_vel_publisher": bool(self.strict_single_cmd_vel_publisher),
            "strict_cmd_vel_exempt_publishers": list(self.strict_cmd_vel_exempt_publishers),
            "allow_rotate_bypass_safety": bool(self.allow_rotate_bypass_safety),
            "strict_blocking_active": bool(self._strict_multi_pub_blocked),
            "strict_block_count": int(self._strict_multi_pub_block_count),
            "clip_events_total": int(self._clip_events_total),
            "last_left_clipped": bool(self._last_left_clipped),
            "last_right_clipped": bool(self._last_right_clipped),
            "last_left_duty_pct": float(self._last_left_duty),
            "last_right_duty_pct": float(self._last_right_duty),
            "max_linear_speed": float(self.get_parameter("max_linear_speed").value),
            "max_angular_speed": float(self.get_parameter("max_angular_speed").value),
            "max_pwm": float(self.get_parameter("max_pwm").value),
            "pwm_ramp_ms": float(self.get_parameter("pwm_ramp_ms").value),
            "pwm_deadband_pct": float(self.get_parameter("pwm_deadband_pct").value),
            "pwm_slew_pct_per_s": float(self.get_parameter("pwm_slew_pct_per_s").value),
            "cmd_rate_hz": float(self.get_parameter("cmd_rate_hz").value),
            "timestamp_s": time.time(),
        }
        msg = String()
        msg.data = json.dumps(payload, separators=(",", ":"))
        self.motor_diag_pub.publish(msg)

    # --------------------------------------------------

    def _set_motor_outputs(self, v_left: float, v_right: float, force: bool = False, bypass_safety: bool = False):
        # Convert speeds to duty+direction and delegate to hardware interface
        max_lin = float(self.get_parameter("max_linear_speed").value)
        max_pwm = float(self.get_parameter("max_pwm").value)
        deadband = float(self.get_parameter("pwm_deadband_pct").value)
        left_scale = float(self.get_parameter("left_speed_scale").value)
        right_scale = float(self.get_parameter("right_speed_scale").value)
        left_scale = max(0.6, min(1.4, left_scale))
        right_scale = max(0.6, min(1.4, right_scale))

        # Optional straightness trim for differential drives.
        v_left *= left_scale
        v_right *= right_scale

        if bypass_safety:
            deadband = 0.0
        deadband = max(0.0, min(deadband, max_pwm))

        def speed_to_pwm(v):
            raw_ratio = float(v / max_lin) if max_lin > 1e-9 else 0.0
            clipped = abs(raw_ratio) > 1.0
            ratio = max(-1.0, min(1.0, raw_ratio))
            direction = 1 if ratio >= 0 else -1
            duty = abs(ratio) * max_pwm
            if duty > 0.0 and duty < deadband:
                duty = 0.0
            return duty, direction, clipped

        left_duty, left_dir, left_clipped = speed_to_pwm(v_left)
        right_duty, right_dir, right_clipped = speed_to_pwm(v_right)
        self._last_left_clipped = bool(left_clipped)
        self._last_right_clipped = bool(right_clipped)
        if left_clipped or right_clipped:
            self._clip_events_total += 1
        self._last_left_duty = float(left_duty)
        self._last_right_duty = float(right_duty)

        now = time.time()
        if not force and self.min_cmd_period > 0 and (now - self.last_output_time) < self.min_cmd_period:
            # If a NEW command arrives quickly, we still apply it immediately
            # so the most recent command always wins (no ambiguity).
            last = self._last_commanded
            changed = (
                last is None
                or abs(left_duty - last[0]) > 0.5
                or abs(right_duty - last[2]) > 0.5
                or left_dir != last[1]
                or right_dir != last[3]
            )
            if not changed:
                return

        # --- Stall protection (time-based)
        # If duty is high for too long, cut output to avoid grinding motors or brownouts.
        if self._stall_timeout_s > 0 and self._stall_duty_pct > 0:
            high_duty = max(left_duty, right_duty) >= self._stall_duty_pct
            if high_duty:
                if self._stall_start_time is None:
                    self._stall_start_time = now
                elif (now - self._stall_start_time) >= self._stall_timeout_s:
                    self._stall_active = True
            else:
                # Reset once commanded duty drops below threshold
                self._stall_start_time = None
                self._stall_active = False

            if self._stall_active and not force:
                left_duty, right_duty = 0.0, 0.0

        # Use the hardware abstraction layer to actually set pins/PWM
        try:
            self.hw.set_motor(left_duty, left_dir, right_duty, right_dir, bypass_ramp=bypass_safety)
            self.last_output_time = now
            self._last_commanded = (left_duty, left_dir, right_duty, right_dir)
        except Exception as e:
            LOG.warning("Failed to set motor outputs: %s", e)

    def _set_mecanum_outputs(self, cmd):
        """Compute mecanum wheel commands and dispatch to hardware interface.

        This keeps drive-type logic contained in the motor driver, while the
        HardwareInterface handles the actual pin/PWM outputs.
        """
        max_lin = float(self.get_parameter("max_linear_speed").value)
        max_pwm = float(self.get_parameter("max_pwm").value)
        deadband = float(self.get_parameter("pwm_deadband_pct").value)
        deadband = max(0.0, min(deadband, max_pwm))

        def speed_to_pwm(v):
            ratio = max(-1.0, min(1.0, v / max_lin))
            direction = 1 if ratio >= 0 else -1
            duty = abs(ratio) * max_pwm
            if duty > 0.0 and duty < deadband:
                duty = 0.0
            return duty, direction

        fl_d, fl_dir = speed_to_pwm(cmd.fl)
        fr_d, fr_dir = speed_to_pwm(cmd.fr)
        rl_d, rl_dir = speed_to_pwm(cmd.rl)
        rr_d, rr_dir = speed_to_pwm(cmd.rr)
        self._last_left_clipped = False
        self._last_right_clipped = False
        self._last_left_duty = float((fl_d + rl_d) * 0.5)
        self._last_right_duty = float((fr_d + rr_d) * 0.5)

        try:
            self.hw.set_mecanum(fl_d, fl_dir, fr_d, fr_dir, rl_d, rl_dir, rr_d, rr_dir)
            self.last_output_time = time.time()
        except Exception as e:
            LOG.warning("Failed to set mecanum outputs: %s", e)

    def _set_mecanum_stop(self, force: bool = False):
        """
        Explicit mecanum stop path used by watchdog and safety handling.
        """
        now = time.time()
        if not force and self.min_cmd_period > 0 and (now - self.last_output_time) < self.min_cmd_period:
            return
        try:
            self.hw.set_mecanum(
                0.0, 1,
                0.0, 1,
                0.0, 1,
                0.0, 1,
                bypass_ramp=True,
            )
            self.last_output_time = now
        except Exception as e:
            LOG.warning("Failed to set mecanum stop outputs: %s", e)

    # --------------------------------------------------

    def destroy_node(self):
        try:
            # Soft-stop on shutdown (honors ramp/slew for gentle hardware stop).
            self._set_motor_outputs(0.0, 0.0, force=True)
        except Exception:
            pass
        try:
            if hasattr(self, "hw"):
                self.hw.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "audit"):
                self.audit.close()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    ensure_ros_domain_id()
    rclpy.init(args=args)
    node = MotorDriverNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
