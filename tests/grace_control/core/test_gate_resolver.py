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
    # Mark as GRACE orchestrator
    (wt / ".grace" / "state").mkdir(parents=True)
    cmds, origins = resolve_default_t0(["apps/api/main.py"], wt)
    assert any("grace_lint.py" in " ".join(c) for c in cmds), f"missing grace_lint, got {cmds}"
    assert any("ruff" in " ".join(c) for c in cmds), f"missing ruff, got {cmds}"
    assert any("auto:t0:backend_grace_lint" in o for o in origins)
    assert any("auto:t0:ruff" in o for o in origins)


def test_t0_frontend_grace_lint(tmp_path):
    wt = _make_worktree(tmp_path, scripts={"grace_front_lint.py": "print('ok')"})
    # Mark as GRACE orchestrator
    (wt / ".grace" / "state").mkdir(parents=True)
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
    # Mark as GRACE orchestrator
    (wt / ".grace" / "state").mkdir(parents=True)
    cmds, origins = resolve_default_t0(["app/page.tsx"], wt)
    assert any("check-markers.sh" in " ".join(c) for c in cmds)
    assert any("auto:t0:frontend_markers_fallback" in o for o in origins)


def test_t0_target_repo_skips_grace_lint(tmp_path):
    """Target repo (not GRACE orchestrator) should skip grace_lint and grace_front_lint
    even if those scripts exist."""
    wt = _make_worktree(tmp_path, scripts={
        "grace_lint.py": "print('backend')",
        "grace_front_lint.py": "print('frontend')",
    })
    cmds, origins = resolve_default_t0(["apps/api/main.py", "app/page.tsx"], wt)
    grace_cmds = [c for c in cmds if "grace_lint.py" in " ".join(c) or "grace_front_lint.py" in " ".join(c)]
    assert not grace_cmds, f"target repo should not get GRACE linters, got: {grace_cmds}"
    assert any("ruff" in " ".join(c) for c in cmds)


def test_resolve_linter_mode_orchestrator(tmp_path):
    """GRACE orchestrator repo → strict mode."""
    from grace_control.core.gate_resolver import resolve_linter_mode
    (tmp_path / ".grace" / "state").mkdir(parents=True)
    assert resolve_linter_mode(tmp_path) == "strict"


def test_resolve_linter_mode_target_disabled(tmp_path):
    """Target repo without canon.yaml → disabled."""
    from grace_control.core.gate_resolver import resolve_linter_mode
    assert resolve_linter_mode(tmp_path) == "disabled"


def test_resolve_linter_mode_target_canon(tmp_path):
    """Target repo with grace/canon.yaml → reads gate_mode."""
    from grace_control.core.gate_resolver import resolve_linter_mode
    canon_dir = tmp_path / "grace"
    canon_dir.mkdir()
    (canon_dir / "canon.yaml").write_text("gate_mode: changed-files\n")
    assert resolve_linter_mode(tmp_path) == "changed-files"


def test_resolve_linter_mode_target_canon_strict(tmp_path):
    """grace/canon.yaml with gate_mode: strict → strict."""
    from grace_control.core.gate_resolver import resolve_linter_mode
    canon_dir = tmp_path / "grace"
    canon_dir.mkdir()
    (canon_dir / "canon.yaml").write_text("gate_mode: strict\n")
    assert resolve_linter_mode(tmp_path) == "strict"


def test_path_is_excluded_dir(tmp_path):
    """_path_is_excluded detects node_modules, .venv, __pycache__ dirs."""
    from grace_control.core.gate_resolver import _path_is_excluded
    assert _path_is_excluded("node_modules/pkg/index.js")
    assert _path_is_excluded(".venv/lib/site-packages/pkg.py")
    assert _path_is_excluded("src/__pycache__/module.cpython.py")


def test_path_is_excluded_prefix(tmp_path):
    """_path_is_excluded detects alembic/, migrations/ prefixes."""
    from grace_control.core.gate_resolver import _path_is_excluded
    assert _path_is_excluded("alembic/versions/001_add_table.py")
    assert _path_is_excluded("migrations/001_initial.sql")
    assert _path_is_excluded("components/ui/Button.tsx")


