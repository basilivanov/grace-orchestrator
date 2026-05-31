# Execution Packet: FEAT-GRACE-CP-LEGACY-W04-LEGACY-SMOKE

## Objective

Verify that legacy code (flows/, platform/, tasks/) works with the new prefect_compat no-op decorators. Ensure all Prefect imports use try/except pattern. Run a dry-run smoke test of run_e2e_packet to confirm the bridge is functional.

This is a Phase 0 prerequisite — must be done first before any new code can rely on the legacy runner.

## Slice

- slice_id: `SLICE-LEGACY`
- slice_slug: `legacy-smoke`
- feature_id: `FEAT-GRACE-CP-LEGACY`
- packet_id: `FEAT-GRACE-CP-LEGACY-W04-LEGACY-SMOKE`
- wave_id: `W04`
- status: `ready`
- phase: `PHASE-0`
- depends_on: ``
- feature_dir: `grace/packets/FEAT-GRACE-CP-LEGACY`

## Source Of Truth

- `CANONICAL_DECISIONS.md` §1 (legacy code stays)
- `tasks/PHASE_0_CLEANUP_REVISED.md` Task 0.1, 0.5
- `src/prefect_grace/prefect_compat.py` — no-op decorators
- `src/prefect_grace/platform/e2e_packet_runner.py` — target runner
- `development-plan.xml` — FEAT-GRACE-LEGACY

## Impacted Modules

- `M-GRACE-LEGACY-COMPAT`

## Allowed Write Scope

- `src/prefect_grace/platform/e2e_packet_runner.py` (import section only — add try/except)
- `src/prefect_grace/platform/managed_packet_runner.py` (import section only)
- `src/prefect_grace/tasks/codex_launcher.py` (import section only)
- `scripts/test_legacy.py`
- `grace/packets/FEAT-GRACE-CP-LEGACY/**`

## Frozen Scope

- `src/prefect_grace/**` — ALL CODE except import sections in 3 specified files
- `src/prefect_grace/flows/**` — Prefect flows (keep as-is)
- `src/prefect_grace/platform/*.py` — except import section in 3 files
- `src/prefect_grace/tasks/*.py` — except import section in codex_launcher.py
- `src/grace_control/**` — new code (not created yet at this phase)

## Must Preserve

- Legacy code logic unchanged — only import sections updated
- prefect_compat.py already exists and works (verified)
- All legacy tests must still pass
- No behavior changes to run_e2e_packet, managed_packet_runner, or codex_launcher
- Dry-run mode must work (default behavior, no live agents)

### GRACE Canon Compliance (обязательно)

Изменения минимальны (только import-секции), но новые файлы должны иметь контракты:
- **scripts/test_legacy.py**: AI_HEADER + MODULE_CONTRACT
- **Изменённые import-секции**: сохранить существующие контракты

## Required Design Decisions

### 1. Try/Except Import Pattern

Replace direct `from prefect import ...` with:

```python
# OLD:
from prefect import task, flow, get_run_logger

# NEW:
try:
    from prefect import task, flow, get_run_logger
except ImportError:
    from prefect_grace.prefect_compat import task, flow, get_run_logger
```

### 2. Files to Update (import section only)

- `src/prefect_grace/platform/e2e_packet_runner.py`
- `src/prefect_grace/platform/managed_packet_runner.py`
- `src/prefect_grace/tasks/codex_launcher.py`

### 3. Legacy Test Script

```python
"""Test legacy code works with prefect_compat."""
from pathlib import Path
from prefect_grace.platform.e2e_packet_runner import run_e2e_packet

def test_legacy_runner():
    project_root = Path.cwd()
    packet_path = project_root / "grace/packets/FEAT-GRACE-CP-LEGACY/TEST_PACKET.md"
    state_root = project_root / ".grace"
    worktree_root = project_root / ".grace/worktrees"

    # Create minimal test packet
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text("""# Execution Packet: TEST

## Objective
Legacy smoke test.

## Slice
- packet_id: `TEST`
- feature_id: `FEAT-GRACE-CP-LEGACY`
- wave_id: `W04`

## Allowed Write Scope
- /tmp/grace-smoke-test/test.py

## Frozen Scope
- /tmp/grace-smoke-test/**
""")

    # Dry-run (safe, no agents)
    result = run_e2e_packet(
        project_root=project_root,
        packet_path=packet_path,
        state_root=state_root,
        worktree_root=worktree_root,
        dry_run=True,
        execute_agent=False,
    )

    assert result is not None
    print(f"OK: legacy runner works (domain_status={result.domain_status})")

if __name__ == "__main__":
    test_legacy_runner()
    print("ALL LEGACY SMOKE TESTS PASSED")
```

## Implementation Requirements

1. Update 3 legacy files: import section only (try/except pattern)
2. Create `scripts/test_legacy.py`: smoke test script
3. Verify no Prefect runtime errors on import
4. Verify dry-run of run_e2e_packet works
5. Verify all existing legacy tests still pass

## Acceptance Criteria

- [ ] 3 legacy files updated with try/except import pattern
- [ ] `from prefect_grace.platform.e2e_packet_runner import run_e2e_packet` works without Prefect runtime
- [ ] `python scripts/test_legacy.py` exit 0
- [ ] All existing tests pass (no regressions)
- [ ] No behavior changes to legacy code
- [ ] Import error when Prefect not installed → graceful fallback to compat

## Verification

```bash
# Test legacy imports work
python3 -c "
from prefect_grace.platform.e2e_packet_runner import run_e2e_packet
from prefect_grace.platform.managed_packet_runner import run_managed_packet
from prefect_grace.tasks.codex_launcher import launch_codex
print('OK: all legacy imports work')
"

# Run legacy smoke test
python3 scripts/test_legacy.py

# Run existing tests
pytest tests/ -v --ignore=tests/test_e2e_mvp0.py --ignore=tests/test_db_schema.py

# Static checks on legacy code
ruff check src/prefect_grace/platform/e2e_packet_runner.py
ruff check src/prefect_grace/tasks/codex_launcher.py
```

## Expected Evidence

- `test-results/legacy.xml`
- Import test output (all 3 modules)
- Smoke test output (runner works in dry-run)
- Existing test output (no regressions)

## Escalation Triggers

- ImportError on legacy module (prefect_compat not working)
- run_e2e_packet raises unexpected exception in dry-run
- Existing tests fail after import update
- prefect_compat.py missing or broken
- More than 3 files need import updates

## Reviewer Gate

Reviewer must reject if:
- Legacy code behavior changed (not just imports)
- More than import section modified in any file
- Try/except catches too broadly (bare except)
- Existing tests regress
- prefect_compat not used (direct import still present)
- Missing GRACE contracts on test_legacy.py
