#!/usr/bin/env python3
"""
save_camera_profile.py

Persist camera discovery results into config/camera_profiles.yaml.

Primary use:
- Run this after camera identification exports CAMERA_* values.
- The helper writes one robot profile entry so future bringup can be done
  without repeating camera-specific CLI arguments every session.

New behavior:
- On interactive terminals, the helper now enumerates detected cameras and asks
  which one should be used for FPV + forward-facing SLAM.
- Camera options include both USB webcams and Raspberry Pi CSI modules when
  discoverable from runtime tools.

Implementation note for maintainers:
- This file is intentionally linear and heavily commented because the value
  assembly logic has many fallbacks (CLI, env, runtime probing, YAML defaults).
- The final printed report is designed to mirror those fallbacks using
  "(from <source>)" tags so operators can audit exactly where each field came
  from before/after writing camera_profiles.yaml.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO, Tuple

import yaml
from .path_defaults import MissingConfigError, default_camera_profiles_path, default_robot_name


@dataclass
class CameraCandidate:
    """
    One camera option presented to operators.

    `kind`:
      - "usb": USB/V4L2 camera path
      - "csi": Raspberry Pi CSI camera module
      - "internal": non-CSI integrated camera (for example laptop built-in)

    `device` is the concrete path used by current swarm camera bringup
    (`video_device` -> OpenCV/V4L2). For CSI cameras, this is the mapped
    `/dev/video*` endpoint when available.

    Why we persist this object:
    - The menu needs stable payload data that can be printed, selected, and then
      copied into YAML without extra re-queries.
    - Keeping both the friendly label and the low-level node path in one record
      prevents mismatches between what the operator saw and what gets saved.
    """

    kind: str
    display_name: str
    device: str
    card: str = ""
    sensor: str = ""
    source_note: str = ""


def _run_cmd_text(cmd: list[str], timeout_s: float = 2.0) -> str:
    """
    Execute a command and return stdout on success, otherwise an empty string.

    Why this helper exists:
    - Camera probing should never hard-fail profile persistence.
    - When optional tools (for example v4l2-ctl) are missing, we degrade
      gracefully and fall back to environment values/defaults.
    """
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _run_cmd_text_any_output(cmd: list[str], timeout_s: float = 2.0) -> str:
    """
    Execute a command and return stdout, falling back to stderr on success.

    Some camera tools print discovery output to stderr even with exit code 0.
    We use this helper only for inventory commands where that behavior is
    expected and useful (for example rpicam/libcamera camera listing).
    """
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or proc.stderr or "").strip()


def _probe_v4l2_stream(device: str, timeout_s: float = 5.0) -> Tuple[Optional[bool], str]:
    """
    Probe whether a V4L2 node can stream multiple frames reliably.

    Returns:
      (True, note)   -> probe succeeded and stream looked healthy
      (False, note)  -> probe ran and reported stream failure
      (None, note)   -> probe unavailable (for example missing v4l2-ctl)
    """
    dev = str(device or "").strip()
    if not dev:
        return False, "missing_device"

    cmd = [
        "v4l2-ctl",
        "-d",
        dev,
        "--stream-mmap=3",
        "--stream-count=24",
        "--stream-to=/dev/null",
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except FileNotFoundError:
        return None, "v4l2-ctl_missing"
    except subprocess.TimeoutExpired:
        return False, "probe_timeout"
    except Exception as exc:
        return False, f"probe_error:{exc}"

    merged = f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()
    merged_l = merged.lower()
    if proc.returncode != 0:
        return False, f"probe_exit_{proc.returncode}"
    if any(token in merged_l for token in ("error", "failed", "unable", "dqbuf", "not supported")):
        return False, "probe_stream_error"
    if "24/" in merged or "frames" in merged_l:
        return True, "probe_stream_ok"
    return True, "probe_ok"


def _parse_int(value: Any) -> Optional[int]:
    """
    Parse an integer from permissive numeric input (for example "15.0").
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def _parse_bool(value: Any) -> Optional[bool]:
    """
    Parse bool-like text from CLI/environment/profile sources.
    """
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return None


def _sanitize_profile_fourcc(source: str, raw_fourcc: Any) -> str:
    """
    Normalize persisted fourcc based on source class.

    CSI profiles keep a small allow-list of commonly stable formats.
    """
    fourcc = str(raw_fourcc or "").strip().upper()
    if len(fourcc) != 4:
        fourcc = ""
    if str(source or "").strip().lower() == "csi":
        if fourcc in ("BGR3", "RGB3", "YUYV", "UYVY", "YVYU", "VYUY", "MJPG"):
            return fourcc
        return "YUYV"
    return fourcc or "MJPG"


def _pick_device_from_system() -> str:
    """
    Best-effort camera device detection.

    Detection order:
    1) Stable by-id entries (prefer index0 when available).
    2) /dev/video0 if present.
    3) First /dev/video* as final fallback.
    """
    by_id_dir = Path("/dev/v4l/by-id")
    if by_id_dir.exists():
        # We sort by two keys:
        # - first: entries containing "index0" (preferred stream endpoint)
        # - second: lexical order for deterministic behavior
        entries = sorted(
            (p for p in by_id_dir.iterdir() if p.exists()),
            key=lambda p: ("index0" not in p.name, p.name),
        )
        if entries:
            return str(entries[0])

    if Path("/dev/video0").exists():
        return "/dev/video0"

    videos = sorted(Path("/dev").glob("video*"))
    if videos:
        return str(videos[0])
    return ""


