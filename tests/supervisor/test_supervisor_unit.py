# AI_HEADER: tests for supervisor — SourceRouter, MtimeWatcher, PidRegistry
# Pure unit tests; no subprocesses, no DB, no FastAPI.
import json
from pathlib import Path

from grace_control.supervisor import (
    MtimeWatcher,
    PidRegistry,
    SourceRouter,
)


class TestSourceRouter:
    def setup_method(self) -> None:
        self.router = SourceRouter()

    def test_api_change_routes_to_api(self) -> None:
        assert self.router.collect(["api/routers/packets.py"]) == "api"
        assert self.router.classify("api/main.py") == "api"

    def test_core_change_routes_to_workers(self) -> None:
        assert self.router.collect(["core/git_context.py"]) == "workers"
        assert self.router.classify("adapters/foo.py") == "workers"
        assert self.router.classify("services/packet_service.py") == "workers"

    def test_supervisor_self_change_routes_to_all(self) -> None:
        assert self.router.collect(["supervisor.py"]) == "all"
        assert self.router.classify("supervisor_client.py") == "all"
        assert self.router.classify("supervisor/foo.py") == "all"

    def test_mixed_api_and_worker_routes_to_all(self) -> None:
        # Mixed (api + workers) means restart everything to avoid state drift.
        assert self.router.collect(["api/main.py", "core/foo.py"]) == "all"

    def test_unknown_paths_are_ignored(self) -> None:
        assert self.router.classify("README.md") == "ignore"
        assert self.router.classify("docs/notes.md") == "ignore"
        assert self.router.classify("tests/test_foo.py") == "ignore"
        assert self.router.collect(["README.md", "tests/test_foo.py"]) == "ignore"

    def test_empty_input_is_ignored(self) -> None:
        assert self.router.collect([]) == "ignore"


class TestMtimeWatcher:
    def test_scan_finds_python_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.py").write_text("y = 2")
        w = MtimeWatcher(tmp_path)
        snap = w.scan()
        assert "a.py" in snap
        assert str(Path("sub/b.py")) in snap

    def test_scan_ignores_pycache(self, tmp_path: Path) -> None:
        (tmp_path / "ok.py").write_text("x = 1")
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "junk.py").write_text("should be ignored")
        w = MtimeWatcher(tmp_path)
        snap = w.scan()
        assert "ok.py" in snap
        assert all("__pycache__" not in p for p in snap)

    def test_diff_detects_changes(self, tmp_path: Path) -> None:
        f = tmp_path / "a.py"
        f.write_text("v1")
        w = MtimeWatcher(tmp_path)
        w.prime()
        f.write_text("v2")
        # Force a different mtime even on filesystems with low resolution
        import os
        new_mtime = os.stat(f).st_mtime + 2.0
        os.utime(f, (new_mtime, new_mtime))
        changed = w.diff()
        assert "a.py" in changed

    def test_diff_detects_deletions(self, tmp_path: Path) -> None:
        f = tmp_path / "a.py"
        f.write_text("x = 1")
        w = MtimeWatcher(tmp_path)
        w.prime()
        f.unlink()
        changed = w.diff()
        assert "a.py" in changed


class TestPidRegistry:
    def test_load_when_missing(self, tmp_path: Path) -> None:
        r = PidRegistry(tmp_path)
        assert r.load() == {"version": PidRegistry.VERSION, "api": None, "workers": []}

    def test_save_and_load(self, tmp_path: Path) -> None:
        r = PidRegistry(tmp_path)
        from grace_control.supervisor import ChildRecord
        api = ChildRecord(role="api", pid=42, started_at=1.0, argv=["python"])
        worker = ChildRecord(role="worker", pid=43, started_at=1.5, argv=["python", "worker.py"])
        r.save(api, [worker])
        loaded = r.load()
        assert loaded["api"]["pid"] == 42
        assert len(loaded["workers"]) == 1
        assert loaded["workers"][0]["pid"] == 43

    def test_save_atomic(self, tmp_path: Path) -> None:
        """save() must not leave a half-written file behind."""
        r = PidRegistry(tmp_path)
        from grace_control.supervisor import ChildRecord
        api = ChildRecord(role="api", pid=99, started_at=2.0, argv=["x"])
        r.save(api, [])
        # No .tmp leftover
        leftover = list(tmp_path.glob("supervisor.json.tmp"))
        assert leftover == []
        # File is valid JSON
        assert json.loads((tmp_path / "supervisor.json").read_text())["api"]["pid"] == 99