def test_path_is_not_excluded(tmp_path):
    """_path_is_excluded allows normal source files."""
    from grace_control.core.gate_resolver import _path_is_excluded
    assert not _path_is_excluded("apps/api/app/main.py")
    assert not _path_is_excluded("components/today/tab-bar.tsx")
    assert not _path_is_excluded("__tests__/components/TabBar.test.tsx")


def test_t0_changed_files_mode(tmp_path):
    """changed-files mode runs GRACE lint on each changed file individually."""
    wt = _make_worktree(tmp_path, scripts={
        "grace_lint.py": "print('ok')",
        "grace_front_lint.py": "print('ok')",
    })
    canon_dir = tmp_path / "grace"
    canon_dir.mkdir()
    (canon_dir / "canon.yaml").write_text("gate_mode: changed-files\n")
    cmds, origins = resolve_default_t0(["apps/api/main.py", "app/page.tsx"], wt)
    # Each file should be checked individually (not combined)
    grace_backend_calls = [c for c in cmds if "grace_lint.py" in " ".join(c)]
    grace_frontend_calls = [c for c in cmds if "grace_front_lint.py" in " ".join(c)]
    assert len(grace_backend_calls) == 1, f"expected 1 backend call, got {grace_backend_calls}"
    assert len(grace_frontend_calls) == 1, f"expected 1 frontend call, got {grace_frontend_calls}"
    assert any("apps/api/main.py" in " ".join(c) for c in grace_backend_calls)
    assert any("app/page.tsx" in " ".join(c) for c in grace_frontend_calls)
    assert any("ruff" in " ".join(c) for c in cmds)


def test_t0_changed_files_excludes_noise(tmp_path):
    """Excluded paths are not passed to GRACE linters even in changed-files mode."""
    wt = _make_worktree(tmp_path, scripts={
        "grace_front_lint.py": "print('ok')",
    })
    canon_dir = tmp_path / "grace"
    canon_dir.mkdir()
    (canon_dir / "canon.yaml").write_text("gate_mode: changed-files\n")
    cmds, origins = resolve_default_t0([
        "components/today/tab-bar.tsx",
        "components/ui/Button.tsx",  # excluded (vendor)
        "alembic/versions/001_add_table.py",  # excluded (generated)
    ], wt)
    grace_calls = [c for c in cmds if "grace_front_lint.py" in " ".join(c)]
    call_args = " ".join(" ".join(c) for c in grace_calls)
    assert "components/today/tab-bar.tsx" in call_args
    assert "components/ui/Button.tsx" not in call_args, f"vendor file should be excluded: {call_args}"
    assert "alembic/versions/" not in call_args, f"alembic should be excluded: {call_args}"


def test_t0_changed_files_canon_yaml_glob_exclude(tmp_path):
    """canon.yaml glob excludes paths NOT already hardcoded: generated/**/*.ts."""
    wt = _make_worktree(tmp_path, scripts={
        "grace_front_lint.py": "print('ok')",
    })
    canon_dir = tmp_path / "grace"
    canon_dir.mkdir()
    (canon_dir / "canon.yaml").write_text(
        "gate_mode: changed-files\nexclude:\n  - 'generated/**/*.ts'\n"
    )
    cmds, origins = resolve_default_t0([
        "generated/api/types.ts",     # excluded by canon.yaml glob
        "src/handlers/controller.ts",  # not excluded
    ], wt)
    grace_calls = [c for c in cmds if "grace_front_lint.py" in " ".join(c)]
    call_args = " ".join(" ".join(c) for c in grace_calls)
    assert "src/handlers/controller.ts" in call_args
    assert "generated/api/types.ts" not in call_args, (
        f"glob-excluded file should be filtered out via canon.yaml: {call_args}"
    )


