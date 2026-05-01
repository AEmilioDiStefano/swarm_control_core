from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = CORE_ROOT / "swarm_control_core" / "swarm_fpv_ui.py"


def test_mobile_landscape_layout_prioritizes_center_video_and_right_controls():
    text = UI_PATH.read_text(encoding="utf-8")

    assert "@media (orientation: landscape) and (max-width: 1180px)" in text
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

    assert 'grid-template-columns: 300px minmax(0,1fr) 300px' in text
    assert 'grid-template-areas:"fleet video controls"' in text
    assert '<aside class="panel fleet-panel">' in text
    assert '<section class="panel video-panel">' in text
    assert '<aside class="panel control-sidebar">' in text
    assert '<div class="modebar" id="modeControls"></div>' in text
    assert '<div class="controls" id="driveControls"></div>' in text
    assert '<div class="meta" id="capMeta"></div>' in text
    assert ".control-sidebar .controls" in text
    assert "align-self:center" in text