def _detect_v4l2_mode(device: str) -> Tuple[Optional[int], Optional[int], str, Optional[int]]:
    """
    Query current camera mode via v4l2-ctl.

    Returns:
      (width, height, fourcc, fps)

    Notes on parsing:
    - `--get-fmt-video` usually prints:
        Width/Height      : 640/480
        Pixel Format      : 'MJPG'
    - `--get-parm` often prints:
        Frames per second: 15.000 (15/1)
    """
    if not device:
        return None, None, "", None

    fmt_out = _run_cmd_text(["v4l2-ctl", "-d", device, "--get-fmt-video"], timeout_s=2.0)
    parm_out = _run_cmd_text(["v4l2-ctl", "-d", device, "--get-parm"], timeout_s=2.0)

    width: Optional[int] = None
    height: Optional[int] = None
    fourcc = ""
    fps: Optional[int] = None

    # Width/Height parsing:
    # We capture both numbers and convert to int. If regex does not match,
    # we intentionally leave values as None so higher-level fallback applies.
    m_wh = re.search(r"Width/Height\s*:\s*(\d+)\s*/\s*(\d+)", fmt_out)
    if m_wh:
        width = _parse_int(m_wh.group(1))
        height = _parse_int(m_wh.group(2))

    # FourCC parsing:
    # This extracts the 4-character code inside single quotes.
    # Example line: Pixel Format      : 'MJPG'
    m_fourcc = re.search(r"Pixel\s+Format\s*:\s*'([A-Za-z0-9]{4})'", fmt_out)
    if m_fourcc:
        fourcc = m_fourcc.group(1).upper()

    # FPS parsing:
    # We parse the decimal value then normalize to the nearest int, because
    # launch uses integer FPS and we want clean persisted values.
    m_fps = re.search(r"Frames\s+per\s+second\s*:\s*([0-9.]+)", parm_out)
    if m_fps:
        try:
            fps = int(round(float(m_fps.group(1))))
        except Exception:
            fps = None

    return width, height, fourcc, fps


def _load_yaml(path: Path) -> Dict[str, Any]:
    """
    Load camera_profiles.yaml or return a safe skeleton.
    """
    if not path.exists():
        return {
            "defaults": {
                "source": "usb",
                "device": "/dev/video0",
                "width": 640,
                "height": 480,
                "fps": 15,
                "fourcc": "MJPG",
                "force_v4l2": True,
            },
            "profiles": {},
        }

    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        data = {}

    if not isinstance(data, dict):
        data = {}
    data.setdefault("defaults", {})
    data.setdefault("profiles", {})
    if not isinstance(data["defaults"], dict):
        data["defaults"] = {}
    if not isinstance(data["profiles"], dict):
        data["profiles"] = {}
    return data


def _choose_value(candidates: list[Tuple[str, Any]]) -> Tuple[Any, str]:
    """
    Pick first non-empty candidate and return (value, source_tag).
    """
    for source, raw in candidates:
        if raw is None:
            continue
        if isinstance(raw, str) and not raw.strip():
            continue
        return raw, source
    return None, "unset"


def _normalize_text_label(text: str) -> str:
    """
    Convert underscored/raw identifiers into human-readable labels.

    This is used for camera menu entries so operators see meaningful choices
    instead of raw udev strings.
    """
    s = str(text or "").strip()
    if not s:
        return "Unknown Camera"
    s = s.replace("_", " ")
    s = re.sub(r"\s+", " ", s)
    s = s.replace(" .", ".")
    return s.strip()


def _friendly_usb_name(by_id_name: str, fallback_card: str) -> str:
    """
    Build a user-friendly USB camera name from a by-id entry.

    Example transformation:
      usb-Sonix_Technology_Co.__Ltd._Steren_COM-126_SN0001-video-index0
      -> USB Camera: Sonix Technology Co. Ltd. Steren COM-126 SN0001
    """
    raw = str(by_id_name or "").strip()
    if raw:
        raw = re.sub(r"^usb-", "", raw)
        raw = re.sub(r"-video-index\d+$", "", raw)
        pretty = _normalize_text_label(raw)
        # Some integrated laptop cameras still appear under /dev/v4l/by-id
        # with a usb-* udev prefix. Keep label truthful for operators.
        if _looks_like_internal_camera_name(pretty):
            return f"Integrated Camera: {pretty}"
        return f"USB Camera: {pretty}"

    if fallback_card:
        pretty = _normalize_text_label(fallback_card)
        if _looks_like_internal_camera_name(pretty):
            return f"Integrated Camera: {pretty}"
        return f"USB Camera: {pretty}"

    return "USB Camera"


def _friendly_internal_name(by_id_name: str, fallback_card: str) -> str:
    """
    Build a user-friendly integrated/non-external camera label.
    """
    raw = str(by_id_name or "").strip()
    if raw:
        raw = re.sub(r"^usb-", "", raw)
        raw = re.sub(r"-video-index\d+$", "", raw)
        pretty = _normalize_text_label(raw)
        return f"Integrated Camera: {pretty}"

    if fallback_card:
        return f"Integrated Camera: {_normalize_text_label(fallback_card)}"

    return "Integrated Camera"


def _parse_v4l2_list_devices() -> List[Dict[str, Any]]:
    """
    Parse `v4l2-ctl --list-devices` into structured groups.

    Output shape:
    [
      {"card": "<card text>", "nodes": ["/dev/video0", ...]},
      ...
    ]

    The parser keeps ordering stable so menu indices are deterministic.
    """
    out = _run_cmd_text(["v4l2-ctl", "--list-devices"], timeout_s=3.0)
    if not out:
        return []

    # Each dict in this list corresponds to one camera "group" printed by
    # v4l2-ctl, which may include multiple /dev/video* nodes.
    groups: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for line in out.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Section headers from v4l2-ctl normally end with ':'.
        if not line.startswith(("\t", " ")) and stripped.endswith(":"):
            current = {"card": stripped[:-1], "nodes": []}
            groups.append(current)
            continue

        # Indented lines are device nodes under the current camera section.
        if current is not None and stripped.startswith("/dev/video"):
            current["nodes"].append(stripped)

    return groups


