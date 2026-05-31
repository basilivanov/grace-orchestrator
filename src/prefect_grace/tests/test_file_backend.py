"""
Tests for storage.file_backend module.

Tests concurrent access, corruption recovery, atomic writes, and error handling.
"""

import multiprocessing
import shutil
import time
from pathlib import Path

import pytest
import yaml

from prefect_grace.storage.file_backend import (
    read_yaml,
    write_yaml,
    locked_update_yaml,
)


def test_read_yaml_nonexistent_file(tmp_path):
    """Test reading a file that doesn't exist returns empty dict."""
    result = read_yaml(tmp_path / "nonexistent.yaml")
    assert result == {}


def test_read_yaml_existing_file(tmp_path):
    """Test reading an existing YAML file."""
    test_file = tmp_path / "test.yaml"
    test_data = {"key": "value", "count": 42}
    test_file.write_text(yaml.safe_dump(test_data), encoding="utf-8")

    result = read_yaml(test_file)
    assert result == test_data


def test_write_yaml_creates_file(tmp_path):
    """Test writing creates a new file."""
    test_file = tmp_path / "test.yaml"
    test_data = {"key": "value", "count": 42}

    write_yaml(test_file, test_data)

    assert test_file.exists()
    loaded = yaml.safe_load(test_file.read_text(encoding="utf-8"))
    assert loaded == test_data


def test_write_yaml_creates_backup(tmp_path):
    """Test writing creates a backup of existing file."""
    test_file = tmp_path / "test.yaml"
    original_data = {"original": "data"}
    new_data = {"new": "data"}

    # Write original
    write_yaml(test_file, original_data, create_backup=False)

    # Write new with backup
    write_yaml(test_file, new_data, create_backup=True)

    # Check backup exists with original data
    backup_file = test_file.with_suffix(test_file.suffix + ".backup")
    assert backup_file.exists()
    backup_data = yaml.safe_load(backup_file.read_text(encoding="utf-8"))
    assert backup_data == original_data

    # Check main file has new data
    main_data = yaml.safe_load(test_file.read_text(encoding="utf-8"))
    assert main_data == new_data


def test_locked_update_yaml_creates_file(tmp_path):
    """Test locked update creates file if it doesn't exist."""
    test_file = tmp_path / "test.yaml"

    def mutator(data):
        data["counter"] = 1
        return data

    result = locked_update_yaml(test_file, mutator)

    assert test_file.exists()
    assert result == {"counter": 1}


def test_locked_update_yaml_updates_existing(tmp_path):
    """Test locked update modifies existing file."""
    test_file = tmp_path / "test.yaml"
    initial_data = {"counter": 0, "name": "test"}
    write_yaml(test_file, initial_data, create_backup=False)

    def mutator(data):
        data["counter"] = data.get("counter", 0) + 1
        return data

    result = locked_update_yaml(test_file, mutator)

    assert result == {"counter": 1, "name": "test"}
    loaded = read_yaml(test_file)
    assert loaded == {"counter": 1, "name": "test"}


def _concurrent_increment_worker(file_path, worker_id, increments):
    """Worker function for concurrent increment test."""
    for i in range(increments):
        def mutator(data):
            # Increment global counter
            data["global_counter"] = data.get("global_counter", 0) + 1
            # Increment worker-specific counter
            worker_key = f"worker_{worker_id}"
            data[worker_key] = data.get(worker_key, 0) + 1
            return data

        locked_update_yaml(file_path, mutator)


def test_concurrent_writes_no_lost_updates(tmp_path):
    """
    Test that concurrent writes don't lose updates.

    4 workers × 25 increments = 100 total increments expected.
    """
    test_file = tmp_path / "concurrent.yaml"
    write_yaml(test_file, {"global_counter": 0}, create_backup=False)

    num_workers = 4
    increments_per_worker = 25

    # Spawn worker processes
    processes = []
    for worker_id in range(num_workers):
        p = multiprocessing.Process(
            target=_concurrent_increment_worker,
            args=(test_file, worker_id, increments_per_worker)
        )
        p.start()
        processes.append(p)

    # Wait for all workers to complete
    for p in processes:
        p.join()

    # Verify results
    result = read_yaml(test_file)
    assert result["global_counter"] == num_workers * increments_per_worker

    # Verify each worker's counter
    for worker_id in range(num_workers):
        worker_key = f"worker_{worker_id}"
        assert result[worker_key] == increments_per_worker


