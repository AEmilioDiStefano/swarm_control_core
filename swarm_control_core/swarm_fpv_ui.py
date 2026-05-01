#!/usr/bin/env python3
"""
swarm_fpv_ui.py

Browser-first FPV control surface for heterogeneous robots.

Design goals:
- Main low-latency WebRTC stream for the selected robot.
- Medium thumbnail streams for the rest of the fleet.
- Robot capability-aware controls (diff vs mecanum now, extensible for aerial later).
- Control lock semantics so one operator controls one robot at a time.
- Explicit hooks for autonomy mode commands (manual/follow/patrol/detect).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import ipaddress
import json
import os
import secrets
import socket
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

_MISSING_REQUIRED_DEPS: List[Tuple[str, str, str]] = []

try:
    import aiohttp
    from aiohttp import web
except Exception as e:
    aiohttp = None  # type: ignore[assignment]
    web = None  # type: ignore[assignment]
    _MISSING_REQUIRED_DEPS.append(("aiohttp", "python3-aiohttp", str(e)))

try:
    import numpy as np
except Exception as e:
    np = None  # type: ignore[assignment]
    _MISSING_REQUIRED_DEPS.append(("numpy", "python3-numpy", str(e)))

try:
    from PIL import Image as PILImage
except Exception as e:
    PILImage = None  # type: ignore[assignment]
    _MISSING_REQUIRED_DEPS.append(("Pillow", "python3-pil", str(e)))
import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import String

from .adapter_runtime import (
    resolve_robot_adapter_binding,
    translate_state_for_robot,
    translate_task_for_robot,
)
from .drive_profiles import load_profile_registry, resolve_robot_profile
from .fleet_contracts import (
    fleet_contract_manifest,
    validate_robot_health_event,
    validate_robot_registry_event,
    validate_robot_state_event,
)
from .fleet_state import (
    build_robot_health_event,
    build_robot_registry_event,
    build_robot_state_event,
)
from .fpv_api_contracts import api_schema_info
from .fpv_auth_models import (
    AUTH_MODE_DEV,
    AUTH_MODE_OFF,
    AuthConfig,
    Principal,
    SWARM_SCOPE_CONTROL,
    SWARM_SCOPE_READ,
)
from .fpv_auth_service import build_auth_service
from .path_defaults import MissingConfigError, detect_workspace_root
from .runtime_env import ensure_ros_domain_id

_MISSING_WEBRTC_DEPS: List[Tuple[str, str, str]] = []

try:
    from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
except Exception as e:
    RTCConfiguration = object  # type: ignore[assignment]
    RTCIceServer = object  # type: ignore[assignment]
    RTCPeerConnection = object  # type: ignore[assignment]
    RTCSessionDescription = object  # type: ignore[assignment]
    VideoStreamTrack = object  # type: ignore[assignment]
    _MISSING_WEBRTC_DEPS.append(("aiortc", "python3-aiortc", str(e)))

try:
    from av import VideoFrame
except Exception as e:
    VideoFrame = object  # type: ignore[assignment]
    _MISSING_WEBRTC_DEPS.append(("av", "python3-av", str(e)))

HAS_WEBRTC = len(_MISSING_WEBRTC_DEPS) == 0

HAS_REQUIRED_WEB_DEPS = len(_MISSING_REQUIRED_DEPS) == 0


IMG_CAMERA_RE = re.compile(r"^/([^/]+)/camera/image_raw$")
IMG_FLAT_RE = re.compile(r"^/([^/]+)/image_raw$")
IMG_CAMERA_COMP_RE = re.compile(r"^/([^/]+)/camera/image_raw/compressed$")
IMG_FLAT_COMP_RE = re.compile(r"^/([^/]+)/image_raw/compressed$")
HB_RE = re.compile(r"^/([^/]+)/heartbeat$")


def now_s() -> float:
    return time.time()


def _normalize_image_subscription_mode(raw: Any) -> str:
    v = str(raw or "").strip().lower()
    if v in ("all", "all_robots", "full"):
        return "all"
    return "active_only"


def _no_cache_headers() -> Dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


def _normalize_main_stream_mode(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in ("webrtc_only", "webrtc-only", "webrtc"):
        return "webrtc_only"
    if value in ("jpeg_poll", "jpeg-poll"):
        return "jpeg_poll"
    if value in ("jpeg_only", "jpeg-only", "jpeg"):
        return "jpeg_only"
    return ""


def _request_host_without_port(req: web.Request) -> str:
    host = str(req.headers.get("Host") or req.host or "").strip().lower()
    if host.startswith("[") and "]" in host:
        return host[1 : host.find("]")]
    return re.sub(r":\d+$", "", host)


def _bounded_int(raw: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(raw).strip())
    except Exception:
        value = int(fallback)
    return max(int(minimum), min(int(maximum), value))


def _encode_rgb_to_jpeg_variant(rgb: np.ndarray, max_w: int, max_h: int, quality: int) -> bytes:
    img = PILImage.fromarray(rgb, mode="RGB")

    if max_w > 0 or max_h > 0:
        width, height = img.size
        target_w = max_w if max_w > 0 else width
        target_h = max_h if max_h > 0 else height
        scale = min(float(target_w) / float(width), float(target_h) / float(height), 1.0)
        if scale < 0.999:
            img = img.resize(
                (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
                PILImage.Resampling.BILINEAR if hasattr(PILImage, "Resampling") else PILImage.BILINEAR,
            )

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=int(quality))
    return buf.getvalue()


def _detect_ipv4_addresses() -> List[str]:
    """
    Best-effort discovery of local IPv4 addresses for operator copy/paste.
    """
    out: Set[str] = set()
    out.add("127.0.0.1")

    # Linux-first path (most reliable on Ubuntu).
    try:
        proc = subprocess.run(
            ["ip", "-o", "-4", "addr", "show", "scope", "global", "up"],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.5,
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                # Example:
                # 2: wlp1s0    inet 192.168.8.185/24 brd ...
                parts = line.split()
                if "inet" in parts:
                    idx = parts.index("inet")
                    if idx + 1 < len(parts):
                        cidr = parts[idx + 1]
                        ip = cidr.split("/", 1)[0].strip()
                        if ip:
                            out.add(ip)
    except Exception:
        pass

    # Fallback path if `ip` command is unavailable.
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, 0, socket.IPPROTO_TCP)
        for info in infos:
            ip = str(info[4][0]).strip()
            if ip:
                out.add(ip)
    except Exception:
        pass

    return sorted(out)


def _community_allow_lan_bind() -> bool:
    return str(os.environ.get("SWARM_CORE_ALLOW_LAN_BIND", "0")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    if normalized in ("127.0.0.1", "localhost", "::1"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except Exception:
        return False


def _is_private_or_wildcard_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    if normalized in ("0.0.0.0", "::"):
        return True
    if _is_loopback_host(normalized):
        return True
    try:
        ip = ipaddress.ip_address(normalized)
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local)
    except Exception:
        return False


def _normalize_webrtc_ice_transport_policy(raw_value: Any) -> str:
    policy = str(raw_value or "").strip().lower()
    if policy == "relay":
        return "relay"
    return "all"


def _parse_webrtc_ice_servers_json(raw_value: str) -> Tuple[List[Dict[str, Any]], str]:
    """
    Parse and sanitize a JSON ICE server list.

    Accepted row forms:
    - {"urls":"stun:host:port"}
    - {"urls":["stun:...", "turn:..."], "username":"u", "credential":"p"}
    - "stun:host:port"  (shorthand)
    """
    raw = str(raw_value or "").strip()
    if not raw:
        raw = "[]"

    try:
        parsed = json.loads(raw)
    except Exception:
        return [], "invalid_json"

    if not isinstance(parsed, list):
        return [], "must_be_array"

    out: List[Dict[str, Any]] = []
    for row in parsed:
        urls: List[str] = []
        username = ""
        credential = ""

        if isinstance(row, str):
            v = row.strip()
            if v:
                urls = [v]
        elif isinstance(row, dict):
            urls_raw = row.get("urls", row.get("url", []))
            if isinstance(urls_raw, str):
                v = urls_raw.strip()
                if v:
                    urls = [v]
            elif isinstance(urls_raw, list):
                urls = [str(v).strip() for v in urls_raw if str(v).strip()]

            username = str(row.get("username") or "").strip()
            credential = str(row.get("credential") or "").strip()
        else:
            continue

        if not urls:
            continue

        entry: Dict[str, Any] = {"urls": urls}
        if username:
            entry["username"] = username
        if credential:
            entry["credential"] = credential
        out.append(entry)

    return out, ""


def _webrtc_ice_servers_log_summary(ice_servers: List[Dict[str, Any]]) -> str:
    if not ice_servers:
        return "0 configured"
    rows: List[str] = []
    for idx, row in enumerate(ice_servers, start=1):
        urls = row.get("urls", [])
        if isinstance(urls, str):
            urls_list = [urls]
        else:
            urls_list = [str(v).strip() for v in (urls or []) if str(v).strip()]
        has_turn = any(u.startswith("turn:") or u.startswith("turns:") for u in urls_list)
        has_auth = bool(str(row.get("username") or "").strip() or str(row.get("credential") or "").strip())
        rows.append(f"{idx}:{'TURN' if has_turn else 'STUN'}:{len(urls_list)}url:{'auth' if has_auth else 'noauth'}")
    return ", ".join(rows)


def _webrtc_turn_entry_count(ice_servers: List[Dict[str, Any]]) -> int:
    total = 0
    for row in ice_servers:
        urls = row.get("urls", [])
        if isinstance(urls, str):
            urls_list = [urls]
        else:
            urls_list = [str(v).strip() for v in (urls or []) if str(v).strip()]
        if any(u.lower().startswith("turn:") or u.lower().startswith("turns:") for u in urls_list):
            total += 1
    return total


@dataclass
class ControlLock:
    controller_id: str
    last_heartbeat_s: float
    operator_id: str = ""
    operator_name: str = ""
    session_id: str = ""
    tenant_id: str = ""
    site_id: str = ""


@dataclass
class DevLoginSession:
    session_id: str
    username: str
    subject: str
    created_s: float
    last_seen_s: float
    client_id: str = ""


class RosFleetHub(Node):
    """
    ROS bridge layer for the browser UI.
    """

    def __init__(self):
        super().__init__("swarm_fpv_ui")

        self.declare_parameter("profiles_path", "")
        # Match default low-latency camera clamp (15fps) to avoid redundant
        # frame work in multi-robot sessions.
        self.declare_parameter("webrtc_fps", 15.0)
        self.declare_parameter("webrtc_main_only", True)
        self.declare_parameter("thumb_jpeg_quality", 70)
        self.declare_parameter("thumb_refresh_hz", 0.5)
        self.declare_parameter("drive_cmd_rate_hz", 20.0)
        self.declare_parameter("drive_hold_timeout_s", 0.35)
        self.declare_parameter("drive_rate_ema_alpha", 0.25)
        self.declare_parameter("image_subscription_mode", "active_only")
        self.declare_parameter("image_thumb_interest_ttl_s", 0.75)
        self.declare_parameter("thumb_robots_per_tick", 0)
        self.declare_parameter("allow_unknown_robot_control", False)

        self.webrtc_fps = float(self.get_parameter("webrtc_fps").value)
        self.webrtc_main_only = str(self.get_parameter("webrtc_main_only").value).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        self.thumb_jpeg_quality = int(self.get_parameter("thumb_jpeg_quality").value)
        self.thumb_refresh_hz = float(self.get_parameter("thumb_refresh_hz").value)
        self.drive_cmd_rate_hz = max(1.0, float(self.get_parameter("drive_cmd_rate_hz").value))
        self.drive_hold_timeout_s = max(0.05, float(self.get_parameter("drive_hold_timeout_s").value))
        self.drive_rate_ema_alpha = min(1.0, max(0.01, float(self.get_parameter("drive_rate_ema_alpha").value)))
        self.image_subscription_mode = _normalize_image_subscription_mode(
            self.get_parameter("image_subscription_mode").value
        )
        self.image_thumb_interest_ttl_s = max(
            0.2,
            float(self.get_parameter("image_thumb_interest_ttl_s").value),
        )
        self.thumb_robots_per_tick = max(
            0,
            int(self.get_parameter("thumb_robots_per_tick").value),
        )
        self.allow_unknown_robot_control = str(
            self.get_parameter("allow_unknown_robot_control").value
        ).strip().lower() in ("1", "true", "yes", "on")
        profiles_path = str(self.get_parameter("profiles_path").value).strip() or None

        self._profile_registry = None
        try:
            self._profile_registry = load_profile_registry(profiles_path)
        except FileNotFoundError as ex:
            self.get_logger().error(f"[fpv_ui] Required profile registry missing: {ex}")
            raise
        except Exception as ex:
            self.get_logger().error(
                f"[fpv_ui] Failed to load profile registry from {profiles_path or '<default>'}: {ex}"
            )
            self._profile_registry = None
        self._trusted_robots: Set[str] = self._load_trusted_robots()
        self._unknown_robot_warned: Set[str] = set()

        self.active_robot: Optional[str] = None
        self.active_robot_sub = self.create_subscription(String, "/active_robot", self._on_active_robot, 10)
        self.active_robot_pub = self.create_publisher(String, "/active_robot", 10)

        self._img_subs: Dict[str, Dict[str, Any]] = {}
        self._latest_img_msg: Dict[str, Image] = {}
        self._latest_jpeg: Dict[str, bytes] = {}
        self._img_topic_for_robot: Dict[str, str] = {}
        self._img_source_for_robot: Dict[str, str] = {}
        self._img_last_frame_s: Dict[str, float] = {}
        self._img_prev_frame_s: Dict[str, float] = {}
        self._img_fps_ema: Dict[str, float] = {}
        self._img_last_encoding: Dict[str, str] = {}
        self._img_last_probe_s: Dict[str, float] = {}
        self._img_interest_until_s: Dict[str, float] = {}
        # Per-robot decoded-frame cache keyed by latest frame stamp.
        # This avoids re-decoding the same JPEG repeatedly when WebRTC recv()
        # runs faster than camera publish FPS or when multiple clients attach.
        self._latest_rgb_cache: Dict[str, np.ndarray] = {}
        self._latest_rgb_cache_stamp: Dict[str, float] = {}
        # Per-robot transformed JPEG variants keyed by latest frame stamp and
        # remote-view profile (size + quality). This avoids repeated resize /
        # encode work when multiple remote viewers request the same robot.
        self._jpeg_variant_cache: Dict[str, Dict[Tuple[int, int, int], bytes]] = {}
        self._jpeg_variant_cache_stamp: Dict[str, float] = {}
        self._camera_health_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._cam_diag_subs: Dict[str, Any] = {}
        self._cam_diag_payload: Dict[str, Dict[str, Any]] = {}

        self._hb_subs: Dict[str, Any] = {}
        self._hb_last_seen_s: Dict[str, float] = {}
        self._robot_meta: Dict[str, Dict[str, str]] = {}
        self._topic_seen_s: Dict[str, float] = {}
        self._active_topic_robots: Set[str] = set()
        self._robot_last_visible_s: Dict[str, float] = {}

        self._cmd_pubs: Dict[str, Any] = {}
        self._mode_pubs: Dict[str, Any] = {}
        self._drive_targets: Dict[str, Dict[str, float]] = {}
        self._drive_last_rx_s: Dict[str, float] = {}
        self._drive_last_pub_s: Dict[str, float] = {}
        self._drive_rx_hz_ema: Dict[str, float] = {}
        self._drive_pub_hz_ema: Dict[str, float] = {}

        self._known_robots: Set[str] = set()
        self._discovery_scan_error_streak: int = 0
        self._robot_presence_timeout_s: float = 5.0
        self._robot_presence_bootstrap_grace_s: float = 3.0
        self._robot_live_state: Dict[str, bool] = {}
        self.create_timer(1.0, self._refresh_discovery)
        # Fast interest-sync keeps active robot switching snappy and allows
        # short-lived thumbnail subscriptions without waiting a full discovery tick.
        self.create_timer(0.25, self._sync_image_subscriptions)
        self.create_timer(1.0 / self.drive_cmd_rate_hz, self._drive_publish_tick)
        self.get_logger().info(
            "[swarm_fpv_ui] image_subscription_mode=%s thumb_interest_ttl_s=%.2f thumb_robots_per_tick=%d"
            % (
                self.image_subscription_mode,
                float(self.image_thumb_interest_ttl_s),
                int(self.thumb_robots_per_tick),
            )
        )
        self.get_logger().info(
            "[swarm_fpv_ui] trusted_robots=%s allow_unknown_robot_control=%s"
            % (
                ",".join(sorted(self._trusted_robots)) or "<none>",
                "true" if self.allow_unknown_robot_control else "false",
            )
        )

    def _load_trusted_robots(self) -> Set[str]:
        registry = self._profile_registry if isinstance(self._profile_registry, dict) else {}
        robots = registry.get("robots", {}) or {}
        if not isinstance(robots, dict):
            return set()
        return {str(name).strip() for name in robots.keys() if str(name).strip()}

    def is_trusted_robot(self, robot: str) -> bool:
        return str(robot or "").strip() in self._trusted_robots

    def robot_control_allowed(self, robot: str) -> bool:
        robot = str(robot or "").strip()
        if not robot:
            return False
        return self.is_trusted_robot(robot) or bool(self.allow_unknown_robot_control)

    def _robot_trust_public(self, robot: str) -> Dict[str, Any]:
        trusted = self.is_trusted_robot(robot)
        control_allowed = self.robot_control_allowed(robot)
        if trusted:
            status = "trusted"
            reason = "Robot exists in the configured robot registry."
        elif control_allowed:
            status = "unknown_control_allowed"
            reason = "Robot is not in the registry, but unknown robot control override is enabled."
        else:
            status = "unknown_readonly"
            reason = (
                "Robot is visible on ROS, but is not in the configured robot registry; "
                "video/diagnostics are allowed and control is blocked."
            )
        return {
            "trusted": bool(trusted),
            "control_allowed": bool(control_allowed),
            "trust_status": status,
            "trust_reason": reason,
        }

    def _warn_unknown_robot_once(self, robot: str, context: str = "discovery") -> None:
        robot = str(robot or "").strip()
        if not robot or self.is_trusted_robot(robot) or self.allow_unknown_robot_control:
            return
        if robot in self._unknown_robot_warned:
            return
        self._unknown_robot_warned.add(robot)
        known = ", ".join(sorted(self._trusted_robots)) or "<none>"
        self.get_logger().warn(
            "[swarm_fpv_ui] untrusted robot '%s' discovered via %s; keeping it read-only. "
            "Known trusted robots: %s. Run sync_robot_entries_core/add_robot_core on the control machine, "
            "or set SWARM_CORE_ALLOW_UNKNOWN_ROBOT_CONTROL=1 only in a trusted lab."
            % (robot, str(context or "discovery"), known)
        )

    def _on_active_robot(self, msg: String):
        self.active_robot = str(msg.data or "").strip() or None

    def set_active_robot(self, robot: str):
        robot = str(robot or "").strip()
        if not robot:
            return
        msg = String()
        msg.data = robot
        self.active_robot_pub.publish(msg)
        self.active_robot = robot
        self.mark_image_interest(robot, ttl_s=max(2.0, float(self.image_thumb_interest_ttl_s)))

    def _refresh_discovery(self):
        robots: Set[str] = set()
        scan_ok = True
        try:
            topics = self.get_topic_names_and_types()
            if self._discovery_scan_error_streak:
                self._discovery_scan_error_streak = 0
        except Exception as exc:
            scan_ok = False
            topics = []
            self._discovery_scan_error_streak += 1
            if self._discovery_scan_error_streak in (1, 10):
                self.get_logger().warn(
                    "[swarm_fpv_ui] discovery topic scan failed (%s); keeping last known robots"
                    % str(exc)
                )
        for t, _types in topics:
            m = (
                IMG_CAMERA_COMP_RE.match(t)
                or IMG_FLAT_COMP_RE.match(t)
                or IMG_CAMERA_RE.match(t)
                or IMG_FLAT_RE.match(t)
            )
            if m:
                if self._topic_publishers(t) > 0:
                    robots.add(m.group(1))
                continue
            m = HB_RE.match(t)
            if m:
                if self._topic_publishers(t) > 0:
                    robots.add(m.group(1))

        t_now = now_s()
        for robot in robots:
            if robot not in self._active_topic_robots:
                self._topic_seen_s[robot] = t_now
                self._robot_last_visible_s[robot] = t_now
        if scan_ok:
            self._active_topic_robots = set(robots)
        if robots:
            self._known_robots.update(robots)
        elif not scan_ok:
            robots = set(self._known_robots)
        else:
            robots = set()

        # Keep recently alive robots through brief DDS/topic graph churn so the
        # UI does not flap active selection or tear down WebRTC unnecessarily.
        known_live = {robot for robot in set(self._known_robots) if self._robot_recently_alive(robot, t_now)}
        if known_live:
            robots.update(known_live)
            for robot in known_live:
                self._robot_last_visible_s[robot] = t_now

        visible = self.visible_robots(t_now)
        self._known_robots = set(visible)

        for robot in sorted(visible):
            self._warn_unknown_robot_once(robot, "topic discovery")
            self.ensure_heartbeat_subscription(robot)
            self.ensure_camera_diag_subscription(robot)
        self._log_robot_liveness_transitions(t_now)
        self._sync_image_subscriptions()

    def list_robots(self) -> Set[str]:
        t_now = now_s()
        return {
            robot for robot in set(self._known_robots)
            if self._robot_recently_alive(robot, t_now)
        }

    def visible_robots(self, t_now: Optional[float] = None) -> Set[str]:
        t_now = now_s() if t_now is None else float(t_now)
        candidates: Set[str] = set(self._known_robots)
        candidates.update(self._robot_last_visible_s.keys())
        candidates.update(self._hb_last_seen_s.keys())
        candidates.update(self._img_last_frame_s.keys())
        candidates.update(self._topic_seen_s.keys())

        visible: Set[str] = set()
        for robot in candidates:
            if self._robot_recently_alive(robot, t_now):
                visible.add(robot)
            else:
                self._robot_last_visible_s.pop(robot, None)
        return visible

    def _robot_recently_alive(self, robot: str, t_now: Optional[float] = None) -> bool:
        t_now = now_s() if t_now is None else float(t_now)
        hb_last = float(self._hb_last_seen_s.get(robot, 0.0))
        if hb_last > 0.0 and (t_now - hb_last) <= self._robot_presence_timeout_s:
            return True
        frame_last = float(self._img_last_frame_s.get(robot, 0.0))
        if frame_last > 0.0 and (t_now - frame_last) <= max(2.0, self._robot_presence_timeout_s):
            return True
        topic_last = float(self._topic_seen_s.get(robot, 0.0))
        if topic_last > 0.0 and (t_now - topic_last) <= self._robot_presence_bootstrap_grace_s:
            return True
        return False

    def _robot_liveness_snapshot(self, robot: str, t_now: float) -> Dict[str, Any]:
        hb_last = float(self._hb_last_seen_s.get(robot, 0.0))
        frame_last = float(self._img_last_frame_s.get(robot, 0.0))
        topic_last = float(self._topic_seen_s.get(robot, 0.0))
        hb_age = (t_now - hb_last) if hb_last > 0.0 else None
        frame_age = (t_now - frame_last) if frame_last > 0.0 else None
        topic_age = (t_now - topic_last) if topic_last > 0.0 else None
        hb_live = bool(hb_age is not None and hb_age <= self._robot_presence_timeout_s)
        frame_live = bool(frame_age is not None and frame_age <= max(2.0, self._robot_presence_timeout_s))
        topic_live = bool(topic_age is not None and topic_age <= self._robot_presence_bootstrap_grace_s)
        return {
            "alive": bool(hb_live or frame_live or topic_live),
            "hb_age": hb_age,
            "frame_age": frame_age,
            "topic_age": topic_age,
            "hb_live": hb_live,
            "frame_live": frame_live,
            "topic_live": topic_live,
        }

    def _robot_presence_public(self, robot: str, t_now: Optional[float] = None) -> Dict[str, Any]:
        t_now = now_s() if t_now is None else float(t_now)
        snap = self._robot_liveness_snapshot(robot, t_now)
        if snap["hb_live"] or snap["frame_live"]:
            status = "live"
            reason = "Robot is publishing recent heartbeat or frames."
        elif snap["topic_live"]:
            status = "bootstrap"
            reason = "Robot topic graph is present, but heartbeat/frame freshness is still settling."
        else:
            missing = []
            if not snap["hb_live"]:
                missing.append("heartbeat")
            if not snap["frame_live"]:
                missing.append("camera")
            if not snap["topic_live"]:
                missing.append("topic_graph")
            missing_txt = ",".join(missing) or "unknown"
            status = "stale"
            reason = f"Recent robot liveness evidence is missing: {missing_txt}."
        return {
            "robot_alive": bool(snap["alive"]),
            "presence_status": status,
            "presence_reason": reason,
            "heartbeat_age_s": snap["hb_age"],
            "topic_age_s": snap["topic_age"],
        }

    @staticmethod
    def _fmt_age(value: Optional[float]) -> str:
        if value is None:
            return "none"
        return f"{float(value):.2f}s"

    def _log_robot_liveness_transitions(self, t_now: float) -> None:
        candidates: Set[str] = set(self._known_robots)
        candidates.update(self._hb_subs.keys())
        candidates.update(self._img_subs.keys())
        candidates.update(self._topic_seen_s.keys())
        candidates.update(self._hb_last_seen_s.keys())
        candidates.update(self._img_last_frame_s.keys())
        for robot in sorted(candidates):
            snap = self._robot_liveness_snapshot(robot, t_now)
            alive = bool(snap["alive"])
            prev = self._robot_live_state.get(robot)
            if prev is None:
                self._robot_live_state[robot] = alive
                continue
            if prev == alive:
                continue
            self._robot_live_state[robot] = alive
            if alive:
                self.get_logger().info(
                    "[swarm_fpv_ui] robot '%s' live again: heartbeat_age=%s frame_age=%s topic_age=%s"
                    % (
                        robot,
                        self._fmt_age(snap["hb_age"]),
                        self._fmt_age(snap["frame_age"]),
                        self._fmt_age(snap["topic_age"]),
                    )
                )
                continue
            reasons = []
            if not snap["hb_live"]:
                reasons.append("heartbeat")
            if not snap["frame_live"]:
                reasons.append("camera")
            if not snap["topic_live"]:
                reasons.append("topic_graph")
            self.get_logger().warn(
                "[swarm_fpv_ui] robot '%s' went stale: missing=%s heartbeat_age=%s frame_age=%s topic_age=%s"
                % (
                    robot,
                    ",".join(reasons) or "unknown",
                    self._fmt_age(snap["hb_age"]),
                    self._fmt_age(snap["frame_age"]),
                    self._fmt_age(snap["topic_age"]),
                )
            )

    def mark_image_interest(self, robot: str, ttl_s: Optional[float] = None) -> None:
        robot = str(robot or "").strip()
        if not robot:
            return
        if self.image_subscription_mode == "all":
            return
        ttl = float(ttl_s) if ttl_s is not None else float(self.image_thumb_interest_ttl_s)
        ttl = max(0.2, ttl)
        until = now_s() + ttl
        prev = float(self._img_interest_until_s.get(robot, 0.0))
        if until > prev:
            self._img_interest_until_s[robot] = until

    def _desired_image_subscription_robots(self) -> Set[str]:
        live_robots = self.list_robots()
        if self.image_subscription_mode == "all":
            return set(live_robots)

        desired: Set[str] = set()
        active = str(self.active_robot or "").strip()
        if active and active in live_robots:
            desired.add(active)

        t_now = now_s()
        for robot, until in list(self._img_interest_until_s.items()):
            if until >= t_now and robot in live_robots:
                desired.add(robot)
            elif until < t_now:
                self._img_interest_until_s.pop(robot, None)
        return desired

    def _drop_image_subscription(self, robot: str) -> None:
        subs = dict(self._img_subs.pop(robot, {}) or {})
        for _topic, sub in subs.items():
            try:
                self.destroy_subscription(sub)
            except Exception:
                pass
        self._img_topic_for_robot.pop(robot, None)
        self._img_source_for_robot.pop(robot, None)
        self._img_last_probe_s.pop(robot, None)
        # Keep the last compressed frame and thumbnail variants as a lightweight
        # visual cache. Dropping the ROS subscription should stop background
        # camera ingress without making fleet tiles flash black between sparse
        # preview refreshes.
        self._latest_img_msg.pop(robot, None)
        self._latest_rgb_cache.pop(robot, None)
        self._latest_rgb_cache_stamp.pop(robot, None)
        self._img_prev_frame_s.pop(robot, None)
        self._img_fps_ema.pop(robot, None)
        self._img_last_encoding.pop(robot, None)
        self._camera_health_cache.pop(robot, None)

    def _sync_image_subscriptions(self) -> None:
        desired = self._desired_image_subscription_robots()
        current = set(self._img_subs.keys())
        for robot in sorted(desired - current):
            self.ensure_image_subscription(robot)
        t_now = now_s()
        for robot in sorted(current - desired):
            if self.image_subscription_mode != "all":
                if float(self._img_interest_until_s.get(robot, 0.0)) >= t_now:
                    continue
            self._drop_image_subscription(robot)

    def _update_rate_ema(
        self,
        robot: str,
        now: float,
        last_seen: Dict[str, float],
        rate_ema: Dict[str, float],
    ) -> None:
        prev = last_seen.get(robot)
        if prev is not None:
            dt = max(1e-6, now - prev)
            inst_hz = 1.0 / dt
            prev_ema = float(rate_ema.get(robot, inst_hz))
            alpha = float(self.drive_rate_ema_alpha)
            rate_ema[robot] = ((1.0 - alpha) * prev_ema) + (alpha * inst_hz)
        last_seen[robot] = now

    def _record_drive_rx(self, robot: str, now: float) -> None:
        self._update_rate_ema(robot, now, self._drive_last_rx_s, self._drive_rx_hz_ema)

    def _record_drive_pub(self, robot: str, now: float) -> None:
        self._update_rate_ema(robot, now, self._drive_last_pub_s, self._drive_pub_hz_ema)

    def _rate_ema_snapshot(
        self,
        robot: str,
        now: float,
        last_seen: Dict[str, float],
        rate_ema: Dict[str, float],
        *,
        stale_after_s: float,
    ) -> float:
        last = float(last_seen.get(robot, 0.0))
        if last <= 0.0:
            return 0.0
        if (now - last) > max(0.1, float(stale_after_s)):
            return 0.0
        return float(rate_ema.get(robot, 0.0))

    def drive_telemetry(self, robot: str) -> Dict[str, Any]:
        robot = str(robot or "").strip()
        now = now_s()
        target = self._drive_targets.get(robot) or {}
        updated_s = float(target.get("updated_s", 0.0))
        age = (now - updated_s) if updated_s > 0.0 else None
        active = bool(age is not None and age <= self.drive_hold_timeout_s)
        target_hz = float(self.drive_cmd_rate_hz)
        ws_rx_hz = self._rate_ema_snapshot(
            robot,
            now,
            self._drive_last_rx_s,
            self._drive_rx_hz_ema,
            stale_after_s=max(1.0, 2.0 * self.drive_hold_timeout_s),
        )
        cmd_pub_hz = self._rate_ema_snapshot(
            robot,
            now,
            self._drive_last_pub_s,
            self._drive_pub_hz_ema,
            stale_after_s=max(1.0, 3.0 / max(1.0, target_hz)),
        )
        if active and cmd_pub_hz < (0.6 * target_hz):
            rate_status = "degraded"
        elif active:
            rate_status = "ok"
        else:
            rate_status = "idle"
        return {
            "ws_rx_hz": ws_rx_hz,
            "cmd_pub_hz": cmd_pub_hz,
            "target_age_s": age,
            "hold_active": active,
            "rate_status": rate_status,
            "cmd_rate_target_hz": target_hz,
            "hold_timeout_s": float(self.drive_hold_timeout_s),
        }

    def drive_telemetry_snapshot(self) -> Dict[str, Dict[str, Any]]:
        robots = set(self.visible_robots())
        robots.update(self._drive_targets.keys())
        robots.update(self._drive_rx_hz_ema.keys())
        robots.update(self._drive_pub_hz_ema.keys())
        return {r: self.drive_telemetry(r) for r in sorted(robots)}

    def ensure_image_subscription(self, robot: str):
        robot = str(robot or "").strip()
        if not robot:
            return

        preferred_comp_topic = f"/{robot}/camera/image_raw/compressed"
        fallback_comp_topic = f"/{robot}/image_raw/compressed"
        preferred_raw_topic = f"/{robot}/camera/image_raw"
        fallback_raw_topic = f"/{robot}/image_raw"
        topic = self._choose_image_topic(
            robot,
            preferred_comp_topic,
            fallback_comp_topic,
            preferred_raw_topic,
            fallback_raw_topic,
        )
        self._img_topic_for_robot[robot] = topic
        self._img_source_for_robot[robot] = "compressed" if topic.endswith("/compressed") else "raw"

        def _mark_frame(r: str, src_topic: str, encoding: str):
            if src_topic:
                self._img_topic_for_robot[r] = src_topic
            self._img_source_for_robot[r] = "compressed" if src_topic.endswith("/compressed") else "raw"
            self._img_last_encoding[r] = str(encoding or "")
            t_now = now_s()
            self._img_last_frame_s[r] = t_now
            t_prev = self._img_prev_frame_s.get(r)
            if t_prev is not None:
                dt = max(1e-6, t_now - t_prev)
                inst_fps = 1.0 / dt
                prev_ema = float(self._img_fps_ema.get(r, inst_fps))
                # Light smoothing keeps FPS readable and stable.
                self._img_fps_ema[r] = (0.75 * prev_ema) + (0.25 * inst_fps)
            self._img_prev_frame_s[r] = t_now

        def _cb_raw(msg: Image, r=robot, src_topic: str = ""):
            self._latest_img_msg[r] = msg
            _mark_frame(r, src_topic, str(msg.encoding or ""))

        def _cb_compressed(msg: CompressedImage, r=robot, src_topic: str = ""):
            data = bytes(msg.data or b"")
            if not data:
                return
            self._latest_jpeg[r] = data
            fmt = str(msg.format or "").strip().lower()
            _mark_frame(r, src_topic, fmt or "jpeg")

        # Prefer compressed topics in multicast deployments to reduce loss from
        # large raw Image payloads over lossy links.
        subs = self._img_subs.setdefault(robot, {})
        if topic.endswith("/compressed"):
            subscription_plan = [
                (CompressedImage, preferred_comp_topic, _cb_compressed),
                (CompressedImage, fallback_comp_topic, _cb_compressed),
            ]
        else:
            subscription_plan = [
                (Image, preferred_raw_topic, _cb_raw),
                (Image, fallback_raw_topic, _cb_raw),
            ]

        for msg_type, t, cb_fn in subscription_plan:
            if t in subs:
                continue
            subs[t] = self.create_subscription(
                msg_type,
                t,
                lambda msg, r=robot, src=t, fn=cb_fn: fn(msg, r=r, src_topic=src),
                qos_profile_sensor_data,
            )

    def _topic_publishers(self, topic: str) -> int:
        try:
            return len(self.get_publishers_info_by_topic(topic))
        except Exception:
            return 0

    def _choose_image_topic(
        self,
        robot: str,
        preferred_comp_topic: str,
        fallback_comp_topic: str,
        preferred_raw_topic: str,
        fallback_raw_topic: str,
    ) -> str:
        """
        Select the best image topic for this robot.

        Priority:
        1) Use compressed camera namespace when it has publishers.
        2) Else use compressed flat image topic when it has publishers.
        3) Else use raw camera namespace when it has publishers.
        4) Else use raw flat image topic when it has publishers.
        5) If none have publishers, keep current topic if set.
        """
        if self._topic_publishers(preferred_comp_topic) > 0:
            return preferred_comp_topic
        if self._topic_publishers(fallback_comp_topic) > 0:
            return fallback_comp_topic
        if self._topic_publishers(preferred_raw_topic) > 0:
            return preferred_raw_topic
        if self._topic_publishers(fallback_raw_topic) > 0:
            return fallback_raw_topic
        current_topic = str(self._img_topic_for_robot.get(robot, "")).strip()
        if current_topic in (
            preferred_comp_topic,
            fallback_comp_topic,
            preferred_raw_topic,
            fallback_raw_topic,
        ):
            return current_topic
        return preferred_comp_topic

    def maybe_retarget_image_subscription(
        self,
        robot: str,
        stale_after_s: float = 1.0,
        min_probe_interval_s: float = 1.0,
    ):
        """
        Re-evaluate topic choice at runtime.

        This fixes a common startup race:
        - UI starts before camera publishers are discovered.
        - initial subscription selects fallback topic.
        - publisher appears later on the preferred topic.
        Without this re-check, the UI can stay on a dead topic forever.
        """
        robot = str(robot or "").strip()
        if not robot:
            return
        # In active-only mode, do not auto-create subscriptions from generic
        # health checks for robots that are currently not watched.
        if robot not in self._img_subs:
            return
        t_now = now_s()
        last_probe = float(self._img_last_probe_s.get(robot, 0.0))
        if (t_now - last_probe) < max(0.1, min_probe_interval_s):
            return
        self._img_last_probe_s[robot] = t_now
        preferred_comp_topic = f"/{robot}/camera/image_raw/compressed"
        fallback_comp_topic = f"/{robot}/image_raw/compressed"
        preferred_raw_topic = f"/{robot}/camera/image_raw"
        fallback_raw_topic = f"/{robot}/image_raw"
        current_topic = str(self._img_topic_for_robot.get(robot, "")).strip()
        target_topic = self._choose_image_topic(
            robot,
            preferred_comp_topic,
            fallback_comp_topic,
            preferred_raw_topic,
            fallback_raw_topic,
        )
        if not current_topic:
            self.ensure_image_subscription(robot)
            return

        # If current stream is stale/no-frame and the other topic is live, switch immediately.
        last = self._img_last_frame_s.get(robot)
        is_stale = (last is None) or ((now_s() - float(last)) > max(0.2, stale_after_s))
        if current_topic != target_topic:
            if is_stale:
                self.ensure_image_subscription(robot)
                return
            # Non-stale stream is still flowing; avoid unnecessary flapping.
            return

    def ensure_heartbeat_subscription(self, robot: str):
        robot = str(robot or "").strip()
        if not robot or robot in self._hb_subs:
            return

        topic = f"/{robot}/heartbeat"

        def _cb(msg: String, r=robot):
            try:
                payload = json.loads(msg.data or "{}")
            except Exception:
                return
            self._hb_last_seen_s[r] = now_s()
            self._robot_meta[r] = {
                "drive_type": str(payload.get("drive_type", "unknown")),
                "hardware": str(payload.get("hardware", "unknown")),
                "profile": str(payload.get("profile", "")),
            }

        self._hb_subs[robot] = self.create_subscription(String, topic, _cb, 10)

    def ensure_camera_diag_subscription(self, robot: str):
        robot = str(robot or "").strip()
        if not robot or robot in self._cam_diag_subs:
            return

        topic = f"/{robot}/camera/diagnostics"

        def _cb(msg: String, r=robot):
            try:
                payload = json.loads(msg.data or "{}")
                if isinstance(payload, dict):
                    self._cam_diag_payload[r] = payload
            except Exception:
                return

        self._cam_diag_subs[robot] = self.create_subscription(String, topic, _cb, 10)

    def _profile_meta(self, robot: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "drive_type": "unknown",
            "hardware": "unknown",
            "profile": "",
            "adapter_profile": "",
            "adapter_name": "passthrough",
            "requested_adapter_name": "passthrough",
        }
        out.update(self._robot_trust_public(robot))
        if not self.is_trusted_robot(robot):
            self._warn_unknown_robot_once(robot, "profile lookup")
            return out
        if not self._profile_registry:
            return out
        binding = resolve_robot_adapter_binding(
            self._profile_registry,
            robot,
            logger=lambda msg: self.get_logger().warn(str(msg)),
        )
        prof = dict(binding.get("robot_profile", {}) or {})
        out["drive_type"] = str(prof.get("drive_type") or "unknown")
        out["hardware"] = str(prof.get("hardware") or "unknown")
        out["profile"] = str(prof.get("profile_name") or "")
        out["adapter_profile"] = str(binding.get("adapter_profile") or "")
        out["adapter_name"] = str(binding.get("adapter_name") or "passthrough")
        out["requested_adapter_name"] = str(
            binding.get("requested_adapter_name") or out["adapter_name"]
        )
        return out

    def robot_meta(self, robot: str) -> Dict[str, Any]:
        base = self._profile_meta(robot)
        live = dict(self._robot_meta.get(robot, {}) or {})
        if str(live.get("drive_type", "")).strip():
            return {
                "drive_type": str(live.get("drive_type", "unknown")),
                "hardware": str(live.get("hardware", "unknown")),
                "profile": str(live.get("profile", "")),
                "adapter_profile": str(base.get("adapter_profile", "")),
                "adapter_name": str(base.get("adapter_name", "passthrough")),
                "requested_adapter_name": str(
                    base.get("requested_adapter_name", base.get("adapter_name", "passthrough"))
                ),
                "trusted": bool(base.get("trusted", False)),
                "control_allowed": bool(base.get("control_allowed", False)),
                "trust_status": str(base.get("trust_status", "")),
                "trust_reason": str(base.get("trust_reason", "")),
            }
        return base

    def translate_task_payload(self, robot: str, payload: Mapping[str, Any], flow: str = "") -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if not self.robot_control_allowed(robot):
            self._warn_unknown_robot_once(robot, flow or "task translation")
            return dict(payload), {
                "robot": str(robot or "").strip(),
                "adapter_profile": "blocked_untrusted_robot",
                "requested_adapter_name": "none",
                "adapter_name": "none",
                "adapter_params": {},
                "robot_profile": {},
                "fallback_reason": "untrusted_robot_control_blocked",
            }
        return translate_task_for_robot(
            self._profile_registry,
            robot,
            payload,
            flow=flow,
            logger=lambda msg: self.get_logger().warn(str(msg)),
        )

    def translate_state_payload(self, robot: str, payload: Mapping[str, Any], flow: str = "") -> Tuple[Dict[str, Any], Dict[str, Any]]:
        return translate_state_for_robot(
            self._profile_registry,
            robot,
            payload,
            flow=flow,
            logger=lambda msg: self.get_logger().warn(str(msg)),
        )

    def robot_capabilities(self, robot: str) -> Dict[str, Any]:
        """
        Capability model intentionally generic for future aerial integration.
        """
        meta = self.robot_meta(robot)
        trust = self._robot_trust_public(robot)
        dt = str(meta.get("drive_type", "")).lower()
        can_strafe = ("omni" in dt) or ("mecanum" in dt)
        can_vertical = ("aerial" in dt) or ("uav" in dt) or ("drone" in dt)
        profile = "ground_xyaw"
        if can_strafe:
            profile = "ground_xyyaw"
        if can_vertical:
            profile = "aerial_xyyawz"

        drive_params: Dict[str, Any] = {}
        if self._profile_registry and self.is_trusted_robot(robot):
            try:
                resolved = resolve_robot_profile(self._profile_registry, robot)
                drive_params = dict(resolved.get("drive_params", {}) or {})
            except Exception:
                drive_params = {}

        def _safe_float(name: str, default: float, *, min_value: Optional[float] = None) -> float:
            raw = drive_params.get(name, default)
            try:
                out = float(raw)
            except Exception:
                out = float(default)
            if min_value is not None:
                out = max(float(min_value), out)
            return out

        def _safe_int(name: str, default: int, *, min_value: int = 0) -> int:
            raw = drive_params.get(name, default)
            try:
                out = int(raw)
            except Exception:
                out = int(default)
            return max(int(min_value), out)

        teleop_linear = _safe_float("teleop_linear_mps", 0.5, min_value=0.0)
        teleop_angular = _safe_float("teleop_angular_rps", 1.0, min_value=0.0)
        teleop_step = _safe_float("teleop_speed_step", 1.1)
        if teleop_step <= 1.0:
            teleop_step = 1.1
        teleop_medium_steps = _safe_int("teleop_medium_steps", 10, min_value=0)
        teleop_fast_linear_steps = _safe_int("teleop_fast_linear_steps", 15, min_value=0)
        teleop_fast_angular_steps = _safe_int("teleop_fast_angular_steps", 10, min_value=0)
        teleop_omni_turn_gain = _safe_float("teleop_omni_turn_gain", 0.5, min_value=0.0)
        teleop_diff_arc_inner_ratio = _safe_float("teleop_diff_arc_inner_ratio", 0.6)
        teleop_diff_arc_inner_ratio = max(0.0, min(1.0, teleop_diff_arc_inner_ratio))
        wheel_separation_m = drive_params.get("wheel_separation_m", drive_params.get("wheel_base_m", 0.18))
        try:
            wheel_separation_m = float(wheel_separation_m)
        except Exception:
            wheel_separation_m = 0.18
        wheel_separation_m = max(1e-3, wheel_separation_m)

        return {
            "control_profile": profile,
            "can_strafe": bool(can_strafe),
            "can_vertical": bool(can_vertical),
            "can_yaw": True,
            "drive_type": meta.get("drive_type", "unknown"),
            "hardware": meta.get("hardware", "unknown"),
            "profile": meta.get("profile", ""),
            "adapter_profile": meta.get("adapter_profile", ""),
            "adapter_name": meta.get("adapter_name", "passthrough"),
            "requested_adapter_name": meta.get(
                "requested_adapter_name",
                meta.get("adapter_name", "passthrough"),
            ),
            "trusted": bool(trust["trusted"]),
            "control_allowed": bool(trust["control_allowed"]),
            "trust_status": str(trust["trust_status"]),
            "trust_reason": str(trust["trust_reason"]),
            "teleop_linear_mps": teleop_linear,
            "teleop_angular_rps": teleop_angular,
            "teleop_speed_step": teleop_step,
            "teleop_medium_steps": teleop_medium_steps,
            "teleop_fast_linear_steps": teleop_fast_linear_steps,
            "teleop_fast_angular_steps": teleop_fast_angular_steps,
            "teleop_omni_turn_gain": teleop_omni_turn_gain,
            "teleop_diff_arc_inner_ratio": teleop_diff_arc_inner_ratio,
            "wheel_separation_m": wheel_separation_m,
        }

    def camera_health(self, robot: str) -> Dict[str, Any]:
        """
        Live camera health snapshot for UI diagnostics.
        """
        robot = str(robot or "").strip()
        t_now = now_s()
        cached = self._camera_health_cache.get(robot)
        if cached is not None:
            cached_ts, cached_payload = cached
            if (t_now - float(cached_ts)) <= 0.35:
                return dict(cached_payload)

        presence = self._robot_presence_public(robot, t_now)

        def _ret(payload: Dict[str, Any]) -> Dict[str, Any]:
            snap = dict(payload)
            snap.update(presence)
            self._camera_health_cache[robot] = (now_s(), snap)
            return snap

        if not robot:
            return _ret({
                "topic": "",
                "has_frame": False,
                "status": "no_frame",
                "frame_age_s": None,
                "fps": 0.0,
                "publisher_count": 0,
                "probable_cause": "Invalid robot id.",
                "encoding": "unknown",
                "camera_strategy": "",
                "camera_last_error": "",
            })

        watched = robot in self._img_subs
        if self.image_subscription_mode != "all" and not watched:
            topic = f"/{robot}/camera/image_raw/compressed"
            publisher_count = self._topic_publishers(topic)
            diag = dict(self._cam_diag_payload.get(robot, {}) or {})
            cause = (
                "Stream not subscribed right now (active-only mode); select robot or open its thumbnail to warm stream."
            )
            if publisher_count <= 0:
                cause = "No camera publisher detected on expected topic."
            return _ret({
                "topic": topic,
                "has_frame": False,
                "status": "no_frame",
                "frame_age_s": None,
                "fps": 0.0,
                "publisher_count": publisher_count,
                "probable_cause": cause,
                "encoding": "unknown",
                "camera_strategy": str(diag.get("active_strategy", "")),
                "camera_last_error": str(diag.get("last_error", "")),
            })

        self.maybe_retarget_image_subscription(robot, stale_after_s=0.8)
        topic = str(self._img_topic_for_robot.get(robot, f"/{robot}/camera/image_raw/compressed"))
        enc = str(self._img_last_encoding.get(robot, "")).strip().lower()
        supported = (
            enc in (
                "",
                "rgb8",
                "bgr8",
                "rgba8",
                "bgra8",
                "mono8",
                "8uc1",
                "8uc3",
                "8uc4",
                "yuv422_yuy2",
                "yuv422",
                "yuyv",
                "yuy2",
                "jpeg",
                "jpg",
                "compressed",
            )
            or ("jpeg" in enc)
            or ("jpg" in enc)
        )
        try:
            pubs = self.get_publishers_info_by_topic(topic)
        except Exception:
            pubs = []
        publisher_count = len(pubs)
        diag = dict(self._cam_diag_payload.get(robot, {}) or {})
        last = self._img_last_frame_s.get(robot)
        fps = float(self._img_fps_ema.get(robot, 0.0))
        if last is None:
            if publisher_count <= 0:
                cause = "No camera publisher detected on selected topic (camera node down or wrong topic)."
            else:
                cause = "Publisher exists but no frames received yet (possible QoS mismatch, startup delay, or unsupported encoding)."
            return _ret({
                "topic": topic,
                "has_frame": False,
                "status": "no_frame",
                "frame_age_s": None,
                "fps": 0.0,
                "publisher_count": publisher_count,
                "probable_cause": cause,
                "encoding": enc or "unknown",
                "camera_strategy": str(diag.get("active_strategy", "")),
                "camera_last_error": str(diag.get("last_error", "")),
            })
        age = max(0.0, now_s() - float(last))
        if age > 2.0:
            status = "stale"
            if publisher_count <= 0:
                cause = "Camera stream stopped and no publisher is currently present (node/device likely offline)."
            else:
                cause = "Publisher still present but frame updates are stale (transport stall, camera freeze, or ROS network drop)."
        elif age > 0.5:
            status = "degraded"
            cause = "Frames are arriving slowly (network congestion, USB camera throttling, or CPU load)."
        else:
            status = "live"
            cause = "Camera stream healthy."
        if (not supported) and enc:
            cause = f"Camera encoding '{enc}' is not decoded by UI yet; stream may appear blank."
            if status == "live":
                status = "degraded"
        return _ret({
            "topic": topic,
            "has_frame": True,
            "status": status,
            "frame_age_s": age,
            "fps": fps,
            "publisher_count": publisher_count,
            "probable_cause": cause,
            "encoding": enc or "unknown",
            "camera_strategy": str(diag.get("active_strategy", "")),
            "camera_last_error": str(diag.get("last_error", "")),
        })

    def latest_rgb(self, robot: str, max_age_s: Optional[float] = None) -> Optional[np.ndarray]:
        if max_age_s is not None:
            last = self._img_last_frame_s.get(robot)
            if last is None:
                return None
            if (now_s() - float(last)) > max(0.05, float(max_age_s)):
                return None
        frame_stamp = float(self._img_last_frame_s.get(robot, 0.0))
        cached_stamp = float(self._latest_rgb_cache_stamp.get(robot, -1.0))
        if frame_stamp > 0.0 and cached_stamp == frame_stamp:
            cached = self._latest_rgb_cache.get(robot)
            if cached is not None:
                return cached

        decoded: Optional[np.ndarray] = None
        source = str(self._img_source_for_robot.get(robot, "")).strip().lower()
        if source == "compressed":
            blob = self._latest_jpeg.get(robot)
            if blob:
                try:
                    img = PILImage.open(io.BytesIO(blob)).convert("RGB")
                    decoded = np.asarray(img, dtype=np.uint8)
                except Exception:
                    decoded = None

        if decoded is None:
            msg = self._latest_img_msg.get(robot)
            if msg is None:
                blob = self._latest_jpeg.get(robot)
                if blob:
                    try:
                        img = PILImage.open(io.BytesIO(blob)).convert("RGB")
                        decoded = np.asarray(img, dtype=np.uint8)
                    except Exception:
                        decoded = None
            else:
                enc = str(msg.encoding or "").strip().lower()
                h, w = int(msg.height), int(msg.width)
                if h > 0 and w > 0:
                    data = msg.data

                    def _reshape_rows(channels: int) -> Optional[np.ndarray]:
                        row_bytes = int(getattr(msg, "step", 0)) or (w * channels)
                        min_row_bytes = w * channels
                        if row_bytes < min_row_bytes:
                            return None
                        needed = row_bytes * h
                        if len(data) < needed:
                            return None
                        flat = np.frombuffer(data[:needed], dtype=np.uint8).reshape((h, row_bytes))
                        return flat[:, :min_row_bytes].reshape((h, w, channels))

                    if enc in ("rgb8",):
                        decoded = _reshape_rows(3)
                    elif enc in ("bgr8", "8uc3"):
                        arr = _reshape_rows(3)
                        decoded = arr[:, :, ::-1] if arr is not None else None
                    elif enc in ("rgba8",):
                        arr = _reshape_rows(4)
                        decoded = arr[:, :, :3] if arr is not None else None
                    elif enc in ("bgra8", "8uc4"):
                        arr = _reshape_rows(4)
                        decoded = arr[:, :, :3][:, :, ::-1] if arr is not None else None
                    elif enc in ("mono8", "8uc1"):
                        arr = _reshape_rows(1)
                        if arr is not None:
                            g = arr[:, :, 0]
                            decoded = np.stack([g, g, g], axis=-1)
                    elif enc in ("yuv422_yuy2", "yuv422", "yuyv", "yuy2"):
                        row_bytes = int(getattr(msg, "step", 0)) or (w * 2)
                        if row_bytes >= (w * 2):
                            needed = row_bytes * h
                            if len(data) >= needed:
                                flat = np.frombuffer(data[:needed], dtype=np.uint8).reshape((h, row_bytes))
                                arr = flat[:, : (w * 2)]
                                y0 = arr[:, 0::4].astype(np.int16)
                                u = arr[:, 1::4].astype(np.int16)
                                y1 = arr[:, 2::4].astype(np.int16)
                                v = arr[:, 3::4].astype(np.int16)

                                y = np.empty((h, w), dtype=np.int16)
                                y[:, 0::2] = y0
                                y[:, 1::2] = y1
                                u_full = np.repeat(u, 2, axis=1)
                                v_full = np.repeat(v, 2, axis=1)

                                c = y - 16
                                d = u_full - 128
                                e = v_full - 128
                                r = (298 * c + 409 * e + 128) >> 8
                                g = (298 * c - 100 * d - 208 * e + 128) >> 8
                                b = (298 * c + 516 * d + 128) >> 8
                                decoded = np.stack(
                                    [
                                        np.clip(r, 0, 255).astype(np.uint8),
                                        np.clip(g, 0, 255).astype(np.uint8),
                                        np.clip(b, 0, 255).astype(np.uint8),
                                    ],
                                    axis=-1,
                                )

        if decoded is not None and frame_stamp > 0.0:
            self._latest_rgb_cache[robot] = decoded
            self._latest_rgb_cache_stamp[robot] = frame_stamp
        return decoded

    def get_cached_jpeg_variant(
        self,
        robot: str,
        frame_stamp: float,
        *,
        max_w: int,
        max_h: int,
        quality: int,
    ) -> Optional[bytes]:
        robot = str(robot or "").strip()
        if not robot or frame_stamp <= 0.0:
            return None
        cached_stamp = float(self._jpeg_variant_cache_stamp.get(robot, -1.0))
        if cached_stamp != float(frame_stamp):
            return None
        variants = self._jpeg_variant_cache.get(robot)
        if not variants:
            return None
        return variants.get((int(max_w), int(max_h), int(quality)))

    def cache_jpeg_variant(
        self,
        robot: str,
        frame_stamp: float,
        *,
        max_w: int,
        max_h: int,
        quality: int,
        jpeg_bytes: bytes,
    ) -> None:
        robot = str(robot or "").strip()
        if not robot or frame_stamp <= 0.0 or not jpeg_bytes:
            return
        key = (int(max_w), int(max_h), int(quality))
        cached_stamp = float(self._jpeg_variant_cache_stamp.get(robot, -1.0))
        if cached_stamp != float(frame_stamp):
            self._jpeg_variant_cache_stamp[robot] = float(frame_stamp)
            self._jpeg_variant_cache[robot] = {}
        variants = self._jpeg_variant_cache.setdefault(robot, {})
        variants[key] = bytes(jpeg_bytes)
        while len(variants) > 8:
            oldest_key = next(iter(variants))
            if oldest_key == key and len(variants) == 1:
                break
            variants.pop(oldest_key, None)

    def _publish_drive_once(self, robot: str, lin: float, yaw: float, lat: float = 0.0, vert: float = 0.0):
        robot = str(robot or "").strip()
        if not robot:
            return
        if not self.robot_control_allowed(robot):
            self._warn_unknown_robot_once(robot, "drive command")
            return
        translated, binding = self.translate_task_payload(
            robot,
            {
                "type": "drive",
                "robot": robot,
                "lin": float(lin),
                "yaw": float(yaw),
                "lat": float(lat),
                "vert": float(vert),
            },
            flow="fpv_ui.drive",
        )

        def _as_float(raw: Any, fallback: float) -> float:
            try:
                return float(raw)
            except Exception:
                return float(fallback)

        data = dict(translated or {})
        target_robot = str(data.get("robot") or robot).strip() or robot
        if not self.robot_control_allowed(target_robot):
            self._warn_unknown_robot_once(target_robot, "translated drive target")
            return

        lin_out = _as_float(
            data.get(
                "lin",
                data.get("linear_x", data.get("vx", lin)),
            ),
            lin,
        )
        lat_out = _as_float(
            data.get(
                "lat",
                data.get("linear_y", data.get("vy", lat)),
            ),
            lat,
        )
        vert_out = _as_float(
            data.get(
                "vert",
                data.get("linear_z", data.get("vz", vert)),
            ),
            vert,
        )
        yaw_out = _as_float(
            data.get(
                "yaw",
                data.get("angular_z", data.get("wz", yaw)),
            ),
            yaw,
        )

        pub = self._cmd_pubs.get(target_robot)
        if pub is None:
            pub = self.create_publisher(Twist, f"/{target_robot}/cmd_vel", 10)
            self._cmd_pubs[target_robot] = pub

        t = Twist()
        t.linear.x = float(lin_out)
        t.linear.y = float(lat_out)
        t.linear.z = float(vert_out)
        t.angular.z = float(yaw_out)
        pub.publish(t)
        self._record_drive_pub(target_robot, now_s())
        self.get_logger().debug(
            f"[adapter_dispatch] drive robot={target_robot} adapter={binding.get('adapter_name')} "
            f"profile={binding.get('adapter_profile')}"
        )

    def set_drive_target(self, robot: str, lin: float, yaw: float, lat: float = 0.0, vert: float = 0.0):
        robot = str(robot or "").strip()
        if not robot:
            return False
        if not self.robot_control_allowed(robot):
            self._warn_unknown_robot_once(robot, "drive target")
            return False
        now = now_s()
        self._record_drive_rx(robot, now)
        self._drive_targets[robot] = {
            "lin": float(lin),
            "yaw": float(yaw),
            "lat": float(lat),
            "vert": float(vert),
            "updated_s": float(now),
        }

        # Keep first operator response snappy while timer provides steady cadence.
        last_pub = float(self._drive_last_pub_s.get(robot, 0.0))
        is_stop = (
            abs(float(lin)) < 1e-6
            and abs(float(yaw)) < 1e-6
            and abs(float(lat)) < 1e-6
            and abs(float(vert)) < 1e-6
        )
        if is_stop or (now - last_pub) >= (0.5 / self.drive_cmd_rate_hz):
            self._publish_drive_once(robot, lin=lin, yaw=yaw, lat=lat, vert=vert)
        return True

    def publish_drive(self, robot: str, lin: float, yaw: float, lat: float = 0.0, vert: float = 0.0):
        """
        Backward-compatible API: update target command for fixed-rate publishing.
        """
        self.set_drive_target(robot, lin=lin, yaw=yaw, lat=lat, vert=vert)

    def _drive_publish_tick(self):
        if not self._drive_targets:
            return
        now = now_s()
        stale: List[str] = []
        for robot, target in list(self._drive_targets.items()):
            age = now - float(target.get("updated_s", 0.0))
            if age > self.drive_hold_timeout_s:
                self._publish_drive_once(robot, lin=0.0, yaw=0.0, lat=0.0, vert=0.0)
                stale.append(robot)
                continue
            self._publish_drive_once(
                robot,
                lin=float(target.get("lin", 0.0)),
                yaw=float(target.get("yaw", 0.0)),
                lat=float(target.get("lat", 0.0)),
                vert=float(target.get("vert", 0.0)),
            )
        for robot in stale:
            self._drive_targets.pop(robot, None)

    def publish_autonomy_mode(self, robot: str, mode: str):
        robot = str(robot or "").strip()
        mode = str(mode or "").strip().lower()
        if not robot or not mode:
            return
        if not self.robot_control_allowed(robot):
            self._warn_unknown_robot_once(robot, "autonomy mode")
            return
        translated, binding = self.translate_task_payload(
            robot,
            {
                "type": "autonomy_mode",
                "robot": robot,
                "mode": mode,
            },
            flow="fpv_ui.autonomy_mode",
        )
        data = dict(translated or {})
        target_robot = str(data.get("robot") or robot).strip() or robot
        if not self.robot_control_allowed(target_robot):
            self._warn_unknown_robot_once(target_robot, "translated autonomy target")
            return
        target_mode = str(
            data.get("mode", data.get("autonomy_mode", mode))
        ).strip().lower() or mode

        pub = self._mode_pubs.get(target_robot)
        if pub is None:
            pub = self.create_publisher(String, f"/{target_robot}/autonomy/mode", 10)
            self._mode_pubs[target_robot] = pub
        msg = String()
        msg.data = json.dumps(
            {
                "mode": target_mode,
                "source": "swarm_fpv_ui",
                "adapter_profile": str(binding.get("adapter_profile") or ""),
                "adapter_name": str(binding.get("adapter_name") or "passthrough"),
            },
            separators=(",", ":"),
        )
        pub.publish(msg)


class RosVideoTrack(VideoStreamTrack):  # type: ignore[misc]
    def __init__(self, hub: RosFleetHub, robot: str, fps: float):
        super().__init__()
        self.hub = hub
        self.robot = robot
        self.period = 1.0 / max(1.0, float(fps))
        self._last_sent = 0.0

    async def recv(self):
        frame = None
        while frame is None:
            frame = self.hub.latest_rgb(self.robot, max_age_s=max(1.0, 4.0 * self.period))
            if frame is None:
                await asyncio.sleep(min(self.period, 0.2))
        now = time.time()
        dt = now - self._last_sent
        if dt < self.period:
            await asyncio.sleep(self.period - dt)
        self._last_sent = time.time()
        vf = VideoFrame.from_ndarray(frame, format="rgb24")
        vf.pts, vf.time_base = await self.next_timestamp()
        return vf


class BrowserServer:
    def __init__(
        self,
        hub: RosFleetHub,
        auth_config: AuthConfig,
        site_id: str = "",
        dev_login_enabled: bool = False,
        dev_users_json: str = "",
        webrtc_ice_servers_json: str = "[]",
        webrtc_ice_transport_policy: str = "all",
    ):
        self.hub = hub
        self.auth_config = auth_config.normalized()
        self.auth = build_auth_service(self.auth_config)
        self.site_id = str(site_id or "").strip()
        self.dev_login_enabled = bool(dev_login_enabled)
        self._dev_users = self._load_dev_users(dev_users_json)
        self.webrtc_ice_transport_policy = _normalize_webrtc_ice_transport_policy(webrtc_ice_transport_policy)
        self.webrtc_ice_servers, webrtc_ice_err = _parse_webrtc_ice_servers_json(webrtc_ice_servers_json)
        self._webrtc_turn_entries = _webrtc_turn_entry_count(self.webrtc_ice_servers)
        self._webrtc_offer_total = 0
        self._webrtc_offer_success = 0
        self._webrtc_offer_failed = 0
        self._webrtc_pc_opened_total = 0
        self._webrtc_pc_closed_total = 0
        self._webrtc_client_events_total = 0
        self._webrtc_last_offer_error = ""
        self._webrtc_last_offer_error_s = 0.0
        self._webrtc_last_offer_robot = ""
        self._webrtc_last_offer_client_id = ""
        self._webrtc_last_client_event: Dict[str, Any] = {}
        self._webrtc_pc_sessions: Dict[int, Dict[str, Any]] = {}
        self._webrtc_pc_by_client_id: Dict[str, RTCPeerConnection] = {}
        self.ws_clients: Dict[str, web.WebSocketResponse] = {}
        self.ws_principals: Dict[str, Principal] = {}
        self.client_active_robot: Dict[str, str] = {}
        self.locks: Dict[str, ControlLock] = {}
        self._dev_sessions_by_id: Dict[str, DevLoginSession] = {}
        self._dev_session_id_by_username: Dict[str, str] = {}
        self._dev_session_id_by_client: Dict[str, str] = {}
        self._dev_session_pending_ttl_s = 45.0
        self._dev_session_orphan_ttl_s = 2.0
        self.lock_timeout_s = 5.0
        self.pcs: Set[RTCPeerConnection] = set() if HAS_WEBRTC else set()
        if webrtc_ice_err:
            self.hub.get_logger().warn(
                f"[swarm_fpv_ui] Invalid SWARM_CORE_WEBRTC_ICE_SERVERS_JSON ({webrtc_ice_err}); using []"
            )
        self.hub.get_logger().info(
            "[swarm_fpv_ui] WebRTC ICE config: "
            f"policy={self.webrtc_ice_transport_policy} "
            f"servers={_webrtc_ice_servers_log_summary(self.webrtc_ice_servers)}"
        )
        if self.webrtc_ice_transport_policy == "relay" and self._webrtc_turn_entries < 1:
            self.hub.get_logger().warn(
                "[swarm_fpv_ui] WebRTC relay policy enabled but no TURN servers were configured. "
                "Remote/mobile WebRTC sessions are expected to fail."
            )
        asyncio.create_task(self._lock_reaper())
        asyncio.create_task(self._dev_session_reaper())

    def _principal_can_control(self, principal: Principal) -> bool:
        # Community edition runs in local auth_mode=off; do not gate drive/autonomy
        # on scope claims in this mode.
        if self.auth_config.mode == AUTH_MODE_OFF:
            return True
        return principal.has_scope(SWARM_SCOPE_CONTROL)

    def _webrtc_client_config_public(self) -> Dict[str, Any]:
        return {
            "iceServers": list(self.webrtc_ice_servers),
            "iceTransportPolicy": self.webrtc_ice_transport_policy,
        }

    def _webrtc_state_counts(self, key: str) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for row in self._webrtc_pc_sessions.values():
            state = str(row.get(key) or "").strip().lower() or "unknown"
            out[state] = int(out.get(state, 0)) + 1
        return out

    def _webrtc_telemetry_public(self) -> Dict[str, Any]:
        now = now_s()
        err_age = None
        if self._webrtc_last_offer_error and self._webrtc_last_offer_error_s > 0.0:
            err_age = max(0.0, now - self._webrtc_last_offer_error_s)
        return {
            "offers_total": int(self._webrtc_offer_total),
            "offers_success": int(self._webrtc_offer_success),
            "offers_failed": int(self._webrtc_offer_failed),
            "active_peer_connections": int(len(self._webrtc_pc_sessions)),
            "opened_peer_connections_total": int(self._webrtc_pc_opened_total),
            "closed_peer_connections_total": int(self._webrtc_pc_closed_total),
            "connection_states": self._webrtc_state_counts("connection_state"),
            "ice_connection_states": self._webrtc_state_counts("ice_connection_state"),
            "ice_gathering_states": self._webrtc_state_counts("ice_gathering_state"),
            "client_events_total": int(self._webrtc_client_events_total),
            "last_client_event": dict(self._webrtc_last_client_event),
            "last_offer_error": self._webrtc_last_offer_error,
            "last_offer_error_age_s": err_age,
            "last_offer_robot": self._webrtc_last_offer_robot,
            "last_offer_client_id": self._webrtc_last_offer_client_id,
        }

    def _webrtc_public(self) -> Dict[str, Any]:
        return {
            "enabled": bool(HAS_WEBRTC),
            "client_config": self._webrtc_client_config_public(),
            "server_config": {
                "ice_server_entries": int(len(self.webrtc_ice_servers)),
                "turn_server_entries": int(self._webrtc_turn_entries),
                "ice_transport_policy": str(self.webrtc_ice_transport_policy),
            },
            "telemetry": self._webrtc_telemetry_public(),
        }

    def _public_active_robot(self, robots: Optional[List[str]] = None) -> Optional[str]:
        live = set(robots if robots is not None else sorted(self.hub.visible_robots()))
        active = str(self.hub.active_robot or "").strip()
        if active and active in live:
            return active
        return None

    def _record_webrtc_offer(self, *, ok: bool, robot: str, client_id: str = "", error: str = "") -> None:
        self._webrtc_offer_total += 1
        self._webrtc_last_offer_robot = str(robot or "")
        self._webrtc_last_offer_client_id = str(client_id or "")
        if ok:
            self._webrtc_offer_success += 1
            self._webrtc_last_offer_error = ""
            self._webrtc_last_offer_error_s = 0.0
            return
        self._webrtc_offer_failed += 1
        self._webrtc_last_offer_error = str(error or "offer_failed")
        self._webrtc_last_offer_error_s = now_s()

    def _record_webrtc_client_event(
        self,
        *,
        client_id: str,
        robot: str,
        event: str,
        connection_state: str,
        ice_connection_state: str,
        ice_gathering_state: str,
    ) -> None:
        self._webrtc_client_events_total += 1
        self._webrtc_last_client_event = {
            "time_s": now_s(),
            "client_id": str(client_id or ""),
            "robot": str(robot or ""),
            "event": str(event or ""),
            "connection_state": str(connection_state or ""),
            "ice_connection_state": str(ice_connection_state or ""),
            "ice_gathering_state": str(ice_gathering_state or ""),
        }

    def _register_pc_session(self, pc: RTCPeerConnection, robot: str, client_id: str, principal: Principal) -> None:
        session_id = id(pc)
        self._webrtc_pc_sessions[session_id] = {
            "robot": str(robot or ""),
            "client_id": str(client_id or ""),
            "principal": str(principal.subject or ""),
            "started_s": now_s(),
            "updated_s": now_s(),
            "connection_state": str(getattr(pc, "connectionState", "") or ""),
            "ice_connection_state": str(getattr(pc, "iceConnectionState", "") or ""),
            "ice_gathering_state": str(getattr(pc, "iceGatheringState", "") or ""),
        }
        cid = str(client_id or "").strip()
        if cid:
            self._webrtc_pc_by_client_id[cid] = pc
        self._webrtc_pc_opened_total += 1

    def _update_pc_session(
        self,
        pc: RTCPeerConnection,
        *,
        connection_state: Optional[str] = None,
        ice_connection_state: Optional[str] = None,
        ice_gathering_state: Optional[str] = None,
    ) -> None:
        row = self._webrtc_pc_sessions.get(id(pc))
        if not row:
            return
        if connection_state is not None:
            row["connection_state"] = str(connection_state)
        if ice_connection_state is not None:
            row["ice_connection_state"] = str(ice_connection_state)
        if ice_gathering_state is not None:
            row["ice_gathering_state"] = str(ice_gathering_state)
        row["updated_s"] = now_s()

    async def _close_pc(self, pc: RTCPeerConnection) -> None:
        try:
            if getattr(pc, "_swarm_closed", False):
                return
            setattr(pc, "_swarm_closed", True)
        except Exception:
            pass

        sid = id(pc)
        session = self._webrtc_pc_sessions.get(sid)
        if session is not None:
            cid = str(session.get("client_id") or "").strip()
            if cid and self._webrtc_pc_by_client_id.get(cid) is pc:
                self._webrtc_pc_by_client_id.pop(cid, None)
            self._webrtc_pc_closed_total += 1
            self._webrtc_pc_sessions.pop(sid, None)
        else:
            stale_client_ids = [cid for cid, mapped_pc in self._webrtc_pc_by_client_id.items() if mapped_pc is pc]
            for cid in stale_client_ids:
                self._webrtc_pc_by_client_id.pop(cid, None)

        self.pcs.discard(pc)
        try:
            await pc.close()
        except Exception:
            pass

    def _build_pc(self) -> RTCPeerConnection:
        if not HAS_WEBRTC:
            # Unreachable in normal call flow, but keeps typing/runtime robust.
            return RTCPeerConnection()  # type: ignore[call-arg]

        ice_servers_cfg: List[Any] = []
        for row in self.webrtc_ice_servers:
            urls_raw = row.get("urls", [])
            if isinstance(urls_raw, str):
                urls = [urls_raw]
            else:
                urls = [str(v).strip() for v in (urls_raw or []) if str(v).strip()]
            if not urls:
                continue
            kwargs: Dict[str, Any] = {"urls": urls}
            username = str(row.get("username") or "").strip()
            credential = str(row.get("credential") or "").strip()
            if username:
                kwargs["username"] = username
            if credential:
                kwargs["credential"] = credential
            ice_servers_cfg.append(RTCIceServer(**kwargs))

        try:
            cfg = RTCConfiguration(iceServers=ice_servers_cfg)
            try:
                setattr(cfg, "iceTransportPolicy", self.webrtc_ice_transport_policy)
            except Exception:
                pass
            return RTCPeerConnection(configuration=cfg)
        except Exception as exc:
            self.hub.get_logger().warn(
                f"[swarm_fpv_ui] Failed to apply ICE configuration ({exc}); falling back to RTCPeerConnection()"
            )
            return RTCPeerConnection()

    def _load_dev_users(self, users_json: str) -> Dict[str, Dict[str, Any]]:
        users: Dict[str, Dict[str, Any]] = {}
        raw = str(users_json or "").strip()
        if raw:
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = []
            if isinstance(parsed, list):
                for row in parsed:
                    if not isinstance(row, dict):
                        continue
                    username = str(row.get("username") or "").strip()
                    password = str(row.get("password") or "")
                    if not username or not password:
                        continue
                    users[username] = {
                        "username": username,
                        "password": password,
                        "subject": str(row.get("subject") or username).strip(),
                        "display_name": str(row.get("display_name") or username).strip(),
                        "roles_csv": str(row.get("roles") or "operator"),
                        "scopes_csv": str(row.get("scopes") or f"{SWARM_SCOPE_READ},{SWARM_SCOPE_CONTROL}"),
                        "tenant_id": str(row.get("tenant_id") or "dev").strip(),
                    }

        # Safe default for local development if mode=dev and users were not provided.
        if not users and self.auth_config.mode == "dev":
            users["operator"] = {
                "username": "operator",
                "password": "operator",
                "subject": "op_001",
                "display_name": "Operator",
                "roles_csv": "operator",
                "scopes_csv": f"{SWARM_SCOPE_READ},{SWARM_SCOPE_CONTROL}",
                "tenant_id": "dev",
            }
        return users

    def _build_dev_token(self, user: Dict[str, Any], session_id: str) -> str:
        # Token format consumed by DevAuthService:
        # dev|subject|display_name|roles_csv|scopes_csv|tenant_id|session_id
        subject = str(user.get("subject") or "op").replace("|", " ").strip()
        display_name = str(user.get("display_name") or subject).replace("|", " ").strip()
        roles_csv = str(user.get("roles_csv") or "operator").replace("|", " ").strip()
        scopes_csv = str(user.get("scopes_csv") or SWARM_SCOPE_READ).replace("|", " ").strip()
        tenant_id = str(user.get("tenant_id") or "dev").replace("|", " ").strip()
        sess = str(session_id or "").replace("|", " ").strip()
        return f"dev|{subject}|{display_name}|{roles_csv}|{scopes_csv}|{tenant_id}|{sess}"

    def _managed_dev_session_id(self, principal: Principal) -> str:
        if self.auth_config.mode != "dev":
            return ""
        sid = str(principal.session_id or "").strip()
        if not sid.startswith("sess_"):
            return ""
        return sid

    def _touch_dev_session(self, principal: Principal, client_id: str = "") -> bool:
        sid = self._managed_dev_session_id(principal)
        if not sid:
            return True
        sess = self._dev_sessions_by_id.get(sid)
        if sess is None:
            return False
        if sess.subject != str(principal.subject or "").strip():
            return False
        t = now_s()
        sess.last_seen_s = t
        cid = str(client_id or "").strip()
        if cid:
            sess.client_id = cid
            self._dev_session_id_by_client[cid] = sid
        return True

    def _dev_session_is_active(self, sess: DevLoginSession, t_now: Optional[float] = None) -> bool:
        t = float(t_now if t_now is not None else now_s())
        client_id = str(sess.client_id or "").strip()
        if client_id:
            ws = self.ws_clients.get(client_id)
            if ws is not None and not ws.closed:
                return True
            ttl = max(0.1, float(self._dev_session_orphan_ttl_s))
        else:
            ttl = max(0.1, float(self._dev_session_pending_ttl_s))
        return (t - float(sess.last_seen_s)) <= ttl

    async def _close_dev_session(self, session_id: str, reason: str = "", close_ws: bool = True) -> bool:
        sid = str(session_id or "").strip()
        if not sid:
            return False
        sess = self._dev_sessions_by_id.pop(sid, None)
        if sess is None:
            return False

        if self._dev_session_id_by_username.get(sess.username) == sid:
            self._dev_session_id_by_username.pop(sess.username, None)
        client_id = str(sess.client_id or "").strip()
        if client_id and self._dev_session_id_by_client.get(client_id) == sid:
            self._dev_session_id_by_client.pop(client_id, None)

        if close_ws and client_id:
            ws = self.ws_clients.get(client_id)
            if ws is not None and not ws.closed:
                try:
                    await ws.close(code=1001, message=b"session_ended")
                except Exception:
                    pass

        if reason:
            self.hub.get_logger().info(
                f"[swarm_fpv_ui] Closed dev session sid={sid} user={sess.username} reason={reason}"
            )
        return True

    async def _close_dev_session_by_client(self, client_id: str, reason: str = "") -> bool:
        cid = str(client_id or "").strip()
        if not cid:
            return False
        sid = self._dev_session_id_by_client.pop(cid, None)
        if not sid:
            return False
        return await self._close_dev_session(sid, reason=reason, close_ws=False)

    def _bind_dev_session_to_client(self, principal: Principal, client_id: str) -> Tuple[bool, str]:
        sid = self._managed_dev_session_id(principal)
        if not sid:
            return True, ""
        sess = self._dev_sessions_by_id.get(sid)
        if sess is None:
            return False, "Session expired. Please log in again."
        if sess.subject != str(principal.subject or "").strip():
            return False, "Session identity mismatch. Please log in again."

        cid = str(client_id or "").strip()
        if not cid:
            return False, "Missing client_id"

        prior_sid = self._dev_session_id_by_client.get(cid)
        if prior_sid and prior_sid != sid:
            prior = self._dev_sessions_by_id.get(prior_sid)
            if prior is not None and str(prior.client_id or "").strip() == cid:
                prior.client_id = ""

        prev_client_id = str(sess.client_id or "").strip()
        if prev_client_id and prev_client_id != cid:
            other_ws = self.ws_clients.get(prev_client_id)
            if other_ws is not None and not other_ws.closed:
                return False, "This session is already active in another browser tab."
            self._dev_session_id_by_client.pop(prev_client_id, None)

        sess.client_id = cid
        sess.last_seen_s = now_s()
        self._dev_session_id_by_client[cid] = sid
        return True, ""

    async def _lock_reaper(self):
        while True:
            await asyncio.sleep(1.0)
            t = now_s()
            dead = [robot for robot, lk in self.locks.items() if (t - lk.last_heartbeat_s) > self.lock_timeout_s]
            for robot in dead:
                self.locks.pop(robot, None)
            if dead:
                await self._broadcast_lock_update()

    async def _dev_session_reaper(self):
        while True:
            await asyncio.sleep(1.0)
            t = now_s()
            stale_ids = [
                sid
                for sid, sess in list(self._dev_sessions_by_id.items())
                if not self._dev_session_is_active(sess, t_now=t)
            ]
            for sid in stale_ids:
                await self._close_dev_session(sid, reason="expired", close_ws=True)

    def _locks_public(self) -> Dict[str, str]:
        return {robot: lk.controller_id for robot, lk in self.locks.items()}

    def _locks_meta_public(self) -> Dict[str, Dict[str, str]]:
        return {
            robot: {
                "client_id": lk.controller_id,
                "operator_id": lk.operator_id,
                "operator_name": lk.operator_name,
                "session_id": lk.session_id,
                "tenant_id": lk.tenant_id,
                "site_id": lk.site_id,
            }
            for robot, lk in self.locks.items()
        }

    async def _broadcast_lock_update(self):
        await self._broadcast(
            {
                "type": "lock_update",
                "locks": self._locks_public(),
                "lock_meta": self._locks_meta_public(),
            }
        )

    def _principal_public(self, principal: Principal) -> Dict[str, Any]:
        out = principal.to_public_dict()
        # Keep metadata light on browser side.
        out["scopes"] = sorted(principal.scopes)
        out["roles"] = sorted(principal.roles)
        return out

    def _locked_by_other(self, robot: str, client_id: str) -> bool:
        lk = self.locks.get(robot)
        if lk is None:
            return False
        return lk.controller_id != client_id

    def _touch_lock(self, robot: str, client_id: str, principal: Principal) -> bool:
        """
        Refresh lock heartbeat and report whether visible ownership changed.
        """
        prev = self.locks.get(robot)
        self.locks[robot] = ControlLock(
            controller_id=client_id,
            last_heartbeat_s=now_s(),
            operator_id=str(principal.subject or ""),
            operator_name=str(principal.display_name or ""),
            session_id=str(principal.session_id or ""),
            tenant_id=str(principal.tenant_id or ""),
            site_id=self.site_id,
        )
        if prev is None:
            return True
        return prev.controller_id != client_id

    def _deny_response(self, reason: str, status: int) -> web.Response:
        return web.json_response({"error": reason or "unauthorized", "status": int(status)}, status=int(status))

    def _authorize_http(self, req: web.Request, required_scope: str) -> Tuple[Optional[Principal], Optional[web.Response]]:
        decision = self.auth.authorize_http(req, required_scope=required_scope)
        if decision.ok and decision.principal is not None:
            principal = decision.principal
            if not self._touch_dev_session(principal):
                return None, self._deny_response("Session expired. Please log in again.", 401)
            return principal, None
        return None, self._deny_response(decision.reason or "unauthorized", decision.http_status or 401)

    async def _broadcast(self, payload: Dict[str, Any]):
        data = json.dumps(payload)
        for ws in list(self.ws_clients.values()):
            try:
                await ws.send_str(data)
            except Exception:
                pass

    async def _send_ws_error(self, ws: web.WebSocketResponse, message: str):
        try:
            await ws.send_str(json.dumps({"type": "error", "message": message}))
        except Exception:
            pass

    async def handle_index(self, req: web.Request):
        default_main_stream = ""
        default_jpeg_poll_ms = ""
        default_jpeg_max_w = ""
        default_jpeg_max_h = ""
        default_jpeg_quality = ""
        trycloudflare_main_stream = _normalize_main_stream_mode(
            os.environ.get("SWARM_CORE_TRYCLOUDFLARE_MAIN_STREAM", "")
        )
        if trycloudflare_main_stream:
            req_host = _request_host_without_port(req)
            if req_host.endswith(".trycloudflare.com"):
                default_main_stream = trycloudflare_main_stream
                default_jpeg_poll_ms = str(
                    _bounded_int(
                        os.environ.get("SWARM_CORE_TRYCLOUDFLARE_JPEG_POLL_MS", "80"),
                        fallback=80,
                        minimum=40,
                        maximum=500,
                    )
                )
                default_jpeg_max_w = str(
                    _bounded_int(
                        os.environ.get("SWARM_CORE_TRYCLOUDFLARE_JPEG_MAX_W", "512"),
                        fallback=512,
                        minimum=0,
                        maximum=1920,
                    )
                )
                default_jpeg_max_h = str(
                    _bounded_int(
                        os.environ.get("SWARM_CORE_TRYCLOUDFLARE_JPEG_MAX_H", "384"),
                        fallback=384,
                        minimum=0,
                        maximum=1080,
                    )
                )
                default_jpeg_quality = str(
                    _bounded_int(
                        os.environ.get("SWARM_CORE_TRYCLOUDFLARE_JPEG_QUALITY", "60"),
                        fallback=60,
                        minimum=30,
                        maximum=95,
                    )
                )
        html = _INDEX_HTML.format(
            style_href=f"/style.css?v={_STYLE_ASSET_VERSION}",
            app_href=f"/app.js?v={_APP_ASSET_VERSION}",
            default_main_stream=default_main_stream,
            default_jpeg_poll_ms=default_jpeg_poll_ms,
            default_jpeg_max_w=default_jpeg_max_w,
            default_jpeg_max_h=default_jpeg_max_h,
            default_jpeg_quality=default_jpeg_quality,
        )
        return web.Response(text=html, content_type="text/html", headers=_no_cache_headers())

    async def handle_style(self, _req: web.Request):
        return web.Response(text=_STYLE_CSS, content_type="text/css", headers=_no_cache_headers())

    async def handle_js(self, _req: web.Request):
        return web.Response(text=_APP_JS, content_type="application/javascript", headers=_no_cache_headers())

    async def handle_auth_config(self, _req: web.Request):
        return web.json_response(
            {
                "api": api_schema_info(),
                "site_id": self.site_id,
                "auth": {
                    "mode": self.auth_config.mode,
                    "allow_anonymous_readonly": bool(self.auth_config.allow_readonly_anonymous),
                    "dev_login_enabled": bool(self.dev_login_enabled),
                },
            }
        )

    async def handle_dev_login(self, req: web.Request):
        if self.auth_config.mode != "dev" or not self.dev_login_enabled:
            return web.json_response({"error": "Not found"}, status=404)
        try:
            body = await req.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        if not username or not password:
            return web.json_response({"error": "username and password are required"}, status=400)

        user = self._dev_users.get(username)
        if not user or str(user.get("password") or "") != password:
            return web.json_response({"error": "Invalid credentials"}, status=401)

        existing_sid = self._dev_session_id_by_username.get(username)
        if existing_sid:
            existing = self._dev_sessions_by_id.get(existing_sid)
            if existing is None:
                self._dev_session_id_by_username.pop(username, None)
            elif self._dev_session_is_active(existing):
                return web.json_response(
                    {
                        "error": (
                            "Credentials already in use by an active session. "
                            "Close the other browser tab or wait a few seconds and retry."
                        )
                    },
                    status=409,
                )
            else:
                await self._close_dev_session(existing_sid, reason="replaced_stale_session", close_ws=True)

        session_id = f"sess_{int(time.time() * 1000)}_{secrets.token_hex(3)}"
        subject = str(user.get("subject") or username).strip()
        t_now = now_s()
        self._dev_sessions_by_id[session_id] = DevLoginSession(
            session_id=session_id,
            username=username,
            subject=subject,
            created_s=t_now,
            last_seen_s=t_now,
            client_id="",
        )
        self._dev_session_id_by_username[username] = session_id
        token = self._build_dev_token(user, session_id)
        roles = [v.strip() for v in str(user.get("roles_csv") or "").split(",") if v.strip()]
        scopes = [v.strip() for v in str(user.get("scopes_csv") or "").split(",") if v.strip()]
        principal = {
            "subject": subject,
            "display_name": user.get("display_name"),
            "roles": roles,
            "scopes": scopes,
            "tenant_id": user.get("tenant_id"),
            "session_id": session_id,
        }
        return web.json_response(
            {
                "access_token": token,
                "token_type": "Bearer",
                "auth_mode": "dev",
                "principal": principal,
            }
        )

    async def handle_dev_logout(self, req: web.Request):
        if self.auth_config.mode != "dev" or not self.dev_login_enabled:
            return web.json_response({"ok": True, "session_closed": False})

        decision = self.auth.authorize_http(req, required_scope=SWARM_SCOPE_READ)
        principal = decision.principal if (decision.ok and decision.principal is not None) else None
        if principal is None:
            return web.json_response({"ok": True, "session_closed": False})

        sid = self._managed_dev_session_id(principal)
        if not sid:
            return web.json_response({"ok": True, "session_closed": False})

        closed = await self._close_dev_session(sid, reason="logout", close_ws=True)
        return web.json_response({"ok": True, "session_closed": bool(closed)})

    async def handle_state(self, req: web.Request):
        principal, denied = self._authorize_http(req, SWARM_SCOPE_READ)
        if denied is not None:
            return denied
        assert principal is not None

        robots = sorted(self.hub.visible_robots())
        live_robots = sorted(self.hub.list_robots())
        active_robot = self._public_active_robot(robots)
        contract = fleet_contract_manifest()
        return web.json_response(
            {
                "api": api_schema_info(),
                "fleet_contract": contract,
                "site_id": self.site_id,
                "auth": {
                    "mode": self.auth_config.mode,
                    "allow_anonymous_readonly": bool(self.auth_config.allow_readonly_anonymous),
                    "dev_login_enabled": bool(self.dev_login_enabled),
                },
                "principal": self._principal_public(principal),
                "robots": robots,
                "live_robots": live_robots,
                "active_robot": active_robot,
                "locks": self._locks_public(),
                "lock_meta": self._locks_meta_public(),
                "robot_caps": {r: self.hub.robot_capabilities(r) for r in robots},
                "robot_health": {r: self.hub.camera_health(r) for r in robots},
                "drive_telemetry": self.hub.drive_telemetry_snapshot(),
                "features": {
                    "webrtc": bool(HAS_WEBRTC),
                    "autonomy_modes": ["manual", "follow", "patrol", "detect"],
                    "auth_mode": self.auth_config.mode,
                },
                "stream": {
                    "mode": ("webrtc_only" if bool(self.hub.webrtc_main_only) else "jpeg_poll"),
                },
                "webrtc": self._webrtc_public(),
                "thumb_hz": float(self.hub.thumb_refresh_hz),
                "thumb_robots_per_tick": int(self.hub.thumb_robots_per_tick),
            }
        )

    async def handle_fleet_state(self, req: web.Request):
        """
        Additive fleet-contract snapshot endpoint.
        """
        principal, denied = self._authorize_http(req, SWARM_SCOPE_READ)
        if denied is not None:
            return denied
        assert principal is not None

        source = "swarm_control_core.fpv_ui"
        robots = sorted(self.hub.visible_robots())
        live_robots = sorted(self.hub.list_robots())
        active_robot = self._public_active_robot(robots)

        robot_registry = []
        robot_state = []
        robot_health = []
        validation = {"registry": True, "state": True, "health": True}

        for robot in robots:
            caps = self.hub.robot_capabilities(robot)
            meta = self.hub.robot_meta(robot)
            health = self.hub.camera_health(robot)
            lock = self.locks.get(robot)
            owner = str(lock.controller_id).strip() if lock is not None else ""

            reg_event = build_robot_registry_event(
                robot=robot,
                source=source,
                robot_caps=caps,
                profile=str(meta.get("profile", "")),
                drive_type=str(meta.get("drive_type", "")),
                hardware=str(meta.get("hardware", "")),
            )
            reg_payload = reg_event.get("payload")
            if isinstance(reg_payload, dict):
                reg_payload["adapter_profile"] = str(meta.get("adapter_profile", ""))
                reg_payload["adapter_name"] = str(meta.get("adapter_name", "passthrough"))
                reg_payload["requested_adapter_name"] = str(
                    meta.get("requested_adapter_name", meta.get("adapter_name", "passthrough"))
                )
            st_event = build_robot_state_event(
                robot=robot,
                source=source,
                control_mode="manual",
                active=(robot == active_robot),
                lock_owner=owner,
            )
            st_payload = st_event.get("payload")
            if isinstance(st_payload, dict):
                st_payload["adapter_profile"] = str(meta.get("adapter_profile", ""))
                st_payload["adapter_name"] = str(meta.get("adapter_name", "passthrough"))
            hl_event = build_robot_health_event(robot=robot, source=source, robot_health=health)
            hl_payload = hl_event.get("payload")
            if isinstance(hl_payload, dict):
                hl_payload["adapter_profile"] = str(meta.get("adapter_profile", ""))
                hl_payload["adapter_name"] = str(meta.get("adapter_name", "passthrough"))

            reg_translated, reg_binding = self.hub.translate_state_payload(
                robot,
                reg_event.get("payload", {}),
                flow="fpv_ui.fleet_state.registry",
            )
            st_translated, st_binding = self.hub.translate_state_payload(
                robot,
                st_event.get("payload", {}),
                flow="fpv_ui.fleet_state.state",
            )
            hl_translated, hl_binding = self.hub.translate_state_payload(
                robot,
                hl_event.get("payload", {}),
                flow="fpv_ui.fleet_state.health",
            )

            reg_event["adapter_translation"] = {
                "adapter_profile": str(reg_binding.get("adapter_profile") or ""),
                "adapter_name": str(reg_binding.get("adapter_name") or "passthrough"),
                "requested_adapter_name": str(
                    reg_binding.get("requested_adapter_name")
                    or reg_binding.get("adapter_name")
                    or "passthrough"
                ),
                "payload": reg_translated,
            }
            st_event["adapter_translation"] = {
                "adapter_profile": str(st_binding.get("adapter_profile") or ""),
                "adapter_name": str(st_binding.get("adapter_name") or "passthrough"),
                "requested_adapter_name": str(
                    st_binding.get("requested_adapter_name")
                    or st_binding.get("adapter_name")
                    or "passthrough"
                ),
                "payload": st_translated,
            }
            hl_event["adapter_translation"] = {
                "adapter_profile": str(hl_binding.get("adapter_profile") or ""),
                "adapter_name": str(hl_binding.get("adapter_name") or "passthrough"),
                "requested_adapter_name": str(
                    hl_binding.get("requested_adapter_name")
                    or hl_binding.get("adapter_name")
                    or "passthrough"
                ),
                "payload": hl_translated,
            }

            ok_reg, _ = validate_robot_registry_event(reg_event)
            ok_st, _ = validate_robot_state_event(st_event)
            ok_hl, _ = validate_robot_health_event(hl_event)
            validation["registry"] = bool(validation["registry"] and ok_reg)
            validation["state"] = bool(validation["state"] and ok_st)
            validation["health"] = bool(validation["health"] and ok_hl)

            robot_registry.append(reg_event)
            robot_state.append(st_event)
            robot_health.append(hl_event)

        return web.json_response(
            {
                "api": api_schema_info(),
                "fleet_contract": fleet_contract_manifest(),
                "site_id": self.site_id,
                "principal": self._principal_public(principal),
                "robots": robots,
                "robot_registry": robot_registry,
                "robot_state": robot_state,
                "robot_health": robot_health,
                "validation": validation,
            }
        )

    async def handle_jpeg(self, req: web.Request):
        _principal, denied = self._authorize_http(req, SWARM_SCOPE_READ)
        if denied is not None:
            return denied

        robot = str(req.query.get("robot") or "").strip()
        if not robot:
            return web.Response(status=400, text="robot query param required")
        self.hub.mark_image_interest(robot)
        jpeg_blob = self.hub._latest_jpeg.get(robot)
        max_w = _bounded_int(req.query.get("max_w"), fallback=0, minimum=0, maximum=1920)
        max_h = _bounded_int(req.query.get("max_h"), fallback=0, minimum=0, maximum=1080)
        requested_quality = req.query.get("quality")
        quality = _bounded_int(
            requested_quality if requested_quality not in (None, "") else int(self.hub.thumb_jpeg_quality),
            fallback=int(self.hub.thumb_jpeg_quality),
            minimum=30,
            maximum=95,
        )

        if jpeg_blob and max_w <= 0 and max_h <= 0 and requested_quality in (None, ""):
            return web.Response(body=jpeg_blob, content_type="image/jpeg", headers=_no_cache_headers())

        frame_stamp = float(self.hub._img_last_frame_s.get(robot, 0.0))
        cached_variant = self.hub.get_cached_jpeg_variant(
            robot,
            frame_stamp,
            max_w=max_w,
            max_h=max_h,
            quality=quality,
        )
        if cached_variant is not None:
            return web.Response(body=cached_variant, content_type="image/jpeg", headers=_no_cache_headers())

        frame = self.hub.latest_rgb(robot)
        if frame is None:
            return web.Response(status=404, text="no frame yet")
        frame_stamp = float(self.hub._latest_rgb_cache_stamp.get(robot, frame_stamp))
        cached_variant = self.hub.get_cached_jpeg_variant(
            robot,
            frame_stamp,
            max_w=max_w,
            max_h=max_h,
            quality=quality,
        )
        if cached_variant is not None:
            return web.Response(body=cached_variant, content_type="image/jpeg", headers=_no_cache_headers())

        jpeg_bytes = await asyncio.to_thread(
            _encode_rgb_to_jpeg_variant,
            frame,
            max_w,
            max_h,
            quality,
        )
        self.hub.cache_jpeg_variant(
            robot,
            frame_stamp,
            max_w=max_w,
            max_h=max_h,
            quality=quality,
            jpeg_bytes=jpeg_bytes,
        )
        return web.Response(
            body=jpeg_bytes,
            content_type="image/jpeg",
            headers=_no_cache_headers(),
        )

    async def handle_offer(self, req: web.Request):
        principal, denied = self._authorize_http(req, SWARM_SCOPE_READ)
        if denied is not None:
            return denied
        assert principal is not None

        if not HAS_WEBRTC:
            return web.Response(status=501, text="WebRTC unavailable (install aiortc + av)")
        pc: Optional[RTCPeerConnection] = None
        robot = ""
        client_id = ""
        try:
            body = await req.json()
            robot = str(body.get("robot") or "").strip()
            client_id = str(body.get("client_id") or "").strip()
            if not robot:
                return web.Response(status=400, text="robot required")
            self.hub.mark_image_interest(robot, ttl_s=max(3.0, float(self.hub.image_thumb_interest_ttl_s)))
            if client_id:
                prior_pc = self._webrtc_pc_by_client_id.get(client_id)
                if prior_pc is not None:
                    await self._close_pc(prior_pc)

            offer = RTCSessionDescription(sdp=body["sdp"], type=body["type"])
            pc = self._build_pc()
            self.pcs.add(pc)
            self._register_pc_session(pc, robot=robot, client_id=client_id, principal=principal)

            @pc.on("connectionstatechange")
            async def _on_state():
                state = str(getattr(pc, "connectionState", "") or "")
                self._update_pc_session(pc, connection_state=state)
                if state in ("failed", "closed", "disconnected"):
                    await self._close_pc(pc)

            @pc.on("iceconnectionstatechange")
            async def _on_ice_state():
                state = str(getattr(pc, "iceConnectionState", "") or "")
                self._update_pc_session(pc, ice_connection_state=state)
                if state == "failed":
                    await self._close_pc(pc)

            @pc.on("icegatheringstatechange")
            async def _on_ice_gather_state():
                state = str(getattr(pc, "iceGatheringState", "") or "")
                self._update_pc_session(pc, ice_gathering_state=state)

            pc.addTrack(RosVideoTrack(self.hub, robot, fps=self.hub.webrtc_fps))
            await pc.setRemoteDescription(offer)
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            self._record_webrtc_offer(ok=True, robot=robot, client_id=client_id)
            return web.json_response({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})
        except Exception as exc:
            self._record_webrtc_offer(ok=False, robot=robot, client_id=client_id, error=str(exc))
            self.hub.get_logger().warn(f"[swarm_fpv_ui] WebRTC offer failed: {exc}")
            if pc is not None:
                await self._close_pc(pc)
            return web.Response(status=503, text="WebRTC handshake failed")

    async def handle_ws(self, req: web.Request):
        principal, denied = self._authorize_http(req, SWARM_SCOPE_READ)
        if denied is not None:
            return denied
        assert principal is not None

        client_id = str(req.query.get("client_id") or f"client_{int(time.time()*1000)}")
        ok, reason = self._bind_dev_session_to_client(principal, client_id)
        if not ok:
            return self._deny_response(reason or "Session unavailable", 401)

        ws = web.WebSocketResponse(heartbeat=10.0)
        await ws.prepare(req)

        self.ws_clients[client_id] = ws
        self.ws_principals[client_id] = principal

        robots = sorted(self.hub.visible_robots())
        live_robots = sorted(self.hub.list_robots())
        active_robot = self._public_active_robot(robots)
        await ws.send_str(
            json.dumps(
                {
                    "type": "hello",
                    "client_id": client_id,
                    "principal": self._principal_public(principal),
                    "api": api_schema_info(),
                    "site_id": self.site_id,
                    "robots": robots,
                    "live_robots": live_robots,
                    "active_robot": active_robot,
                    "locks": self._locks_public(),
                    "lock_meta": self._locks_meta_public(),
                    "robot_caps": {r: self.hub.robot_capabilities(r) for r in robots},
                    "robot_health": {r: self.hub.camera_health(r) for r in robots},
                    "drive_telemetry": self.hub.drive_telemetry_snapshot(),
                    "features": {"webrtc": bool(HAS_WEBRTC), "auth_mode": self.auth_config.mode},
                    "stream": {
                        "mode": ("webrtc_only" if bool(self.hub.webrtc_main_only) else "jpeg_poll"),
                    },
                    "webrtc": self._webrtc_public(),
                    "thumb_hz": float(self.hub.thumb_refresh_hz),
                    "thumb_robots_per_tick": int(self.hub.thumb_robots_per_tick),
                }
            )
        )

        try:
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except Exception:
                    continue
                self._touch_dev_session(principal, client_id=client_id)
                mtype = str(data.get("type") or "")

                if mtype == "heartbeat":
                    if not self._principal_can_control(principal):
                        continue
                    robot = str(data.get("robot") or "").strip()
                    if robot and not self.hub.robot_control_allowed(robot):
                        continue
                    if robot and (not self._locked_by_other(robot, client_id)):
                        changed = self._touch_lock(robot, client_id, principal)
                        if changed:
                            await self._broadcast_lock_update()
                    continue

                if mtype == "set_active_robot":
                    robot = str(data.get("robot") or "").strip()
                    if not robot:
                        continue
                    self.client_active_robot[client_id] = robot
                    self.hub.set_active_robot(robot)
                    await self._broadcast({"type": "active_robot", "robot": robot})
                    continue

                if mtype == "webrtc_telemetry":
                    robot = str(data.get("robot") or "").strip()
                    event = str(data.get("event") or "").strip()
                    conn_state = str(data.get("connection_state") or "").strip()
                    ice_conn_state = str(data.get("ice_connection_state") or "").strip()
                    ice_gather_state = str(data.get("ice_gathering_state") or "").strip()
                    self._record_webrtc_client_event(
                        client_id=client_id,
                        robot=robot,
                        event=event,
                        connection_state=conn_state,
                        ice_connection_state=ice_conn_state,
                        ice_gathering_state=ice_gather_state,
                    )
                    continue

                if mtype == "drive":
                    if not self._principal_can_control(principal):
                        await self._send_ws_error(ws, "Missing scope 'swarm:control'")
                        continue
                    robot = str(data.get("robot") or "").strip()
                    if not robot:
                        continue
                    if not self.hub.robot_control_allowed(robot):
                        await self._send_ws_error(
                            ws,
                            f"Robot '{robot}' is visible but not trusted for control. "
                            "Add/sync it into robot_instances.yaml before driving.",
                        )
                        continue
                    if self._locked_by_other(robot, client_id):
                        await self._send_ws_error(ws, f"Robot '{robot}' locked by another user")
                        continue
                    lin = float(data.get("lin", 0.0))
                    yaw = float(data.get("yaw", 0.0))
                    lat = float(data.get("lat", 0.0))
                    vert = float(data.get("vert", 0.0))
                    changed = self._touch_lock(robot, client_id, principal)
                    if changed:
                        await self._broadcast_lock_update()
                    self.hub.set_drive_target(robot, lin=lin, yaw=yaw, lat=lat, vert=vert)
                    continue

                if mtype == "autonomy_mode":
                    if not self._principal_can_control(principal):
                        await self._send_ws_error(ws, "Missing scope 'swarm:control'")
                        continue
                    robot = str(data.get("robot") or "").strip()
                    mode = str(data.get("mode") or "").strip().lower()
                    if not robot or not mode:
                        continue
                    if not self.hub.robot_control_allowed(robot):
                        await self._send_ws_error(
                            ws,
                            f"Robot '{robot}' is visible but not trusted for control. "
                            "Add/sync it into robot_instances.yaml before changing modes.",
                        )
                        continue
                    if self._locked_by_other(robot, client_id):
                        await self._send_ws_error(ws, f"Robot '{robot}' locked by another user")
                        continue
                    changed = self._touch_lock(robot, client_id, principal)
                    if changed:
                        await self._broadcast_lock_update()
                    self.hub.publish_autonomy_mode(robot, mode)
                    continue
        finally:
            self.ws_clients.pop(client_id, None)
            self.ws_principals.pop(client_id, None)
            prior_pc = self._webrtc_pc_by_client_id.pop(client_id, None)
            if prior_pc is not None:
                await self._close_pc(prior_pc)
            self.client_active_robot.pop(client_id, None)
            to_release = [r for r, lk in self.locks.items() if lk.controller_id == client_id]
            for robot in to_release:
                self.locks.pop(robot, None)
            await self._close_dev_session_by_client(client_id, reason="ws_disconnected")
            await self._broadcast_lock_update()
        return ws


_STYLE_CSS = r"""
:root{
  --bg:#0a0f16;
  --panel:#111a24;
  --panel2:#0c141d;
  --text:#dbe7f5;
  --muted:#9ab0c8;
  --accent:#39a0ff;
  --danger:#ff5757;
  --ok:#34d399;
  --line:rgba(255,255,255,.1);
}
*{box-sizing:border-box}
body{
  margin:0;
  background:radial-gradient(1200px 700px at 20% -20%,#17314f 0%,transparent 55%),var(--bg);
  color:var(--text);
  font-family: ui-sans-serif,system-ui,Segoe UI,Roboto,Arial,sans-serif;
}
header{
  display:flex;align-items:center;gap:14px;
  padding:12px 16px;border-bottom:1px solid var(--line);
}
.title{font-weight:700;letter-spacing:.4px}
.status{font-size:13px;color:var(--muted)}
.header-spacer{flex:1}
.transport-badge{
  font-size:12px;
  border-radius:999px;
  padding:4px 9px;
  border:1px solid var(--line);
  background:rgba(255,255,255,.04);
  color:var(--muted);
  font-weight:600;
}
.transport-badge.webrtc{
  background:rgba(52,211,153,.14);
  border-color:rgba(52,211,153,.45);
  color:#7af2c3;
}
.transport-badge.fallback{
  background:rgba(250,204,21,.12);
  border-color:rgba(250,204,21,.45);
  color:#ffe28a;
}
.transport-badge.offline{
  background:rgba(255,87,87,.14);
  border-color:rgba(255,87,87,.45);
  color:#ff9c9c;
}
main{
  --fleet-col:clamp(190px,18vw,300px);
  --control-col:clamp(220px,20vw,300px);
  display:grid;
  grid-template-columns:var(--fleet-col) minmax(0,1fr) var(--control-col);
  grid-template-areas:"fleet video controls";
  gap:12px;
  padding:12px;
  min-height:calc(100vh - 56px);
  align-items:start;
}
@media (max-width: 900px){
  main{
    grid-template-columns:1fr;
    grid-template-areas:
      "fleet"
      "video"
      "controls";
  }
}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.fleet-panel{grid-area:fleet}
.video-panel{grid-area:video}
.control-sidebar{grid-area:controls;max-height:calc(100vh - 80px);overflow-y:auto}
.hdr{padding:10px 12px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between}
.label{font-weight:600}
.small{font-size:12px;color:var(--muted)}
.thumb-rail{padding:10px;display:grid;gap:10px}
.thumb-rail{
  max-height:calc(100vh - 140px);
  overflow-y:auto;
  align-content:start;
}
.thumb{
  position:relative;background:#000;border:1px solid var(--line);border-radius:12px;overflow:hidden;
  aspect-ratio:16/10;cursor:pointer;
}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.thumb video.thumb-live{
  position:absolute;
  inset:0;
  width:100%;
  height:100%;
  object-fit:cover;
  display:none;
  background:#000;
  z-index:1;
}
.thumb.sel{outline:2px solid rgba(57,160,255,.7)}
.badge{position:absolute;left:8px;top:8px;font-size:12px;padding:4px 8px;border-radius:999px;background:rgba(0,0,0,.55);border:1px solid rgba(255,255,255,.18);z-index:2}
.badge2{top:34px}
.badge-right{left:auto;right:8px}
.main-wrap{padding:10px;display:grid;grid-template-rows:auto auto auto;gap:10px}
.hero{
  background:#000;border:1px solid var(--line);border-radius:12px;overflow:hidden;
  width:100%;aspect-ratio:16/9;display:grid;place-items:center;position:relative;
}
video{
  width:100%;
  height:100%;
  object-fit:cover;
  position:absolute;
  inset:0;
}
.main-fallback{
  width:100%;
  height:100%;
  object-fit:cover;
  position:absolute;
  inset:0;
  background:#000;
}
.meta{
  display:grid;gap:6px;padding:8px 10px;background:var(--panel2);border:1px solid var(--line);border-radius:12px
}
.profile-label{
  font-weight:700;
  letter-spacing:.3px;
  margin-bottom:2px;
}
.controls{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.controls{
  grid-template-columns: 1fr;
  justify-items:center;
}
.control-stack{
  padding:10px;
  min-height:calc(100vh - 128px);
  display:flex;
  flex-direction:column;
  gap:0;
}
.control-sidebar .modebar{
  grid-template-columns:repeat(2,minmax(0,1fr));
  margin-top:auto;
  margin-bottom:24px;
}
.control-sidebar .controls{
  margin-bottom:24px;
  justify-items:stretch;
}
.control-sidebar .controls + .meta{
  margin-bottom:auto;
}
.control-sidebar .meta{
  align-self:start;
}
.control-sidebar .btn{
  min-width:0;
  min-height:42px;
  padding:8px 5px;
  font-size:11px;
  line-height:1.05;
  display:grid;
  place-items:center;
  text-align:center;
  white-space:normal;
  overflow-wrap:anywhere;
}
.drive-pad{
  display:grid;
  gap:8px;
  width:min(780px, 100%);
}
.drive-pad.no-strafe{
  grid-template-columns:repeat(3,minmax(0,1fr));
}
.drive-pad.with-strafe{
  grid-template-columns:repeat(3,minmax(0,1fr));
}
.drive-spacer{
  visibility:hidden;
}
.btn{
  border:1px solid var(--line);background:var(--panel2);color:var(--text);
  border-radius:10px;padding:10px 8px;font-size:13px;
  user-select:none;
  -webkit-user-select:none;
  -webkit-touch-callout:none;
  touch-action:none;
}
.btn.primary{border-color:rgba(57,160,255,.5)}
.btn.danger{border-color:rgba(255,87,87,.5)}
.btn.active{
  background:rgba(57,160,255,.35);
  border-color:rgba(57,160,255,.9);
  box-shadow:0 0 0 1px rgba(57,160,255,.35) inset, 0 0 14px rgba(57,160,255,.25);
  color:#dff0ff;
}
.btn:disabled{opacity:.45}
.modebar{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.health{
  margin-top:2px;
  display:grid;
  grid-template-columns:1fr;
  gap:8px;
}
.health-card{
  border:1px solid var(--line);
  border-radius:12px;
  padding:10px;
  background:linear-gradient(180deg,rgba(255,255,255,.03),rgba(0,0,0,.06));
}
.health-top{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:8px;
  margin-bottom:8px;
}
.health-head{
  display:flex;
  align-items:center;
  gap:6px;
}
.health-name{font-weight:600}
.pill{
  font-size:11px;
  border-radius:999px;
  padding:3px 8px;
  border:1px solid transparent;
}
.pill.live{background:rgba(52,211,153,.14);border-color:rgba(52,211,153,.45);color:#7af2c3}
.pill.degraded{background:rgba(250,204,21,.12);border-color:rgba(250,204,21,.45);color:#ffe28a}
.pill.stale,.pill.no_frame{background:rgba(255,87,87,.14);border-color:rgba(255,87,87,.45);color:#ff9c9c}
.tip{
  position:relative;
  width:16px;height:16px;
  border-radius:50%;
  display:inline-grid;
  place-items:center;
  font-size:11px;
  color:var(--muted);
  border:1px solid var(--line);
  background:rgba(255,255,255,.02);
  cursor:help;
  user-select:none;
}
.tip::after{
  content:attr(data-tip);
  position:absolute;
  left:20px;
  top:-4px;
  min-width:220px;
  max-width:360px;
  opacity:0;
  pointer-events:none;
  transform:translateY(4px);
  transition:opacity .12s ease, transform .12s ease;
  background:#0b131d;
  border:1px solid var(--line);
  border-radius:10px;
  color:var(--text);
  padding:8px 10px;
  line-height:1.35;
  z-index:10;
  white-space:normal;
}
.tip:hover::after{
  opacity:1;
  transform:translateY(0);
}
.health-row{font-size:12px;color:var(--muted);margin:3px 0}
.health-row b{color:var(--text);font-weight:600}
.webrtc-diag{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
  gap:8px;
}
.webrtc-card{
  border:1px solid var(--line);
  border-radius:12px;
  padding:10px;
  background:linear-gradient(180deg,rgba(255,255,255,.03),rgba(0,0,0,.06));
}
.webrtc-title{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:8px;
  margin-bottom:8px;
}
.webrtc-row{
  font-size:12px;
  color:var(--muted);
  margin:3px 0;
}
.webrtc-row b{
  color:var(--text);
  font-weight:600;
}
.webrtc-mono{
  font-family: ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
.drive-pad,.modebar{
  user-select:none;
  -webkit-user-select:none;
}
@media (orientation: landscape) and (max-width: 1180px) and (pointer: coarse){
  html,body{max-width:100%;overflow-x:hidden}
  body{overscroll-behavior-x:none}
  header{padding:6px 8px;gap:8px}
  .title{font-size:13px;white-space:nowrap}
  .status{font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .transport-badge{font-size:10px;padding:3px 7px;white-space:nowrap}
  main{
    --touch-side:clamp(116px,20vw,184px);
    grid-template-columns:var(--touch-side) minmax(0,1fr) var(--touch-side);
    grid-template-rows:min-content 1fr auto auto auto;
    grid-template-areas:
      "fleet video modes"
      "fleet video drive"
      "details details details"
      "webrtc webrtc webrtc"
      "health health health";
    gap:8px;
    padding:8px;
    min-height:auto;
    overflow-x:hidden;
    align-items:start;
  }
  .fleet-panel{grid-area:fleet;min-width:0;max-height:calc(100svh - 54px)}
  .video-panel{
    display:contents;
    background:transparent;
    border:0;
    overflow:visible;
  }
  .video-panel > .hdr{display:none}
  .control-sidebar{
    display:contents;
    background:transparent;
    border:0;
    overflow:visible;
  }
  .control-sidebar > .hdr{display:none}
  .main-wrap{display:contents}
  .control-stack{display:contents}
  .thumb-rail{
    max-height:calc(100svh - 104px);
    padding:6px;
    gap:6px;
  }
  .hdr{padding:7px 8px}
  aside .label{font-size:12px}
  aside .small{display:none}
  .thumb{border-radius:8px;aspect-ratio:4/3}
  .badge{left:4px;top:4px;font-size:9px;padding:2px 5px}
  .badge-right{left:auto;right:4px}
  .hero{
    grid-area:video;
    align-self:center;
    justify-self:center;
    min-width:0;
    max-height:calc(100svh - 54px);
    border-radius:12px;
  }
  .modebar{
    grid-area:modes;
    align-self:start;
    min-width:0;
    grid-template-columns:repeat(2,minmax(0,1fr));
    gap:6px;
    margin:0;
  }
  .controls{
    grid-area:drive;
    align-self:start;
    min-width:0;
    justify-items:stretch;
    margin:0;
  }
  .control-sidebar .controls + .meta{margin:0}
  .drive-pad{
    width:100%;
    gap:6px;
  }
  .drive-pad.no-strafe,
  .drive-pad.with-strafe{
    grid-template-columns:repeat(3,minmax(0,1fr));
  }
  .btn{
    min-width:0;
    min-height:44px;
    padding:7px 4px;
    border-radius:11px;
    font-size:10px;
    line-height:1.05;
    display:grid;
    place-items:center;
    text-align:center;
    white-space:normal;
    overflow-wrap:anywhere;
  }
  .modebar .btn{
    min-height:34px;
    padding:5px 3px;
    font-size:10px;
  }
  .meta{
    grid-area:details;
    min-width:0;
  }
  .webrtc-diag{
    grid-area:webrtc;
    min-width:0;
    grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
  }
  .health{
    grid-area:health;
    min-width:0;
    grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
  }
}
@media (orientation: landscape) and (max-width: 760px){
  main{--touch-side:clamp(108px,19vw,142px);gap:6px;padding:6px}
  .fleet-panel{max-height:calc(100svh - 46px)}
  .thumb-rail{max-height:calc(100svh - 86px);padding:5px;gap:5px}
  .hero{max-height:calc(100svh - 46px)}
  .btn{min-height:40px;font-size:9px;padding:6px 3px}
  .modebar .btn{min-height:31px;font-size:9px}
  .drive-pad,.modebar{gap:5px}
}
"""

_INDEX_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta name="swarm-fpv-default-main-stream" content="{default_main_stream}"/>
  <meta name="swarm-fpv-jpeg-poll-ms" content="{default_jpeg_poll_ms}"/>
  <meta name="swarm-fpv-jpeg-max-w" content="{default_jpeg_max_w}"/>
  <meta name="swarm-fpv-jpeg-max-h" content="{default_jpeg_max_h}"/>
  <meta name="swarm-fpv-jpeg-quality" content="{default_jpeg_quality}"/>
  <title>Swarm FPV UI</title>
  <link rel="stylesheet" href="{style_href}"/>
</head>
<body>
<header>
  <div class="title">Swarm FPV Control</div>
  <div class="status" id="status">Connecting...</div>
  <div class="header-spacer"></div>
  <div class="transport-badge offline" id="transportBadge">No stream</div>
</header>
<main>
  <aside class="panel fleet-panel">
    <div class="hdr">
      <div>
        <div class="label">Fleet Cameras</div>
        <div class="small">Select a robot to focus</div>
      </div>
    </div>
    <div class="thumb-rail" id="thumbRail"></div>
  </aside>
  <section class="panel video-panel">
    <div class="hdr">
      <div>
        <div class="label" id="activeTitle">No Robot Selected</div>
        <div class="small" id="activeMeta">Choose a camera feed from the left rail</div>
      </div>
    </div>
    <div class="main-wrap">
      <div class="hero">
        <video id="mainVideo" autoplay playsinline muted></video>
        <img id="mainJpeg" class="main-fallback" alt="FPV JPEG fallback" style="display:none"/>
      </div>
      <div class="webrtc-diag" id="webrtcDiagPanel"></div>
      <div class="health" id="healthPanel"></div>
    </div>
  </section>
  <aside class="panel control-sidebar">
    <div class="hdr">
      <div>
        <div class="label">Controls</div>
        <div class="small">Playbooks and drive pad</div>
      </div>
    </div>
    <div class="control-stack">
      <div class="modebar" id="modeControls"></div>
      <div class="controls" id="driveControls"></div>
      <div class="meta" id="capMeta"></div>
    </div>
  </aside>
</main>
<script src="{app_href}"></script>
</body>
</html>
"""

_APP_JS = r"""
let ws = null;
let clientId = "c_" + Math.floor(Math.random() * 1e9);
let robots = [];
let liveRobots = [];
let robotCaps = {};
let robotHealth = {};
let driveTelemetry = {};
let locks = {};
let lockMeta = {};
let activeRobot = null;
let features = { webrtc: false };
let webrtcClientConfig = { iceServers: [], iceTransportPolicy: "all" };
let webrtcServerConfig = {};
let webrtcTelemetry = {};
let streamConfig = { mode: "webrtc_only", fps: 15 };
let localActiveRobotPinned = false;
const thumbRequestInFlight = new Map();
const thumbFailureStreak = new Map();
const thumbBackoffUntilMs = new Map();
const thumbImageCache = new Map();
let thumbRoundRobinCursor = 0;
let thumbRobotsPerTick = 0;
let thumbDriveSuppressedUntilMs = 0;
let authConfig = { mode: "off", allow_anonymous_readonly: true, dev_login_enabled: false };
let pc = null;
let mainFallbackTimer = null;
let mainFallbackInFlight = false;
let webrtcAttemptInFlight = false;
let webrtcRetryAtMs = 0;
let webrtcSwitchNonce = 0;
let webrtcOfferAbortController = null;
let mainVideoLastFrameAtMs = 0;
let mainVideoFrameWatchStarted = false;
let activeRobotSwitchAtMs = 0;
let localRobotSwitchTimer = null;
let pendingLocalRobotSelection = null;
let robotsSig = "";
let locksSig = "";
let stateRefreshInFlight = false;
const DRIVE_HOLD_INTERVAL_MS = 100;
const ROBOT_SWITCH_DEBOUNCE_MS = 140;
const ROBOT_SWITCH_GRACE_MS = 1400;
const WEBRTC_RETRY_INTERVAL_MS = 1600;
const WEBRTC_STALE_FRAME_MS = 3200;
const THUMB_DRIVE_SUPPRESS_MS = 2000;
const THUMB_JPEG_MAX_W = 240;
const THUMB_JPEG_MAX_H = 180;
const THUMB_JPEG_QUALITY = 55;
const THUMB_MINIMAL_STALE_MS = 8000;
const driveHoldTimers = new Map();
const driveHoldCommands = new Map();
const driveHoldButtonTokens = new Map();
const driveHoldOrder = [];
const pressedDriveKeys = new Set();
let keyboardDriveHooked = false;
let driveProfileRobot = null;
let strafeMode = false;
let driveLinearSpeed = 0.5;
let driveAngularSpeed = 1.0;
let driveSpeedStep = 1.1;
let driveSlowLinear = 0.5;
let driveSlowAngular = 1.0;
let driveMediumLinear = 0.5;
let driveMediumAngular = 1.0;
let driveFastLinear = 0.5;
let driveFastAngular = 1.0;
let driveOmniTurnGain = 0.5;
let driveDiffArcInnerRatio = 0.6;
let driveWheelSeparation = 0.18;
const driveButtonsByToken = new Map();
const activeDriveButtonTokens = new Set();
let activeDriveHoldTag = "";

const NO_SIGNAL_IMG = "data:image/svg+xml;utf8," + encodeURIComponent(
  "<svg xmlns='http://www.w3.org/2000/svg' width='640' height='360'>"
  + "<rect width='100%' height='100%' fill='black'/>"
  + "<text x='50%' y='50%' dominant-baseline='middle' text-anchor='middle' fill='#94a3b8' font-size='24'>NO SIGNAL</text>"
  + "</svg>"
);

const $ = (id) => document.getElementById(id);
const setStatus = (s) => { $("status").textContent = s; };
const urlParams = new URLSearchParams(window.location.search);
const defaultMainStreamMeta = document.querySelector('meta[name="swarm-fpv-default-main-stream"]');
const jpegPollMsMeta = document.querySelector('meta[name="swarm-fpv-jpeg-poll-ms"]');
const jpegMaxWMeta = document.querySelector('meta[name="swarm-fpv-jpeg-max-w"]');
const jpegMaxHMeta = document.querySelector('meta[name="swarm-fpv-jpeg-max-h"]');
const jpegQualityMeta = document.querySelector('meta[name="swarm-fpv-jpeg-quality"]');
const defaultMainStream = String(
  (defaultMainStreamMeta && defaultMainStreamMeta.getAttribute("content")) || ""
).trim();
const defaultJpegPollMs = String(
  (jpegPollMsMeta && jpegPollMsMeta.getAttribute("content")) || ""
).trim();
const defaultJpegMaxW = String(
  (jpegMaxWMeta && jpegMaxWMeta.getAttribute("content")) || ""
).trim();
const defaultJpegMaxH = String(
  (jpegMaxHMeta && jpegMaxHMeta.getAttribute("content")) || ""
).trim();
const defaultJpegQuality = String(
  (jpegQualityMeta && jpegQualityMeta.getAttribute("content")) || ""
).trim();
const requestedMainStream = String(
  urlParams.get("main_stream")
  || urlParams.get("stream")
  || defaultMainStream
  || ""
).trim();
const jpegMainPollMs = Math.max(40, _toInt(defaultJpegPollMs, 120));
const jpegMainMaxW = Math.max(0, _toInt(defaultJpegMaxW, 0));
const jpegMainMaxH = Math.max(0, _toInt(defaultJpegMaxH, 0));
const jpegMainQuality = Math.max(0, _toInt(defaultJpegQuality, 0));
let accessToken = String(
  urlParams.get("access_token")
  || urlParams.get("token")
  || localStorage.getItem("swarm_fpv_access_token")
  || ""
).trim();
let pageExitHooked = false;
let pageExitLogoutSent = false;
if (accessToken){
  localStorage.setItem("swarm_fpv_access_token", accessToken);
}

function clearStoredAccessToken(){
  accessToken = "";
  pageExitLogoutSent = false;
  try{
    localStorage.removeItem("swarm_fpv_access_token");
  }catch(_e){}
}

function withAuthPath(path){
  const p = String(path || "");
  if (!accessToken) return p;
  return p + (p.includes("?") ? "&" : "?") + "access_token=" + encodeURIComponent(accessToken);
}

function buildMainJpegUrl(robot){
  const params = new URLSearchParams();
  params.set("robot", String(robot || ""));
  params.set("t", String(Date.now()));
  if (jpegMainMaxW > 0){
    params.set("max_w", String(jpegMainMaxW));
  }
  if (jpegMainMaxH > 0){
    params.set("max_h", String(jpegMainMaxH));
  }
  if (jpegMainQuality > 0){
    params.set("quality", String(jpegMainQuality));
  }
  return withAuthPath(`/api/jpeg?${params.toString()}`);
}

function authHeaders(extra={}){
  const headers = Object.assign({}, extra);
  if (accessToken){
    headers["Authorization"] = "Bearer " + accessToken;
  }
  return headers;
}

function _closeRealtimeClients(){
  try{
    stopAllDriveHolds(true);
    pressedDriveKeys.clear();
  }catch(_e){}
  if (localRobotSwitchTimer){
    clearTimeout(localRobotSwitchTimer);
    localRobotSwitchTimer = null;
    pendingLocalRobotSelection = null;
  }
  if (webrtcOfferAbortController){
    try { webrtcOfferAbortController.abort(); } catch(_e){}
    webrtcOfferAbortController = null;
  }
  if (ws){
    try { ws.close(1000, "page_close"); } catch(_e){}
    ws = null;
  }
  if (pc){
    try { pc.close(); } catch(_e){}
    pc = null;
  }
  updateTransportBadge();
}

function sendPageExitLogout(reason){
  if (pageExitLogoutSent) return;
  const token = String(accessToken || "").trim();
  if (!token) return;
  pageExitLogoutSent = true;
  const payload = JSON.stringify({ reason: String(reason || "page_close") });
  const url = withAuthPath("/api/dev/logout");
  try{
    if (navigator.sendBeacon){
      const blob = new Blob([payload], { type: "application/json" });
      navigator.sendBeacon(url, blob);
      return;
    }
  }catch(_e){}
  try{
    fetch(url, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: payload,
      keepalive: true,
    }).catch(() => {});
  }catch(_e){}
}

function hookPageExitSessionShutdown(){
  if (pageExitHooked) return;
  pageExitHooked = true;
  const onExit = () => {
    sendPageExitLogout("page_close");
    _closeRealtimeClients();
    clearStoredAccessToken();
  };
  window.addEventListener("pagehide", onExit);
  window.addEventListener("beforeunload", onExit);
}

function _toNumber(v, fallback=0.0){
  const n = Number(v);
  return Number.isFinite(n) ? n : Number(fallback);
}

function _toInt(v, fallback=0){
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? n : Number(fallback);
}

function _clamp(v, lo, hi){
  return Math.max(lo, Math.min(hi, v));
}

function _isDiffDrive(cap){
  const dt = String((cap && cap.drive_type) || "").toLowerCase();
  return dt === "diff_drive" || dt === "diff" || dt === "diff-drive";
}

function _speedSummary(){
  const mode = strafeMode ? "STRAFE" : "NORMAL";
  return `[${mode}] lin=${driveLinearSpeed.toFixed(2)} ang=${driveAngularSpeed.toFixed(2)}`;
}

function _keyToken(event){
  const code = String((event && event.code) || "").toLowerCase();
  if (code) return "code:" + code;
  return "key:" + String((event && event.key) || "").toLowerCase();
}

function setDriveButtonActive(token, active){
  const k = String(token || "").trim();
  if (!k) return;
  const btn = driveButtonsByToken.get(k);
  if (!btn) return;
  if (active){
    btn.classList.add("active");
    activeDriveButtonTokens.add(k);
    return;
  }
  btn.classList.remove("active");
  activeDriveButtonTokens.delete(k);
}

function clearDriveButtonActiveStates(){
  for (const k of activeDriveButtonTokens){
    const btn = driveButtonsByToken.get(k);
    if (btn){
      btn.classList.remove("active");
    }
  }
  activeDriveButtonTokens.clear();
}

function startMainVideoFrameWatch(){
  if (mainVideoFrameWatchStarted) return;
  const video = $("mainVideo");
  if (!video || typeof video.requestVideoFrameCallback !== "function"){
    return;
  }
  mainVideoFrameWatchStarted = true;
  const pump = () => {
    try{
      video.requestVideoFrameCallback(() => {
        mainVideoLastFrameAtMs = Date.now();
        pump();
      });
    }catch(_e){}
  };
  pump();
}

function driveButtonTokenForEvent(event){
  const key = String((event && event.key) || "");
  const code = String((event && event.code) || "");
  const k = key.toLowerCase();

  if (key === "5" || code === "Numpad5" || key === " " || code === "Space" || k === "s"){
    return "stop";
  }
  if (key === "ArrowUp" || key === "8" || code === "Numpad8"){
    return "8";
  }
  if (key === "ArrowDown" || key === "2" || code === "Numpad2"){
    return "2";
  }
  if (key === "ArrowLeft" || key === "4" || code === "Numpad4"){
    return "arrow_left";
  }
  if (key === "ArrowRight" || key === "6" || code === "Numpad6"){
    return "arrow_right";
  }
  if (key === "7" || code === "Numpad7") return "7";
  if (key === "9" || code === "Numpad9") return "9";
  if (key === "1" || code === "Numpad1") return "1";
  if (key === "3" || code === "Numpad3") return "3";
  return "";
}

function _isTypingContext(event){
  const el = (event && event.target) || document.activeElement;
  if (!el) return false;
  const tag = String(el.tagName || "").toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.isContentEditable) return true;
  return false;
}

function _clearDriveHoldTimer(tag, keepEntry=true){
  const timer = driveHoldTimers.get(tag);
  if (timer){
    clearInterval(timer);
  }
  if (keepEntry){
    driveHoldTimers.set(tag, null);
  } else {
    driveHoldTimers.delete(tag);
  }
}

function _syncDriveHoldController(sendStopIfIdle=true){
  const nextTag = driveHoldOrder.length ? driveHoldOrder[driveHoldOrder.length - 1] : "";
  const prevTag = activeDriveHoldTag;
  if (prevTag && prevTag !== nextTag){
    _clearDriveHoldTimer(prevTag, true);
  }
  if (!nextTag){
    activeDriveHoldTag = "";
    clearDriveButtonActiveStates();
    if (sendStopIfIdle){
      drive(0, 0, 0, 0);
    }
    return;
  }

  activeDriveHoldTag = nextTag;
  clearDriveButtonActiveStates();
  const btnToken = String(driveHoldButtonTokens.get(nextTag) || "").trim();
  if (btnToken){
    setDriveButtonActive(btnToken, true);
  }

  if (nextTag === prevTag && driveHoldTimers.get(nextTag)){
    return;
  }

  const cmdFn = driveHoldCommands.get(nextTag);
  if (typeof cmdFn !== "function"){
    return;
  }
  cmdFn();
  const timer = setInterval(cmdFn, DRIVE_HOLD_INTERVAL_MS);
  driveHoldTimers.set(nextTag, timer);
}

function startDriveHold(tag, cmdFn, buttonToken=""){
  if (!tag || typeof cmdFn !== "function") return;
  if (driveHoldCommands.has(tag)) return;
  driveHoldCommands.set(tag, cmdFn);
  const safeButtonToken = String(buttonToken || "").trim();
  if (safeButtonToken){
    driveHoldButtonTokens.set(tag, safeButtonToken);
  } else {
    driveHoldButtonTokens.delete(tag);
  }
  driveHoldTimers.set(tag, null);
  driveHoldOrder.push(tag);
  _syncDriveHoldController(false);
}

function stopDriveHold(tag, sendStop=true){
  if (!tag) return;
  const idx = driveHoldOrder.indexOf(tag);
  const wasActive = (activeDriveHoldTag === tag);
  _clearDriveHoldTimer(tag, false);
  driveHoldCommands.delete(tag);
  driveHoldButtonTokens.delete(tag);
  if (idx >= 0){
    driveHoldOrder.splice(idx, 1);
  }
  if (wasActive || driveHoldOrder.length === 0){
    _syncDriveHoldController(sendStop);
  }
}

function stopAllDriveHolds(sendStop=true){
  for (const tag of driveHoldOrder){
    _clearDriveHoldTimer(tag, false);
  }
  driveHoldCommands.clear();
  driveHoldButtonTokens.clear();
  driveHoldOrder.length = 0;
  driveHoldTimers.clear();
  activeDriveHoldTag = "";
  clearDriveButtonActiveStates();
  if (sendStop){
    drive(0, 0, 0, 0);
  }
}

function stopDriveHoldsByPrefix(prefix, sendStop=true){
  const safePrefix = String(prefix || "");
  if (!safePrefix) return;
  const matches = driveHoldOrder.filter((tag) => String(tag || "").startsWith(safePrefix));
  if (!matches.length) return;
  for (const tag of matches){
    stopDriveHold(tag, false);
  }
  if (sendStop && driveHoldOrder.length === 0){
    drive(0, 0, 0, 0);
  }
}

function configureDriveProfile(robot){
  const c = capFor(robot || "");
  const baseLinear = Math.max(0.0, _toNumber(c.teleop_linear_mps, 0.5));
  const baseAngular = Math.max(0.0, _toNumber(c.teleop_angular_rps, 1.0));
  let step = _toNumber(c.teleop_speed_step, 1.1);
  if (step <= 1.0) step = 1.1;
  const mediumSteps = Math.max(0, _toInt(c.teleop_medium_steps, 10));
  const fastLinearSteps = Math.max(0, _toInt(c.teleop_fast_linear_steps, 15));
  const fastAngularSteps = Math.max(0, _toInt(c.teleop_fast_angular_steps, 10));

  driveSlowLinear = baseLinear;
  driveSlowAngular = baseAngular;
  driveSpeedStep = step;
  driveMediumLinear = driveSlowLinear * Math.pow(driveSpeedStep, mediumSteps);
  driveMediumAngular = driveSlowAngular * Math.pow(driveSpeedStep, mediumSteps);
  driveFastLinear = driveSlowLinear * Math.pow(driveSpeedStep, fastLinearSteps);
  driveFastAngular = driveSlowAngular * Math.pow(driveSpeedStep, fastAngularSteps);
  driveLinearSpeed = driveSlowLinear;
  driveAngularSpeed = driveSlowAngular;
  driveOmniTurnGain = Math.max(0.0, _toNumber(c.teleop_omni_turn_gain, 0.5));
  driveDiffArcInnerRatio = _clamp(_toNumber(c.teleop_diff_arc_inner_ratio, 0.6), 0.0, 1.0);
  driveWheelSeparation = Math.max(1e-3, _toNumber(c.wheel_separation_m, 0.18));
  strafeMode = false;
  driveProfileRobot = robot || null;
}

function _diffArcCommand(token, linearMag){
  const outer = Math.abs(linearMag);
  const inner = outer * driveDiffArcInnerRatio;
  let vLeft = 0.0;
  let vRight = 0.0;
  if (token === "7"){
    vLeft = inner;
    vRight = outer;
  } else if (token === "9"){
    vLeft = outer;
    vRight = inner;
  } else if (token === "1"){
    vLeft = -inner;
    vRight = -outer;
  } else if (token === "3"){
    vLeft = -outer;
    vRight = -inner;
  } else {
    return null;
  }
  const L = Math.max(1e-6, driveWheelSeparation);
  const v = 0.5 * (vLeft + vRight);
  const w = (vRight - vLeft) / L;
  return { lin: v, yaw: w, lat: 0.0, vert: 0.0 };
}

function _omniArcCommand(token, linearMag, angularMag){
  const yawMag = driveOmniTurnGain * angularMag;
  if (token === "7") return { lin: +linearMag, yaw: +yawMag, lat: 0.0, vert: 0.0 };
  if (token === "9") return { lin: +linearMag, yaw: -yawMag, lat: 0.0, vert: 0.0 };
  if (token === "1") return { lin: -linearMag, yaw: +yawMag, lat: 0.0, vert: 0.0 };
  if (token === "3") return { lin: -linearMag, yaw: -yawMag, lat: 0.0, vert: 0.0 };
  return null;
}

function driveCommandForToken(token){
  if (!activeRobot) return null;
  if (!canControlRobot(activeRobot)) return null;
  const c = capFor(activeRobot);
  const S = Math.max(0.0, _toNumber(driveLinearSpeed, 0.0));
  const A = Math.max(0.0, _toNumber(driveAngularSpeed, 0.0));

  if (token === "arrow_up") return { lin: +S, yaw: 0.0, lat: 0.0, vert: 0.0 };
  if (token === "arrow_down") return { lin: -S, yaw: 0.0, lat: 0.0, vert: 0.0 };
  if (token === "arrow_left"){
    if (strafeMode && c.can_strafe) return { lin: 0.0, yaw: 0.0, lat: +S, vert: 0.0 };
    return { lin: 0.0, yaw: +A, lat: 0.0, vert: 0.0 };
  }
  if (token === "arrow_right"){
    if (strafeMode && c.can_strafe) return { lin: 0.0, yaw: 0.0, lat: -S, vert: 0.0 };
    return { lin: 0.0, yaw: -A, lat: 0.0, vert: 0.0 };
  }

  if (token === "8") return { lin: +S, yaw: 0.0, lat: 0.0, vert: 0.0 };
  if (token === "2") return { lin: -S, yaw: 0.0, lat: 0.0, vert: 0.0 };

  if (token === "4"){
    if (strafeMode && c.can_strafe) return { lin: 0.0, yaw: 0.0, lat: +S, vert: 0.0 };
    return { lin: 0.0, yaw: +A, lat: 0.0, vert: 0.0 };
  }
  if (token === "6"){
    if (strafeMode && c.can_strafe) return { lin: 0.0, yaw: 0.0, lat: -S, vert: 0.0 };
    return { lin: 0.0, yaw: -A, lat: 0.0, vert: 0.0 };
  }

  if (token === "7" || token === "9" || token === "1" || token === "3"){
    if (strafeMode && c.can_strafe){
      if (token === "7") return { lin: +S, yaw: 0.0, lat: +S, vert: 0.0 };
      if (token === "9") return { lin: +S, yaw: 0.0, lat: -S, vert: 0.0 };
      if (token === "1") return { lin: -S, yaw: 0.0, lat: +S, vert: 0.0 };
      if (token === "3") return { lin: -S, yaw: 0.0, lat: -S, vert: 0.0 };
    }
    if (_isDiffDrive(c)){
      return _diffArcCommand(token, S);
    }
    return _omniArcCommand(token, S, A);
  }

  return null;
}

function toggleStrafeMode(){
  if (!activeRobot) return false;
  if (!canControlRobot(activeRobot)){
    setStatus(`[TRUST] '${activeRobot}' is read-only until it is added/synced into the trusted robot registry.`);
    return true;
  }
  const c = capFor(activeRobot);
  if (!c.can_strafe){
    strafeMode = false;
    setStatus("[STRAFE] Disabled: active robot is not mecanum/omni.");
    renderCapabilityMeta();
    renderDriveControls();
    return true;
  }
  strafeMode = !strafeMode;
  stopAllDriveHolds(true);
  pressedDriveKeys.clear();
  setStatus(`[STRAFE] ${strafeMode ? "ENABLED" : "DISABLED"} ${_speedSummary()}`);
  renderCapabilityMeta();
  renderDriveControls();
  return true;
}

function driveCommandForEvent(event){
  const key = String((event && event.key) || "");
  const code = String((event && event.code) || "");
  const k = key.toLowerCase();

  if (key === "5" || code === "Numpad5" || key === " " || code === "Space" || k === "s"){
    return { lin: 0.0, yaw: 0.0, lat: 0.0, vert: 0.0, stop: true };
  }
  if (key === "ArrowUp") return driveCommandForToken("arrow_up");
  if (key === "ArrowDown") return driveCommandForToken("arrow_down");
  if (key === "ArrowLeft") return driveCommandForToken("arrow_left");
  if (key === "ArrowRight") return driveCommandForToken("arrow_right");
  if (key === "8" || code === "Numpad8") return driveCommandForToken("8");
  if (key === "2" || code === "Numpad2") return driveCommandForToken("2");
  if (key === "4" || code === "Numpad4") return driveCommandForToken("4");
  if (key === "6" || code === "Numpad6") return driveCommandForToken("6");
  if (key === "7" || code === "Numpad7") return driveCommandForToken("7");
  if (key === "9" || code === "Numpad9") return driveCommandForToken("9");
  if (key === "1" || code === "Numpad1") return driveCommandForToken("1");
  if (key === "3" || code === "Numpad3") return driveCommandForToken("3");
  return null;
}

function handleTeleopSpeedAndModeKey(event){
  const key = String((event && event.key) || "");
  const code = String((event && event.code) || "");
  const k = key.toLowerCase();

  if (k === "m"){
    const sorted = [...robots].sort((a, b) => a.localeCompare(b));
    if (!sorted.length){
      return true;
    }
    const idx = sorted.indexOf(activeRobot);
    const next = sorted[(idx >= 0 ? idx + 1 : 0) % sorted.length];
    setActiveRobot(next, true, "local");
    setStatus(`[ROBOT] active=${next} ${_speedSummary()}`);
    return true;
  }

  if (!activeRobot) return false;

  if (k === "0" || code === "Numpad0"){
    return toggleStrafeMode();
  }

  if (k === "i"){
    driveLinearSpeed = driveSlowLinear;
    driveAngularSpeed = driveSlowAngular;
    setStatus(`[SPEED] slow ${_speedSummary()}`);
    renderCapabilityMeta();
    return true;
  }
  if (k === "o"){
    driveLinearSpeed = driveMediumLinear;
    driveAngularSpeed = driveMediumAngular;
    setStatus(`[SPEED] medium ${_speedSummary()}`);
    renderCapabilityMeta();
    return true;
  }
  if (k === "p"){
    driveLinearSpeed = driveFastLinear;
    driveAngularSpeed = driveFastAngular;
    setStatus(`[SPEED] fast ${_speedSummary()}`);
    renderCapabilityMeta();
    return true;
  }
  if (k === "w" || key === "+" || code === "NumpadAdd"){
    driveLinearSpeed *= driveSpeedStep;
    driveAngularSpeed *= driveSpeedStep;
    setStatus(`[SPEED] both+ ${_speedSummary()}`);
    renderCapabilityMeta();
    return true;
  }
  if (k === "e" || key === "-" || code === "NumpadSubtract"){
    driveLinearSpeed /= driveSpeedStep;
    driveAngularSpeed /= driveSpeedStep;
    setStatus(`[SPEED] both- ${_speedSummary()}`);
    renderCapabilityMeta();
    return true;
  }
  if (k === "q" || key === "/" || code === "NumpadDivide"){
    driveLinearSpeed *= driveSpeedStep;
    setStatus(`[SPEED] linear+ ${_speedSummary()}`);
    renderCapabilityMeta();
    return true;
  }
  if (k === "r" || key === "*" || code === "NumpadMultiply"){
    driveLinearSpeed /= driveSpeedStep;
    setStatus(`[SPEED] linear- ${_speedSummary()}`);
    renderCapabilityMeta();
    return true;
  }
  return false;
}

function hookKeyboardDrive(){
  if (keyboardDriveHooked) return;
  keyboardDriveHooked = true;

  window.addEventListener("keydown", (e) => {
    if (_isTypingContext(e)) return;
    if (handleTeleopSpeedAndModeKey(e)){
      e.preventDefault();
      return;
    }
    const cmd = driveCommandForEvent(e);
    if (!cmd) return;
    e.preventDefault();
    const token = _keyToken(e);
    const btnToken = driveButtonTokenForEvent(e);
    if (cmd.stop){
      stopAllDriveHolds(true);
      pressedDriveKeys.clear();
      clearDriveButtonActiveStates();
      return;
    }
    if (e.repeat || pressedDriveKeys.has(token)) return;
    pressedDriveKeys.add(token);
    startDriveHold(token, () => drive(cmd.lin, cmd.yaw, cmd.lat, cmd.vert), btnToken);
  }, { passive: false });

  window.addEventListener("keyup", (e) => {
    const cmd = driveCommandForEvent(e);
    if (!cmd) return;
    e.preventDefault();
    const token = _keyToken(e);
    pressedDriveKeys.delete(token);
    if (!cmd.stop){
      stopDriveHold(token, true);
    } else {
      clearDriveButtonActiveStates();
    }
  }, { passive: false });

  window.addEventListener("pointerup", () => {
    if (driveHoldOrder.length > 0){
      stopDriveHoldsByPrefix("btn:", true);
    }
  });

  window.addEventListener("mouseup", () => {
    if (driveHoldOrder.length > 0){
      stopDriveHoldsByPrefix("btn:", true);
    }
  });

  window.addEventListener("touchend", () => {
    if (driveHoldOrder.length > 0){
      stopDriveHoldsByPrefix("btn:", true);
    }
  }, { passive: true });

  window.addEventListener("touchcancel", () => {
    if (driveHoldOrder.length > 0){
      stopDriveHoldsByPrefix("btn:", true);
    }
  }, { passive: true });

  window.addEventListener("blur", () => {
    pressedDriveKeys.clear();
    stopAllDriveHolds(true);
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden){
      pressedDriveKeys.clear();
      stopAllDriveHolds(true);
      if (isWebrtcMainOnly()){
        const fb = $("mainJpeg");
        if (fb) fb.style.display = "none";
      }
    }
  });
}

function isLockedByOther(robot){
  const owner = locks[robot];
  if (!owner) return false;
  return owner !== clientId;
}

function lockSignature(lockMap){
  if (!lockMap) return "";
  const entries = Object.entries(lockMap)
    .map(([k, v]) => [String(k), String(v || "")])
    .sort((a, b) => a[0].localeCompare(b[0]));
  return entries.map(([k, v]) => `${k}:${v}`).join("|");
}

function wsSend(obj){
  if (ws && ws.readyState === WebSocket.OPEN){
    ws.send(JSON.stringify(obj));
  }
}

function normalizeIceTransportPolicy(raw){
  const v = String(raw || "").toLowerCase().trim();
  return v === "relay" ? "relay" : "all";
}

function sanitizeIceServers(raw){
  if (!Array.isArray(raw)) return [];
  const out = [];
  for (const row of raw){
    if (!row || typeof row !== "object") continue;
    let urls = row.urls;
    if (typeof urls === "string"){
      urls = [urls];
    }
    if (!Array.isArray(urls)) continue;
    const cleanUrls = urls.map((u) => String(u || "").trim()).filter((u) => u.length > 0);
    if (!cleanUrls.length) continue;
    const entry = { urls: cleanUrls };
    const username = String(row.username || "").trim();
    const credential = String(row.credential || "").trim();
    if (username) entry.username = username;
    if (credential) entry.credential = credential;
    out.push(entry);
  }
  return out;
}

function applyWebrtcState(payload){
  const w = payload && payload.webrtc ? payload.webrtc : null;
  if (!w || typeof w !== "object") return;
  const cfg = (w.client_config && typeof w.client_config === "object") ? w.client_config : {};
  const nextIceServers = sanitizeIceServers(cfg.iceServers);
  webrtcClientConfig = {
    iceServers: nextIceServers,
    iceTransportPolicy: normalizeIceTransportPolicy(cfg.iceTransportPolicy),
  };
  webrtcServerConfig = (w.server_config && typeof w.server_config === "object") ? w.server_config : {};
  webrtcTelemetry = (w.telemetry && typeof w.telemetry === "object") ? w.telemetry : {};
  if (typeof w.enabled === "boolean"){
    features.webrtc = Boolean(features.webrtc) && Boolean(w.enabled);
  }
}

function normalizeStreamMode(raw){
  const v = String(raw || "").trim().toLowerCase();
  if (v === "webrtc_only" || v === "webrtc-only" || v === "webrtc") return "webrtc_only";
  if (v === "jpeg_poll" || v === "jpeg-poll") return "jpeg_poll";
  if (v === "jpeg_only" || v === "jpeg-only" || v === "jpeg") return "jpeg_only";
  return "";
}

function applyStreamState(payload){
  const s = (payload && payload.stream && typeof payload.stream === "object") ? payload.stream : {};
  const serverMode = normalizeStreamMode(s.mode) || "webrtc_only";
  const overrideMode = normalizeStreamMode(requestedMainStream);
  streamConfig = {
    mode: overrideMode || serverMode,
    fps: Math.max(2, Math.min(60, _toNumber(s.fps, 15))),
  };
}

function isWebrtcMainOnly(){
  return streamConfig.mode === "webrtc_only";
}

function isJpegMainOnly(){
  return streamConfig.mode === "jpeg_only";
}

function allowsWebrtcMain(){
  return !isJpegMainOnly();
}

function applyThumbPolicy(payload){
  const n = Math.floor(_toNumber(payload && payload.thumb_robots_per_tick, 0));
  thumbRobotsPerTick = Math.max(0, n);
}

function isRobotLive(robot){
  const name = String(robot || "").trim();
  return Boolean(name && Array.isArray(liveRobots) && liveRobots.includes(name));
}

function robotPresenceStatus(robot){
  const h = (robotHealth && robotHealth[robot]) ? robotHealth[robot] : {};
  const raw = String(h.presence_status || "").trim().toLowerCase();
  if (raw) return raw;
  return isRobotLive(robot) ? "live" : "stale";
}

function robotThumbPriority(robot){
  const h = (robotHealth && robotHealth[robot]) ? robotHealth[robot] : {};
  const cam = String(h.status || "no_frame").trim().toLowerCase();
  const presence = robotPresenceStatus(robot);
  if (presence === "live" && cam === "live") return 0;
  if (presence === "live" && cam === "degraded") return 1;
  if (presence === "bootstrap") return 2;
  if (presence === "live") return 3;
  return 4;
}

function noteThumbFailure(robot){
  const name = String(robot || "").trim();
  if (!name) return;
  const streak = 1 + Number(thumbFailureStreak.get(name) || 0);
  thumbFailureStreak.set(name, streak);
  const capped = Math.min(5, streak);
  let backoffMs = 500 * (2 ** (capped - 1));
  const priority = robotThumbPriority(name);
  if (priority >= 4){
    backoffMs = Math.max(backoffMs, 6000);
  } else if (priority >= 3){
    backoffMs = Math.max(backoffMs, 2500);
  }
  thumbBackoffUntilMs.set(name, Date.now() + backoffMs);
}

function noteThumbSuccess(robot){
  const name = String(robot || "").trim();
  if (!name) return;
  thumbFailureStreak.delete(name);
  thumbBackoffUntilMs.delete(name);
}

function canAttemptThumb(robot, force=false){
  const name = String(robot || "").trim();
  if (!name) return false;
  if (force) return true;
  const untilMs = Number(thumbBackoffUntilMs.get(name) || 0);
  return Date.now() >= untilMs;
}

function thumbNeedsRefresh(imgEl, staleMs){
  if (!imgEl) return true;
  const last = Number(imgEl.dataset.lastFrameMs || 0);
  return last <= 0 || (Date.now() - last) >= Math.max(1000, Number(staleMs) || 0);
}

function normalizeRobotChoice(robot, available){
  const name = String(robot || "").trim();
  if (!name) return null;
  return Array.isArray(available) && available.includes(name) ? name : null;
}

function pickActiveRobot(preferredRobot, available, fallbackToFirst=true){
  const chosen = normalizeRobotChoice(preferredRobot, available);
  if (chosen) return chosen;
  if (fallbackToFirst && Array.isArray(available) && available.length){
    const first = String(available[0] || "").trim();
    return first || null;
  }
  return null;
}

function reconcileActiveRobotChoice(preferredRobot, available, currentRobot=null){
  const chosen = normalizeRobotChoice(preferredRobot, available);
  if (chosen) return chosen;
  const current = normalizeRobotChoice(currentRobot, available);
  if (current) return current;
  const liveSorted = Array.isArray(liveRobots)
    ? [...liveRobots].filter((robot) => Array.isArray(available) && available.includes(robot)).sort((a, b) => a.localeCompare(b))
    : [];
  return pickActiveRobot(null, liveSorted.length ? liveSorted : available, true);
}

function _toBool(v){
  if (typeof v === "boolean") return v;
  if (typeof v === "number") return v !== 0;
  const s = String(v || "").trim().toLowerCase();
  return s === "1" || s === "true" || s === "yes" || s === "on";
}

function isDriveSessionActive(){
  const dt = driveTelemetry || {};
  for (const robot of Object.keys(dt)){
    const row = dt[robot];
    if (row && (_toBool(row.hold_active) || _toBool(row.active))){
      return true;
    }
  }
  return false;
}

function startWebrtcRetryLoop(){
  setInterval(() => {
    if (document.hidden) return;
    if (!shouldRetryWebRTC()) return;
    setupWebRTC(activeRobot, webrtcSwitchNonce);
  }, 200);
}

async function fetchState(){
  const r = await fetch(withAuthPath("/api/state"), { headers: authHeaders() });
  let payload = {};
  try { payload = await r.json(); } catch(_e) {}
  if (!r.ok){
    const err = new Error(String(payload.error || `HTTP ${r.status}`));
    err.status = r.status;
    err.payload = payload;
    throw err;
  }
  return payload;
}

async function fetchStateWithReauth(){
  try{
    return await fetchState();
  }catch(err){
    const status = Number(err && err.status);
    if (status !== 401 || !accessToken){
      throw err;
    }
    clearStoredAccessToken();
    const loginReady = await ensureDevLoginIfRequired();
    if (!loginReady){
      throw err;
    }
    return await fetchState();
  }
}

async function fetchAuthConfig(){
  const r = await fetch("/api/auth/config");
  let payload = {};
  try { payload = await r.json(); } catch(_e) {}
  if (!r.ok){
    const err = new Error(String(payload.error || `HTTP ${r.status}`));
    err.status = r.status;
    err.payload = payload;
    throw err;
  }
  return payload;
}

async function loginDev(username, password){
  const r = await fetch("/api/dev/login", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ username, password }),
  });
  let payload = {};
  try { payload = await r.json(); } catch(_e) {}
  if (!r.ok){
    const err = new Error(String(payload.error || `HTTP ${r.status}`));
    err.status = r.status;
    err.payload = payload;
    throw err;
  }
  return payload;
}

async function ensureDevLoginIfRequired(){
  if (accessToken) return true;
  if (authConfig.mode !== "dev") return true;
  if (authConfig.allow_anonymous_readonly) return true;
  if (!authConfig.dev_login_enabled){
    setStatus("Authentication required: dev login is disabled.");
    return false;
  }

  for (let attempt = 1; attempt <= 3; attempt++){
    const username = window.prompt("FPV login username", "operator");
    if (username === null) return false;
    const password = window.prompt("FPV login password", "");
    if (password === null) return false;
    try{
      const out = await loginDev(String(username), String(password));
      const token = String(out.access_token || "").trim();
      if (!token){
        setStatus("Login failed: missing access token.");
        continue;
      }
      accessToken = token;
      pageExitLogoutSent = false;
      localStorage.setItem("swarm_fpv_access_token", accessToken);
      setStatus("Login successful.");
      return true;
    }catch(err){
      setStatus(`Login failed (${attempt}/3): ${err.message || "unknown error"}`);
    }
  }
  return false;
}

function capFor(robot){
  return robotCaps[robot] || {
    control_profile: "ground_xyaw",
    can_strafe: false,
    can_vertical: false,
    can_yaw: true,
    drive_type: "unknown",
    hardware: "unknown",
    profile: "",
    trusted: false,
    control_allowed: false,
    trust_status: "unknown_readonly",
    trust_reason: "Robot is not in the trusted registry.",
    teleop_linear_mps: 0.5,
    teleop_angular_rps: 1.0,
    teleop_speed_step: 1.1,
    teleop_medium_steps: 10,
    teleop_fast_linear_steps: 15,
    teleop_fast_angular_steps: 10,
    teleop_omni_turn_gain: 0.5,
    teleop_diff_arc_inner_ratio: 0.6,
    wheel_separation_m: 0.18
  };
}

function canControlRobot(robot){
  const name = String(robot || "").trim();
  if (!name) return false;
  const c = capFor(name);
  return Boolean(c && c.control_allowed);
}

function renderThumbRail(){
  const rail = $("thumbRail");
  rail.innerHTML = "";
  const sorted = [...robots].sort((a,b) => a.localeCompare(b));
  const liveSet = new Set(sorted);
  let primedThumbs = 0;
  for (const robot of sorted){
    const div = document.createElement("div");
    div.className = "thumb" + (robot === activeRobot ? " sel" : "");
    div.onclick = () => setActiveRobot(robot, true, "local");

    const img = document.createElement("img");
    const cachedThumb = thumbImageCache.get(robot) || {};
    img.src = cachedThumb.src || NO_SIGNAL_IMG;
    img.alt = "";
    img.dataset.lastFrameMs = String(cachedThumb.lastFrameMs || 0);
    div.appendChild(img);
    if (robot === activeRobot){
      const live = document.createElement("video");
      live.className = "thumb-live";
      live.autoplay = true;
      live.muted = true;
      live.playsInline = true;
      live.dataset.robot = robot;
      live.setAttribute("playsinline", "");
      div.appendChild(live);
    }
    // Prime only a small subset to avoid startup request bursts on large fleets.
    const primeBudget = Math.max(0, Math.floor(Number(thumbRobotsPerTick) || 0));
    if (primeBudget > 0 && robot !== activeRobot && primedThumbs < primeBudget && robotThumbPriority(robot) <= 1){
      refreshThumbImage(img, robot);
      primedThumbs += 1;
    }

    const lockBadge = document.createElement("div");
    lockBadge.className = "badge";
    const owner = locks[robot];
    if (!owner){
      lockBadge.textContent = canControlRobot(robot) ? "AVAILABLE" : "READ ONLY";
    }else if (owner === clientId){
      lockBadge.textContent = "YOU";
    }else{
      lockBadge.textContent = "IN USE";
    }

    const nameBadge = document.createElement("div");
    nameBadge.className = "badge badge-right";
    nameBadge.textContent = robot;

    div.appendChild(lockBadge);
    div.appendChild(nameBadge);
    rail.appendChild(div);
  }
  for (const robot of Array.from(thumbImageCache.keys())){
    if (!liveSet.has(robot)){
      thumbImageCache.delete(robot);
    }
  }
  syncActiveThumbVideo();
}

function updateThumbSelection(){
  const tiles = document.querySelectorAll(".thumb");
  for (const tile of tiles){
    const nameBadge = tile.querySelector(".badge-right");
    const robot = (nameBadge && nameBadge.textContent) ? nameBadge.textContent.trim() : "";
    tile.classList.toggle("sel", Boolean(robot) && robot === activeRobot);
  }
}

function syncActiveThumbVideo(){
  const main = $("mainVideo");
  const stream = main && main.srcObject ? main.srcObject : null;
  for (const live of document.querySelectorAll("video.thumb-live")){
    const robot = String(live.dataset.robot || "").trim();
    if (robot && robot === activeRobot && stream){
      if (live.srcObject !== stream){
        try { live.srcObject = stream; } catch(_e) {}
      }
      live.style.display = "block";
      try {
        const p = live.play();
        if (p && typeof p.catch === "function") p.catch(() => {});
      } catch(_e) {}
    } else {
      live.style.display = "none";
      if (live.srcObject){
        try { live.srcObject = null; } catch(_e) {}
      }
    }
  }
}

function refreshThumbImage(imgEl, robot){
  // Offscreen preload prevents tile flicker:
  // - old frame stays visible while loading next frame
  // - if fetch fails, old frame remains instead of flashing to black
  if (!imgEl || !robot) return;
  if (!canAttemptThumb(robot)) return;
  if (thumbRequestInFlight.get(robot)) return;
  thumbRequestInFlight.set(robot, true);
  const next = new Image();
  next.onload = () => {
    const loadedAtMs = Date.now();
    imgEl.src = next.src;
    imgEl.dataset.lastFrameMs = String(loadedAtMs);
    thumbImageCache.set(robot, { src: next.src, lastFrameMs: loadedAtMs });
    thumbRequestInFlight.delete(robot);
    noteThumbSuccess(robot);
  };
  next.onerror = () => {
    thumbRequestInFlight.delete(robot);
    noteThumbFailure(robot);
    if (!imgEl.src) imgEl.src = NO_SIGNAL_IMG;
  };
  next.src = withAuthPath(
    `/api/jpeg?robot=${encodeURIComponent(robot)}&max_w=${THUMB_JPEG_MAX_W}&max_h=${THUMB_JPEG_MAX_H}&quality=${THUMB_JPEG_QUALITY}&t=${Date.now()}`
  );
}

function renderCapabilityMeta(){
  const el = $("capMeta");
  if (!activeRobot){
    el.innerHTML = `<div class="small">No active robot</div>`;
    return;
  }
  const c = capFor(activeRobot);
  const trustLabel = c.control_allowed ? "trusted/control enabled" : "read-only/untrusted";
  el.innerHTML = `
    <div class="profile-label">Profiles</div>
    <div><b>Drive Type:</b> ${c.drive_type}</div>
    <div><b>Hardware:</b> ${c.hardware}</div>
    <div><b>Control Profile:</b> ${c.control_profile}</div>
    <div><b>Trust:</b> ${trustLabel}</div>
    <div><b>Drive Mode:</b> ${strafeMode ? "STRAFE" : "NORMAL"}</div>
    <div><b>Speed:</b> linear=${driveLinearSpeed.toFixed(2)} angular=${driveAngularSpeed.toFixed(2)}</div>
  `;
}

function drive(lin=0.0, yaw=0.0, lat=0.0, vert=0.0){
  if (!activeRobot) return;
  if (!canControlRobot(activeRobot)){
    setStatus(`[TRUST] '${activeRobot}' is visible but read-only. Add/sync it into robot_instances.yaml before driving.`);
    return;
  }
  if (isLockedByOther(activeRobot)){
    setStatus(`Robot '${activeRobot}' locked by another operator`);
    return;
  }
  wsSend({ type: "drive", robot: activeRobot, lin, yaw, lat, vert });
}

function renderDriveControls(){
  const wrap = $("driveControls");
  wrap.innerHTML = "";
  driveButtonsByToken.clear();
  activeDriveButtonTokens.clear();
  if (!activeRobot) return;
  const c = capFor(activeRobot);
  if (!c.control_allowed){
    const msg = document.createElement("div");
    msg.className = "small";
    msg.textContent = "Read-only: this robot is visible on ROS but is not in the trusted robot registry.";
    wrap.appendChild(msg);
    return;
  }

  const pad = document.createElement("div");
  pad.className = "drive-pad " + (c.can_strafe ? "with-strafe" : "no-strafe");
  wrap.appendChild(pad);

  let btnSeq = 0;
  const mkBtn = (txt, onDown, onUp, cls="", parent=pad, opts={}) => {
    const b = document.createElement("button");
    b.className = "btn " + cls;
    b.type = "button";
    b.textContent = txt;
    b.setAttribute("draggable", "false");
    b.oncontextmenu = (e) => { e.preventDefault(); };
    b.ondragstart = (e) => { e.preventDefault(); };
    b.onselectstart = (e) => { e.preventDefault(); };
    const continuous = opts.continuous !== false;
    const btnToken = String(opts.token || "").trim();
    if (btnToken){
      driveButtonsByToken.set(btnToken, b);
    }
    if (opts.gridColumn){
      b.style.gridColumn = String(opts.gridColumn);
    }
    const holdTag = opts.holdTag || `btn:${activeRobot || "none"}:${txt}:${btnSeq++}`;
    const start = (e) => {
      e.preventDefault();
      if (window.getSelection){
        const sel = window.getSelection();
        if (sel){
          try { sel.removeAllRanges(); } catch(_e) {}
        }
      }
      if (typeof b.setPointerCapture === "function"){
        try { b.setPointerCapture(e.pointerId); } catch(_e) {}
      }
      if (continuous){
        startDriveHold(holdTag, onDown, btnToken);
      } else {
        onDown();
      }
    };
    const stop = (e) => {
      e.preventDefault();
      if (continuous){
        stopDriveHold(holdTag, true);
      } else {
        onUp();
      }
    };
    if (window.PointerEvent){
      b.onpointerdown = start;
      b.onpointerup = stop;
      b.onpointercancel = stop;
      b.onlostpointercapture = stop;
    } else {
      b.onmousedown = start;
      b.onmouseup = stop;
      b.onmouseleave = stop;
      b.ontouchstart = start;
      b.ontouchend = stop;
      b.ontouchcancel = stop;
    }
    parent.appendChild(b);
  };

  const stopFn = () => drive(0,0,0,0);
  const sendToken = (token) => {
    const cmd = driveCommandForToken(token);
    if (!cmd) return;
    drive(cmd.lin, cmd.yaw, cmd.lat, cmd.vert);
  };
  const leftMidLabel = (c.can_strafe && strafeMode) ? "STRAFE LEFT" : "ROTATE LEFT";
  const rightMidLabel = (c.can_strafe && strafeMode) ? "STRAFE RIGHT" : "ROTATE RIGHT";

  mkBtn("LEFT-FORWARD", () => sendToken("7"), stopFn, "", pad, { token: "7" });
  mkBtn("FORWARD", () => sendToken("8"), stopFn, "primary", pad, { token: "8" });
  mkBtn("RIGHT-FORWARD", () => sendToken("9"), stopFn, "", pad, { token: "9" });

  mkBtn(leftMidLabel, () => sendToken("arrow_left"), stopFn, "", pad, { token: "arrow_left" });
  mkBtn("STOP", stopFn, stopFn, "danger", pad, { continuous: false, token: "stop" });
  mkBtn(rightMidLabel, () => sendToken("arrow_right"), stopFn, "", pad, { token: "arrow_right" });

  mkBtn("LEFT-BACKWARD", () => sendToken("1"), stopFn, "", pad, { token: "1" });
  mkBtn("BACKWARD", () => sendToken("2"), stopFn, "primary", pad, { token: "2" });
  mkBtn("RIGHT-BACKWARD", () => sendToken("3"), stopFn, "", pad, { token: "3" });

  if (c.can_strafe){
    const auxMode = document.createElement("div");
    auxMode.className = "drive-pad no-strafe";
    auxMode.style.marginTop = "8px";
    wrap.appendChild(auxMode);
    mkBtn(
      strafeMode ? "SWITCH TO NORMAL DRIVE" : "SWITCH TO STRAFE DRIVE",
      () => { toggleStrafeMode(); },
      () => {},
      strafeMode ? "primary active" : "primary",
      auxMode,
      { continuous: false, token: "toggle_strafe", gridColumn: "1 / -1" },
    );
  }
  if (c.can_vertical){
    const aux = document.createElement("div");
    aux.className = "drive-pad no-strafe";
    aux.style.marginTop = "8px";
    wrap.appendChild(aux);
    mkBtn("Ascend", () => drive(0,0,0,Math.abs(driveLinearSpeed)), stopFn, "", aux, { token: "ascend" });
    mkBtn("STOP Z", stopFn, stopFn, "danger", aux, { continuous: false, token: "stop_z" });
    mkBtn("Descend", () => drive(0,0,0,-Math.abs(driveLinearSpeed)), stopFn, "", aux, { token: "descend" });
  }
}

function sendAutonomyMode(mode){
  if (!activeRobot) return;
  if (!canControlRobot(activeRobot)){
    setStatus(`[TRUST] '${activeRobot}' is visible but read-only. Add/sync it before changing modes.`);
    return;
  }
  if (isLockedByOther(activeRobot)){
    setStatus(`Robot '${activeRobot}' locked by another operator`);
    return;
  }
  wsSend({ type: "autonomy_mode", robot: activeRobot, mode });
}

function renderModeControls(){
  const wrap = $("modeControls");
  wrap.innerHTML = "";
  if (activeRobot && !canControlRobot(activeRobot)){
    const msg = document.createElement("div");
    msg.className = "small";
    msg.textContent = "Autonomy controls disabled until this robot is trusted.";
    wrap.appendChild(msg);
    return;
  }
  const modes = [
    ["Manual", "manual"],
    ["Follow", "follow"],
    ["Patrol", "patrol"],
    ["Detect", "detect"],
  ];
  for (const [label, mode] of modes){
    const b = document.createElement("button");
    b.className = "btn";
    b.textContent = label;
    b.onclick = () => sendAutonomyMode(mode);
    wrap.appendChild(b);
  }
}

function fmtHealthAge(v){
  if (v === null || v === undefined) return "--";
  return `${Number(v).toFixed(2)}s`;
}

function fmtHealthFps(v){
  if (v === null || v === undefined) return "--";
  if (Number(v) <= 0.01) return "0.0";
  return Number(v).toFixed(1);
}

function fmtDriveHz(v){
  if (v === null || v === undefined) return "--";
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0.01) return "0.0";
  return n.toFixed(1);
}

function renderHealthPanel(){
  const wrap = $("healthPanel");
  wrap.innerHTML = "";
  if (!robots.length){
    wrap.innerHTML = `<div class="health-card"><div class="health-row"><b>No robots discovered</b></div></div>`;
    return;
  }
  const sorted = [...robots].sort((a,b) => a.localeCompare(b));
  for (const robot of sorted){
    const dt = driveTelemetry[robot] || {
      ws_rx_hz: 0.0,
      cmd_pub_hz: 0.0,
      target_age_s: null,
      hold_active: false,
      cmd_rate_target_hz: 0.0,
      hold_timeout_s: 0.0,
    };
    const h = robotHealth[robot] || {
      status: "no_frame",
      presence_status: "stale",
      presence_reason: "No robot presence diagnostics available yet.",
      heartbeat_age_s: null,
      topic_age_s: null,
      topic: `/${robot}/image_raw`,
      frame_age_s: null,
      fps: 0.0,
      publisher_count: 0,
      probable_cause: "No diagnostics available yet.",
      encoding: "unknown",
      camera_strategy: "",
      camera_last_error: ""
    };
    const cap = capFor(robot);
    const status = String(h.status || "no_frame");
    const cause = String(h.probable_cause || "No diagnostics available.");
    const safeCause = cause.replace(/"/g, "&quot;");
    const card = document.createElement("div");
    card.className = "health-card";
    card.innerHTML = `
      <div class="health-top">
        <div class="health-head">
          <div class="health-name">${robot}</div>
          <div class="tip" data-tip="${safeCause}" title="${safeCause}">?</div>
        </div>
        <div class="pill ${status}">${status.replace("_"," ")}</div>
      </div>
      <div class="health-row"><b>Topic:</b> ${h.topic || "--"}</div>
      <div class="health-row"><b>Encoding:</b> ${h.encoding || "unknown"}</div>
      <div class="health-row"><b>Strategy:</b> ${h.camera_strategy || "--"}</div>
      <div class="health-row"><b>Cam error:</b> ${h.camera_last_error || "--"}</div>
      <div class="health-row"><b>Presence:</b> ${h.presence_status || "--"}</div>
      <div class="health-row"><b>Trust:</b> ${cap.control_allowed ? "control enabled" : "read-only"} (${cap.trust_status || "unknown"})</div>
      <div class="health-row"><b>Heartbeat age:</b> ${fmtHealthAge(h.heartbeat_age_s)}</div>
      <div class="health-row"><b>Topic age:</b> ${fmtHealthAge(h.topic_age_s)}</div>
      <div class="health-row"><b>Publishers:</b> ${Number(h.publisher_count || 0)}</div>
      <div class="health-row"><b>Frame age:</b> ${fmtHealthAge(h.frame_age_s)}</div>
      <div class="health-row"><b>FPS (EMA):</b> ${fmtHealthFps(h.fps)}</div>
      <div class="health-row"><b>Drive in (WS Hz):</b> ${fmtDriveHz(dt.ws_rx_hz)}</div>
      <div class="health-row"><b>cmd_vel out (Hz):</b> ${fmtDriveHz(dt.cmd_pub_hz)}</div>
      <div class="health-row"><b>Drive target age:</b> ${fmtHealthAge(dt.target_age_s)}</div>
      <div class="health-row"><b>Drive hold active:</b> ${dt.hold_active ? "yes" : "no"}</div>
      <div class="health-row"><b>Drive rate status:</b> ${dt.rate_status || "idle"}</div>
      <div class="health-row"><b>Drive loop:</b> ${fmtDriveHz(dt.cmd_rate_target_hz)}Hz (timeout ${fmtHealthAge(dt.hold_timeout_s)})</div>
    `;
    wrap.appendChild(card);
  }
}

function _fmtStateCounters(v){
  if (!v || typeof v !== "object") return "--";
  const entries = Object.entries(v)
    .map(([k, n]) => [String(k), Number(n)])
    .filter(([k, n]) => k && Number.isFinite(n));
  if (!entries.length) return "--";
  entries.sort((a, b) => a[0].localeCompare(b[0]));
  return entries.map(([k, n]) => `${k}:${n}`).join(" | ");
}

function _fmtNumber(v, fallback=0){
  const n = Number(v);
  return Number.isFinite(n) ? n : Number(fallback);
}

function _escapeHtml(s){
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderWebrtcDiagnostics(){
  const wrap = $("webrtcDiagPanel");
  if (!wrap) return;

  const enabled = Boolean(features && features.webrtc);
  const localConn = pc ? String(pc.connectionState || "new") : "none";
  const localIceConn = pc ? String(pc.iceConnectionState || "new") : "none";
  const localIceGather = pc ? String(pc.iceGatheringState || "new") : "none";

  let pillClass = "no_frame";
  let pillText = "inactive";
  if (enabled){
    if (localConn === "connected"){
      pillClass = "live";
      pillText = "connected";
    } else if (localConn === "connecting" || localConn === "new"){
      pillClass = "degraded";
      pillText = localConn;
    } else if (localConn === "none"){
      pillClass = "degraded";
      pillText = "ready";
    } else {
      pillClass = "stale";
      pillText = localConn;
    }
  }

  const t = (webrtcTelemetry && typeof webrtcTelemetry === "object") ? webrtcTelemetry : {};
  const sc = (webrtcServerConfig && typeof webrtcServerConfig === "object") ? webrtcServerConfig : {};
  const iceServers = Array.isArray(webrtcClientConfig.iceServers) ? webrtcClientConfig.iceServers : [];
  const icePolicy = normalizeIceTransportPolicy(webrtcClientConfig.iceTransportPolicy);
  const turnServerEntries = _fmtNumber(sc.turn_server_entries);
  const offerErr = String(t.last_offer_error || "").trim();
  const offerErrAge = t.last_offer_error_age_s;
  const errAgeTxt = Number.isFinite(Number(offerErrAge)) ? `${Number(offerErrAge).toFixed(1)}s` : "--";
  const lastClientEvent = (t.last_client_event && typeof t.last_client_event === "object") ? t.last_client_event : {};
  const lastClientEventName = String(lastClientEvent.event || "--");
  const lastClientEventRobot = String(lastClientEvent.robot || "--");

  wrap.innerHTML = `
    <div class="webrtc-card">
      <div class="webrtc-title">
        <div><b>WebRTC Client</b></div>
        <div class="pill ${pillClass}">${_escapeHtml(pillText)}</div>
      </div>
      <div class="webrtc-row"><b>Enabled:</b> ${enabled ? "true" : "false"}</div>
      <div class="webrtc-row"><b>ICE policy:</b> <span class="webrtc-mono">${_escapeHtml(icePolicy)}</span></div>
      <div class="webrtc-row"><b>ICE servers:</b> ${iceServers.length}</div>
      <div class="webrtc-row"><b>TURN entries:</b> ${turnServerEntries}</div>
      <div class="webrtc-row"><b>PC state:</b> <span class="webrtc-mono">${_escapeHtml(localConn)}</span></div>
      <div class="webrtc-row"><b>ICE state:</b> <span class="webrtc-mono">${_escapeHtml(localIceConn)}</span></div>
      <div class="webrtc-row"><b>Gathering:</b> <span class="webrtc-mono">${_escapeHtml(localIceGather)}</span></div>
      <div class="webrtc-row"><b>Last client event:</b> <span class="webrtc-mono">${_escapeHtml(lastClientEventName)}</span></div>
      <div class="webrtc-row"><b>Event robot:</b> <span class="webrtc-mono">${_escapeHtml(lastClientEventRobot)}</span></div>
    </div>
    <div class="webrtc-card">
      <div class="webrtc-title">
        <div><b>WebRTC Server</b></div>
      </div>
      <div class="webrtc-row"><b>Offers:</b> total=${_fmtNumber(t.offers_total)} ok=${_fmtNumber(t.offers_success)} fail=${_fmtNumber(t.offers_failed)}</div>
      <div class="webrtc-row"><b>Peer conns:</b> active=${_fmtNumber(t.active_peer_connections)} opened=${_fmtNumber(t.opened_peer_connections_total)} closed=${_fmtNumber(t.closed_peer_connections_total)}</div>
      <div class="webrtc-row"><b>Conn states:</b> <span class="webrtc-mono">${_escapeHtml(_fmtStateCounters(t.connection_states))}</span></div>
      <div class="webrtc-row"><b>ICE conn:</b> <span class="webrtc-mono">${_escapeHtml(_fmtStateCounters(t.ice_connection_states))}</span></div>
      <div class="webrtc-row"><b>ICE gather:</b> <span class="webrtc-mono">${_escapeHtml(_fmtStateCounters(t.ice_gathering_states))}</span></div>
      <div class="webrtc-row"><b>Client events total:</b> ${_fmtNumber(t.client_events_total)}</div>
      <div class="webrtc-row"><b>Last offer robot:</b> <span class="webrtc-mono">${_escapeHtml(String(t.last_offer_robot || "--"))}</span></div>
      <div class="webrtc-row"><b>Last offer client:</b> <span class="webrtc-mono">${_escapeHtml(String(t.last_offer_client_id || "--"))}</span></div>
      <div class="webrtc-row"><b>Last error:</b> <span class="webrtc-mono">${_escapeHtml(offerErr || "--")}</span></div>
      <div class="webrtc-row"><b>Error age:</b> <span class="webrtc-mono">${_escapeHtml(errAgeTxt)}</span></div>
    </div>
  `;
  updateTransportBadge();
}

function hasWebRtcFrameNow(){
  const v = $("mainVideo");
  const freshFrame = (!mainVideoFrameWatchStarted) || ((Date.now() - Number(mainVideoLastFrameAtMs || 0)) <= 1200);
  return Boolean(
    features.webrtc &&
    activeRobot &&
    v &&
    v.srcObject &&
    v.readyState >= 2 &&
    freshFrame &&
    v.videoWidth > 0 &&
    v.videoHeight > 0
  );
}

function shouldRetryWebRTC(){
  if (!activeRobot) return false;
  if (!allowsWebrtcMain()) return false;
  if (!features.webrtc) return false;
  if (webrtcAttemptInFlight) return false;
  if (Date.now() < webrtcRetryAtMs) return false;
  if (!pc) return true;
  const conn = String(pc.connectionState || "").toLowerCase();
  const ice = String(pc.iceConnectionState || "").toLowerCase();
  if (conn === "failed" || conn === "disconnected" || conn === "closed"){
    return true;
  }
  if (ice === "failed" || ice === "disconnected" || ice === "closed"){
    return true;
  }
  if (hasWebRtcFrameNow()){
    return false;
  }
  const sinceSwitchMs = Date.now() - Number(activeRobotSwitchAtMs || 0);
  if (sinceSwitchMs < WEBRTC_STALE_FRAME_MS){
    return false;
  }
  const sinceFrameMs = Date.now() - Number(mainVideoLastFrameAtMs || 0);
  return sinceFrameMs >= WEBRTC_STALE_FRAME_MS;
}

function updateTransportBadge(){
  const badge = $("transportBadge");
  if (!badge) return;
  const inSwitchGrace = Boolean(
    activeRobot &&
    features.webrtc &&
    (Date.now() - activeRobotSwitchAtMs) < ROBOT_SWITCH_GRACE_MS
  );
  const fb = $("mainJpeg");
  const jpegVisible = Boolean(fb && fb.style.display !== "none" && activeRobot);

  let klass = "offline";
  let text = "No stream";

  if (!activeRobot){
    text = "No robot";
  } else if (isJpegMainOnly()){
    klass = "fallback";
    text = jpegVisible ? "JPEG" : "JPEG loading";
  } else if (inSwitchGrace){
    klass = "fallback";
    text = "WebRTC switching";
  } else if (hasWebRtcFrameNow()){
    klass = "webrtc";
    text = "WebRTC";
  } else if (!features.webrtc){
    klass = "fallback";
    text = isWebrtcMainOnly() ? "WebRTC unavailable" : "JPEG fallback";
  } else if (!isWebrtcMainOnly() && jpegVisible){
    klass = "fallback";
    text = "JPEG fallback";
  } else {
    const conn = pc ? String(pc.connectionState || "new") : "new";
    if (conn === "connecting" || conn === "new" || webrtcAttemptInFlight){
      klass = "fallback";
      text = "WebRTC connecting";
    } else {
      klass = "fallback";
      text = "WebRTC retrying";
    }
  }

  badge.className = `transport-badge ${klass}`;
  badge.textContent = text;
}

function closePeerConnection(targetPc=null){
  const candidate = targetPc || pc;
  if (!candidate) return;
  try { candidate.ontrack = null; } catch(_e){}
  try { candidate.onconnectionstatechange = null; } catch(_e){}
  try { candidate.oniceconnectionstatechange = null; } catch(_e){}
  try { candidate.onicegatheringstatechange = null; } catch(_e){}
  try { candidate.close(); } catch(_e){}
  if (pc === candidate){
    pc = null;
    mainVideoLastFrameAtMs = 0;
    const v = $("mainVideo");
    if (v && v.srcObject){
      try { v.srcObject = null; } catch(_e){}
    }
    syncActiveThumbVideo();
  }
}

async function setupWebRTC(robot, switchNonce=webrtcSwitchNonce){
  const requestedRobot = String(robot || "");
  if (!allowsWebrtcMain()){
    if (robot){
      setStatus("JPEG main stream active.");
      const fb = $("mainJpeg");
      if (fb) fb.style.display = "block";
    }
    updateTransportBadge();
    return;
  }
  if (!features.webrtc || !robot){
    if (robot && !features.webrtc){
      setStatus(isWebrtcMainOnly() ? "WebRTC unavailable" : "WebRTC unavailable, using JPEG fallback");
    }
    if (isWebrtcMainOnly()){
      const fb = $("mainJpeg");
      if (fb) fb.style.display = "none";
    }
    updateTransportBadge();
    return;
  }
  if (Number(switchNonce) !== webrtcSwitchNonce){
    return;
  }
  if (webrtcAttemptInFlight){
    return;
  }
  webrtcAttemptInFlight = true;
  let attemptPc = null;
  try{
    if (Number(switchNonce) !== webrtcSwitchNonce || requestedRobot !== String(activeRobot || "")){
      return;
    }
    if (webrtcOfferAbortController){
      try { webrtcOfferAbortController.abort(); } catch(_e){}
      webrtcOfferAbortController = null;
    }
    closePeerConnection();
    const rtcCfg = {};
    if (Array.isArray(webrtcClientConfig.iceServers) && webrtcClientConfig.iceServers.length){
      rtcCfg.iceServers = webrtcClientConfig.iceServers;
    }
    const transportPolicy = normalizeIceTransportPolicy(webrtcClientConfig.iceTransportPolicy);
    rtcCfg.iceTransportPolicy = transportPolicy;
    pc = new RTCPeerConnection(rtcCfg);
    attemptPc = pc;
    renderWebrtcDiagnostics();
    updateTransportBadge();

    const sendWebrtcTelemetry = (eventName) => {
      wsSend({
        type: "webrtc_telemetry",
        robot,
        event: String(eventName || ""),
        connection_state: String((attemptPc && attemptPc.connectionState) || ""),
        ice_connection_state: String((attemptPc && attemptPc.iceConnectionState) || ""),
        ice_gathering_state: String((attemptPc && attemptPc.iceGatheringState) || ""),
      });
    };

    attemptPc.onconnectionstatechange = () => {
      if (attemptPc !== pc) return;
      sendWebrtcTelemetry("connection_state");
      renderWebrtcDiagnostics();
      updateTransportBadge();
    };
    attemptPc.oniceconnectionstatechange = () => {
      if (attemptPc !== pc) return;
      sendWebrtcTelemetry("ice_connection_state");
      renderWebrtcDiagnostics();
      updateTransportBadge();
    };
    attemptPc.onicegatheringstatechange = () => {
      if (attemptPc !== pc) return;
      sendWebrtcTelemetry("ice_gathering_state");
      renderWebrtcDiagnostics();
      updateTransportBadge();
    };

    // Explicit recvonly m-line avoids aiortc negotiation failures on
    // browser-only viewer sessions.
    try { attemptPc.addTransceiver("video", { direction: "recvonly" }); } catch(_e) {}
    attemptPc.ontrack = (evt) => {
      if (attemptPc !== pc) return;
      if (Number(switchNonce) !== webrtcSwitchNonce || !activeRobot || activeRobot !== requestedRobot){
        return;
      }
      if (evt.track.kind === "video"){
        $("mainVideo").srcObject = evt.streams[0];
        mainVideoLastFrameAtMs = Date.now();
        syncActiveThumbVideo();
      }
      webrtcRetryAtMs = 0;
      sendWebrtcTelemetry("track");
      renderWebrtcDiagnostics();
      updateTransportBadge();
    };
    const offer = await attemptPc.createOffer();
    if (Number(switchNonce) !== webrtcSwitchNonce || requestedRobot !== String(activeRobot || "")){
      closePeerConnection(attemptPc);
      return;
    }
    await attemptPc.setLocalDescription(offer);
    sendWebrtcTelemetry("local_description_set");
    renderWebrtcDiagnostics();
    const offerAbort = new AbortController();
    webrtcOfferAbortController = offerAbort;
    const resp = await fetch(withAuthPath("/webrtc/offer"), {
      method: "POST",
      headers: authHeaders({"Content-Type": "application/json"}),
      body: JSON.stringify({
        robot,
        client_id: clientId,
        sdp: attemptPc.localDescription.sdp,
        type: attemptPc.localDescription.type,
      }),
      signal: offerAbort.signal,
    });
    if (webrtcOfferAbortController === offerAbort){
      webrtcOfferAbortController = null;
    }
    if (Number(switchNonce) !== webrtcSwitchNonce || requestedRobot !== String(activeRobot || "")){
      closePeerConnection(attemptPc);
      return;
    }
    if (!resp.ok){
      if (isWebrtcMainOnly()){
        setStatus("WebRTC unavailable (main stream is WebRTC-only)");
      } else {
        setStatus("WebRTC unavailable, using JPEG fallback");
      }
      sendWebrtcTelemetry("offer_failed");
      if (isWebrtcMainOnly()){
        const fb = $("mainJpeg");
        if (fb) fb.style.display = "none";
      } else {
        const fb = $("mainJpeg");
        if (fb) fb.style.display = "block";
      }
      webrtcRetryAtMs = Date.now() + WEBRTC_RETRY_INTERVAL_MS;
      renderWebrtcDiagnostics();
      updateTransportBadge();
      return;
    }
    try{
      if (Number(switchNonce) !== webrtcSwitchNonce || !activeRobot || activeRobot !== requestedRobot){
        webrtcRetryAtMs = 0;
        closePeerConnection(attemptPc);
        return;
      }
      const ans = await resp.json();
      if (Number(switchNonce) !== webrtcSwitchNonce || !activeRobot || activeRobot !== requestedRobot){
        closePeerConnection(attemptPc);
        return;
      }
      await attemptPc.setRemoteDescription(ans);
      sendWebrtcTelemetry("remote_description_set");
      const fb = $("mainJpeg");
      if (fb) fb.style.display = "none";
      webrtcRetryAtMs = 0;
      renderWebrtcDiagnostics();
      updateTransportBadge();
    }catch(_e){
      if (isWebrtcMainOnly()){
        setStatus("WebRTC handshake failed (main stream is WebRTC-only)");
      } else {
        setStatus("WebRTC handshake failed, using JPEG fallback");
      }
      sendWebrtcTelemetry("answer_failed");
      if (isWebrtcMainOnly()){
        const fb = $("mainJpeg");
        if (fb) fb.style.display = "none";
      } else {
        const fb = $("mainJpeg");
        if (fb) fb.style.display = "block";
      }
      webrtcRetryAtMs = Date.now() + WEBRTC_RETRY_INTERVAL_MS;
      renderWebrtcDiagnostics();
      updateTransportBadge();
    }
  }catch(_err){
    setStatus(isWebrtcMainOnly() ? "WebRTC retrying" : "WebRTC retrying, JPEG fallback active");
    if (isWebrtcMainOnly()){
      const fb = $("mainJpeg");
      if (fb) fb.style.display = "none";
    } else {
      const fb = $("mainJpeg");
      if (fb) fb.style.display = "block";
    }
    webrtcRetryAtMs = Date.now() + WEBRTC_RETRY_INTERVAL_MS;
    updateTransportBadge();
  } finally {
    if (webrtcOfferAbortController && webrtcOfferAbortController.signal.aborted){
      webrtcOfferAbortController = null;
    }
    webrtcAttemptInFlight = false;
    updateTransportBadge();
  }
}

function setupMainFallbackLoop(){
  if (mainFallbackTimer){
    clearInterval(mainFallbackTimer);
    mainFallbackTimer = null;
  }
  mainFallbackInFlight = false;
  mainFallbackTimer = setInterval(() => {
    const fb = $("mainJpeg");
    if (!fb) return;
    if (!activeRobot){
      fb.style.display = "none";
      mainFallbackInFlight = false;
      updateTransportBadge();
      return;
    }
    const inSwitchGrace = Boolean(
      allowsWebrtcMain() &&
      features.webrtc &&
      (Date.now() - activeRobotSwitchAtMs) < ROBOT_SWITCH_GRACE_MS
    );
    if (inSwitchGrace){
      fb.style.display = "none";
      mainFallbackInFlight = false;
      if (!webrtcAttemptInFlight && Date.now() >= webrtcRetryAtMs){
        setupWebRTC(activeRobot, webrtcSwitchNonce);
      }
      updateTransportBadge();
      return;
    }
    if (hasWebRtcFrameNow()){
      fb.style.display = "none";
      mainFallbackInFlight = false;
      updateTransportBadge();
      return;
    }
    if (allowsWebrtcMain() && features.webrtc && !webrtcAttemptInFlight && Date.now() >= webrtcRetryAtMs){
      setupWebRTC(activeRobot, webrtcSwitchNonce);
    }
    if (isWebrtcMainOnly()){
      fb.style.display = "none";
      mainFallbackInFlight = false;
      updateTransportBadge();
      return;
    }
    fb.style.display = "block";
    if (mainFallbackInFlight){
      updateTransportBadge();
      return;
    }
    mainFallbackInFlight = true;
    const next = new Image();
    next.onload = () => {
      fb.src = next.src;
      mainFallbackInFlight = false;
      updateTransportBadge();
    };
    next.onerror = () => {
      mainFallbackInFlight = false;
      if (!fb.src) fb.src = NO_SIGNAL_IMG;
      updateTransportBadge();
    };
    next.src = buildMainJpegUrl(activeRobot);
    updateTransportBadge();
  }, jpegMainPollMs);
}

function setActiveRobot(robot, announce=true, source="local"){
  const src = String(source || "local").toLowerCase();
  if (src === "local"){
    pendingLocalRobotSelection = robot;
    if (localRobotSwitchTimer){
      clearTimeout(localRobotSwitchTimer);
    }
    localRobotSwitchTimer = setTimeout(() => {
      localRobotSwitchTimer = null;
      const targetRobot = pendingLocalRobotSelection;
      pendingLocalRobotSelection = null;
      setActiveRobot(targetRobot, announce, "local_now");
    }, ROBOT_SWITCH_DEBOUNCE_MS);
    return;
  }

  const effectiveSource = (src === "local_now") ? "local" : src;
  if (localRobotSwitchTimer && effectiveSource !== "local"){
    clearTimeout(localRobotSwitchTimer);
    localRobotSwitchTimer = null;
    pendingLocalRobotSelection = null;
  }

  if (effectiveSource === "server" && localActiveRobotPinned && robot && robot !== activeRobot){
    const currentStillAvailable = Boolean(activeRobot && robots.includes(activeRobot));
    if (currentStillAvailable){
      return;
    }
  }
  const changed = robot !== activeRobot;
  if (changed){
    stopAllDriveHolds(true);
    pressedDriveKeys.clear();
    webrtcSwitchNonce += 1;
    activeRobotSwitchAtMs = Date.now();
    webrtcRetryAtMs = activeRobotSwitchAtMs + 100;
    if (webrtcOfferAbortController){
      try { webrtcOfferAbortController.abort(); } catch(_e){}
      webrtcOfferAbortController = null;
    }
    closePeerConnection();
  }
  if (changed && effectiveSource === "local"){
    localActiveRobotPinned = true;
  }
  activeRobot = robot;
  if (activeRobot && (changed || driveProfileRobot !== activeRobot)){
    configureDriveProfile(activeRobot);
  }
  if (!activeRobot){
    driveProfileRobot = null;
    strafeMode = false;
  }
  $("activeTitle").textContent = robot || "No Robot Selected";
  const c = capFor(robot || "");
  $("activeMeta").textContent = robot ? `${c.drive_type} | ${c.hardware}` : "Choose a camera feed from the left rail";
  if (announce && robot && changed){
    wsSend({ type: "set_active_robot", robot });
  }
  if (changed){
    renderThumbRail();
  } else {
    updateThumbSelection();
    syncActiveThumbVideo();
  }
  renderCapabilityMeta();
  renderDriveControls();
  renderModeControls();
  renderWebrtcDiagnostics();
  updateTransportBadge();
  if (changed){
    if (!robot){
      const v = $("mainVideo");
      if (v) v.srcObject = null;
      const fb = $("mainJpeg");
      if (fb) fb.style.display = "none";
      syncActiveThumbVideo();
    } else {
      if (allowsWebrtcMain()){
        setupWebRTC(robot, webrtcSwitchNonce);
      } else {
        const fb = $("mainJpeg");
        if (fb) fb.style.display = "block";
        updateTransportBadge();
      }
    }
  }
}

function refreshThumbs(){
  if (document.hidden) return;
  const nowMs = Date.now();
  if (isDriveSessionActive()){
    thumbDriveSuppressedUntilMs = nowMs + THUMB_DRIVE_SUPPRESS_MS;
  }
  if (nowMs < thumbDriveSuppressedUntilMs){
    return;
  }
  const inactiveTiles = [];
  for (const tile of document.querySelectorAll(".thumb")){
    const img = tile.querySelector("img");
    const nameBadge = tile.querySelector(".badge-right");
    const robot = (nameBadge && nameBadge.textContent) ? nameBadge.textContent.trim() : "";
    if (!img || !robot) continue;
    if (robot === activeRobot){
      continue;
    } else {
      inactiveTiles.push({ img, robot });
    }
  }
  syncActiveThumbVideo();
  if (!inactiveTiles.length){
    thumbRoundRobinCursor = 0;
    return;
  }
  const configuredLimit = Math.max(0, Math.floor(Number(thumbRobotsPerTick) || 0));
  const minimalMode = configuredLimit <= 0;
  const healthy = [];
  const unhealthy = [];
  for (const row of inactiveTiles){
    if (minimalMode && !thumbNeedsRefresh(row.img, THUMB_MINIMAL_STALE_MS)) continue;
    if (robotThumbPriority(row.robot) <= 1){
      healthy.push(row);
    } else {
      unhealthy.push(row);
    }
  }
  const pool = healthy.concat(unhealthy);
  const total = pool.length;
  if (!total){
    thumbRoundRobinCursor = 0;
    return;
  }
  const limit = minimalMode ? 1 : configuredLimit;
  const start = ((thumbRoundRobinCursor % total) + total) % total;
  const count = Math.min(limit, total);
  for (let i = 0; i < count; i += 1){
    const idx = (start + i) % total;
    refreshThumbImage(pool[idx].img, pool[idx].robot);
  }
  thumbRoundRobinCursor = (start + count) % total;
}

function startHeartbeat(){
  setInterval(() => {
    if (!activeRobot) return;
    wsSend({ type: "heartbeat", robot: activeRobot });
  }, 1000);
}

async function main(){
  setStatus("Loading...");
  try{
    const cfg = await fetchAuthConfig();
    authConfig = (cfg && cfg.auth) ? cfg.auth : authConfig;
  }catch(err){
    setStatus(`Auth config load failed: ${err.message || "unknown error"}`);
    return;
  }

  const loginReady = await ensureDevLoginIfRequired();
  if (!loginReady){
    setStatus("Login canceled.");
    return;
  }
  hookPageExitSessionShutdown();

  let s = null;
  try{
    s = await fetchStateWithReauth();
  }catch(err){
    setStatus(`State load failed: ${err.message || "unknown error"}`);
    return;
  }
  robots = s.robots || [];
  liveRobots = s.live_robots || liveRobots;
  robotsSig = [...robots].sort().join("|");
  locks = s.locks || {};
  locksSig = lockSignature(locks);
  robotCaps = s.robot_caps || {};
  robotHealth = s.robot_health || {};
  driveTelemetry = s.drive_telemetry || {};
  features = s.features || { webrtc: false };
  applyWebrtcState(s);
  applyStreamState(s);
  applyThumbPolicy(s);
  const bootstrapRobot = pickActiveRobot(s.active_robot, robots, true);

  renderThumbRail();
  renderCapabilityMeta();
  renderDriveControls();
  renderModeControls();
  renderWebrtcDiagnostics();
  renderHealthPanel();
  setActiveRobot(bootstrapRobot, false, "bootstrap");
  hookKeyboardDrive();

  const wsParams = new URLSearchParams();
  wsParams.set("client_id", clientId);
  if (accessToken){
    wsParams.set("access_token", accessToken);
  }
  const wsProto = (window.location.protocol === "https:") ? "wss" : "ws";
  ws = new WebSocket(`${wsProto}://${window.location.host}/ws?${wsParams.toString()}`);
  ws.onopen = () => setStatus("Connected");
  ws.onerror = () => setStatus("Websocket error");
  ws.onclose = () => setStatus("Disconnected");
  ws.onmessage = (evt) => {
    let d = null;
    try { d = JSON.parse(evt.data); } catch(_e){ return; }
    if (d.type === "hello"){
      const newRobots = d.robots || robots;
      liveRobots = d.live_robots || liveRobots;
      const newSig = [...newRobots].sort().join("|");
      robots = newRobots;
      locks = d.locks || locks;
      lockMeta = d.lock_meta || lockMeta;
      locksSig = lockSignature(locks);
      robotCaps = d.robot_caps || robotCaps;
      robotHealth = d.robot_health || robotHealth;
      driveTelemetry = d.drive_telemetry || driveTelemetry;
      features = d.features || features;
      applyWebrtcState(d);
      applyStreamState(d);
      applyThumbPolicy(d);
      let nextActiveRobot = activeRobot;
      if (d.active_robot && (!localActiveRobotPinned || !activeRobot)){
        nextActiveRobot = d.active_robot;
      }
      nextActiveRobot = reconcileActiveRobotChoice(nextActiveRobot, robots, activeRobot);
      if (!nextActiveRobot){
        localActiveRobotPinned = false;
      }
      if (newSig !== robotsSig){
        robotsSig = newSig;
        renderThumbRail();
      }
      renderCapabilityMeta();
      renderDriveControls();
      renderModeControls();
      renderWebrtcDiagnostics();
      renderHealthPanel();
      if (nextActiveRobot !== activeRobot){
        setActiveRobot(nextActiveRobot, false, "server");
      }
      return;
    }
    if (d.type === "active_robot"){
      if (d.robot && d.robot !== activeRobot){
        setActiveRobot(d.robot, false, "server");
      }
      return;
    }
    if (d.type === "lock_update"){
      const nextLocks = d.locks || {};
      lockMeta = d.lock_meta || lockMeta;
      const nextSig = lockSignature(nextLocks);
      if (nextSig !== locksSig){
        locks = nextLocks;
        locksSig = nextSig;
        renderThumbRail();
        renderHealthPanel();
      }
      return;
    }
    if (d.type === "error"){
      setStatus(d.message || "Error");
      return;
    }
  };

  const thumbHz = Math.max(0.1, _toNumber(s.thumb_hz, 0.5));
  setInterval(refreshThumbs, Math.floor(1000 / thumbHz));
  setTimeout(refreshThumbs, 0);
  setInterval(async () => {
    if (stateRefreshInFlight) return;
    stateRefreshInFlight = true;
    try{
      const st = await fetchState();
      const newRobots = st.robots || robots;
      liveRobots = st.live_robots || liveRobots;
      const newSig = [...newRobots].sort().join("|");
      robots = newRobots;
      robotCaps = st.robot_caps || robotCaps;
      robotHealth = st.robot_health || robotHealth;
      driveTelemetry = st.drive_telemetry || driveTelemetry;
      features = st.features || features;
      applyWebrtcState(st);
      applyStreamState(st);
      applyThumbPolicy(st);
      let nextActiveRobot = activeRobot;
      if (!localActiveRobotPinned && st.active_robot){
        nextActiveRobot = st.active_robot;
      }
      nextActiveRobot = reconcileActiveRobotChoice(nextActiveRobot, robots, activeRobot);
      if (!nextActiveRobot){
        localActiveRobotPinned = false;
      }
      if (newSig !== robotsSig){
        robotsSig = newSig;
        renderThumbRail();
      }
      renderCapabilityMeta();
      renderWebrtcDiagnostics();
      renderHealthPanel();
      if (nextActiveRobot !== activeRobot){
        setActiveRobot(nextActiveRobot, false, "server");
      }
    }catch(err){
      const status = Number(err && err.status);
      if (status === 401){
        clearStoredAccessToken();
        setStatus("Session expired. Reloading for login...");
        setTimeout(() => { window.location.reload(); }, 300);
        return;
      }
      if (err && err.message){
        setStatus(`State refresh failed: ${err.message}`);
      }
    } finally {
      stateRefreshInFlight = false;
    }
  }, 1000);
  startHeartbeat();
  startWebrtcRetryLoop();
  setupMainFallbackLoop();
  startMainVideoFrameWatch();
}

main();
"""

_STYLE_ASSET_VERSION = hashlib.sha1(_STYLE_CSS.encode("utf-8")).hexdigest()[:10]
_APP_ASSET_VERSION = hashlib.sha1(_APP_JS.encode("utf-8")).hexdigest()[:10]


def _spin_ros(node: Node):
    executor = rclpy.executors.MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        executor.shutdown()


def _print_dependency_preflight() -> bool:
    """
    Print a concise startup dependency check so missing packages are obvious
    without exposing a long traceback.
    """
    print("[swarm_fpv_ui] Dependency preflight")
    if not HAS_REQUIRED_WEB_DEPS:
        try:
            workspace = str(detect_workspace_root())
        except MissingConfigError:
            workspace = "<workspace_root>"
        print("[swarm_fpv_ui] Missing required Python packages:")
        for name, apt_pkg, reason in _MISSING_REQUIRED_DEPS:
            print(f"  - {name} (install: {apt_pkg})")
            print(f"    reason: {reason}")
        print("[swarm_fpv_ui] Install missing dependencies, then rebuild and source:")
        print("  sudo apt install -y python3-aiohttp python3-numpy python3-pil")
        print(f"  cd {workspace} && colcon build --packages-select swarm_control_core")
        print(f"  source {workspace}/install/setup.bash")
        return False

    print("[swarm_fpv_ui] Required dependencies: OK")
    if not HAS_WEBRTC:
        print("[swarm_fpv_ui] WebRTC dependencies missing. Main-pane video will remain unavailable until installed.")
        for name, apt_pkg, reason in _MISSING_WEBRTC_DEPS:
            print(f"  - {name} (install: {apt_pkg})")
            print(f"    reason: {reason}")
        print("[swarm_fpv_ui] Install to enable local WebRTC:")
        print("  sudo apt install -y python3-aiortc python3-av")
    return True


def _install_aiohttp_disconnect_exception_filter() -> None:
    """
    Suppress noisy asyncio task exceptions caused by a known aiohttp transport
    race on abrupt client disconnects.

    This filters:
    - AssertionError from aiohttp RequestHandler.start when transport is gone.
    - Benign aioice STUN retry InvalidStateError race noise.
    All other exceptions still follow the default loop exception handler path.
    """
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    warned_once = {"value": False}

    def _handler(loop_obj: asyncio.AbstractEventLoop, context: Dict[str, Any]) -> None:
        exc = context.get("exception")
        fut = context.get("future")
        coro_qualname = ""
        coro_module = ""
        try:
            if fut is not None and hasattr(fut, "get_coro"):
                coro = fut.get_coro()  # type: ignore[assignment]
                coro_qualname = str(getattr(coro, "__qualname__", "") or "")
                coro_module = str(getattr(coro, "__module__", "") or "")
        except Exception:
            coro_qualname = ""
            coro_module = ""

        is_known_aiohttp_disconnect_race = (
            isinstance(exc, AssertionError)
            and coro_qualname == "RequestHandler.start"
            and "aiohttp.web_protocol" in coro_module
        )

        handle_txt = str(context.get("handle") or "")
        msg_txt = str(context.get("message") or "")
        retry_ctx = ("transaction.__retry" in handle_txt.lower() or "transaction.__retry" in msg_txt.lower())
        exc_txt = str(exc or "")
        is_known_aioice_stun_retry_race = retry_ctx and (
            (
                isinstance(exc, asyncio.InvalidStateError)
                and "invalid state" in exc_txt.lower()
            )
            or (
                isinstance(exc, AttributeError)
                and "'nonetype' object has no attribute 'sendto'" in exc_txt.lower()
            )
            or (
                isinstance(exc, AttributeError)
                and "'nonetype' object has no attribute 'call_exception_handler'" in exc_txt.lower()
            )
        )
        is_known_aiortc_connect_close_race = (
            msg_txt.strip().lower() == "task exception was never retrieved"
            and isinstance(exc, asyncio.InvalidStateError)
            and "rtcicetransport is closed" in exc_txt.lower()
            and coro_qualname == "RTCPeerConnection.__connect"
            and "aiortc.rtcpeerconnection" in coro_module
        )

        if is_known_aiohttp_disconnect_race:
            if not warned_once["value"]:
                warned_once["value"] = True
                print(
                    "[swarm_fpv_ui] Noted and suppressing known aiohttp disconnect assertion "
                    "(abrupt client disconnect before request parse)."
                )
            return

        if is_known_aioice_stun_retry_race:
            if not warned_once.get("aioice"):
                warned_once["aioice"] = True
                print(
                    "[swarm_fpv_ui] Noted and suppressing known aioice STUN retry close race "
                    "(Transaction.__retry transport/loop teardown)."
                )
            return

        if is_known_aiortc_connect_close_race:
            if not warned_once.get("aiortc_connect"):
                warned_once["aiortc_connect"] = True
                print(
                    "[swarm_fpv_ui] Noted and suppressing known aiortc connect/close race "
                    "(RTCPeerConnection.__connect after transport teardown)."
                )
            return

        if previous_handler is not None:
            previous_handler(loop_obj, context)
        else:
            loop_obj.default_exception_handler(context)

    loop.set_exception_handler(_handler)


async def _run_server():
    _install_aiohttp_disconnect_exception_filter()
    ensure_ros_domain_id()
    rclpy.init(args=None)
    hub = RosFleetHub()
    bind_host_default = str(os.environ.get("SWARM_CORE_BIND_HOST", "127.0.0.1")).strip() or "127.0.0.1"
    bind_port_default_raw = str(os.environ.get("SWARM_CORE_BIND_PORT", "8080")).strip()
    try:
        bind_port_default = int(bind_port_default_raw)
    except Exception:
        bind_port_default = 8080
    hub.declare_parameter("bind_host", bind_host_default)
    hub.declare_parameter("bind_port", bind_port_default)
    hub.declare_parameter("auth_mode", os.environ.get("SWARM_CORE_AUTH_MODE", AUTH_MODE_OFF))
    hub.declare_parameter("auth_issuer", os.environ.get("SWARM_CORE_AUTH_ISSUER", ""))
    hub.declare_parameter("auth_audience", os.environ.get("SWARM_CORE_AUTH_AUDIENCE", ""))
    hub.declare_parameter("auth_jwks_url", os.environ.get("SWARM_CORE_AUTH_JWKS_URL", ""))
    hub.declare_parameter(
        "allow_anonymous_readonly",
        str(os.environ.get("SWARM_CORE_ALLOW_ANON_READONLY", "true")).strip().lower() in ("1", "true", "yes", "on"),
    )
    hub.declare_parameter("site_id", os.environ.get("SWARM_EDGE_SITE_ID", ""))
    hub.declare_parameter(
        "dev_login_enabled",
        str(os.environ.get("SWARM_CORE_DEV_LOGIN_ENABLED", "true")).strip().lower() in ("1", "true", "yes", "on"),
    )
    hub.declare_parameter("dev_users_json", os.environ.get("SWARM_CORE_DEV_USERS_JSON", ""))
    bind_host = str(hub.get_parameter("bind_host").value).strip() or "127.0.0.1"
    bind_port = int(hub.get_parameter("bind_port").value)
    auth_mode = str(hub.get_parameter("auth_mode").value).strip().lower() or AUTH_MODE_OFF
    auth_issuer = str(hub.get_parameter("auth_issuer").value).strip()
    auth_audience = str(hub.get_parameter("auth_audience").value).strip()
    auth_jwks_url = str(hub.get_parameter("auth_jwks_url").value).strip()
    allow_anon_raw = hub.get_parameter("allow_anonymous_readonly").value
    allow_anon = str(allow_anon_raw).strip().lower() in ("1", "true", "yes", "on")
    site_id = str(hub.get_parameter("site_id").value).strip()
    dev_login_raw = hub.get_parameter("dev_login_enabled").value
    dev_login_enabled = str(dev_login_raw).strip().lower() in ("1", "true", "yes", "on")
    dev_users_json = str(hub.get_parameter("dev_users_json").value or "")
    if bind_port < 1 or bind_port > 65535:
        raise ValueError(f"Invalid bind_port '{bind_port}'. Expected 1..65535.")

    # Community edition hard guardrails:
    # - local/LAN operation only
    # - dev auth only (no external auth providers)
    # - no custom TURN/STUN relay configuration
    allow_lan_bind = _community_allow_lan_bind()
    if _is_loopback_host(bind_host):
        pass
    elif allow_lan_bind and _is_private_or_wildcard_host(bind_host):
        pass
    else:
        hub.get_logger().warn(
            f"[community] bind_host '{bind_host}' is not allowed. "
            "Forcing loopback 127.0.0.1 (set SWARM_CORE_ALLOW_LAN_BIND=1 for private LAN bind)."
        )
        bind_host = "127.0.0.1"

    if auth_mode not in (AUTH_MODE_OFF, AUTH_MODE_DEV):
        hub.get_logger().warn(
            f"[community] auth_mode '{auth_mode}' is not supported in community edition. "
            "Forcing auth_mode=off."
        )
        auth_mode = AUTH_MODE_OFF
    auth_issuer = ""
    auth_audience = ""
    auth_jwks_url = ""
    if auth_mode == AUTH_MODE_OFF:
        allow_anon = False
    site_id = "community_local"
    if auth_mode != AUTH_MODE_DEV:
        dev_login_enabled = False
        dev_users_json = ""
    webrtc_ice_servers_json = "[]"
    webrtc_ice_transport_policy = "all"

    auth_config = AuthConfig(
        mode=auth_mode,
        issuer=auth_issuer,
        audience=auth_audience,
        jwks_url=auth_jwks_url,
        allow_readonly_anonymous=allow_anon,
    )
    auth_config.validate()

    t = threading.Thread(target=_spin_ros, args=(hub,), daemon=True)
    t.start()

    server = BrowserServer(
        hub,
        auth_config=auth_config,
        site_id=site_id,
        dev_login_enabled=dev_login_enabled,
        dev_users_json=dev_users_json,
        webrtc_ice_servers_json=webrtc_ice_servers_json,
        webrtc_ice_transport_policy=webrtc_ice_transport_policy,
    )
    app = web.Application()
    app.add_routes(
        [
            web.get("/", server.handle_index),
            web.get("/style.css", server.handle_style),
            web.get("/app.js", server.handle_js),
            web.get("/api/auth/config", server.handle_auth_config),
            web.post("/api/dev/login", server.handle_dev_login),
            web.post("/api/dev/logout", server.handle_dev_logout),
            web.get("/api/state", server.handle_state),
            web.get("/api/fleet/state", server.handle_fleet_state),
            web.get("/api/jpeg", server.handle_jpeg),
            web.post("/webrtc/offer", server.handle_offer),
            web.get("/ws", server.handle_ws),
        ]
    )

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=bind_host, port=bind_port)
    await site.start()
    hub.get_logger().info(f"Swarm FPV UI bind: {bind_host}:{bind_port}")
    hub.get_logger().info(
        f"Swarm FPV UI auth_mode={auth_config.mode} allow_anonymous_readonly={auth_config.allow_readonly_anonymous}"
    )
    if auth_config.mode == AUTH_MODE_OFF and bind_host not in ("127.0.0.1", "localhost"):
        hub.get_logger().warn(
            "FPV UI is running with auth_mode=off on a non-loopback bind host. "
            "Use auth_mode=dev before exposing this endpoint outside a trusted lab."
        )
    hub.get_logger().info(f"Swarm FPV UI dev_login_enabled={dev_login_enabled}")
    if hub.webrtc_main_only:
        hub.get_logger().info("Swarm FPV UI stream_mode=webrtc_only_main")
    else:
        hub.get_logger().info("Swarm FPV UI stream_mode=webrtc_plus_jpeg_fallback")
    if site_id:
        hub.get_logger().info(f"Swarm FPV UI site_id={site_id}")
    urls = _detect_ipv4_addresses()
    if bind_host in ("0.0.0.0", "::", ""):
        hub.get_logger().info("Swarm FPV UI URLs:")
        for ip in urls:
            hub.get_logger().info(f"  http://{ip}:{bind_port}")
    else:
        hub.get_logger().info(f"Swarm FPV UI URL: http://{bind_host}:{bind_port}")

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        if HAS_WEBRTC:
            for pc in list(server.pcs):
                try:
                    await server._close_pc(pc)
                except Exception:
                    pass
        hub.destroy_node()
        rclpy.shutdown()


def main():
    if not _print_dependency_preflight():
        return 1
    asyncio.run(_run_server())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