def _map_video_node_to_by_id() -> Dict[str, str]:
    """
    Build `/dev/videoN` -> `/dev/v4l/by-id/...` mapping where available.

    Why this matters:
    - by-id names are stable across reboots for USB cameras.
    - the menu can show friendlier and more deterministic USB labels.
    """
    mapping: Dict[str, str] = {}
    by_id_dir = Path("/dev/v4l/by-id")
    if not by_id_dir.exists():
        return mapping

    for p in sorted(by_id_dir.iterdir()):
        try:
            target = str(p.resolve())
        except Exception:
            continue
        if target.startswith("/dev/video"):
            mapping[target] = str(p)
    return mapping


def _video_node_has_capture_cap(node: str) -> bool:
    """
    Check whether `/dev/videoN` advertises capture capability.

    This avoids offering metadata-only nodes in the menu.
    """
    if not node:
        return False
    text = _run_cmd_text(["v4l2-ctl", "-d", node, "--all"], timeout_s=2.0)
    if not text:
        # If we cannot query caps (tool missing / permission issue), keep node
        # eligible rather than dropping potentially valid cameras.
        return True
    lowered = text.lower()
    return ("video capture" in lowered) or ("video capture mplane" in lowered)


def _looks_like_csi_card(card: str) -> bool:
    """
    Heuristic classification for Raspberry Pi CSI camera device groups.

    We intentionally keep broad matching because card names vary by OS/kernel.
    """
    s = str(card or "").lower()
    markers = (
        "unicam",
        "bcm2835",
        "rp1-cfe",
        "csi",
        "imx",
        "ov5647",
        "ov9281",
        "arducam",
    )
    return any(m in s for m in markers)


def _looks_like_internal_camera_name(value: str) -> bool:
    """
    Heuristic classification for integrated/non-external cameras.
    """
    s = str(value or "").lower().replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s)
    markers = (
        "integrated camera",
        "integrated webcam",
        "built in",
        "builtin",
        "internal camera",
        "facetime",
        "ipu6",
        "ipu3",
        "mipi",
        "onboard camera",
    )
    return any(m in s for m in markers)


def _looks_like_non_camera_pipeline_card(card: str) -> bool:
    """
    Identify Raspberry Pi video *pipeline* blocks that are not real camera sensors.

    Why this filter exists:
    - Raspberry Pi stacks often expose many `/dev/video*` nodes for ISP/codec
      components (for example `bcm2835-codec-*`, `bcm2835-isp`, `rpivid`).
    - Those nodes are useful for encode/decode pipelines, but selecting them as
      the FPV/SLAM source produces invalid sizes (for example 32x32) or open
      failures.
    - We therefore skip these groups during menu construction so operators only
      choose from physical camera endpoints.
    """
    s = str(card or "").lower()
    # Keep this marker list intentionally specific to known non-sensor blocks to
    # avoid accidentally filtering legitimate USB camera product names.
    markers = (
        "bcm2835-codec",
        "bcm2835-isp",
        "rpivid",
        "rp1-isp",
        "rp1-codec",
    )
    return any(m in s for m in markers)


def _read_sysfs_video_node_name(node: str) -> str:
    """
    Read `/sys/class/video4linux/videoN/name` for a node when available.

    This acts as a lightweight fallback identity source when higher-level tools
    (`v4l2-ctl`, `rpicam-hello`) are missing or partially available.
    """
    n = str(node or "").strip()
    if not n.startswith("/dev/video"):
        return ""
    base = Path(n).name
    p = Path("/sys/class/video4linux") / base / "name"
    try:
        return p.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _sensor_code_to_friendly_module(sensor_code: str) -> str:
    """
    Map common sensor IDs to user-friendly Raspberry Pi camera names.

    The goal is to show choices operators can understand at a glance.
    """
    code = str(sensor_code or "").strip().lower()
    mapping = {
        "ov5647": "Raspberry Pi Camera Module 1 (v1.3, 5MP)",
        "imx219": "Raspberry Pi Camera Module 2 (v2, 8MP)",
        "imx477": "Raspberry Pi HQ Camera (12.3MP)",
        "imx708": "Raspberry Pi Camera Module 3 (12MP)",
        "imx296": "Raspberry Pi Global Shutter Camera (1.6MP)",
        "imx500": "Raspberry Pi AI Camera (IMX500)",
    }
    if code in mapping:
        return mapping[code]
    if code:
        return f"Raspberry Pi CSI Camera ({code.upper()})"
    return "Raspberry Pi CSI Camera"


def _detect_csi_sensors_from_libcamera() -> Dict[int, str]:
    """
    Detect CSI sensors from rpicam/libcamera camera listing.

    We try modern command first (`rpicam-hello`), then fallback to
    `libcamera-hello` for older environments.

    Returns mapping: camera_index -> sensor_code
    """
    raw = _run_cmd_text_any_output(["rpicam-hello", "--list-cameras"], timeout_s=3.0)
    if not raw:
        raw = _run_cmd_text_any_output(["libcamera-hello", "--list-cameras"], timeout_s=3.0)
    if not raw:
        return {}

    # We keep a map by camera index so future extensions can target multi-camera
    # CSI setups deterministically (for example, camera 0 vs camera 1).
    out: Dict[int, str] = {}
    for line in raw.splitlines():
        # Expected examples:
        #   0 : ov5647 [2592x1944 ...]
        #   1 : imx219 [3280x2464 ...]
        m = re.search(r"^\s*(\d+)\s*:\s*['\"]?([A-Za-z0-9_\-]+)['\"]?(?:\s*\[|$)", line)
        if not m:
            continue
        # Parsed values are normalized immediately so downstream code can rely on
        # canonical types and case.
        idx = _parse_int(m.group(1))
        sensor = m.group(2).strip().lower()
        if idx is None:
            continue
        out[idx] = sensor
    return out


