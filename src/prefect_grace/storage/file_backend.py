"""
File-based storage backend with fcntl locking for safe concurrent access.

This module provides atomic file operations with exclusive locking to prevent
race conditions when multiple processes access the same state files.

Key features:
- fcntl-based exclusive locking (POSIX systems)
- Atomic writes via temp file + rename
- Automatic backup creation before writes
- Corruption recovery from backup files
- Proper error propagation (no silent swallowing)
"""

from __future__ import annotations

import fcntl
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

import yaml


def read_yaml(path: Path | str) -> dict[str, Any] | list[dict[str, Any]]:
    """
    Read YAML file without locking (safe for read-only operations).

    Args:
        path: Path to YAML file

    Returns:
        Parsed YAML data (dict or list), or {} if file doesn't exist

    Raises:
        ValueError: If file is corrupted and backup recovery fails
        IOError: If file system errors occur
    """
    path = Path(path)

    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if data is not None else {}
    except yaml.YAMLError as e:
        # Attempt recovery from backup
        backup_path = path.with_suffix(path.suffix + ".backup")
        if backup_path.exists():
            try:
                with open(backup_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    # Restore from backup
                    shutil.copy2(backup_path, path)
                    return data if data is not None else {}
            except yaml.YAMLError:
                pass

        raise ValueError(
            f"Corrupted YAML file at {path} and backup recovery failed: {e}"
        )


def write_yaml(
    path: Path | str,
    data: dict[str, Any] | list[dict[str, Any]],
    create_backup: bool = True
) -> None:
    """
    Atomically write YAML file with optional backup.

    Uses temp file + rename for atomic writes to prevent partial writes
    from corrupting the file if the process is interrupted.

    Args:
        path: Path to YAML file
        data: Data to write
        create_backup: Whether to create .backup file before overwriting

    Raises:
        IOError: If file system errors occur
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Create backup if file exists and backup requested
    if create_backup and path.exists():
        backup_path = path.with_suffix(path.suffix + ".backup")
        shutil.copy2(path, backup_path)

    # Write to temp file first
    fd, temp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp"
    )

    try:
        with open(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False
            )

        # Atomic rename
        Path(temp_path).replace(path)
    except Exception:
        # Clean up temp file on error
        try:
            Path(temp_path).unlink()
        except Exception:
            pass
        raise


def locked_update_yaml(
    path: Path | str,
    mutator: Callable[[dict[str, Any] | list[dict[str, Any]]], dict[str, Any] | list[dict[str, Any]]]
) -> dict[str, Any] | list[dict[str, Any]]:
    """
    Update YAML file with exclusive lock to prevent race conditions.

    This function:
    1. Acquires an exclusive lock on the file
    2. Reads current data
    3. Applies mutator function
    4. Writes updated data atomically
    5. Releases lock

    The mutator function receives the current data and must return the updated data.

    Args:
        path: Path to YAML file
        mutator: Function that takes current data and returns updated data

    Returns:
        Updated data after mutation

    Raises:
        ValueError: If mutator raises an error
        IOError: If file system errors occur

    Example:
        def increment_counter(data):
            data['counter'] = data.get('counter', 0) + 1
            return data

        locked_update_yaml('state.yaml', increment_counter)
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Create file if it doesn't exist (with proper handling for race conditions)
    if not path.exists():
        try:
            # Use 'x' mode to create exclusively (fails if file exists)
            with open(path, "x", encoding="utf-8") as f:
                yaml.safe_dump({}, f)
        except FileExistsError:
            # Another process created it, that's fine
            pass

    # Open file for reading and writing
    with open(path, "r+", encoding="utf-8") as handle:
        try:
            # Acquire exclusive lock (blocks until available)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

            # Read current data
            raw = handle.read()
            payload = yaml.safe_load(raw)
            if payload is None:
                payload = {}

            # Apply mutation
            updated = mutator(payload)

            # Create backup before overwriting
            backup_path = path.with_suffix(path.suffix + ".backup")
            handle.seek(0)
            backup_content = handle.read()
            if backup_content:
                backup_path.write_text(backup_content, encoding="utf-8")

            # Write updated data
            handle.seek(0)
            handle.truncate()
            yaml.safe_dump(
                updated,
                handle,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False
            )
            handle.flush()

            return updated
        finally:
            # Always release lock
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
