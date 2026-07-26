import multiprocessing
import stat
from pathlib import Path

import pytest
import yaml

from swarm_control_core.config_io import (
    ConfigLockTimeout,
    atomic_write_text,
    locked_config,
)


def _locked_increment(args):
    path_str, key = args
    path = Path(path_str)
    with locked_config(path):
        data = yaml.safe_load(path.read_text()) if path.exists() else {}
        data = data or {}
        data[key] = True
        atomic_write_text(path, yaml.safe_dump(data))
    return key


def test_parallel_locked_writers_lose_no_updates(tmp_path):
    target = tmp_path / "robot_instances.yaml"
    keys = [f"robot{i}" for i in range(24)]
    with multiprocessing.Pool(8) as pool:
        pool.map(_locked_increment, [(str(target), key) for key in keys])

    data = yaml.safe_load(target.read_text())
    assert sorted(data) == sorted(keys)


def test_atomic_write_keeps_original_on_failure(tmp_path):
    target = tmp_path / "config.yaml"
    atomic_write_text(target, "robots: {legion1: {}}\n")

    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with locked_config(target):
            raise Boom()

    assert target.read_text() == "robots: {legion1: {}}\n"
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_atomic_write_sets_owner_only_permissions(tmp_path):
    target = tmp_path / "camera_profiles.yaml"
    atomic_write_text(target, "profiles: {}\n")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600

    with locked_config(target):
        pass
    lock_path = tmp_path / ".swarm_config.lock"
    assert lock_path.exists()
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600


def _hold_lock(path_str, hold_event, release_event):
    with locked_config(Path(path_str)):
        hold_event.set()
        release_event.wait(timeout=30)


def test_lock_contention_times_out_with_actionable_error(tmp_path):
    target = tmp_path / "robot_instances.yaml"
    hold_event = multiprocessing.Event()
    release_event = multiprocessing.Event()
    holder = multiprocessing.Process(
        target=_hold_lock, args=(str(target), hold_event, release_event)
    )
    holder.start()
    try:
        assert hold_event.wait(timeout=10)
        with pytest.raises(ConfigLockTimeout, match="Another swarm command"):
            with locked_config(target, timeout_s=0.3):
                pass
    finally:
        release_event.set()
        holder.join(timeout=10)
