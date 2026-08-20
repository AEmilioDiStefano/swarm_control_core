#!/usr/bin/env bash
# shellcheck shell=bash

# Shared ROS 2 discovery policy for every swarm_control_core launch path.
#
# Modes:
#   hybrid    SUBNET multicast plus any configured unicast peers (default)
#   multicast SUBNET multicast only
#   static    multicast-free LOCALHOST discovery plus configured peers
#
# CycloneDDS on ROS 2 Jazzy intentionally ignores ROS_STATIC_PEERS when the
# automatic discovery range is OFF.  LOCALHOST is therefore the correct
# multicast-free setting when static peers are present.

swarm_core_discovery_log() {
  printf '[swarm_core_discovery] %s\n' "$*" >&2
}

swarm_core_discovery_peer_file() {
  local config_dir="${SWARM_CORE_CONFIG_DIR:-${HOME}/.config/swarm_control_core}"
  printf '%s' "${SWARM_CORE_STATIC_PEERS_FILE:-${config_dir}/discovery_peers}"
}

swarm_core_validate_static_peer() {
  local peer="${1:-}"
  [[ -n "$peer" ]] || return 1
  # Accept IPv4, host names, IPv6, scope IDs, and optional ports.
  # Reject shell/XML separators, whitespace, and URI fragments.
  [[ "$peer" =~ ^[[:alnum:]_.:%-]+$ ]]
}

swarm_core_collect_static_peers() {
  local peer_file raw line peer
  local -a peers=()
  local -A seen=()

  peer_file="$(swarm_core_discovery_peer_file)"
  raw="${SWARM_CORE_STATIC_PEERS:-}"
  if [[ -f "$peer_file" ]]; then
    raw+=$'\n'
    raw+="$(sed 's/[[:space:]]*#.*$//' "$peer_file")"
  fi

  while IFS= read -r line; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -n "$line" ]] || continue
    while IFS= read -r peer; do
      peer="${peer#"${peer%%[![:space:]]*}"}"
      peer="${peer%"${peer##*[![:space:]]}"}"
      [[ -n "$peer" ]] || continue
      if ! swarm_core_validate_static_peer "$peer"; then
        swarm_core_discovery_log "ERROR: invalid static peer '${peer}' in ${peer_file}."
        return 1
      fi
      if [[ -z "${seen[$peer]+x}" ]]; then
        seen[$peer]=1
        peers+=("$peer")
      fi
    done < <(printf '%s\n' "$line" | tr ',;' '\n')
  done <<< "$raw"

  local joined=""
  for peer in "${peers[@]}"; do
    if [[ -n "$joined" ]]; then
      joined+=";"
    fi
    joined+="$peer"
  done
  printf '%s' "$joined"
}

swarm_core_add_static_peer() {
  local peer="${1:-}" peer_file peer_dir tmp existing
  if ! swarm_core_validate_static_peer "$peer"; then
    swarm_core_discovery_log "ERROR: refusing invalid static peer '${peer}'."
    return 1
  fi

  peer_file="$(swarm_core_discovery_peer_file)"
  peer_dir="$(dirname "$peer_file")"
  install -d -m 700 "$peer_dir"
  touch "$peer_file"
  chmod 600 "$peer_file"

  if grep -Fvx '#' "$peer_file" 2>/dev/null | sed 's/[[:space:]]*#.*$//' | grep -Fxq "$peer"; then
    return 0
  fi

  tmp="$(mktemp "${peer_file}.tmp.XXXXXX")"
  existing="$(sed 's/[[:space:]]*#.*$//' "$peer_file" | sed '/^[[:space:]]*$/d')"
  if [[ -n "$existing" ]]; then
    printf '%s\n' "$existing" > "$tmp"
  fi
  printf '%s\n' "$peer" >> "$tmp"
  chmod 600 "$tmp"
  mv -f "$tmp" "$peer_file"
  swarm_core_discovery_log "Recorded static peer ${peer} in ${peer_file}."
}

swarm_core_apply_discovery_env() {
  local mode peers requested_rmw
  mode="${SWARM_CORE_DISCOVERY_MODE:-hybrid}"
  mode="$(printf '%s' "$mode" | tr '[:upper:]' '[:lower:]')"
  peers="$(swarm_core_collect_static_peers)" || return 1

  unset ROS_DISCOVERY_SERVER ROS_SUPER_CLIENT ROS_LOCALHOST_ONLY
  if [[ -n "${SWARM_CORE_CYCLONEDDS_URI:-}" ]]; then
    export CYCLONEDDS_URI="$SWARM_CORE_CYCLONEDDS_URI"
  else
    unset CYCLONEDDS_URI
  fi
  requested_rmw="${SWARM_CORE_RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
  if [[ "$requested_rmw" != "rmw_cyclonedds_cpp" ]]; then
    swarm_core_discovery_log "ERROR: Core discovery policy requires rmw_cyclonedds_cpp (got '${requested_rmw}')."
    return 1
  fi
  export RMW_IMPLEMENTATION="rmw_cyclonedds_cpp"

  case "$mode" in
    hybrid)
      export ROS_AUTOMATIC_DISCOVERY_RANGE="SUBNET"
      if [[ -n "$peers" ]]; then
        export ROS_STATIC_PEERS="$peers"
        export SWARM_DISCOVERY_MODE="hybrid"
      else
        unset ROS_STATIC_PEERS
        export SWARM_DISCOVERY_MODE="multicast"
      fi
      ;;
    multicast)
      export ROS_AUTOMATIC_DISCOVERY_RANGE="SUBNET"
      unset ROS_STATIC_PEERS
      export SWARM_DISCOVERY_MODE="multicast"
      ;;
    static)
      if [[ -z "$peers" ]]; then
        swarm_core_discovery_log "ERROR: static mode requires at least one peer in $(swarm_core_discovery_peer_file)."
        return 1
      fi
      export ROS_AUTOMATIC_DISCOVERY_RANGE="LOCALHOST"
      export ROS_STATIC_PEERS="$peers"
      export SWARM_DISCOVERY_MODE="static"
      ;;
    *)
      swarm_core_discovery_log "ERROR: SWARM_CORE_DISCOVERY_MODE must be hybrid, multicast, or static (got '${mode}')."
      return 1
      ;;
  esac
}

swarm_core_stop_ros_daemon() {
  if command -v ros2 >/dev/null 2>&1; then
    ros2 daemon stop >/dev/null 2>&1 || true
  fi
}
