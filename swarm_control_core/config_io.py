"""Serialized, atomic writes for runtime config files.

Every mutation of a file under the runtime config directory serializes on a
per-directory advisory lock and lands via tmp-file + os.replace, so a crash
or a concurrent writer can never truncate a file or interleave a write.
Lock files and temp files are owner-only: runtime config holds SSH targets
and profile data that must not be world-readable.
"""

from __future__ import annotations

import fcntl
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Union

LOCK_BASENAME = ".swarm_config.lock"
DEFAULT_LOCK_TIMEOUT_S = 30.0

PathLike = Union[str, Path]


class ConfigLockTimeout(RuntimeError):
    """Raised when the runtime-config lock cannot be acquired in time."""


@contextmanager
def locked_config(path: PathLike, timeout_s: float = DEFAULT_LOCK_TIMEOUT_S) -> Iterator[None]:
    """Hold the advisory lock for the config directory containing ``path``.

    One lock per directory keeps lock ordering trivial: no tool ever holds
    two config locks at once, so deadlock is structurally impossible.
    """
    target = Path(path).expanduser()
    config_dir = target.parent
    config_dir.mkdir(parents=True, exist_ok=True)
    lock_path = config_dir / LOCK_BASENAME
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ConfigLockTimeout(
                        f"Another swarm command is updating {config_dir} "
                        f"(lock: {lock_path}). Wait for it to finish and retry."
                    ) from None
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def atomic_write_text(path: PathLike, text: str, mode: int = 0o600) -> None:
    """Write ``text`` to ``path`` atomically with owner-only permissions.

    The temp file is created in the destination directory (same filesystem,
    so os.replace is atomic), fsynced, then renamed over the target. Readers
    always see either the old complete file or the new complete file.
    """
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    dir_fd = None
    try:
        dir_fd = os.open(str(target.parent), os.O_RDONLY)
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        if dir_fd is not None:
            os.close(dir_fd)
