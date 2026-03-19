#!/usr/bin/env python3
"""
camera_adapter.py

Reusable camera normalization layer for swarm_control_core.

Why this module exists:
- Different cameras (CSI + USB) expose different pixel formats/backends.
- OpenCV may choose a backend (often GStreamer) that fails on one robot and
  works on another.
- We need one stable ROS contract for the rest of the system:
    /<robot>/camera/image_raw  (sensor_msgs/msg/Image, bgr8)

Design:
- Try multiple camera-open strategies (V4L2 path/index, generic fallback).
- Publish image frames with a consistent encoding (bgr8).
- Auto-reopen camera if frame capture stalls.
- Publish rich diagnostics to help field debugging:
    /<robot>/camera/diagnostics  (std_msgs/msg/String JSON)

This is intentionally modular and can be reused by other nodes/systems that
need "camera in, normalized ROS image out" behavior.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import rclpy
from cv_bridge import CvBridge
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import String
from .path_defaults import default_robot_name
from .runtime_env import ensure_ros_domain_id


DeviceType = Union[int, str]
_OPENCV_GSTREAMER_AVAILABLE: Optional[bool] = None


@dataclass
class OpenStrategy:
    """
    One concrete camera-open strategy.

    Notes:
    - `device` can be an integer index or /dev/video* path.
    - `backend` allows pinning CAP_V4L2 where available.
    """

    name: str
    device: DeviceType
    backend: int
    fourcc: str = ""
    supports_fourcc_rotation: bool = True
    apply_capture_tuning: bool = True


def _now_s() -> float:
    return time.time()


def _as_int_if_numeric(value: Any) -> Any:
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return int(s)
    return value


def _device_candidates(device_raw: Any) -> List[DeviceType]:
    """
    Build a robust list of device candidates from one input parameter.
    """
    device = _as_int_if_numeric(device_raw)
    out: List[DeviceType] = [device]

    # If /dev/videoN is provided, add N index fallback.
    if isinstance(device, str):
        m = re.match(r"^/dev/video(\d+)$", device.strip())
        if m:
            out.append(int(m.group(1)))

    # If index provided, add /dev/videoN path fallback.
    if isinstance(device, int):
        out.append(f"/dev/video{device}")

    # Deduplicate while preserving order.
    dedup: List[DeviceType] = []
    seen = set()
    for d in out:
        key = f"{type(d).__name__}:{d}"
        if key in seen:
            continue
        seen.add(key)
        dedup.append(d)
    return dedup


def _build_open_strategies(device_raw: Any, include_any_backend: bool = True) -> List[OpenStrategy]:
    """
    Generate open strategies in priority order.
    """
    strategies: List[OpenStrategy] = []
    for d in _device_candidates(device_raw):
        # Prefer V4L2 on Linux for USB cameras.
        strategies.append(OpenStrategy(name=f"v4l2:{d}", device=d, backend=cv2.CAP_V4L2))
        # Generic backend fallback.
        if include_any_backend:
            strategies.append(OpenStrategy(name=f"any:{d}", device=d, backend=cv2.CAP_ANY))
    return strategies


def _build_csi_gstreamer_strategies(width: int, height: int, frame_rate: float) -> List[OpenStrategy]:
    """
    Build explicit libcamera->OpenCV strategies for CSI cameras.

    These pipelines bypass direct V4L2 decoding on systems where /dev/video0
    returns pathological green/black frames.
    """
    fps = max(1, int(round(float(frame_rate))))
    w = max(16, int(width))
    h = max(16, int(height))
    return [
        OpenStrategy(
            name="gst:libcamerasrc:bgr",
            device=(
                "libcamerasrc ! "
                f"video/x-raw,width={w},height={h},framerate={fps}/1 ! "
                "videoconvert ! video/x-raw,format=BGR ! "
                "appsink drop=true sync=false max-buffers=1"
            ),
            backend=cv2.CAP_GSTREAMER,
            fourcc="BGR3",
            supports_fourcc_rotation=False,
            apply_capture_tuning=False,
        ),
        OpenStrategy(
            name="gst:libcamerasrc:rgb",
            device=(
                "libcamerasrc ! "
                f"video/x-raw,width={w},height={h},framerate={fps}/1 ! "
                "videoconvert ! video/x-raw,format=RGB ! "
                "appsink drop=true sync=false max-buffers=1"
            ),
            backend=cv2.CAP_GSTREAMER,
            fourcc="RGB3",
            supports_fourcc_rotation=False,
            apply_capture_tuning=False,
        ),
    ]


def _opencv_has_gstreamer() -> bool:
    """
    Best-effort check whether this OpenCV build includes GStreamer.
    """
    global _OPENCV_GSTREAMER_AVAILABLE
    if _OPENCV_GSTREAMER_AVAILABLE is not None:
        return bool(_OPENCV_GSTREAMER_AVAILABLE)
    try:
        info = cv2.getBuildInformation()
    except Exception:
        _OPENCV_GSTREAMER_AVAILABLE = False
        return False
    m = re.search(
        r"^\s*GStreamer:\s*(YES|NO)\b.*$",
        info,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    if not m:
        _OPENCV_GSTREAMER_AVAILABLE = False
        return False
    _OPENCV_GSTREAMER_AVAILABLE = m.group(1).strip().upper() == "YES"
    return bool(_OPENCV_GSTREAMER_AVAILABLE)


def _normalize_camera_source(raw_value: Any) -> str:
    s = str(raw_value or "").strip().lower()
    if s == "csi":
        return "csi"
    return "usb"


def _sanitize_fourcc(camera_source: str, raw_fourcc: Any) -> str:
    """
    Normalize requested FourCC to safer capture defaults.

    For CSI paths we accept common raw/RGB variants and rotate formats when
    one mode stalls on a given platform.
    """
    fourcc = str(raw_fourcc or "").strip().upper()
    if len(fourcc) != 4:
        fourcc = ""
    if camera_source == "csi":
        if fourcc in ("BGR3", "RGB3", "YUYV", "UYVY", "YVYU", "VYUY", "MJPG"):
            return fourcc
        return "YUYV"
    if not fourcc:
        return "MJPG"
    return fourcc


class CameraAdapterNode(Node):
    """
    Camera normalization node with self-healing reopen logic.
    """

    def __init__(self):
        super().__init__("camera_adapter_node")

        # Core identity / transport contract.
        self.declare_parameter("robot_name", "")
        self.declare_parameter("device", "/dev/video0")
        self.declare_parameter("camera_source", "usb")
        # Dynamic typing here prevents launch-time type crashes when some paths
        # pass `15` and others pass `15.0`.
        self.declare_parameter(
            "frame_rate",
            15.0,
            ParameterDescriptor(dynamic_typing=True),
        )
        self.declare_parameter("width", 640)
        self.declare_parameter("height", 480)
        self.declare_parameter("fourcc", "MJPG")
        self.declare_parameter("force_v4l2", True)
        self.declare_parameter("publish_compressed", True)
        self.declare_parameter("jpeg_quality", 70)
        # Number of extra non-decoding grabs before retrieve to shed stale
        # backend-buffered frames when drivers ignore CAP_PROP_BUFFERSIZE.
        self.declare_parameter("capture_grab_drain", 2)

        # Recovery / diagnostics behavior.
        self.declare_parameter("reopen_stale_after_s", 2.0)
        self.declare_parameter("reopen_no_frame_after_s", 4.0)
        self.declare_parameter("reopen_after_fail_reads", 15)
        self.declare_parameter("diagnostics_hz", 1.0)

        configured_robot_name = str(self.get_parameter("robot_name").value).strip()
        self.robot_name = configured_robot_name or default_robot_name()
        self.device_raw = self.get_parameter("device").value
        self.camera_source = _normalize_camera_source(self.get_parameter("camera_source").value)
        self.frame_rate = max(1.0, float(self.get_parameter("frame_rate").value))
        self.width = int(self.get_parameter("width").value)
        self.height = int(self.get_parameter("height").value)
        requested_fourcc = str(self.get_parameter("fourcc").value or "").upper()
        self.fourcc = _sanitize_fourcc(self.camera_source, requested_fourcc)
        self.force_v4l2 = bool(self.get_parameter("force_v4l2").value)
        self.publish_compressed = bool(self.get_parameter("publish_compressed").value)
        self.jpeg_quality = max(30, min(95, int(self.get_parameter("jpeg_quality").value)))
        self.capture_grab_drain = max(0, int(self.get_parameter("capture_grab_drain").value))
        self.reopen_stale_after_s = max(0.2, float(self.get_parameter("reopen_stale_after_s").value))
        self.reopen_no_frame_after_s = max(0.5, float(self.get_parameter("reopen_no_frame_after_s").value))
        self.reopen_after_fail_reads = max(1, int(self.get_parameter("reopen_after_fail_reads").value))
        self.diagnostics_hz = max(0.2, float(self.get_parameter("diagnostics_hz").value))
        self.opencv_has_gstreamer = _opencv_has_gstreamer()
        if self.camera_source == "csi":
            # CSI frame intervals can jitter; aggressive stale thresholds cause
            # unnecessary reopen loops on otherwise usable streams.
            self.reopen_stale_after_s = max(self.reopen_stale_after_s, 6.0)
            self.reopen_no_frame_after_s = max(self.reopen_no_frame_after_s, 8.0)
        else:
            # USB frame cadence can jitter under bursty I/O; reduce reopen
            # thrash so brief pauses do not flap strategies every 2 seconds.
            self.reopen_stale_after_s = max(self.reopen_stale_after_s, 4.0)
            self.reopen_no_frame_after_s = max(self.reopen_no_frame_after_s, 6.0)
        if requested_fourcc and self.fourcc != requested_fourcc:
            self.get_logger().warn(
                f"[{self.robot_name}.camera] unsupported fourcc '{requested_fourcc}' for source "
                f"{self.camera_source}; using '{self.fourcc}'"
            )

        self.image_topic = f"/{self.robot_name}/camera/image_raw"
        self.compressed_topic = f"/{self.robot_name}/camera/image_raw/compressed"
        self.diag_topic = f"/{self.robot_name}/camera/diagnostics"

        # Use sensor-data QoS for camera transport so lossy links still deliver
        # fresh frames instead of stalling on reliable retransmit behavior.
        self.image_pub = self.create_publisher(Image, self.image_topic, qos_profile_sensor_data)
        self.compressed_pub = self.create_publisher(
            CompressedImage,
            self.compressed_topic,
            qos_profile_sensor_data,
        )
        self.diag_pub = self.create_publisher(String, self.diag_topic, 10)
        self.bridge = CvBridge()

        self.cap: Optional[cv2.VideoCapture] = None
        self.strategy_idx = 0
        # Keep generic backend fallback available for CSI as well. Some
        # platforms only produce valid CSI frames through non-V4L2 paths.
        include_any_backend = True
        self.strategies = _build_open_strategies(self.device_raw, include_any_backend=include_any_backend)
        if self.camera_source == "csi":
            # If caller provided an explicit /dev/video* path, keep path-based
            # strategies only to avoid index remapping ambiguity.
            has_explicit_path = any(
                isinstance(s.device, str) and str(s.device).startswith("/dev/video")
                for s in self.strategies
            )
            if has_explicit_path:
                self.strategies = [s for s in self.strategies if isinstance(s.device, str)]
        if self.force_v4l2 and self.camera_source != "csi":
            # Keep only explicit V4L2 strategies when forced.
            self.strategies = [s for s in self.strategies if s.backend == cv2.CAP_V4L2] or self.strategies
        if self.camera_source == "csi":
            # For CSI, order strategies by preference:
            # 1) explicit libcamera gstreamer pipeline (when available)
            # 2) direct V4L2 by path
            # 3) generic CAP_ANY fallback
            v4l2_strategies = [s for s in self.strategies if s.backend == cv2.CAP_V4L2]
            any_strategies = [s for s in self.strategies if s.backend == cv2.CAP_ANY]
            gst_strategies: List[OpenStrategy] = []
            if self.opencv_has_gstreamer:
                gst_strategies = _build_csi_gstreamer_strategies(self.width, self.height, self.frame_rate)
            else:
                self.get_logger().warn(
                    f"[{self.robot_name}.camera] OpenCV lacks GStreamer; CSI fallback limited to V4L2/CAP_ANY"
                )
            self.strategies = gst_strategies + v4l2_strategies + any_strategies

            # Some CSI stacks open but stall after one frame for specific
            # formats; rotate FourCC candidates per strategy automatically.
            csi_fourcc_candidates: List[str] = []
            # Start with the requested/profile format first, then try common
            # alternatives for platform-specific CSI quirks.
            for f in (self.fourcc, "YUYV", "UYVY", "YVYU", "VYUY", "MJPG", "BGR3", "RGB3"):
                token = str(f or "").strip().upper()
                if len(token) == 4 and token not in csi_fourcc_candidates:
                    csi_fourcc_candidates.append(token)
            expanded: List[OpenStrategy] = []
            for s in self.strategies:
                if not s.supports_fourcc_rotation:
                    expanded.append(s)
                    continue
                for token in csi_fourcc_candidates:
                    expanded.append(
                        OpenStrategy(
                            name=f"{s.name}:{token}",
                            device=s.device,
                            backend=s.backend,
                            fourcc=token,
                            supports_fourcc_rotation=s.supports_fourcc_rotation,
                            apply_capture_tuning=s.apply_capture_tuning,
                        )
                    )
            self.strategies = expanded or self.strategies

        self.frame_count = 0
        self.fail_reads = 0
        self.last_frame_s: Optional[float] = None
        self.last_error = ""
        self.active_strategy = ""
        self.active_fourcc = self.fourcc
        self.last_frame_layout = ""
        # Some CSI drivers expose one FourCC label but hand back a different
        # packed byte order in practice. We auto-detect the best YUV422 decode
        # mode during the first few frames after each open and then lock it.
        self.yuv_decode_mode = ""
        self.yuv_decode_scores: Dict[str, float] = {}
        self.yuv_decode_samples = 0
        self.yuv_decode_lock_after_samples = 6
        self.bad_color_streak = 0
        self.bad_color_rotate_after = 12
        self.last_bgr_mean: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.last_gray_std = 0.0
        self.last_open_s: Optional[float] = None
        self.frames_since_open = 0

        self._open_next_strategy(initial=True)
        self.capture_timer = self.create_timer(1.0 / self.frame_rate, self._capture_once)
        self.diag_timer = self.create_timer(1.0 / self.diagnostics_hz, self._publish_diag)

        self.get_logger().info(
            f"[{self.robot_name}.camera] adapter publishing on {self.image_topic} "
            f"(source={self.camera_source}, device={self.device_raw}, size={self.width}x{self.height}, "
            f"fps={self.frame_rate:.1f}, fourcc={self.fourcc})"
        )
        if self.publish_compressed:
            self.get_logger().info(
                f"[{self.robot_name}.camera] compressed stream on {self.compressed_topic} "
                f"(jpeg_quality={self.jpeg_quality})"
            )

    def _read_latest_frame(self) -> Tuple[bool, Any]:
        """
        Read the newest available frame while minimizing stale queue latency.
        """
        if self.cap is None:
            return False, None

        if self.capture_grab_drain > 0:
            drained = 0
            for _ in range(self.capture_grab_drain):
                try:
                    if not self.cap.grab():
                        break
                    drained += 1
                except Exception:
                    break
            if drained > 0:
                try:
                    ok, frame = self.cap.retrieve()
                    if ok and frame is not None:
                        return True, frame
                except Exception:
                    pass

        return self.cap.read()

    def _release_cap(self):
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = None

    def _configure_cap(self, cap: cv2.VideoCapture, fourcc_override: str = ""):
        """
        Apply common capture preferences.
        """
        requested_fourcc = str(fourcc_override or self.fourcc or "").strip().upper()

        # Keep capture latency bounded when drivers honor buffer sizing.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.frame_rate)
        # For packed YUV422 formats we prefer raw bytes and do conversion in
        # this node because backend-side conversion can produce green-tinted
        # frames on some CSI/V4L2 stacks.
        yuv422_fourcc = ("YUYV", "YUY2", "UYVY", "Y422", "UYNV", "YVYU", "VYUY")
        convert_rgb = 0 if requested_fourcc in yuv422_fourcc else 1
        cap.set(cv2.CAP_PROP_CONVERT_RGB, convert_rgb)
        if len(requested_fourcc) == 4:
            try:
                code = cv2.VideoWriter_fourcc(*requested_fourcc)
                cap.set(cv2.CAP_PROP_FOURCC, code)
            except Exception:
                pass

    def _warmup_reads_ok(self, cap: cv2.VideoCapture, minimum_good_reads: int = 1, attempts: int = 3) -> bool:
        """
        Prime capture and reject clearly unstable open attempts.
        """
        good_reads = 0
        for _ in range(max(1, int(attempts))):
            ok, frame = cap.read()
            if ok and frame is not None:
                good_reads += 1
            time.sleep(0.02)
        return good_reads >= max(1, int(minimum_good_reads))

    def _yuv_decode_priority(self, fourcc: str) -> List[str]:
        token = str(fourcc or "").strip().upper()
        if token in ("UYVY", "Y422", "UYNV"):
            return ["uyvy", "yuy2", "yvyu", "vyuy"]
        if token == "YVYU":
            return ["yvyu", "yuy2", "uyvy", "vyuy"]
        if token == "VYUY":
            return ["vyuy", "yuy2", "uyvy", "yvyu"]
        # Default to YUYV/YUY2 family.
        return ["yuy2", "uyvy", "yvyu", "vyuy"]

    def _score_bgr_candidate(self, frame_bgr: Any) -> float:
        """
        Heuristic quality score for choosing among YUV decode variants.

        We prefer candidates with:
        - visible structure (gray/channel variance)
        - reasonable color balance (avoid extreme single-channel dominance)
        """
        try:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            gray_std = float(cv2.meanStdDev(gray)[1][0][0])

            means, stds = cv2.meanStdDev(frame_bgr)
            b_mean = float(means[0][0])
            g_mean = float(means[1][0])
            r_mean = float(means[2][0])
            b_std = float(stds[0][0])
            g_std = float(stds[1][0])
            r_std = float(stds[2][0])

            hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
            sat_std = float(cv2.meanStdDev(hsv[:, :, 1])[1][0][0])

            means_sum = b_mean + g_mean + r_mean + 1e-6
            dominance = max(b_mean, g_mean, r_mean) / means_sum
            balance = min(b_mean, g_mean, r_mean) / max(1.0, max(b_mean, g_mean, r_mean))

            score = (
                gray_std
                + 0.20 * (b_std + g_std + r_std)
                + 0.08 * sat_std
                + 8.0 * balance
            )
            if dominance > 0.62:
                score -= (dominance - 0.62) * 120.0
            return float(score)
        except Exception:
            return float("-inf")

    def _build_yuv422_candidates(self, packed: Any) -> Dict[str, Any]:
        """
        Build BGR conversion candidates for common packed YUV422 byte orders.
        """
        out: Dict[str, Any] = {}
        try:
            out["yuy2"] = cv2.cvtColor(packed, cv2.COLOR_YUV2BGR_YUY2)
        except Exception:
            pass
        try:
            out["uyvy"] = cv2.cvtColor(packed, cv2.COLOR_YUV2BGR_UYVY)
        except Exception:
            pass

        h, w = int(packed.shape[0]), int(packed.shape[1])
        if w % 2 != 0:
            return out

        try:
            groups = packed.reshape((h, w // 2, 4))
        except Exception:
            return out

        # YVYU: Y0 V Y1 U -> Y0 U Y1 V
        try:
            repacked = groups.copy()
            repacked[:, :, 1] = groups[:, :, 3]
            repacked[:, :, 3] = groups[:, :, 1]
            out["yvyu"] = cv2.cvtColor(repacked.reshape((h, w, 2)), cv2.COLOR_YUV2BGR_YUY2)
        except Exception:
            pass

        # VYUY: V Y0 U Y1 -> Y0 U Y1 V
        try:
            repacked = groups.copy()
            repacked[:, :, 0] = groups[:, :, 1]
            repacked[:, :, 1] = groups[:, :, 2]
            repacked[:, :, 2] = groups[:, :, 3]
            repacked[:, :, 3] = groups[:, :, 0]
            out["vyuy"] = cv2.cvtColor(repacked.reshape((h, w, 2)), cv2.COLOR_YUV2BGR_YUY2)
        except Exception:
            pass

        return out

    def _frame_color_metrics(self, frame_bgr: Any) -> Tuple[Tuple[float, float, float], float]:
        """
        Return (mean_bgr, gray_std) as lightweight health metrics.
        """
        try:
            means, _stds = cv2.meanStdDev(frame_bgr)
            b = float(means[0][0])
            g = float(means[1][0])
            r = float(means[2][0])
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            gray_std = float(cv2.meanStdDev(gray)[1][0][0])
            return (b, g, r), gray_std
        except Exception:
            return (0.0, 0.0, 0.0), 0.0

    def _looks_like_invalid_green_frame(self, mean_bgr: Tuple[float, float, float], gray_std: float) -> bool:
        """
        Detect the pathological all-green frame failure seen on some CSI stacks.

        This intentionally requires both:
        - heavy green dominance and low red/blue
        - very low spatial variance (nearly flat frame)
        """
        b, g, r = mean_bgr
        total = b + g + r + 1e-6
        g_frac = g / total
        rb_max = max(r, b)
        return (
            g > 120.0
            and rb_max < 40.0
            and g_frac > 0.78
            and gray_std < 4.5
        )

    def _yuv422_to_bgr(self, frame: Any) -> Optional[Any]:
        """
        Convert packed YUV422 variants to BGR.

        The adapter receives mixed layouts depending on camera/backend:
        - (H, W, 2) packed YUV422
        - (H, W*2) byte-packed YUV422
        """
        if frame is None:
            return None
        fourcc = str(self.active_fourcc or self.fourcc or "").upper()
        packed: Optional[Any] = None

        if len(frame.shape) == 3 and frame.shape[2] == 2:
            packed = frame
        elif len(frame.shape) == 2 and frame.shape[1] % 2 == 0:
            packed = frame.reshape((frame.shape[0], frame.shape[1] // 2, 2))
        if packed is None:
            return None

        candidates = self._build_yuv422_candidates(packed)
        if not candidates:
            return None

        if self.yuv_decode_mode and self.yuv_decode_mode in candidates:
            return candidates[self.yuv_decode_mode]

        priority = [name for name in self._yuv_decode_priority(fourcc) if name in candidates]
        if not priority:
            priority = list(candidates.keys())
        if not priority:
            return None

        if self.yuv_decode_samples < self.yuv_decode_lock_after_samples:
            for name in priority:
                score = self._score_bgr_candidate(candidates[name])
                self.yuv_decode_scores[name] = self.yuv_decode_scores.get(name, 0.0) + score
            self.yuv_decode_samples += 1
            best = max(priority, key=lambda n: self.yuv_decode_scores.get(n, float("-inf")))
            if self.yuv_decode_samples >= self.yuv_decode_lock_after_samples:
                self.yuv_decode_mode = best
                if best != priority[0]:
                    self.get_logger().warn(
                        f"[{self.robot_name}.camera] yuv decode auto-selected {best} "
                        f"(camera_fourcc={fourcc})"
                    )
            return candidates.get(best)

        return candidates.get(priority[0])

    def _normalize_frame_bgr(self, frame: Any) -> Tuple[Optional[Any], str]:
        """
        Normalize capture output to a BGR image suitable for cv_bridge bgr8.
        """
        if frame is None:
            return None, "none"

        try:
            if len(frame.shape) == 3:
                channels = int(frame.shape[2])
                if channels == 3:
                    return frame, "bgr"
                if channels == 4:
                    return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR), "bgra"
                if channels == 2:
                    bgr = self._yuv422_to_bgr(frame)
                    if bgr is not None:
                        return bgr, "yuv422"
                    return None, f"unsupported_2ch:{tuple(frame.shape)}"
                if channels == 1:
                    mono = frame[:, :, 0]
                    return cv2.cvtColor(mono, cv2.COLOR_GRAY2BGR), "mono"
                return None, f"unsupported_3d:{tuple(frame.shape)}"

            if len(frame.shape) == 2:
                bgr = self._yuv422_to_bgr(frame)
                if bgr is not None:
                    return bgr, "yuv422"
                return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR), "mono"
        except Exception as exc:
            return None, f"convert_error:{exc}"

        return None, f"unsupported_ndim:{len(frame.shape)}"

    def _open_strategy(self, strategy: OpenStrategy) -> bool:
        self._release_cap()
        cap = cv2.VideoCapture(strategy.device, strategy.backend)
        if not cap.isOpened():
            self.last_error = f"open failed ({strategy.name})"
            return False
        if strategy.apply_capture_tuning:
            self._configure_cap(cap, fourcc_override=strategy.fourcc)
        min_warm_reads = 2 if self.camera_source == "csi" else 1
        if not self._warmup_reads_ok(cap, minimum_good_reads=min_warm_reads, attempts=4):
            self.last_error = f"warmup failed ({strategy.name})"
            try:
                cap.release()
            except Exception:
                pass
            return False
        self.cap = cap
        self.active_strategy = strategy.name
        self.active_fourcc = str(strategy.fourcc or self.fourcc or "").upper()
        self.fail_reads = 0
        self.last_error = ""
        self.last_open_s = _now_s()
        self.frames_since_open = 0
        self.last_frame_layout = ""
        self.yuv_decode_mode = ""
        self.yuv_decode_scores = {}
        self.yuv_decode_samples = 0
        self.bad_color_streak = 0
        self.last_bgr_mean = (0.0, 0.0, 0.0)
        self.last_gray_std = 0.0
        self.get_logger().info(f"[{self.robot_name}.camera] opened strategy {strategy.name}")
        return True

    def _open_next_strategy(self, initial: bool = False):
        if not self.strategies:
            self.last_error = "no open strategies"
            self.get_logger().error(f"[{self.robot_name}.camera] no camera open strategies available")
            return
        tries = len(self.strategies)
        for _ in range(tries):
            strategy = self.strategies[self.strategy_idx]
            self.strategy_idx = (self.strategy_idx + 1) % len(self.strategies)
            if self._open_strategy(strategy):
                return
        # Keep severity callsites stable. rclpy logger can raise when severity
        # changes on the same callsite across repeated calls.
        msg = (
            f"[{self.robot_name}.camera] failed to open camera with all strategies; "
            f"retrying (last_error={self.last_error or 'n/a'})"
        )
        if initial:
            self.get_logger().error(msg)
        else:
            self.get_logger().warn(msg)

    def _capture_once(self):
        if self.cap is None:
            self._open_next_strategy(initial=False)
            return

        ok, frame = self._read_latest_frame()
        if not ok or frame is None:
            self.fail_reads += 1
            self.last_error = f"read failed ({self.fail_reads})"
            if self.fail_reads >= self.reopen_after_fail_reads:
                self.get_logger().warn(
                    f"[{self.robot_name}.camera] too many failed reads; rotating strategy (last={self.active_strategy})"
                )
                self._open_next_strategy(initial=False)
            return

        frame_bgr, layout = self._normalize_frame_bgr(frame)
        if frame_bgr is None:
            self.fail_reads += 1
            self.last_error = f"frame normalize failed ({layout})"
            if self.fail_reads >= self.reopen_after_fail_reads:
                self.get_logger().warn(
                    f"[{self.robot_name}.camera] unsupported frame layout; rotating strategy (last={self.active_strategy})"
                )
                self._open_next_strategy(initial=False)
            return

        self.fail_reads = 0
        self.last_frame_layout = layout
        self.last_error = ""
        self.last_bgr_mean, self.last_gray_std = self._frame_color_metrics(frame_bgr)
        if self.camera_source == "csi":
            if self._looks_like_invalid_green_frame(self.last_bgr_mean, self.last_gray_std):
                self.bad_color_streak += 1
            else:
                self.bad_color_streak = 0
            if self.bad_color_streak >= max(3, int(self.bad_color_rotate_after)):
                if len(self.strategies) > 1:
                    b, g, r = self.last_bgr_mean
                    self.last_error = (
                        "suspect_invalid_green_frame "
                        f"(mean_bgr=({b:.1f},{g:.1f},{r:.1f}), gray_std={self.last_gray_std:.2f})"
                    )
                    self.get_logger().warn(
                        f"[{self.robot_name}.camera] invalid green frame streak={self.bad_color_streak}; "
                        f"rotating strategy (last={self.active_strategy})"
                    )
                    self._open_next_strategy(initial=False)
                    return

        compressed_ok = False
        if self.publish_compressed:
            try:
                ok_jpg, jpg_buf = cv2.imencode(
                    ".jpg",
                    frame_bgr,
                    [int(cv2.IMWRITE_JPEG_QUALITY), int(self.jpeg_quality)],
                )
                if ok_jpg:
                    cmsg = CompressedImage()
                    cmsg.format = "jpeg"
                    cmsg.data = jpg_buf.tobytes()
                    self.compressed_pub.publish(cmsg)
                    compressed_ok = True
            except Exception as exc:
                # Compression is optional; raw path can still remain healthy.
                self.last_error = f"jpeg encode failed ({exc})"

        raw_ok = False
        try:
            msg = self.bridge.cv2_to_imgmsg(frame_bgr, encoding="bgr8")
            self.image_pub.publish(msg)
            raw_ok = True
        except Exception as exc:
            # If compressed publishing is healthy, keep stream alive without
            # forcing reopen loops due to raw conversion issues.
            if not compressed_ok:
                self.fail_reads += 1
                self.last_error = f"bridge conversion failed ({exc})"
                if self.fail_reads >= self.reopen_after_fail_reads:
                    self.get_logger().warn(
                        f"[{self.robot_name}.camera] cv_bridge conversion failures; rotating strategy (last={self.active_strategy})"
                    )
                    self._open_next_strategy(initial=False)
                return
            self.last_error = f"raw publish degraded ({exc})"

        if not (raw_ok or compressed_ok):
            self.fail_reads += 1
            self.last_error = f"publish failed ({self.fail_reads})"
            if self.fail_reads >= self.reopen_after_fail_reads:
                self.get_logger().warn(
                    f"[{self.robot_name}.camera] publish failures; rotating strategy (last={self.active_strategy})"
                )
                self._open_next_strategy(initial=False)
            return

        self.frame_count += 1
        self.frames_since_open += 1
        self.last_frame_s = _now_s()

        # If a frame suddenly appears after long gap, log once for clarity.
        if self.frame_count == 1:
            self.get_logger().info(f"[{self.robot_name}.camera] first frame published")

    def _publish_diag(self):
        now = _now_s()
        frame_age = None if self.last_frame_s is None else max(0.0, now - self.last_frame_s)
        open_age = None if self.last_open_s is None else max(0.0, now - self.last_open_s)
        stream_stale = (
            self.frames_since_open > 0
            and frame_age is not None
            and frame_age > self.reopen_stale_after_s
        )
        no_frame_after_open = (
            self.frames_since_open == 0
            and open_age is not None
            and open_age > self.reopen_no_frame_after_s
        )
        stale = bool(stream_stale or no_frame_after_open)
        if stale and self.cap is not None:
            if no_frame_after_open:
                self.get_logger().warn(
                    f"[{self.robot_name}.camera] no frame after open (age={open_age:.2f}s); rotating strategy"
                )
            else:
                self.get_logger().warn(
                    f"[{self.robot_name}.camera] frame stream stale (age={frame_age:.2f}s); rotating strategy"
                )
            self._open_next_strategy(initial=False)

        payload: Dict[str, Any] = {
            "robot": self.robot_name,
            "topic": self.image_topic,
            "compressed_topic": self.compressed_topic if self.publish_compressed else "",
            "camera_source": self.camera_source,
            "opencv_has_gstreamer": bool(self.opencv_has_gstreamer),
            "fourcc": self.fourcc,
            "active_fourcc": self.active_fourcc,
            "active_strategy": self.active_strategy,
            "device_raw": str(self.device_raw),
            "yuv_decode_mode": self.yuv_decode_mode,
            "bad_color_streak": int(self.bad_color_streak),
            "mean_bgr": [float(self.last_bgr_mean[0]), float(self.last_bgr_mean[1]), float(self.last_bgr_mean[2])],
            "gray_std": float(self.last_gray_std),
            "frame_count": int(self.frame_count),
            "frames_since_open": int(self.frames_since_open),
            "open_age_s": open_age,
            "frame_age_s": frame_age,
            "frame_layout": self.last_frame_layout,
            "fail_reads": int(self.fail_reads),
            "stale": bool(stale),
            "last_error": self.last_error,
            "timestamp_s": now,
        }
        msg = String()
        msg.data = json.dumps(payload, separators=(",", ":"))
        self.diag_pub.publish(msg)

    def destroy_node(self):
        self._release_cap()
        super().destroy_node()


def main(args=None):
    ensure_ros_domain_id()
    rclpy.init(args=args)
    node = CameraAdapterNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