def test_t0_changed_files_all_excluded_no_commands(tmp_path):
    """When ALL changed files are excluded, no GRACE lint commands or origins are added."""
    wt = _make_worktree(tmp_path, scripts={
        "grace_front_lint.py": "print('ok')",
    })
    canon_dir = tmp_path / "grace"
    canon_dir.mkdir()
    (canon_dir / "canon.yaml").write_text("gate_mode: changed-files\n")
    cmds, origins = resolve_default_t0([
        "components/ui/Button.tsx",  # excluded (vendor)
        "alembic/versions/001.py",   # excluded (generated)
    ], wt)
    grace_cmds = [c for c in cmds if "grace_front_lint.py" in " ".join(c) or "grace_lint.py" in " ".join(c)]
    assert not grace_cmds, f"no lint commands expected when all excluded, got: {grace_cmds}"
    grace_origins = [o for o in origins if "grace" in o]
    assert not grace_origins, f"no lint origins expected when all excluded, got: {grace_origins}"
    assert any("ruff" in " ".join(c) for c in cmds), "ruff should still run"


def test_t0_frontend_missing_lint_fails_normal(tmp_path):
    """NORMAL with frontend changed but no frontend GRACE lint → fail (for orchestrator repos)."""
    wt = _make_worktree(tmp_path)
    (wt / ".grace" / "state").mkdir(parents=True)
    cmds, origins = resolve_default_t0(["app/page.tsx"], wt, profile="NORMAL")
    assert any("frontend_lint_missing" in o for o in origins), (
        f"expected frontend_lint_missing origin, got {origins}"
    )
    assert any("sys.exit(1)" in " ".join(c) for c in cmds), (
        f"expected failing command, got {cmds}"
    )


def test_t0_frontend_missing_lint_fails_strict(tmp_path):
    """STRICT with frontend changed but no frontend GRACE lint → fail (for orchestrator repos)."""
    wt = _make_worktree(tmp_path)
    (wt / ".grace" / "state").mkdir(parents=True)
    cmds, origins = resolve_default_t0(["app/page.tsx"], wt, profile="STRICT")
    assert any("frontend_lint_missing" in o for o in origins)


def test_t0_frontend_missing_lint_warns_fast(tmp_path):
    """FAST with frontend changed but no frontend GRACE lint → no failing command."""
    wt = _make_worktree(tmp_path)
    (wt / ".grace" / "state").mkdir(parents=True)
    cmds, origins = resolve_default_t0(["app/page.tsx"], wt, profile="FAST")
    frontend_lint_issues = [o for o in origins if "frontend" in o]
    assert not frontend_lint_issues, (
        f"FAST should not get frontend lint issues, got {frontend_lint_issues}"
    )


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
    cmds, origins = resolve_default_t1(["components/Button.tsx"], wt, profile="NORMAL")
    assert any("guardrails.sh" in " ".join(c) for c in cmds)
    assert any("normal" in " ".join(c) for c in cmds)
    assert any("auto:t1:guardrails_normal" in o for o in origins)


def test_t1_fast_returns_empty_even_with_guardrails(tmp_path):
    """FAST must NOT get T1 defaults even if guardrails.sh exists."""
    wt = _make_worktree(tmp_path, scripts={"guardrails.sh": "echo normal"})
    cmds, origins = resolve_default_t1(["components/Button.tsx"], wt, profile="FAST")
    assert cmds == [], f"FAST should get no T1 defaults, got {cmds}"


def test_t1_backend_pytest(tmp_path):
    wt = _make_worktree(tmp_path)
    cmds, origins = resolve_default_t1(["apps/api/main.py"], wt, profile="NORMAL")
    assert any("pytest" in " ".join(c) for c in cmds)
    assert any("auto:t1:pytest" in o for o in origins)


def test_t1_frontend_pnpm_test(tmp_path):
    """When package.json exists and frontend changed, use pnpm test:run."""
    wt = _make_worktree(tmp_path)
    (wt / "package.json").write_text("{}")
    cmds, origins = resolve_default_t1(["app/page.tsx"], wt, profile="NORMAL")
    assert any("pnpm" in " ".join(c) for c in cmds)
    assert any("auto:t1:pnpm_test" in o for o in origins)


def test_t1_frontend_no_package_json(tmp_path):
    """When no package.json, no frontend T1 defaults."""
    wt = _make_worktree(tmp_path)
    cmds, origins = resolve_default_t1(["app/page.tsx"], wt, profile="NORMAL")
    assert cmds == [], f"expected no defaults without package.json, got {cmds}"


def test_t1_no_auto_defaults(tmp_path):
    wt = _make_worktree(tmp_path)
    cmds, origins = resolve_default_t1(["random.txt"], wt, profile="NORMAL")
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
