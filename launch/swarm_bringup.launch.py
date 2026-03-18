from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, LogInfo, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

import os
import re
from ament_index_python.packages import get_package_share_directory
from swarm_control_core.camera_runtime_defaults import apply_low_latency_camera_clamp
from swarm_control_core.path_defaults import (
    MissingConfigError,
    default_camera_profiles_path,
    default_profiles_path,
    default_robot_name,
)

try:
    import yaml
except Exception:
    yaml = None  # type: ignore[assignment]


def _default_ros_domain_id() -> str:
    return str(os.environ.get("ROS_DOMAIN_ID", "17")).strip() or "17"


def _sanitize_ros_name(name: str) -> str:
    # ROS name/topic-safe: alphanumerics + underscore only
    s = re.sub(r"[^A-Za-z0-9_]", "_", (name or "").strip())
    s = s.strip("_")
    return s


def _parse_positive_int(raw_value: str, default: int) -> int:
    """
    Parse numeric launch arg values robustly.

    Accepts values like "15" and "15.0" and clamps to >= 1.
    Falls back to the provided default on invalid input.
    """
    try:
        value = int(float(str(raw_value).strip()))
        if value >= 1:
            return value
    except Exception:
        pass
    return int(default)


def _parse_bool(raw_value: str, default: bool) -> bool:
    s = str(raw_value or "").strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return bool(default)


def _sanitize_camera_fourcc(camera_source: str, raw_fourcc: str) -> str:
    """
    Normalize configured fourcc to safer source-aware defaults.

    CSI paths keep a small allow-list of commonly stable OpenCV formats.
    """
    fourcc = str(raw_fourcc or "").strip().upper()
    if len(fourcc) != 4:
        fourcc = ""
    if camera_source == "csi":
        if fourcc in ("BGR3", "RGB3", "YUYV", "UYVY", "YVYU", "VYUY", "MJPG"):
            return fourcc
        return "YUYV"
    return fourcc or "MJPG"


def _load_camera_profile(camera_profiles_path: str, camera_profile_name: str) -> tuple[dict, dict]:
    """
    Load merged camera profile values and explicit per-robot overrides.

    Returns:
      (merged_profile, explicit_robot_profile)
    """
    out = {}
    explicit_profile = {}
    path = str(camera_profiles_path or "").strip()
    if not path or not os.path.exists(path) or yaml is None:
        return out, explicit_profile

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return out, explicit_profile

    if not isinstance(data, dict):
        return out, explicit_profile

    defaults = data.get("defaults", {})
    if isinstance(defaults, dict):
        out.update(defaults)

    key = str(camera_profile_name or "").strip()
    if not key:
        return out, explicit_profile

    for container_key in ("profiles", "robots"):
        container = data.get(container_key, {})
        if not isinstance(container, dict):
            continue
        row = container.get(key)
        if isinstance(row, dict):
            out.update(row)
            explicit_profile = dict(row)
            return out, explicit_profile
    return out, explicit_profile


