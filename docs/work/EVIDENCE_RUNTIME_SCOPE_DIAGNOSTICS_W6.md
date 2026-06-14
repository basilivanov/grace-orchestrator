# W6: Post-run Scope Enforcement + Runtime Diagnostics

## Status

Complete. All acceptance criteria met.

## Acceptance checklist

| # | Criterion | Status |
|---|-----------|--------|
| 1 | RuntimeDiffInspector exists | ✅ |
| 2 | RuntimeScopeEnforcer exists | ✅ |
| 3 | RuntimeDiagnosticsBuilder exists | ✅ |
| 4 | Changed files detected after agent run | ✅ |
| 5 | Untracked files detected | ✅ |
| 6 | Deleted files detected | ✅ |
| 7 | Scope paths normalized | ✅ |
| 8 | Absolute scope paths rejected | ✅ |
| 9 | Dotdot scope paths rejected | ✅ |
| 10 | Directory scope doesn't allow sibling prefix | ✅ |
| 11 | Out-of-scope changes reject packet | ✅ |
| 12 | Frozen scope changes reject packet | ✅ |
| 13 | Scope rejection happens before acceptance gates | ✅ |
| 14 | Scope enforcement artifact written (scope_enforcement.json) | ✅ |
| 15 | Diff inspection artifact written (diff_inspection.json) | ✅ |
| 16 | Runtime diagnostics artifact written (runtime_diagnostics.json) | ✅ |
| 17 | Changed files included in evidence | ✅ |
| 18 | Runtime events emitted for diff/scope/diagnostics | ✅ |
| 19 | All artifacts go through RuntimeArtifactStore | ✅ |
| 20 | All artifacts are redacted | ✅ |
| 21 | No new `import subprocess` outside allowed legacy helper | ✅ |
| 22 | Existing W1-W5 tests pass | ✅ (175+) |
| 23 | New W6 tests pass | ✅ (21 unit + integration) |
| 24 | No OpenCode server behavior changed | ✅ |

## New files

| File | Purpose |
|------|---------|
| `runtime_scope_enforcer.py` | Pure-logic scope enforcement |
| `runtime_diff_inspector.py` | Git-based diff inspection (async subprocess, no `import subprocess`) |
| `runtime_diagnostics.py` | Diagnostics builder + failure read model |
| `test_runtime_scope_enforcer.py` | 13 unit tests |
| `test_runtime_diff_inspector.py` | 3 unit tests |
| `test_runtime_diagnostics.py` | 4 unit tests |
| `test_w6_subprocess_hygiene.py` | 1 repo hygiene test |

## Integration

PacketExecutionAdapter.execute() flow after W6:

1. W3 selftest
2. Materialize packet
3. Agent run (_call_executor)
4. W2 capture
5. **W6: RuntimeDiffInspector** → `packet.diff_inspection_*` events
6. **W6: RuntimeScopeEnforcer** → `packet.scope_enforcement_*` events
7. **W6: RuntimeDiagnosticsBuilder** → `runtime_diagnostics.json`, `scope_enforcement.json`, `diff_inspection.json`, `changed_files.json`
8. **If scope fails → fast reject** (before acceptance)
9. Acceptance gates (unchanged)
10. Evidence capture (unchanged)

## Config

New setting: `agent_runtime_fail_on_no_changes: bool = False`

## Failure codes

- `AGENT_CHANGED_OUT_OF_SCOPE` — changed files outside allowed scope
- `AGENT_TOUCHED_FROZEN_SCOPE` — changed files in frozen scope
- `AGENT_SCOPE_ENFORCEMENT_FAILED` — generic enforcement failure
- `AGENT_DIFF_INSPECTION_FAILED` — git diff failed
- `AGENT_NO_CHANGES_PRODUCED` — agent produced no changes (if fail_on_no_changes=True)
