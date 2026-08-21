import os
import subprocess
from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
RUN_LOCAL_UI = CORE_ROOT / "scripts" / "swarm_core_run_local_ui.sh"
FREE_UI_PORT = CORE_ROOT / "scripts" / "swarm_core_free_ui_port.sh"


def test_local_ui_defaults_to_no_port_reclamation():
    text = RUN_LOCAL_UI.read_text(encoding="utf-8")

    assert 'RECLAIM_BIND_PORT="${SWARM_CORE_RECLAIM_BIND_PORT:-0}"' in text
    assert 'if [[ "$RECLAIM_BIND_PORT" == "1" ]]' in text
    assert '"${SCRIPT_DIR}/swarm_core_free_ui_port.sh" --host "$BIND_HOST" --port "$BIND_PORT" --no-reclaim' in text


def test_no_reclaim_mode_stops_before_terminating_a_listener(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ss = fake_bin / "ss"
    fake_ss.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' 'State Recv-Q Send-Q Local Address:Port Peer Address:Port'\n"
        "printf '%s\\n' 'LISTEN 0 128 127.0.0.1:8080 0.0.0.0:*'\n",
        encoding="utf-8",
    )
    fake_ss.chmod(0o755)

    result = subprocess.run(
        [
            str(FREE_UI_PORT),
            "--host",
            "127.0.0.1",
            "--port",
            "8080",
            "--no-reclaim",
        ],
        cwd=CORE_ROOT,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert "reclaim is disabled" in result.stderr
    assert "Reclaiming" not in result.stderr
    assert "Terminated" not in result.stderr