def _make_nodes(context, *args, **kwargs):
    requested_robot_name = (LaunchConfiguration("robot_name").perform(context) or "").strip()
    if requested_robot_name:
        robot_name = _sanitize_ros_name(requested_robot_name)
    else:
        try:
            robot_name = _sanitize_ros_name(default_robot_name())
        except MissingConfigError as ex:
            raise RuntimeError(f"{ex} (or pass launch arg robot_name:=<name>)")
    if not robot_name:
        raise RuntimeError(
            "robot_name resolved empty after sanitization. "
            "Set SWARM_COM_ROBOT_NAME/ROBOT_NAME or pass robot_name:=<name>."
        )

    use_camera = LaunchConfiguration("use_camera").perform(context).lower() in ("1", "true", "yes", "on")
    use_camera_autonomy = LaunchConfiguration("use_camera_autonomy").perform(context).lower() in ("1", "true", "yes", "on")

    camera_low_latency_mode = _parse_bool(
        (LaunchConfiguration("camera_low_latency_mode").perform(context) or "").strip(),
        default=True,
    )
    camera_allow_env_overrides = _parse_bool(
        (LaunchConfiguration("camera_allow_env_overrides").perform(context) or "").strip(),
        default=False,
    )
    camera_env_vars = (
        "CAMERA_DEVICE",
        "CAMERA_FPS",
        "CAMERA_WIDTH",
        "CAMERA_HEIGHT",
        "CAMERA_FOURCC",
        "CAMERA_FORCE_V4L2",
    )
    ignored_camera_env_vars = []
    if not camera_allow_env_overrides:
        ignored_camera_env_vars = [
            var_name for var_name in camera_env_vars if str(os.environ.get(var_name, "")).strip()
        ]

    camera_profiles_path = (LaunchConfiguration("camera_profiles_path").perform(context) or "").strip()
    if use_camera and not camera_profiles_path:
        try:
            camera_profiles_path = default_camera_profiles_path()
        except MissingConfigError as ex:
            raise RuntimeError(f"{ex} (or pass launch arg camera_profiles_path:=<path>)")
    camera_profile_name = (LaunchConfiguration("camera_profile_name").perform(context) or "").strip() or robot_name
    camera_profile, explicit_camera_profile = _load_camera_profile(camera_profiles_path, camera_profile_name)
    camera_source = str(camera_profile.get("source", "")).strip().lower()

    # `video_device` is the canonical arg. `camera_device` is kept as a
    # compatibility alias so older operator commands still work.
    video_device = (LaunchConfiguration("video_device").perform(context) or "").strip()
    camera_device_alias = (LaunchConfiguration("camera_device").perform(context) or "").strip()
    if camera_device_alias:
        video_device = camera_device_alias
    if not video_device and camera_allow_env_overrides:
        video_device = os.environ.get("CAMERA_DEVICE", "").strip()
    if not video_device:
        video_device = str(camera_profile.get("device", "")).strip()
    if not video_device:
        video_device = "/dev/video0"

    camera_pipeline = LaunchConfiguration("camera_pipeline").perform(context).strip().lower()
    camera_fps_arg_raw = (LaunchConfiguration("camera_fps").perform(context) or "").strip()
    camera_fps_env_raw = ""
    if (not camera_fps_arg_raw) and camera_allow_env_overrides:
        camera_fps_env_raw = os.environ.get("CAMERA_FPS", "").strip()
    camera_fps_raw = camera_fps_arg_raw or camera_fps_env_raw
    if not camera_fps_raw:
        camera_fps_raw = str(camera_profile.get("fps", "")).strip()
    camera_fps = _parse_positive_int(camera_fps_raw, default=15)
    camera_fps_overridden = bool(camera_fps_arg_raw or camera_fps_env_raw)

    camera_width_arg_raw = (LaunchConfiguration("camera_width").perform(context) or "").strip()
    camera_width_env_raw = ""
    if (not camera_width_arg_raw) and camera_allow_env_overrides:
        camera_width_env_raw = os.environ.get("CAMERA_WIDTH", "").strip()
    camera_width_raw = camera_width_arg_raw or camera_width_env_raw
    if not camera_width_raw:
        camera_width_raw = str(camera_profile.get("width", "")).strip()
    camera_width = _parse_positive_int(camera_width_raw, default=640)
    camera_width_overridden = bool(camera_width_arg_raw or camera_width_env_raw)

    camera_height_arg_raw = (LaunchConfiguration("camera_height").perform(context) or "").strip()
    camera_height_env_raw = ""
    if (not camera_height_arg_raw) and camera_allow_env_overrides:
        camera_height_env_raw = os.environ.get("CAMERA_HEIGHT", "").strip()
    camera_height_raw = camera_height_arg_raw or camera_height_env_raw
    if not camera_height_raw:
        camera_height_raw = str(camera_profile.get("height", "")).strip()
    camera_height = _parse_positive_int(camera_height_raw, default=480)
    camera_height_overridden = bool(camera_height_arg_raw or camera_height_env_raw)

    camera_fourcc_arg_raw = (LaunchConfiguration("camera_fourcc").perform(context) or "").strip().upper()
    camera_fourcc_env_raw = ""
    if not camera_fourcc_arg_raw and camera_allow_env_overrides:
        camera_fourcc_env_raw = os.environ.get("CAMERA_FOURCC", "").strip().upper()
    camera_fourcc_override_raw = camera_fourcc_arg_raw or camera_fourcc_env_raw
    if camera_fourcc_override_raw:
        camera_fourcc = _sanitize_camera_fourcc(camera_source, camera_fourcc_override_raw)
    else:
        explicit_fourcc = str(explicit_camera_profile.get("fourcc", "")).strip().upper()
        merged_fourcc = str(camera_profile.get("fourcc", "")).strip().upper()
        if camera_source == "csi":
            camera_fourcc = _sanitize_camera_fourcc(camera_source, explicit_fourcc or merged_fourcc or "YUYV")
        else:
            camera_fourcc = _sanitize_camera_fourcc(camera_source, explicit_fourcc or merged_fourcc or "MJPG")
    camera_fourcc_overridden = bool(camera_fourcc_arg_raw or camera_fourcc_env_raw)

    camera_force_v4l2_arg_raw = (LaunchConfiguration("camera_force_v4l2").perform(context) or "").strip()
    camera_force_v4l2_env_raw = ""
    if not camera_force_v4l2_arg_raw and camera_allow_env_overrides:
        camera_force_v4l2_env_raw = os.environ.get("CAMERA_FORCE_V4L2", "").strip()
    camera_force_v4l2_override_raw = camera_force_v4l2_arg_raw or camera_force_v4l2_env_raw
    explicit_force_raw = str(explicit_camera_profile.get("force_v4l2", "")).strip()

    if camera_force_v4l2_override_raw:
        camera_force_v4l2 = _parse_bool(camera_force_v4l2_override_raw, default=True)
    else:
        if explicit_force_raw:
            camera_force_v4l2 = _parse_bool(explicit_force_raw, default=True)
        else:
            merged_force_raw = str(camera_profile.get("force_v4l2", "true")).strip()
            camera_force_v4l2 = _parse_bool(merged_force_raw, default=True)

    original_camera_shape = (camera_width, camera_height, camera_fps, camera_fourcc)
    camera_width, camera_height, camera_fps, camera_fourcc, camera_clamp_notes = (
        apply_low_latency_camera_clamp(
            camera_source=camera_source,
            enabled=camera_low_latency_mode,
            width=camera_width,
            height=camera_height,
            fps=camera_fps,
            fourcc=camera_fourcc,
            width_overridden=camera_width_overridden,
            height_overridden=camera_height_overridden,
            fps_overridden=camera_fps_overridden,
            fourcc_overridden=camera_fourcc_overridden,
        )
    )
    camera_fourcc = _sanitize_camera_fourcc(camera_source, camera_fourcc)

    drive_type = LaunchConfiguration("drive_type").perform(context)
    hardware = LaunchConfiguration("hardware").perform(context)
    profiles_path = (LaunchConfiguration("profiles_path").perform(context) or "").strip()
    strict_single_pub_override_raw = (
        LaunchConfiguration("strict_single_cmd_vel_publisher").perform(context) or ""
    ).strip()
    if not profiles_path:
        try:
            profiles_path = default_profiles_path()
        except MissingConfigError as ex:
            raise RuntimeError(f"{ex} (or pass launch arg profiles_path:=<path>)")

    nodes = []

    def _wrap_and_append_log(msg: str, width: int = 30):
        # split message into narrow chunks while respecting word boundaries
        # for terminal-friendly output on narrow terminals (e.g., 30-char windows)
        lines = []
        current_line = ""
        for word in msg.split(" "):
            if not current_line:
                current_line = word
            elif len(current_line) + 1 + len(word) <= width:
                current_line += " " + word
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        for line in lines:
            nodes.append(LogInfo(msg=line))

    def _package_exists(pkg_name: str) -> bool:
        """Check if ROS 2 package is installed using ament index."""
        try:
            get_package_share_directory(pkg_name)
            return True
        except Exception:
            return False

    def _try_node(**node_kwargs):
        pkg = node_kwargs.get("package")
        name = node_kwargs.get("name") or node_kwargs.get("executable")
        
        # Check if package exists before creating Node
        if pkg and not _package_exists(pkg):
            _wrap_and_append_log(f"[SKIP] {name}: pkg '{pkg}'")
            _wrap_and_append_log(f"       not found")
            return
        
        try:
            n = Node(**node_kwargs)
            nodes.append(n)
            _wrap_and_append_log(f"[OK] {name} ready")
        except Exception as e:
            _wrap_and_append_log(f"[FAIL] {name}: {e}")
    # Motor driver under /<robot_name>/...
    motor_driver_params = [
        {"robot_name": robot_name},
        {"cmd_vel_topic": f"/{robot_name}/cmd_vel"},
        {"profiles_path": profiles_path},
        {"drive_type": drive_type},
        {"hardware": hardware},
    ]
    if strict_single_pub_override_raw:
        strict_single_pub_override = _parse_bool(
            strict_single_pub_override_raw,
            default=True,
        )
        motor_driver_params.append(
            {"strict_single_cmd_vel_publisher": strict_single_pub_override}
        )
        _wrap_and_append_log(
            f"[MOTOR] strict_single_cmd_vel_publisher override={strict_single_pub_override}"
        )

    _try_node(
        package="swarm_control_core",
        executable="motor_driver_node_com",
        name="motor_driver_node",
        namespace=robot_name,
        output="screen",
        parameters=motor_driver_params,
    )

    # Heartbeat publisher under /<robot_name>/heartbeat so teleop/control can discover
    _try_node(
        package="swarm_control_core",
        executable="heartbeat_node_com",
        name="heartbeat_node",
        namespace=robot_name,
        output="screen",
        parameters=[
            {"robot_name": robot_name},
            {"profiles_path": profiles_path},
            {"drive_type": drive_type},
            {"hardware": hardware},
        ],
    )

    # Playbook action executor under /<robot_name>/execute_playbook
    _try_node(
        package="swarm_control_core",
        executable="unit_executor_action_server_com",
        name="unit_executor_action_server",
        namespace=robot_name,
        output="screen",
        parameters=[
            {"robot_name": robot_name},
            {"profiles_path": profiles_path},
        ],
    )

    # Camera publisher under /<robot_name>/camera/image_raw.
    # Community package supports adapter pipeline only.
    if use_camera:
        if camera_pipeline and camera_pipeline != "adapter":
            _wrap_and_append_log(
                f"[CAM] camera_pipeline='{camera_pipeline}' unsupported; forcing adapter"
            )
        if camera_allow_env_overrides:
            _wrap_and_append_log("[CAM] env overrides enabled")
        elif ignored_camera_env_vars:
            _wrap_and_append_log(f"[CAM] ignoring env vars: {', '.join(ignored_camera_env_vars)}")
            _wrap_and_append_log(
                "[CAM] set camera_allow_env_overrides:=true to enable CAMERA_* values"
            )
        _wrap_and_append_log(f"[CAM] low_latency={camera_low_latency_mode}")
        if camera_clamp_notes:
            src_w, src_h, src_fps, src_fourcc = original_camera_shape
            _wrap_and_append_log(
                f"[CAM] low-latency clamp {','.join(camera_clamp_notes)}: "
                f"{src_w}x{src_h} {src_fps}fps {src_fourcc} -> "
                f"{camera_width}x{camera_height} {camera_fps}fps {camera_fourcc}"
            )
        _wrap_and_append_log(f"[CAM] profile={camera_profile_name}")
        _wrap_and_append_log(
            f"[CAM] {video_device} {camera_width}x{camera_height} "
            f"{camera_fps}fps {camera_fourcc} v4l2={camera_force_v4l2}"
        )
        _try_node(
            package="swarm_control_core",
            executable="swarm_camera_node_com",
            name="camera",
            namespace=robot_name,
            output="screen",
            parameters=[
                {"robot_name": robot_name},
                {"device": video_device},
                {"camera_source": camera_source},
                {"frame_rate": camera_fps},
                {"width": camera_width},
                {"height": camera_height},
                {"fourcc": camera_fourcc},
                {"force_v4l2": camera_force_v4l2},
            ],
        )

    # Optional camera-driven autonomy node:
    # - modes: manual/follow/patrol/detect on /<robot>/autonomy/mode
    # - publishes status on /<robot>/autonomy/status
    if use_camera_autonomy:
        _try_node(
            package="swarm_control_core",
            executable="camera_autonomy_node_com",
            name="camera_autonomy_node",
            namespace=robot_name,
            output="screen",
            parameters=[
                {"robot_name": robot_name},
                {"profiles_path": profiles_path},
            ],
        )

    return nodes


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "ros_domain_id",
                default_value=_default_ros_domain_id(),
                description="ROS 2 domain ID for community stack (default: 17).",
            ),
            DeclareLaunchArgument(
                "robot_name",
                default_value="",
                description=(
                    "Robot identity used for namespace and profile lookup. "
                    "Set explicitly or via SWARM_COM_ROBOT_NAME/ROBOT_NAME."
                ),
            ),
            DeclareLaunchArgument("video_device", default_value=""),
            DeclareLaunchArgument(
                "camera_device",
                default_value="",
                description="Compatibility alias for video_device (optional).",
            ),
            DeclareLaunchArgument(
                "camera_profiles_path",
                default_value="",
                description=(
                    "Path to camera_profiles.yaml. "
                    "Required when use_camera:=true unless CAMERA_PROFILES_PATH is set."
                ),
            ),
            DeclareLaunchArgument(
                "camera_profile_name",
                default_value="",
                description="Camera profile key; defaults to robot_name.",
            ),
            DeclareLaunchArgument(
                "camera_pipeline",
                default_value="adapter",
                description="Camera pipeline selector (adapter only).",
            ),
            DeclareLaunchArgument(
                "camera_allow_env_overrides",
                default_value="false",
                description="When true, CAMERA_* environment variables may override camera profile values.",
            ),
            DeclareLaunchArgument(
                "camera_low_latency_mode",
                default_value="true",
                description=(
                    "When true, USB camera profile values are clamped to low-latency defaults "
                    "(640x480@15 MJPG) unless explicitly overridden by camera_* launch/env values."
                ),
            ),
            DeclareLaunchArgument("camera_fps", default_value=""),
            DeclareLaunchArgument("camera_width", default_value=""),
            DeclareLaunchArgument("camera_height", default_value=""),
            DeclareLaunchArgument("camera_fourcc", default_value=""),
            DeclareLaunchArgument(
                "camera_force_v4l2",
                default_value="",
                description="When true, adapter prefers V4L2-only open strategies (auto when empty).",
            ),
            DeclareLaunchArgument("use_camera", default_value="true"),
            DeclareLaunchArgument(
                "use_camera_autonomy",
                default_value="false",
                description="Start camera_autonomy_node (follow/patrol/detect/manual).",
            ),
            DeclareLaunchArgument(
                "drive_type",
                default_value="diff_drive",
                description="Robot drive type: 'diff_drive' for differential drive, 'mecanum' for omnidirectional",
            ),
            DeclareLaunchArgument(
                "hardware",
                default_value="L298N_diff",
                description="Motor driver hardware profile: 'L298N_diff', 'dual_tb6612_mecanum', etc.",
            ),
            DeclareLaunchArgument(
                "profiles_path",
                default_value="",
                description=(
                    "Path to robot_instances.yaml (or legacy robot_profiles.yaml). "
                    "Set explicitly or via PROFILES_PATH."
                ),
            ),
            DeclareLaunchArgument(
                "strict_single_cmd_vel_publisher",
                default_value="",
                description=(
                    "Optional motor-driver strict cmd_vel publisher gate override "
                    "(true|false). Leave empty to use profile value."
                ),
            ),
            SetEnvironmentVariable(name="ROS_DOMAIN_ID", value=LaunchConfiguration("ros_domain_id")),
            OpaqueFunction(function=_make_nodes),
        ]
    )
