from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = CORE_ROOT / "swarm_control_core" / "swarm_fpv_ui.py"


def _section(text: str, start: str, end: str) -> str:
    start_idx = text.index(start)
    end_idx = text.index(end, start_idx)
    return text[start_idx:end_idx]


def test_fleet_camera_visibility_uses_live_presence_not_discovery_hold():
    text = UI_PATH.read_text(encoding="utf-8")
    body = _section(text, "    def visible_robots", "    def _robot_recently_alive")

    assert "_robot_recently_alive(robot, t_now)" in body
    assert "_discovery_stale_hold_s" not in body


def test_discovery_does_not_keep_stale_robots_after_clean_empty_scan():
    text = UI_PATH.read_text(encoding="utf-8")
    body = _section(text, "    def _refresh_discovery", "    def list_robots")

    assert "elif not scan_ok:" in body
    assert "elif self._known_robots and (t_now - self._discovery_last_nonempty_s)" not in body


def test_topic_discovery_only_bootstraps_on_publisher_appearance():
    text = UI_PATH.read_text(encoding="utf-8")
    body = _section(text, "    def _refresh_discovery", "    def list_robots")

    assert "self._active_topic_robots: Set[str] = set()" in text
    assert "if robot not in self._active_topic_robots:" in body
    assert "self._active_topic_robots = set(robots)" in body


def test_active_robot_choice_does_not_pin_stale_unavailable_robot():
    text = UI_PATH.read_text(encoding="utf-8")
    body = _section(text, "function reconcileActiveRobotChoice", "function _toBool")

    assert "normalizeRobotChoice(currentRobot, available)" in body
    assert "if (pinned) return pinned;" not in body


def test_thumbnail_previews_are_downscaled_and_have_minimal_safety_floor():
    text = UI_PATH.read_text(encoding="utf-8")
    refresh_body = _section(text, "function refreshThumbImage", "function renderCapabilityMeta")
    sync_body = _section(text, "    def _sync_image_subscriptions", "    def _update_rate_ema")
    drop_body = _section(text, "    def _drop_image_subscription", "    def _sync_image_subscriptions")
    thumbs_body = _section(text, "function refreshThumbs", "function startHeartbeat")

    assert "max_w=${THUMB_JPEG_MAX_W}" in refresh_body
    assert "max_h=${THUMB_JPEG_MAX_H}" in refresh_body
    assert "quality=${THUMB_JPEG_QUALITY}" in refresh_body
    assert "thumbRobotsPerTick" in thumbs_body
    assert "limit = configuredLimit <= 0 ? 1 : configuredLimit" in thumbs_body
    assert "thumbNeedsRefresh(img, staleMs)" in thumbs_body
    assert "_latest_jpeg.pop" not in drop_body
    assert "_img_last_frame_s.pop" not in drop_body
    assert "recent_frame" not in sync_body


def test_fleet_preview_preset_is_exposed_to_client_scheduler():
    text = UI_PATH.read_text(encoding="utf-8")

    assert 'self.declare_parameter("fleet_preview_preset", "scalable_fleet")' in text
    assert "self.fleet_preview_preset = _normalize_fleet_preview_preset" in text
    assert '"fleet_preview_preset": str(self.hub.fleet_preview_preset)' in text
    assert "fleetPreviewPreset = normalizeFleetPreviewPreset" in text
