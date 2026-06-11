"""Tests for gate_resolver — TouchedArea detection and default gate resolution."""

from __future__ import annotations

from pathlib import Path

from grace_control.core.gate_resolver import (
    resolve_default_t0,
    resolve_default_t1,
    resolve_default_t2,
    resolve_touched_areas,
)


def _make_worktree(tmp_path: Path, scripts: dict[str, str] | None = None) -> Path:
    """Create a temp worktree with optional scripts."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    if scripts:
        for name, content in scripts.items():
            path = scripts_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    return tmp_path


# ── Touched area detection ─────────────────────────────────────────────────


def test_touched_areas_backend_py():
    assert resolve_touched_areas(["apps/api/main.py"]) == ["backend"]


def test_touched_areas_frontend_tsx():
    assert resolve_touched_areas(["components/Button.tsx"]) == ["frontend"]


def test_touched_areas_frontend_js():
    assert resolve_touched_areas(["app/layout.js"]) == ["frontend"]


def test_touched_areas_docs_md():
    assert resolve_touched_areas(["docs/guide.md"]) == ["docs"]


def test_touched_areas_contracts():
    assert resolve_touched_areas(["packages/contracts/schema.graphql"]) == ["contracts"]


def test_touched_areas_db():
    result = resolve_touched_areas(["alembic/versions/001_add_table.py"])
    # alembic/ prefix -> db, .py suffix -> backend, but that's fine
    assert "db" in result


def test_touched_areas_multiple():
    result = resolve_touched_areas(["app/page.tsx", "backend/api.py", "docs/README.md"])
    assert "backend" in result
    assert "docs" in result
    assert "frontend" in result


def test_touched_areas_no_match():
    assert resolve_touched_areas(["random.txt", "Makefile", ".gitignore"]) == []


def test_touched_areas_empty():
    assert resolve_touched_areas([]) == []


# ── Default T0 resolution ──────────────────────────────────────────────────


def test_t0_backend_grace_lint_plus_ruff(tmp_path):
    wt = _make_worktree(tmp_path, scripts={"grace_lint.py": "print('ok')"})
    cmds, origins = resolve_default_t0(["apps/api/main.py"], wt)
    assert any("grace_lint.py" in " ".join(c) for c in cmds), f"missing grace_lint, got {cmds}"
    assert any("ruff" in " ".join(c) for c in cmds), f"missing ruff, got {cmds}"
    assert any("auto:t0:backend_grace_lint" in o for o in origins)
    assert any("auto:t0:ruff" in o for o in origins)


def test_t0_frontend_grace_lint(tmp_path):
    wt = _make_worktree(tmp_path, scripts={"grace_front_lint.py": "print('ok')"})
    cmds, origins = resolve_default_t0(["app/page.tsx"], wt)
    assert any("grace_front_lint.py" in " ".join(c) for c in cmds)
    assert any("auto:t0:frontend_grace_lint" in o for o in origins)


def test_t0_backend_only_ruff(tmp_path):
    """No grace_lint.py — fall back to ruff only."""
    wt = _make_worktree(tmp_path)  # no scripts
    cmds, origins = resolve_default_t0(["apps/api/main.py"], wt)
    assert any("ruff" in " ".join(c) for c in cmds)
    assert len(cmds) == 1  # only ruff, no grace_lint


def test_t0_frontend_fallback_markers(tmp_path):
    wt = _make_worktree(tmp_path, scripts={"grace/check-markers.sh": "echo ok"})
    cmds, origins = resolve_default_t0(["app/page.tsx"], wt)
    assert any("check-markers.sh" in " ".join(c) for c in cmds)
    assert any("auto:t0:frontend_markers_fallback" in o for o in origins)


def test_t0_no_matching_changes(tmp_path):
    wt = _make_worktree(tmp_path)
    cmds, origins = resolve_default_t0(["random.txt"], wt)
    assert cmds == []


def test_t0_empty_changed_files(tmp_path):
    wt = _make_worktree(tmp_path, scripts={"grace_lint.py": "ok"})
    cmds, origins = resolve_default_t0([], wt)
    assert cmds == []


# ── Default T1 resolution ──────────────────────────────────────────────────


def test_t1_guardrails_normal(tmp_path):
    wt = _make_worktree(tmp_path, scripts={"guardrails.sh": "echo normal"})
    cmds, origins = resolve_default_t1(["components/Button.tsx"], wt)
    assert any("guardrails.sh" in " ".join(c) for c in cmds)
    assert any("normal" in " ".join(c) for c in cmds)
    assert any("auto:t1:guardrails_normal" in o for o in origins)


def test_t1_backend_pytest(tmp_path):
    wt = _make_worktree(tmp_path)
    cmds, origins = resolve_default_t1(["apps/api/main.py"], wt)
    assert any("pytest" in " ".join(c) for c in cmds)
    assert any("auto:t1:pytest" in o for o in origins)


def test_t1_frontend_pnpm_test(tmp_path):
    """When package.json exists and frontend changed, use pnpm test:run."""
    wt = _make_worktree(tmp_path)
    (wt / "package.json").write_text("{}")
    cmds, origins = resolve_default_t1(["app/page.tsx"], wt)
    assert any("pnpm" in " ".join(c) for c in cmds)
    assert any("auto:t1:pnpm_test" in o for o in origins)


def test_t1_frontend_no_package_json(tmp_path):
    """When no package.json, no frontend T1 defaults."""
    wt = _make_worktree(tmp_path)
    cmds, origins = resolve_default_t1(["app/page.tsx"], wt)
    assert cmds == [], f"expected no defaults without package.json, got {cmds}"


def test_t1_no_auto_defaults(tmp_path):
    wt = _make_worktree(tmp_path)
    cmds, origins = resolve_default_t1(["random.txt"], wt)
    assert cmds == []


# ── Default T2 resolution ──────────────────────────────────────────────────


def test_t2_guardrails_strict(tmp_path):
    wt = _make_worktree(tmp_path, scripts={"guardrails.sh": "echo strict"})
    cmds, origins = resolve_default_t2(["apps/api/main.py"], wt, profile="STRICT")
    assert any("guardrails.sh" in " ".join(c) for c in cmds)
    assert any("strict" in " ".join(c) for c in cmds)
    assert any("auto:t2:guardrails_strict" in o for o in origins)


def test_t2_strict_no_guardrails(tmp_path):
    wt = _make_worktree(tmp_path)
    cmds, origins = resolve_default_t2(["apps/api/main.py"], wt, profile="STRICT")
    assert cmds == [], f"expected no defaults, got {cmds}"


def test_t2_fast_returns_empty_even_with_guardrails(tmp_path):
    """FAST profile must NOT get T2 defaults even if guardrails.sh exists."""
    wt = _make_worktree(tmp_path, scripts={"guardrails.sh": "echo strict"})
    cmds, origins = resolve_default_t2(["apps/api/main.py"], wt, profile="FAST")
    assert cmds == [], f"FAST should get no T2 defaults, got {cmds}"


def test_t2_normal_returns_empty_even_with_guardrails(tmp_path):
    """NORMAL profile must NOT get T2 defaults even if guardrails.sh exists."""
    wt = _make_worktree(tmp_path, scripts={"guardrails.sh": "echo strict"})
    cmds, origins = resolve_default_t2(["apps/api/main.py"], wt, profile="NORMAL")
    assert cmds == [], f"NORMAL should get no T2 defaults, got {cmds}"


# ── Acceptance pipeline command_origins ─────────────────────────────────────


def test_acceptance_report_contains_command_origins():
    """StageResult.command_origins is populated by the pipeline."""
    from grace_control.core.contracts import StageResult, StageName, StageStatus, CommandResult
    result = StageResult(
        name=StageName.T1_TARGETED_TESTS,
        status=StageStatus.PASSED,
        summary="test",
        commands=[CommandResult(command="echo ok", cwd="/", exit_code=0)],
        command_origins=["auto:t1:pytest"],
    )
    assert result.command_origins == ["auto:t1:pytest"]


def test_validate_packet_contract_no_t1_ok():
    """validate_packet_contract no longer fails NORMAL without verification.t1."""
    from grace_control.core.contracts import (
        AcceptanceProfile, ExecutionPacketContract, validate_packet_contract,
    )
    pkt = ExecutionPacketContract(
        packet_id="p1", title="test",
        allowed_write_scope=["src/"], frozen_scope=[],
        acceptance_profile=AcceptanceProfile.NORMAL,
        verification={},
    )
    errors = validate_packet_contract(pkt)
    t1_errors = [e for e in errors if "verification.t1" in e]
    assert not t1_errors, f"should not require verification.t1: {t1_errors}"


def test_validate_packet_contract_strict_no_t1_ok():
    """validate_packet_contract no longer fails STRICT without verification.t1."""
    from grace_control.core.contracts import (
        AcceptanceProfile, ExecutionPacketContract, validate_packet_contract,
    )
    pkt = ExecutionPacketContract(
        packet_id="p1", title="test",
        allowed_write_scope=["src/"], frozen_scope=[],
        acceptance_profile=AcceptanceProfile.STRICT,
        verification={},
    )
    errors = validate_packet_contract(pkt)
    t1_errors = [e for e in errors if "verification.t1" in e]
    assert not t1_errors, f"should not require verification.t1: {t1_errors}"


def test_pipeline_runs_without_verification_block(tmp_path):
    """NORMAL packet with no verification.t1 and no auto defaults → fails clearly."""
    from grace_control.core.acceptance_pipeline import AcceptancePipeline
    from grace_control.core.command_runner import CommandRunner
    from grace_control.core.contracts import (
        AcceptanceProfile, ExecutionPacketContract, FinalVerdict,
    )
    from grace_control.core.evidence import EvidenceCollector
    from grace_control.core.scope_guard import ScopeGuard

    pkt = ExecutionPacketContract(
        packet_id="p1", title="test",
        allowed_write_scope=["src/"], frozen_scope=[],
        acceptance_profile=AcceptanceProfile.NORMAL,
        verification={},
    )
    pipe = AcceptancePipeline(
        repo_root=tmp_path,
        command_runner=CommandRunner(tmp_path),
        scope_guard=ScopeGuard(tmp_path),
        evidence_collector=EvidenceCollector(),
    )
    report = pipe.run(packet=pkt, changed_files=[])
    assert report.final_verdict != FinalVerdict.ACCEPTED
    summaries = [s.summary for s in report.stages]
    assert any("no auto" in (s or "").lower() for s in summaries), (
        f"expected no-auto-defaults message, got: {summaries}"
    )