def test_corruption_recovery(tmp_path):
    """Test recovery from corrupted file using backup."""
    test_file = tmp_path / "test.yaml"
    backup_file = test_file.with_suffix(test_file.suffix + ".backup")

    # Write valid data to both main and backup
    valid_data = {"key": "value", "count": 42}
    write_yaml(test_file, valid_data, create_backup=False)
    write_yaml(backup_file, valid_data, create_backup=False)

    # Corrupt main file only
    test_file.write_text("invalid: yaml: content: [[[", encoding="utf-8")

    # Reading should recover from backup
    result = read_yaml(test_file)
    assert result == valid_data

    # Main file should be restored
    restored = yaml.safe_load(test_file.read_text(encoding="utf-8"))
    assert restored == valid_data


def test_corruption_without_backup_raises_error(tmp_path):
    """Test that corrupted file without backup raises ValueError."""
    test_file = tmp_path / "test.yaml"

    # Write corrupted data
    test_file.write_text("invalid: yaml: content: [[[", encoding="utf-8")

    # Should raise ValueError
    with pytest.raises(ValueError, match="Corrupted YAML file"):
        read_yaml(test_file)


def test_atomic_write_cleanup_on_error(tmp_path):
    """Test that temp files are cleaned up on write errors."""
    test_file = tmp_path / "test.yaml"

    # Make directory read-only to cause write error
    tmp_path.chmod(0o555)

    try:
        with pytest.raises(Exception):
            write_yaml(test_file, {"key": "value"})

        # Check no temp files left behind
        temp_files = list(tmp_path.glob(".test.yaml.*.tmp"))
        assert len(temp_files) == 0
    finally:
        # Restore permissions for cleanup
        tmp_path.chmod(0o755)


def test_locked_update_with_exception_in_mutator(tmp_path):
    """Test that exceptions in mutator are propagated."""
    test_file = tmp_path / "test.yaml"
    write_yaml(test_file, {"counter": 0}, create_backup=False)

    def failing_mutator(data):
        raise ValueError("Mutator failed")

    with pytest.raises(ValueError, match="Mutator failed"):
        locked_update_yaml(test_file, failing_mutator)

    # File should remain unchanged
    result = read_yaml(test_file)
    assert result == {"counter": 0}


def test_locked_update_creates_backup(tmp_path):
    """Test that locked_update creates backup before modifying."""
    test_file = tmp_path / "test.yaml"
    backup_file = test_file.with_suffix(test_file.suffix + ".backup")

    initial_data = {"counter": 0}
    write_yaml(test_file, initial_data, create_backup=False)

    def mutator(data):
        data["counter"] = 1
        return data

    locked_update_yaml(test_file, mutator)

    # Backup should exist with original data
    assert backup_file.exists()
    backup_data = yaml.safe_load(backup_file.read_text(encoding="utf-8"))
    assert backup_data == initial_data


def test_list_data_format(tmp_path):
    """Test that file_backend handles list data format (for ExecutorHistoryStore)."""
    test_file = tmp_path / "history.yaml"

    # Write list data
    list_data = [{"id": 1}, {"id": 2}]
    write_yaml(test_file, list_data, create_backup=False)

    # Read should return list
    result = read_yaml(test_file)
    assert result == list_data

    # Locked update with list
    def mutator(data):
        if isinstance(data, dict):
            data = []
        data.append({"id": 3})
        return data

    result = locked_update_yaml(test_file, mutator)
    assert len(result) == 3
    assert result[-1] == {"id": 3}


def test_nested_directory_creation(tmp_path):
    """Test that nested directories are created automatically."""
    test_file = tmp_path / "level1" / "level2" / "level3" / "test.yaml"
    test_data = {"key": "value"}

    write_yaml(test_file, test_data)

    assert test_file.exists()
    loaded = read_yaml(test_file)
    assert loaded == test_data


def test_unicode_handling(tmp_path):
    """Test that Unicode characters are handled correctly."""
    test_file = tmp_path / "unicode.yaml"
    test_data = {
        "english": "Hello",
        "russian": "Привет",
        "chinese": "你好",
        "emoji": "🚀🎉",
    }

    write_yaml(test_file, test_data)
    result = read_yaml(test_file)

    assert result == test_data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
