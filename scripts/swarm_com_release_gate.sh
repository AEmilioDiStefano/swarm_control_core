#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
failures=0

check_missing_file() {
  local rel="$1"
  if [[ -e "$ROOT/$rel" ]]; then
    echo "[swarm_com_release_gate] FAIL: disallowed file exists '$rel'"
    failures=$((failures + 1))
  else
    echo "[swarm_com_release_gate] PASS: disallowed file missing '$rel'"
  fi
}

check_present() {
  local pattern="$1"
  local file="$2"
  if rg -n "$pattern" "$file" >/dev/null 2>&1; then
    echo "[swarm_com_release_gate] PASS: '$pattern' present in $(basename "$file")"
  else
    echo "[swarm_com_release_gate] FAIL: '$pattern' missing in $(basename "$file")"
    failures=$((failures + 1))
  fi
}

check_missing_file "scripts/swarm_turn_setup_host.sh"
check_missing_file "scripts/swarm_turn_onboard.sh"
check_missing_file "scripts/swarm_install_caddy_if_missing.sh"
check_missing_file "scripts/swarm_prepare_fpv_ingress.sh"
check_missing_file "swarm_control_core/control_lock_manager.py"
check_missing_file "swarm_control_core/fleet_conformance.py"
check_missing_file "swarm_control_core/fpv_camera_mux.py"
check_missing_file "swarm_control_core/fpv_control_arbiter.py"
check_missing_file "swarm_control_core/network_profiles.py"
check_missing_file "swarm_control_core/save_network_profile.py"
check_missing_file "swarm_control_core/save_robot_profile.py"
check_missing_file "swarm_control_core/usb_camera_node.py"
check_missing_file "swarm_control_core/swarm_camera_legacy_node.py"
check_missing_file "swarm_control_core/legacy_usb_camera_node.py"
check_missing_file "config/network_profiles.yaml"

check_present "SWARM_COM_ALLOW_LAN_BIND" "$ROOT/swarm_control_core/swarm_fpv_ui.py"
check_present "auth_mode = AUTH_MODE_OFF" "$ROOT/swarm_control_core/swarm_fpv_ui.py"
check_present "from aiortc import RTCConfiguration" "$ROOT/swarm_control_core/swarm_fpv_ui.py"
check_present "HAS_WEBRTC = len\\(_MISSING_WEBRTC_DEPS\\) == 0" "$ROOT/swarm_control_core/swarm_fpv_ui.py"
if rg -n "camera_adapter_node_com|swarm_camera_legacy_node_com" "$ROOT/setup.py" >/dev/null 2>&1; then
  echo "[swarm_com_release_gate] FAIL: legacy/standalone camera entry points should not exist."
  failures=$((failures + 1))
else
  echo "[swarm_com_release_gate] PASS: no legacy/standalone camera entry points."
fi
check_present "web\\.post\\(\"/webrtc/offer\"" "$ROOT/swarm_control_core/swarm_fpv_ui.py"

if [[ $failures -gt 0 ]]; then
  echo "[swarm_com_release_gate] FAILED ($failures checks)."
  exit 1
fi

echo "[swarm_com_release_gate] All checks passed."