def _inventory_camera_candidates() -> List[CameraCandidate]:
    """
    Discover candidate cameras for operator selection.

    Discovery strategy:
    1) Parse V4L2 device groups so we can collect concrete `/dev/video*` nodes.
    2) Classify each capture-capable node as CSI, USB, or internal camera.
    3) Enrich CSI labels with `rpicam/libcamera --list-cameras` sensor IDs when available.

    The output list is intentionally sorted and deduplicated so menu numbers are
    stable and predictable across repeated runs.
    """
    # Gather all discovery inputs first so classification logic below can stay
    # pure and readable. This separation also makes troubleshooting easier:
    # maintainers can print these three sources independently when debugging.
    groups = _parse_v4l2_list_devices()
    by_id_map = _map_video_node_to_by_id()
    csi_sensors = _detect_csi_sensors_from_libcamera()

    candidates: List[CameraCandidate] = []
    seen_devices = set()

    for group in groups:
        card = str(group.get("card", "")).strip()
        # Entire V4L2 groups can represent codec/ISP pipeline blocks instead of
        # real camera sensors. Dropping them here dramatically reduces duplicate
        # menu rows and prevents accidental selection of invalid endpoints.
        if _looks_like_non_camera_pipeline_card(card):
            continue
        for node in group.get("nodes", []):
            node = str(node or "").strip()
            if not node or node in seen_devices:
                continue

            # Skip obviously non-capture nodes when we can confirm capability.
            # A single physical camera often exposes multiple nodes and only one
            # carries real frames. This filter keeps the menu focused on nodes
            # likely to be valid for FPV/SLAM image streams.
            if not _video_node_has_capture_cap(node):
                continue

            seen_devices.add(node)
            by_id_path = by_id_map.get(node, "")
            by_id_name = Path(by_id_path).name if by_id_path else ""
            sys_name = _read_sysfs_video_node_name(node)

            # Classification:
            # - by-id strongly indicates USB camera class
            # - otherwise fallback to card-name CSI heuristic
            # - sysfs node name is a final hint when card naming is ambiguous
            card_l = card.lower()
            sys_l = sys_name.lower()
            by_id_l = by_id_name.lower()
            internal_hint = (
                _looks_like_internal_camera_name(card)
                or _looks_like_internal_camera_name(sys_name)
                or _looks_like_internal_camera_name(by_id_name)
            )
            is_csi = _looks_like_csi_card(card) or _looks_like_csi_card(sys_name)
            is_usb = (
                (not internal_hint)
                and (
                    bool(by_id_path)
                    or ("usb" in card_l)
                    or ("usb" in sys_l)
                    or by_id_l.startswith("usb-")
                )
            )

            if is_csi:
                # If libcamera provided a sensor map, prefer a known sensor for
                # friendly operator presentation. In mixed/multi-camera cases,
                # this currently chooses camera 0 first, then any available
                # sensor entry as fallback.
                sensor_code = ""
                if csi_sensors:
                    # Try to match sensor code against card/sysfs strings first.
                    # If no direct match is found, fall back to camera index 0.
                    card_blob = f"{card} {sys_name}".lower()
                    for candidate_sensor in csi_sensors.values():
                        cs = str(candidate_sensor or "").strip().lower()
                        if cs and cs in card_blob:
                            sensor_code = cs
                            break
                    if not sensor_code:
                        sensor_code = csi_sensors.get(0, "") or next(iter(csi_sensors.values()), "")
                display = _sensor_code_to_friendly_module(sensor_code)
                candidates.append(
                    CameraCandidate(
                        kind="csi",
                        display_name=display,
                        device=node,
                        card=(card or sys_name),
                        sensor=sensor_code,
                        source_note=f"v4l2 node {node}",
                    )
                )
                continue

            # Non-CSI candidates are classified as integrated/non-external
            # first, then USB. We still prefer by-id for stable persistence
            # because /dev/videoN can reorder across reboot/reattach events.
            if internal_hint and not is_usb:
                kind = "internal"
                display = _friendly_internal_name(by_id_name, fallback_card=(card or sys_name))
            else:
                kind = "usb"
                display = _friendly_usb_name(by_id_name, fallback_card=(card or sys_name))
            preferred_device = by_id_path or node
            candidates.append(
                CameraCandidate(
                    kind=kind,
                    display_name=display,
                    device=preferred_device,
                    card=(card or sys_name),
                    source_note=("/dev/v4l/by-id" if by_id_path else "v4l2 node"),
                )
            )

    # If V4L2 grouping fails, we still offer a fallback candidate so users are
    # not blocked from saving a profile.
    if not candidates:
        fallback = _pick_device_from_system()
        if fallback:
            label = "Generic Camera"
            sys_name = _read_sysfs_video_node_name(fallback)
            fallback_name = Path(fallback).name if fallback.startswith("/dev/v4l/by-id/") else ""
            internal_hint = _looks_like_internal_camera_name(f"{sys_name} {fallback_name}")
            # If libcamera sees a CSI sensor and fallback device is /dev/video0,
            # classify as CSI candidate first for clearer operator intent.
            csi_sensors = _detect_csi_sensors_from_libcamera()
            looks_like_csi_node = _looks_like_csi_card(sys_name)
            if (csi_sensors or looks_like_csi_node) and fallback.startswith("/dev/video"):
                sensor = csi_sensors.get(0, "") or next(iter(csi_sensors.values()), "")
                label = _sensor_code_to_friendly_module(sensor)
                candidates.append(
                    CameraCandidate(
                        kind="csi",
                        display_name=label,
                        device=fallback,
                        card=sys_name,
                        sensor=sensor,
                        source_note="fallback detection",
                    )
                )
            else:
                candidates.append(
                    CameraCandidate(
                        kind="internal" if internal_hint else "usb",
                        display_name=(
                            _friendly_internal_name("", fallback_card=sys_name)
                            if internal_hint
                            else (_friendly_usb_name("", fallback_card=sys_name) if sys_name else label)
                        ),
                        device=fallback,
                        card=sys_name,
                        source_note="fallback detection",
                    )
                )

    def _slug(value: str) -> str:
        s = str(value or "").strip().lower()
        s = re.sub(r"[^a-z0-9]+", "-", s)
        return s.strip("-")

    def _physical_key(c: CameraCandidate) -> str:
        """
        Build a stable identity key representing the *physical* camera.

        We intentionally do not key by raw `/dev/videoN`, because one camera can
        expose multiple nodes (index0/index1 or pipeline nodes). The goal is one
        menu entry per actual camera whenever possible.
        """
        if c.kind == "usb":
            if c.device.startswith("/dev/v4l/by-id/"):
                by_name = Path(c.device).name
                # Collapse index0/index1 variants to one physical key.
                by_name = re.sub(r"-video-index\d+$", "", by_name)
                by_name = re.sub(r"-index\d+$", "", by_name)
                return f"usb:{_slug(by_name)}"
            card_key = _slug(c.card)
            if card_key:
                return f"usb-card:{card_key}"
            return f"usb-node:{_slug(c.device)}"

        if c.kind == "internal":
            if c.device.startswith("/dev/v4l/by-id/"):
                by_name = Path(c.device).name
                by_name = re.sub(r"-video-index\d+$", "", by_name)
                by_name = re.sub(r"-index\d+$", "", by_name)
                return f"internal:{_slug(by_name)}"
            card_key = _slug(c.card)
            if card_key:
                return f"internal-card:{card_key}"
            return f"internal-node:{_slug(c.device)}"

        # CSI key preference:
        # 1) explicit sensor code (best physical identity)
        # 2) card string
        # 3) node path fallback
        sensor_key = _slug(c.sensor)
        if sensor_key:
            return f"csi-sensor:{sensor_key}"
        card_key = _slug(c.card)
        if card_key:
            return f"csi-card:{card_key}"
        return f"csi-node:{_slug(c.device)}"

    def _rank(c: CameraCandidate) -> int:
        """
        Rank duplicate candidates so we keep the most useful representative.
        """
        rank = 0
        if c.kind == "usb":
            if c.device.startswith("/dev/v4l/by-id/"):
                rank += 50
                if "index0" in c.device:
                    rank += 20
            if c.card:
                rank += 5
            return rank

        if c.kind == "internal":
            if c.device.startswith("/dev/v4l/by-id/"):
                rank += 45
                if "index0" in c.device:
                    rank += 20
            if c.card:
                rank += 5
            if _looks_like_internal_camera_name(c.display_name) or _looks_like_internal_camera_name(c.card):
                rank += 10
            return rank

        card_l = str(c.card or "").lower()
        if "unicam" in card_l or "rp1-cfe" in card_l or "csi" in card_l:
            rank += 50
        if c.sensor:
            rank += 20
        if c.device.endswith("video0"):
            rank += 5
        return rank

    # Deduplicate by physical camera identity while preserving first-seen order.
    dedup_by_key: Dict[str, CameraCandidate] = {}
    key_order: List[str] = []
    for c in candidates:
        key = _physical_key(c)
        existing = dedup_by_key.get(key)
        if existing is None:
            dedup_by_key[key] = c
            key_order.append(key)
            continue
        if _rank(c) > _rank(existing):
            dedup_by_key[key] = c

    dedup: List[CameraCandidate] = [dedup_by_key[k] for k in key_order]

    return dedup


