# ############################################################################
# AI_HEADER: test_self_evolution
# ROLE: Unit + integration tests for self-evolution modules.
# ############################################################################

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from grace_control.core.context_collector import (
    CodebaseContext,
    ContextCollector,
    FileContext,
    _analyze_file,
    _extract_exports,
    _extract_module_contract,
    _scan_files,
)
from grace_control.core.self_evolution_guard import (
    GuardCheck,
    GuardResult,
    SelfEvolutionGuard,
)
from grace_control.core.self_reload import GraceSelfReloader, ReloadResult
from grace_control.db.schema import SelfEvolutionSession


class TestFileAnalysis:

    def test_extract_module_contract(self):
        text = """# START_MODULE_CONTRACT
# purpose: Test module.
# inputs: None.
# returns: None.
# side_effects: None.
# END_MODULE_CONTRACT"""
        contract = _extract_module_contract(text)
        assert contract is not None
        assert "purpose: Test module" in contract
        assert "# END_MODULE_CONTRACT" not in contract

    def test_extract_module_contract_missing(self):
        assert _extract_module_contract("no contract here") is None

    def test_extract_exports_functions(self):
        text = """def public_func(): pass\ndef _private_func(): pass\nasync def async_public(): pass"""
        exports = _extract_exports(text)
        assert "public_func" in exports
        assert "_private_func" not in exports
        assert "async_public" in exports

    def test_extract_exports_classes(self):
        text = "class MyService: pass\nclass _Internal: pass"
        exports = _extract_exports(text)
        assert "MyService" in exports
        assert "_Internal" in exports  # classes don't get underscore-filtered

    def test_analyze_file(self):
        content = """# AI_HEADER: test
# START_MODULE_CONTRACT
# purpose: test
# END_MODULE_CONTRACT
# START_MODULE_MAP
# END_MODULE_MAP

def hello():
    return "world"

class Greeter:
    pass
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
            try:
                ctx = _analyze_file(path, path.parent)
                assert ctx.size_lines > 5
                assert ctx.module_contract is not None
                assert "hello" in ctx.exports
                assert "Greeter" in ctx.exports
            finally:
                path.unlink()

    def test_scan_files_directory(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "test_a.py").write_text("# AI_HEADER: a\n# START_MODULE_CONTRACT\n# purpose: a\n# END_MODULE_CONTRACT\n# START_MODULE_MAP\n# END_MODULE_MAP\ndef fn_a(): pass")
            files = _scan_files(root, [d])
            assert len(files) == 1
            assert files[0].exports == ["fn_a"]

    def test_scan_files_nested(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sub = root / "sub"
            sub.mkdir()
            (root / "__init__.py").write_text("def root_init(): pass")
            (sub / "__init__.py").write_text("def sub_init(): pass")
            files = _scan_files(root, [d])
            assert len(files) == 2


class TestContextCollector:

    def test_init(self):
        collector = ContextCollector()
        assert collector._root == Path.cwd()

    def test_init_custom_root(self):
        collector = ContextCollector(project_root=Path("/tmp"))
        assert collector._root == Path("/tmp")

    def test_fallback_analysis(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "src" / "grace_control"
            src.mkdir(parents=True)
            (src / "test.py").write_text("def fn(): pass")
            collector = ContextCollector(project_root=root)
            files = _scan_files(root, ["src/grace_control/"])
            ctx = collector._fallback_analysis("test task", files, ["src/grace_control/"])
            assert ctx.summary.startswith("Fallback analysis")
            assert len(ctx.estimated_scope) >= 1
            assert ctx.complexity_score == 200

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_collect_no_llm(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "src" / "grace_control"
            src.mkdir(parents=True)
            (src / "mod.py").write_text("# AI_HEADER: mod\n# START_MODULE_CONTRACT\n# purpose: m\n# END_MODULE_CONTRACT\n# START_MODULE_MAP\n# END_MODULE_MAP\ndef process(): pass")
            collector = ContextCollector(project_root=root)
            ctx = await collector.collect("add feature", target_scope=["src/grace_control/"], project_root=root)
            assert isinstance(ctx, CodebaseContext)
            assert len(ctx.files) >= 1
            assert len(ctx.estimated_scope) >= 1
            assert "mod.py" in str(ctx.estimated_scope)


class TestSelfEvolutionGuard:

    def test_check_all_pass(self):
        guard = SelfEvolutionGuard()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            content = """# AI_HEADER: test
# START_MODULE_CONTRACT
# purpose: test module.
# inputs: none.
# returns: none.
# side_effects: none.
# emitted_logs: none.
# error_behavior: none.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:
#   - function: test_fn
# END_MODULE_MAP
def test_fn():
    pass
