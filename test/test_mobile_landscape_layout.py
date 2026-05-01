from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = CORE_ROOT / "swarm_control_core" / "swarm_fpv_ui.py"


def test_mobile_landscape_layout_prioritizes_center_video_and_right_controls():
    text = UI_PATH.read_text(encoding="utf-8")

    assert "@media (orientation: landscape) and (max-width: 1180px) and (pointer: coarse)" in text
    assert '"fleet video modes"' in text
    assert '"fleet video drive"' in text
    assert ".hero{" in text
    assert "grid-area:video;" in text
    assert ".modebar{" in text
    assert "grid-area:modes;" in text
    assert ".controls{" in text
    assert "grid-area:drive;" in text


def test_mobile_landscape_avoids_horizontal_scrolling_and_uses_finger_sized_buttons():
    text = UI_PATH.read_text(encoding="utf-8")

    assert "html,body{max-width:100%;overflow-x:hidden}" in text
    assert "overscroll-behavior-x:none" in text
    assert "--touch-side:clamp(116px,20vw,184px)" in text
    assert "min-height:44px" in text
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in text


def test_desktop_layout_has_right_control_sidebar_matching_fleet_column():
    text = UI_PATH.read_text(encoding="utf-8")

    assert "--fleet-col:clamp(190px,18vw,300px)" in text
    assert "--control-col:clamp(220px,20vw,300px)" in text
    assert "grid-template-columns:var(--fleet-col) minmax(0,1fr) var(--control-col)" in text
    assert 'grid-template-areas:"fleet video controls"' in text
    assert '<aside class="panel fleet-panel">' in text
    assert '<section class="panel video-panel">' in text
    assert '<aside class="panel control-sidebar">' in text
    assert '<div class="modebar" id="modeControls"></div>' in text
    assert '<div class="controls" id="driveControls"></div>' in text
    assert '<div class="meta" id="capMeta"></div>' in text
    assert ".control-sidebar .controls" in text
    assert "margin-top:auto" in text
    assert "margin-bottom:24px" in text
    assert ".control-sidebar .controls + .meta" in text
    assert '<div class="profile-label">PROFILES</div>' in text


def test_bottom_robot_cards_stack_and_do_not_trigger_touch_layout_on_desktop():
    text = UI_PATH.read_text(encoding="utf-8")

    assert ".health{" in text
    assert "grid-template-columns:1fr;" in text
    assert "@media (max-width: 900px)" in text
    assert "@media (max-width: 1100px)" not in text


def test_fleet_thumbnails_keep_cached_previews_when_rail_rerenders():
    text = UI_PATH.read_text(encoding="utf-8")

    assert "const thumbImageCache = new Map();" in text
    assert "const cachedThumb = thumbImageCache.get(robot) || {};" in text
    assert "img.src = cachedThumb.src || NO_SIGNAL_IMG;" in text
    assert "thumbImageCache.set(robot, { src: next.src, lastFrameMs: loadedAtMs });" in text


def test_active_robot_thumbnail_mirrors_main_webrtc_stream_instead_of_refetching():
    text = UI_PATH.read_text(encoding="utf-8")

    assert 'live.className = "thumb-live";' in text
    assert "const stream = main && main.srcObject ? main.srcObject : null;" in text
    assert "live.srcObject = stream" in text
    assert "syncActiveThumbVideo();" in text

    refresh_start = text.index("function refreshThumbs")
    refresh_end = text.index("function startHeartbeat", refresh_start)
    refresh_body = text[refresh_start:refresh_end]

    assert "if (robot === activeRobot){" in refresh_body
    assert "continue;" in refresh_body
    assert "refreshThumbImage(pool[idx].img, pool[idx].robot);" in refresh_body
    assert "const activeTiles" not in refresh_body


def test_thumbnail_scheduler_uses_scalable_preview_policy():
    text = UI_PATH.read_text(encoding="utf-8")
    refresh_start = text.index("function refreshThumbs")
    refresh_end = text.index("function startHeartbeat", refresh_start)
    refresh_body = text[refresh_start:refresh_end]

    assert "const THUMB_PREVIEW_PRESETS = {" in text
    assert "scalable_fleet:" in text
    assert "small_lab_live:" in text
    assert "operator_focus:" in text
    assert "single_robot_focus:" in text
    assert "isThumbTileVisible(tile)" in refresh_body
    assert "thumbRowBucket(a) - thumbRowBucket(b)" in refresh_body
    assert "policy.driveBudget" in refresh_body
    assert "thumbRowStaleMs(row)" in refresh_body


def test_stream_switch_uses_handoff_image_until_first_webrtc_frame():
    text = UI_PATH.read_text(encoding="utf-8")

    assert "function showMainHandoff(robot)" in text
    assert "function hideMainHandoffAfterFirstFrame(videoEl, expectedRobot=\"\")" in text
    assert "requestVideoFrameCallback" in text
    assert "showMainHandoff(robot);" in text
    assert "closePeerConnection(null, { clearMain: false });" in text
    assert "hideMainHandoffAfterFirstFrame(main, requestedRobot);" in text