def _pick_menu_default_index(candidates: List[CameraCandidate], preferred_device: str) -> int:
    """
    Choose which menu item should be highlighted as default.

    Priority:
    1) exact device match with preferred_device from args/env/existing profile
    2) first CSI camera (if present) because user requested short-term CSI use
    3) first candidate in list
    """
    preferred = str(preferred_device or "").strip()
    if preferred:
        for i, c in enumerate(candidates):
            if c.device == preferred:
                return i
    for i, c in enumerate(candidates):
        if c.kind == "csi":
            return i
    return 0


def _prompt_camera_selection(
    candidates: List[CameraCandidate],
    default_idx: int,
    prompt_input: TextIO,
) -> CameraCandidate:
    """
    Render an interactive numbered menu and return the selected camera.

    The prompt explicitly states this selection is for FPV + forward-facing SLAM
    so operators understand the consequence of the saved profile.
    """
    default_human = default_idx + 1
    while True:
        raw = _read_prompt_line(
            prompt_input=prompt_input,
            prompt=(
                f"Select camera for FPV+SLAM [1-{len(candidates)}] "
                f"(Enter for {default_human}): "
            ),
        ).strip()
        if not raw:
            return candidates[default_idx]
        idx = _parse_int(raw)
        if idx is None:
            print("[WARN] Enter a number.")
            continue
        if 1 <= idx <= len(candidates):
            return candidates[idx - 1]
        print(f"[WARN] Enter a value between 1 and {len(candidates)}.")


def _print_camera_candidates(candidates: List[CameraCandidate]) -> None:
    """
    Print discovered camera candidates in a consistent operator-facing format.

    We print this even when running non-interactively so users can still see
    what hardware was recognized (for example, when troubleshooting why an
    expected second camera did not appear).
    """
    if not candidates:
        print("[CAMERA PROFILE] No camera candidates detected from runtime inventory.")
        return

    print("[CAMERA PROFILE] Camera candidates detected on this robot:")
    for i, c in enumerate(candidates, start=1):
        if c.kind == "csi":
            tag = "CSI"
        elif c.kind == "internal":
            tag = "INTERNAL"
        else:
            tag = "USB"
        _print_wrapped(f"  {i}. [{tag}] ", c.display_name)
        _print_wrapped("       device: ", c.device)
        if c.card:
            _print_wrapped("         card: ", c.card)
        if c.sensor:
            _print_wrapped("       sensor: ", c.sensor)