"""
            f.write(content)
            f.flush()
            path = Path(f.name)
            try:
                result = guard.check([path])
                assert result.passed
                assert len(result.checks) == 4
                assert all(c.passed for c in result.checks)
            finally:
                path.unlink()

    def test_missing_canon(self):
        guard = SelfEvolutionGuard()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def fn(): pass\n")
            f.flush()
            path = Path(f.name)
            try:
                result = guard.check([path])
                assert not result.passed
                canon = next(c for c in result.checks if c.name == "canon_compliance")
                assert not canon.passed
            finally:
                path.unlink()

    def test_no_self_loop_blocks_guard_files(self):
        guard = SelfEvolutionGuard()
        fake = Path("context_collector.py")
        result = guard.check([fake])
        assert not result.passed
        loop = next(c for c in result.checks if c.name == "no_self_loop")
        assert not loop.passed
        assert "context_collector.py" in loop.detail

    def test_api_contracts_no_api_files(self):
        guard = SelfEvolutionGuard()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("# AI_HEADER: x\n# START_MODULE_CONTRACT\n# p\n# END_MODULE_CONTRACT\n# START_MODULE_MAP\n# END_MODULE_MAP\ndef fn(): pass")
            f.flush()
            path = Path(f.name)
            try:
                result = guard.check([path])
                api = next(c for c in result.checks if c.name == "api_contracts")
                assert api.passed
            finally:
                path.unlink()

    def test_db_schema_additive_ok(self):
        guard = SelfEvolutionGuard()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("# AI_HEADER: schema\n# START_MODULE_CONTRACT\n# p\n# END_MODULE_CONTRACT\n# START_MODULE_MAP\n# END_MODULE_MAP\nclass NewTable(Base):\n    pass")
            f.flush()
            path = Path(f.name)
            try:
                result = guard.check([path])
                db_check = next(c for c in result.checks if c.name == "db_schema")
                assert db_check.passed
            finally:
                path.unlink()

    def test_db_schema_blocks_drop(self):
        guard = SelfEvolutionGuard()
        with tempfile.TemporaryDirectory() as d:
            db_dir = Path(d) / "db"
            db_dir.mkdir()
            f = db_dir / "schema.py"
            f.write_text("# AI_HEADER: schema\n# START_MODULE_CONTRACT\n# p\n# END_MODULE_CONTRACT\n# START_MODULE_MAP\n# END_MODULE_MAP\nDROP TABLE x;\n")
            result = guard.check([f])
            db_check = next(c for c in result.checks if c.name == "db_schema")
            assert not db_check.passed


class TestSelfReloader:

    def test_reload_disabled_by_default(self):
        r = GraceSelfReloader()
        assert not r._enabled

    def test_reload_disabled_returns_success(self):
        import asyncio
        r = GraceSelfReloader()
        result = asyncio.run(r.reload_after_merge("ses-test"))
        assert result.success
        assert "disabled" in result.message.lower()


class TestSelfEvolutionSessionModel:

    def test_default_status(self):
        from datetime import datetime
        session = SelfEvolutionSession(
            id="ses-test1",
            title="Test session",
            description="Testing",
            status="pending",
        )
        assert session.status == "pending"
        assert session.feature_id is None
        assert session.error is None

    def test_status_transitions(self):
        session = SelfEvolutionSession(id="ses-test2", title="T")
        session.status = "collecting_context"
        assert session.status == "collecting_context"
        session.status = "planning"
        session.feature_id = "FEAT-TEST"
        assert session.feature_id == "FEAT-TEST"
        session.status = "done"
        from datetime import datetime
        session.finished_at = datetime.utcnow()
        assert session.status == "done"


class TestSelfEvolutionAPI:

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, api):
        resp = await api.get("/api/self/sessions")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    @pytest.mark.asyncio
    async def test_guard_check(self, api):
        resp = await api.get("/api/self/guard/check")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "passed" in data
        assert "checks" in data
        assert len(data["checks"]) == 4

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_evolve_minimal(self, api):
        resp = await api.post("/api/self/evolve", json={
            "title": "API test evolution",
            "description": "Test from pytest",
            "constraints": {"acceptance_profile": "FAST", "max_files": 1},
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["session_id"].startswith("ses-")
        assert data["status"] == "collecting_context"

    @pytest.mark.asyncio
    async def test_evolve_missing_title(self, api):
        resp = await api.post("/api/self/evolve", json={"description": "no title"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self, api):
        resp = await api.get("/api/self/sessions/ses-nonexist")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_session_context(self, api):
        resp = await api.get("/api/self/sessions/ses-nonexist/context")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_terminal_fails(self, api):
        resp = await api.post("/api/self/sessions/ses-nonexist/cancel")
        assert resp.status_code == 404


class TestWebSocketBroadcast:

    def test_broadcast_importable(self):
        from grace_control.api.ws_broadcast import broadcast_event
        assert callable(broadcast_event)
