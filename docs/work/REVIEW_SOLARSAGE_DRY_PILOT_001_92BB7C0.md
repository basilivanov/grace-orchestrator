# Review: Solar Sage dry pilot 001 — 92bb7c0

Date: 2026-06-10
Reviewed commit: `92bb7c02ac345daf2c95ce7883f6041707e5b8f7`
TZ: `docs/work/TZ_SOLARSAGE_DRY_PILOT_001.md`
Report: `docs/work/REPORT_SOLARSAGE_DRY_PILOT_001.md`
Verdict: **ACCEPTED — target_repo_worktree bridge proven end-to-end**

## 1. Summary

Solar Sage dry pilot 001 passed as an end-to-end real-target smoke:

```text
GRACE orchestrator
→ target_repo_worktree
→ /opt/solarsage-astro
→ coder-opencode
→ docs-only Solar Sage change
→ acceptance FAST
→ merge into Solar Sage main
→ report in GRACE docs/work
```

This proves the first bridge from GRACE control-plane to an external target repo.

## 2. What was verified

### 2.1 Worker now resolves target_repo_root correctly

Accepted.

The previous hidden blocker was that the worker treated GRACE `project_root` as target repo even when `GRACE_TARGET_REPO_ROOT` was set.

The fix now resolves target repo from:

```python
_settings.target_repo_root
or os.environ.get("GRACE_TARGET_REPO_ROOT", "")
or project_root
```

and passes it into `resolve_git_execution_context(target_repo_root=...)`.

This is the key fix that allowed the worker to see `/opt/solarsage-astro` instead of `/tmp/grace-orchestrator-export`.

### 2.2 Scenario loader supports target-repo-only scenarios

Accepted.

`fixture_app` is no longer required if:

```yaml
target_repo_worktree: true
```

This is correct: a real target repo scenario should not require a fixture app.

### 2.3 Runner supports no-fixture target repo mode

Accepted.

`_prepare_fixture()` now returns success when `fixture_app` is empty:

```python
if not fixture_app:
    print("[runner] No fixture app — using target repo directly")
    return True
```

This is the right behavior for Solar Sage target repo mode.

### 2.4 Scenario acceptance profile is now packet-configurable

Accepted.

The runner now reads:

```python
"acceptance_profile": pkt.get("acceptance_profile", "NORMAL")
```

instead of hardcoding `NORMAL`.

For this docs-only pilot, `FAST` is acceptable because there are no meaningful T1/T2 app tests to run.

### 2.5 Scenario is correctly tiny and safe

Accepted.

The scenario only allows:

```text
docs/grace/solar-sage-dry-pilot-001.md
```

and uses a docs-only prompt. This matches the TZ requirement not to start with a business feature.

### 2.6 Report confirms pilot pass

Accepted.

The report says:

```text
Verdict: PASS
Solar Sage base SHA: 7b7552e...
Solar Sage agent commit SHA: 7103e9a...
Solar Sage merge commit SHA: bfa2e58
workspace_mode: target_repo_worktree
workspace_path: /tmp/grace-agent-worktrees/pkt_OylrVWAlHq-attempt-0001
target_repo_root: /opt/solarsage-astro
```

It also reports:

```text
only docs/grace/solar-sage-dry-pilot-001.md changed
no GRACE source files in workspace
API/watchdog 0 restarts
no OOM
Solar Sage repo clean after run
no agent/* branches left
```

This satisfies the pilot goal.

## 3. Minor reporting gap, not blocking

The report marks some evidence criteria as:

```text
Evidence records workspace_mode=target_repo_worktree ✅ (env level)
Evidence records commit_semantics=target_repo_commit ✅ (merge into Solar Sage repo)
Evidence records successful target_repo_preflight ✅ (run completed successfully)
```

This is operationally good enough for pilot 001, but not audit-perfect.

For pilot 002 and later, the report should include actual `packet_runs.result_json` snippets:

```json
"workspace": {
  "workspace_mode": "target_repo_worktree",
  "target_repo_root": "/opt/solarsage-astro",
  "commit_semantics": "target_repo_commit"
},
"target_repo_preflight": {
  "success": true,
  "working_tree_clean": true,
  "remote_sync": true,
  "worktree_conflict": false
}
```

This is not a blocker for continuing, but it should be tightened before relying on reports for formal audit.

## 4. Architecture caution, not blocking pilot 002

The worker now constructs `PacketExecutionAdapter` with:

```python
project_root=self._git_context.target_repo_root
```

This is useful because the executor must operate on the target repo in this mode.

However, it also means the adapter's `self.project_root` is no longer necessarily the GRACE control-plane root. Any future guard that says "inside GRACE project root" should not rely only on `PacketExecutionAdapter.project_root` in worker mode.

For pilot 001 this is safe because:

```text
GRACE_WORKTREE_ROOT=/tmp/grace-agent-worktrees
```

and the report confirms no GRACE files leaked.

Before production hardening, consider explicitly carrying both roots through runtime/evidence:

```text
control_plane_root
 target_repo_root
 worktree_root
```

## 5. Decision

Decision:

```text
ACCEPTED
```

Solar Sage dry pilot 001 proves the GRACE → Solar Sage target worktree bridge.

## 6. Next step

Proceed to:

```text
TZ_SOLARSAGE_DRY_PILOT_002
```

Pilot 002 should be a tiny real UI-safe change with `acceptance_profile=NORMAL` and gates:

```bash
pnpm lint
pnpm typecheck
pnpm test:run
```

Still avoid:

```text
auth
payments
subscriptions
production config
large UI refactor
```