def _terminal_width() -> int:
    """
    Return a conservative terminal width for wrapped status output.

    We cap maximum width so formatting remains readable on wide terminals while
    still behaving well on long, thin panes.
    """
    try:
        width = int(shutil.get_terminal_size(fallback=(80, 24)).columns)
    except Exception:
        width = 80
    return max(48, min(width, 120))


def _print_wrapped(prefix: str, text: Any) -> None:
    """
    Print text with wrapping and a stable indentation prefix.

    `break_long_words=False` avoids chopping device paths into unreadable pieces.
    """
    raw = str(text if text is not None else "").strip()
    if not raw:
        print(prefix.rstrip())
        return
    wrapped = textwrap.wrap(
        raw,
        width=_terminal_width(),
        initial_indent=prefix,
        subsequent_indent=(" " * len(prefix)),
        break_long_words=False,
        break_on_hyphens=False,
    )
    for line in wrapped:
        print(line)


def _print_profile_field(label: str, value: Any, source: str) -> None:
    """
    Print one profile field in thin-terminal-friendly multi-line form.
    """
    _print_wrapped(f"  {label}: ", value)
    _print_wrapped("    source: ", source)


def _acquire_prompt_input() -> Optional[TextIO]:
    """
    Acquire an input stream for interactive prompts.

    Priority:
    1) stdin when it is a TTY
    2) /dev/tty fallback (covers some ros2 run environments where stdin is piped)
    3) None when no interactive terminal is available
    """
    try:
        if sys.stdin.isatty():
            return sys.stdin
    except Exception:
        pass

    try:
        return open("/dev/tty", "r", encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _read_prompt_line(prompt_input: TextIO, prompt: str) -> str:
    """
    Read one line from prompt_input while rendering the prompt text.

    - When input stream is stdin, use builtin input() semantics.
    - When using /dev/tty fallback, manually print prompt and readline().
    """
    if prompt_input is sys.stdin:
        try:
            return input(prompt)
        except EOFError:
            return ""

    print(prompt, end="", flush=True)
    try:
        line = prompt_input.readline()
    except Exception:
        return ""
    if not line:
        return ""
    return line.rstrip("\r\n")


def main(argv: Optional[list[str]] = None) -> int:
    # Argument parsing intentionally mirrors existing camera field names so
    # operators can map values mentally between CLI, env vars, launch args,
    # and YAML keys without translation overhead.
    parser = argparse.ArgumentParser(
        description="Persist detected CAMERA_* values into camera_profiles.yaml",
    )
    parser.add_argument("--robot", default="")
    parser.add_argument(
        "--camera-profiles",
        default="",
        help="Path to camera_profiles.yaml",
    )
    parser.add_argument("--device", default="")
    parser.add_argument("--width", default="")
    parser.add_argument("--height", default="")
    parser.add_argument("--fps", default="")
    parser.add_argument("--fourcc", default="")
    parser.add_argument("--force-v4l2", default="")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip camera menu and use precedence-based auto selection.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    # ---------------------------------------------------------------------
    # Phase 1: Load context (target robot + YAML defaults + existing profile)
    # ---------------------------------------------------------------------
    robot = str(args.robot or "").strip()
    if not robot:
        try:
            robot = default_robot_name()
        except MissingConfigError as ex:
            print(f"[ERROR] {ex}", file=sys.stderr)
            return 2

    camera_profiles_arg = str(args.camera_profiles or "").strip()
    if not camera_profiles_arg:
        try:
            camera_profiles_arg = default_camera_profiles_path()
        except MissingConfigError as ex:
            print(f"[ERROR] {ex}", file=sys.stderr)
            return 2

    profiles_path = Path(camera_profiles_arg).expanduser()
    data = _load_yaml(profiles_path)
    defaults = data.get("defaults", {}) or {}
    profiles = data.get("profiles", {}) or {}
    existing = profiles.get(robot, {}) if isinstance(profiles.get(robot, {}), dict) else {}

    # ---------------------------------------------------------------------
    # Phase 2: Discover what cameras are physically available *right now*.
    # This inventory is reused for:
    # - interactive menu display
    # - deterministic non-interactive auto-selection
    # ---------------------------------------------------------------------
    candidates = _inventory_camera_candidates()

    # ---------------------------------------------------------------------
    # Phase 3: Build pre-menu device preference.
    # This is used to choose which menu item is preselected.
    # Priority is strict and intentional:
    # 1) explicit CLI arg (operator intent for this run)
    # 2) CAMERA_DEVICE env var (session-level override)
    # 3) best-effort OS detection (runtime hardware truth)
    # 4) existing robot profile value (persisted historical choice)
    # 5) global defaults (last resort)
    # ---------------------------------------------------------------------
    preferred_device, src_device_pre = _choose_value([
        ("arg.device", str(args.device or "").strip()),
        ("env.CAMERA_DEVICE", os.environ.get("CAMERA_DEVICE", "").strip()),
        ("detect.system_device", _pick_device_from_system()),
        ("yaml.profiles.<robot>.device", existing.get("device")),
        ("yaml.defaults.device", defaults.get("device")),
        ("fallback", "/dev/video0"),
    ])
    preferred_device = str(preferred_device or "").strip()

    # selected_candidate carries the operator-approved hardware identity that
    # downstream value assembly (size/fps/fourcc/force_v4l2) should be based on.
    selected_candidate: Optional[CameraCandidate] = None
    src_device = src_device_pre
    prompt_input: Optional[TextIO] = None
    if not args.non_interactive:
        prompt_input = _acquire_prompt_input()
    interactive = prompt_input is not None

    if candidates:
        _print_camera_candidates(candidates)
        default_idx = _pick_menu_default_index(candidates, preferred_device)

        # -----------------------------------------------------------------
        # Phase 4: Resolve final camera hardware selection.
        # - Interactive: operator explicitly picks FPV/SLAM camera.
        # - Non-interactive: keep automation stable by selecting the same
        #   deterministic default index each run.
        # -----------------------------------------------------------------
        if interactive:
            selected_candidate = _prompt_camera_selection(
                candidates=candidates,
                default_idx=default_idx,
                prompt_input=prompt_input or sys.stdin,
            )
            src_device = "menu.selection"
        else:
            if not args.non_interactive:
                print(
                    "[INFO] No interactive terminal detected; auto-selecting default camera candidate. "
                    "Run directly in a terminal for manual menu selection."
                )
            selected_candidate = candidates[default_idx]
            src_device = "detect.inventory.default"
    else:
        _print_camera_candidates(candidates)

    # Close /dev/tty handle when one was opened explicitly for prompting.
    if prompt_input is not None and prompt_input is not sys.stdin:
        try:
            prompt_input.close()
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # Phase 5: Decide source/device identity fields saved in YAML.
    # If menu/inventory produced a candidate, that is authoritative.
    # Otherwise we fall back to the pre-menu preference chain.
    # ---------------------------------------------------------------------
    device = ""
    source = "usb"
    selected_label = ""
    selected_sensor = ""
    if selected_candidate is not None:
        device = str(selected_candidate.device or "").strip()
        source = selected_candidate.kind
        selected_label = selected_candidate.display_name
        selected_sensor = selected_candidate.sensor
    else:
        device = preferred_device
        source = str(existing.get("source") or defaults.get("source") or "usb").strip().lower() or "usb"

    # Probe selected streamability before persisting profile values.
    # This avoids saving camera nodes that produce one frame and then stall.
    probe_ok, probe_note = _probe_v4l2_stream(device)
    manual_menu_selected = (src_device == "menu.selection")
    allow_probe_fallback = True
    if manual_menu_selected:
        # Respect explicit operator camera selection by default.
        # Opt in to auto-fallback only when explicitly requested.
        force_fallback = _parse_bool(os.environ.get("SWARM_CORE_CAMERA_ALLOW_PROBE_FALLBACK", "").strip())
        allow_probe_fallback = bool(force_fallback is True)

    if probe_ok is False and selected_candidate is not None and candidates and allow_probe_fallback:
        _print_wrapped(
            "  probe: ",
            f"selected device {device} looked unstable ({probe_note}); searching fallback candidate",
        )
        fallback = None
        fallback_note = ""
        same_kind = [c for c in candidates if c.kind == source and c.device != device]
        other_kind = [c for c in candidates if c.kind != source and c.device != device]
        for c in same_kind + other_kind:
            ok2, note2 = _probe_v4l2_stream(str(c.device))
            if ok2 is True:
                fallback = c
                fallback_note = note2
                break
        if fallback is not None:
            selected_candidate = fallback
            device = str(fallback.device or "").strip()
            source = fallback.kind
            selected_label = fallback.display_name
            selected_sensor = fallback.sensor
            src_device = "probe.fallback.selection"
            _print_wrapped("  probe: ", f"fallback selected {device} ({fallback_note})")
        else:
            _print_wrapped(
                "  probe: ",
                "no better candidate passed stream probe; keeping selected device and continuing",
            )
    elif probe_ok is False and selected_candidate is not None and candidates and not allow_probe_fallback:
        _print_wrapped(
            "  probe: ",
            (
                f"selected device {device} looked unstable ({probe_note}); "
                "keeping explicit menu selection. "
                "Set SWARM_CORE_CAMERA_ALLOW_PROBE_FALLBACK=1 to allow automatic fallback."
            ),
        )

    if probe_ok is None:
        _print_wrapped("  probe: ", f"stream probe unavailable ({probe_note})")

    # We only probe v4l2 mode if we ended with a concrete device path.
    # This keeps the script resilient when no camera is attached.
    det_w, det_h, det_fourcc, det_fps = _detect_v4l2_mode(device)

    # ---------------------------------------------------------------------
    # Phase 6: Assemble profile parameters with explicit precedence chains.
    # Each call returns both value + "source tag" so the summary can show
    # operators exactly where each field originated.
    # ---------------------------------------------------------------------
    width_raw, src_width = _choose_value([
        ("arg.width", str(args.width or "").strip()),
        ("env.CAMERA_WIDTH", os.environ.get("CAMERA_WIDTH", "").strip()),
        ("detect.v4l2.width", det_w),
        ("yaml.profiles.<robot>.width", existing.get("width")),
        ("yaml.defaults.width", defaults.get("width")),
        ("fallback", 640),
    ])
    height_raw, src_height = _choose_value([
        ("arg.height", str(args.height or "").strip()),
        ("env.CAMERA_HEIGHT", os.environ.get("CAMERA_HEIGHT", "").strip()),
        ("detect.v4l2.height", det_h),
        ("yaml.profiles.<robot>.height", existing.get("height")),
        ("yaml.defaults.height", defaults.get("height")),
        ("fallback", 480),
    ])
    fps_raw, src_fps = _choose_value([
        ("arg.fps", str(args.fps or "").strip()),
        ("env.CAMERA_FPS", os.environ.get("CAMERA_FPS", "").strip()),
        ("detect.v4l2.fps", det_fps),
        ("yaml.profiles.<robot>.fps", existing.get("fps")),
        ("yaml.defaults.fps", defaults.get("fps")),
        ("fallback", 15),
    ])

    # For USB cameras we keep MJPG default. For CSI camera modules we prefer
    # probed formats first and keep YUYV as conservative fallback.
    # This does not prevent users from overriding via CLI/env.
    default_fourcc = "YUYV" if source == "csi" else "MJPG"
    detected_fourcc = str(det_fourcc or "").strip().upper()
    fourcc_candidates = [
        ("arg.fourcc", str(args.fourcc or "").strip().upper()),
        ("env.CAMERA_FOURCC", os.environ.get("CAMERA_FOURCC", "").strip().upper()),
    ]
    if source == "csi":
        # CSI selection order:
        # 1) explicit arg/env override
        # 2) probed active v4l2 format for the selected device
        # 3) existing persisted values
        # 4) conservative fallback
        fourcc_candidates.extend(
            [
                ("detect.v4l2.fourcc", detected_fourcc),
                ("yaml.profiles.<robot>.fourcc", existing.get("fourcc")),
                ("yaml.defaults.fourcc", defaults.get("fourcc")),
                ("fallback", default_fourcc),
            ]
        )
    else:
        fourcc_candidates.extend(
            [
                ("detect.v4l2.fourcc", detected_fourcc),
                ("yaml.profiles.<robot>.fourcc", existing.get("fourcc")),
                ("yaml.defaults.fourcc", defaults.get("fourcc")),
                ("fallback", default_fourcc),
            ]
        )
    fourcc_raw, src_fourcc = _choose_value(fourcc_candidates)

    # We keep V4L2 defaulted on for both USB and CSI, then let adapter-side
    # strategy rotation recover if a specific format stalls.
    # This behavior is overrideable via CLI/env.
    default_force = True
    force_candidates = [
        ("arg.force_v4l2", str(args.force_v4l2 or "").strip()),
        ("env.CAMERA_FORCE_V4L2", os.environ.get("CAMERA_FORCE_V4L2", "").strip()),
    ]
    if source == "csi":
        # Keep CSI safe by default even when persisted YAML contains stale USB settings.
        force_candidates.extend(
            [
                ("fallback", default_force),
                ("yaml.profiles.<robot>.force_v4l2", existing.get("force_v4l2")),
                ("yaml.defaults.force_v4l2", defaults.get("force_v4l2")),
            ]
        )
    else:
        force_candidates.extend(
            [
                ("yaml.profiles.<robot>.force_v4l2", existing.get("force_v4l2")),
                ("yaml.defaults.force_v4l2", defaults.get("force_v4l2")),
                ("fallback", default_force),
            ]
        )
    force_raw, src_force = _choose_value(force_candidates)

    # Normalize numeric/boolean values so YAML output is strongly typed.
    # This is important because launch/adapter code expects ints/bools for
    # stable behavior and easier diagnostics.
    width = max(1, _parse_int(width_raw) or 640)
    height = max(1, _parse_int(height_raw) or 480)
    fps = max(1, _parse_int(fps_raw) or 15)
    # Guard against pathological probe/persisted FPS (for example 1fps), which
    # can make teleop feel unusable. Respect explicit operator overrides.
    if fps < 5 and str(src_fps) not in ("arg.fps", "env.CAMERA_FPS"):
        _print_wrapped(
            "  fps guard: ",
            f"resolved {fps}fps from {src_fps}; using 15fps fallback for low-latency control",
        )
        fps = 15
        src_fps = "fallback.low_fps_guard"
    selected_fourcc_raw = (str(fourcc_raw or default_fourcc).strip().upper() or default_fourcc)[:4]
    fourcc = _sanitize_profile_fourcc(source, selected_fourcc_raw)
    if fourcc != selected_fourcc_raw:
        src_fourcc = "fallback.csi_safe_fourcc"
    force_v4l2 = _parse_bool(force_raw)
    if force_v4l2 is None:
        force_v4l2 = bool(default_force)

    if not device:
        print("[ERROR] Could not resolve a camera device path.", file=sys.stderr)
        print("Set CAMERA_DEVICE and retry.", file=sys.stderr)
        return 2

    # ---------------------------------------------------------------------
    # Phase 7: Write normalized profile payload.
    # We replace the entire selected robot profile block every run so camera
    # swaps are reflected cleanly (no stale keys from old hardware remain).
    # If profiles.<robot> does not exist yet, this assignment creates it.
    # ---------------------------------------------------------------------
    profiles[robot] = {
        "source": source,
        "camera_name": selected_label,
        "sensor": selected_sensor,
        "device": device,
        "width": width,
        "height": height,
        "fps": fps,
        "fourcc": fourcc,
        "force_v4l2": force_v4l2,
    }
    data["profiles"] = profiles

    # ---------------------------------------------------------------------
    # Phase 8: Print full provenance report before writing.
    # This gives operators a final confirmation of selected hardware and value
    # sources, which is especially useful when mixed USB/CSI cameras exist.
    # ---------------------------------------------------------------------
    print(f"[CAMERA PROFILE] robot={robot}")
    _print_wrapped("  source: ", source)
    if selected_label:
        _print_wrapped("  camera_name: ", selected_label)
    if selected_sensor:
        _print_wrapped("  sensor: ", selected_sensor)
    _print_profile_field("device", device, src_device)
    _print_profile_field("width", width, src_width)
    _print_profile_field("height", height, src_height)
    _print_profile_field("fps", fps, src_fps)
    _print_profile_field("fourcc", fourcc, src_fourcc)
    _print_profile_field("force_v4l2", force_v4l2, src_force)
    _print_wrapped("  output: ", profiles_path)

    if args.dry_run:
        print("[DRY RUN] No file was written.")
        return 0

    # Create parent directories when missing so first-time setup works without
    # manual directory creation.
    profiles_path.parent.mkdir(parents=True, exist_ok=True)
    with profiles_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)

    print("[OK] camera profile persisted.")
    print("Next bringup can rely on camera_profiles.yaml without repeating CAMERA_* args.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
