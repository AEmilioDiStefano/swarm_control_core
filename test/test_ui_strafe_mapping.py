from pathlib import Path


UI_PATH = Path(__file__).resolve().parents[1] / "swarm_control_core" / "swarm_fpv_ui.py"


def test_mecanum_strafe_mapping_matches_ui_labels():
    text = UI_PATH.read_text(encoding="utf-8")

    assert """if (token === "arrow_left"){
    if (strafeMode && c.can_strafe) return { lin: 0.0, yaw: 0.0, lat: -S, vert: 0.0 };""" in text
    assert """if (token === "arrow_right"){
    if (strafeMode && c.can_strafe) return { lin: 0.0, yaw: 0.0, lat: +S, vert: 0.0 };""" in text

    assert """if (token === "4"){
    if (strafeMode && c.can_strafe) return { lin: 0.0, yaw: 0.0, lat: -S, vert: 0.0 };""" in text
    assert """if (token === "6"){
    if (strafeMode && c.can_strafe) return { lin: 0.0, yaw: 0.0, lat: +S, vert: 0.0 };""" in text

    assert 'if (token === "7") return { lin: +S, yaw: 0.0, lat: -S, vert: 0.0 };' in text
    assert 'if (token === "9") return { lin: +S, yaw: 0.0, lat: +S, vert: 0.0 };' in text
    assert 'if (token === "1") return { lin: -S, yaw: 0.0, lat: -S, vert: 0.0 };' in text
    assert 'if (token === "3") return { lin: -S, yaw: 0.0, lat: +S, vert: 0.0 };' in text
