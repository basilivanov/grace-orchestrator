# Review: `b647c8c` final TZ/canon drift patch

Date: 2026-06-05
Reviewed commit: `b647c8c87050f6b0efe38f459872fdc494b0f706`
Previous audit: `source/codex/final-audit-2026-06-05-w0-w12-vs-tz.md`

## Verdict

Partially accepted, but not done.

The commit fixes important pieces from the final audit:

- README now documents `cli` as the default execution backend.
- `docs/grace/EXECUTION_BACKENDS.md` now describes `UniversalCliAgentBackend` as the strategic/default path.
- GraceLint now includes W7 boundary allowances for `agent_env_builder.py` and `process_supervisor.py`.
- GRC109 exists and is enabled in `DEFAULT_RULES`.
- OpenAPI was regenerated for the new `/api/agents/run` shape.

However, two key audit requirements are still not satisfied:

1. `.grace/lint_allowlist.yaml` still contains old `expires_wave: W12` entries and duplicates.
2. `core/llm_runner.py` was not removed, archived, or refactored; it was converted into a permanent exception even though its own reason says “to be refactored”.

Because of those two issues, the final TZ/canon drift is not fully closed yet.

---

## Accepted items

### A1. Docs now describe `cli` / UniversalCliAgentBackend correctly

Accepted.

`README.md` now links execution backends as:

```text
`cli` (default) / `mock` / `api` (legacy: removed in W8)
```

`docs/grace/EXECUTION_BACKENDS.md` now states:

```text
cli -> UniversalCliAgentBackend — Default runtime backend
mock -> test/smoke backend
api -> optional HTTP provider adapter
legacy -> removed in W8
```

This closes the stale-docs issue for the main execution backend model.

### A2. W7 GraceLint boundary partially fixed

Accepted.

`checker.py` now has:

```python
ALLOWED_ENV = {"config/", "tests/", "scripts/", "tools/", "services/agent_env_builder.py"}
ALLOWED_SUBPROCESS = {
    "services/git_service.py",
    "services/worktree_cleanup_service.py",
    "services/process_supervisor.py",
    "core/llm_runner.py",
    "scripts/",
    "tests/",
}
```

This correctly recognizes `agent_env_builder.py` and `process_supervisor.py` as W7 execution-boundary files.

### A3. GRC109 exists and is enabled

Accepted as a first implementation.

`checker.py` now defines:

```python
_KNOWN_CLI_AGENTS = {"opencode", "codex", "agy", "gemini", "claude"}
```

and `DEFAULT_RULES` includes `GRC109`.

---

## Still open blockers

### P1-1. Allowlist still contains old `expires_wave: W12` entries

Current `.grace/lint_allowlist.yaml` still has old W12 entries:

```yaml
- rule: GRC103
  path: src/grace_control/adapters/packet_executor.py
  reason: adapter wires PacketRun.status ("running", "failed")
  expires_wave: W12

- rule: GRC108
  path: src/grace_control/adapters/packet_executor.py
  reason: large file, partially refactored in W6 (target <300)
  expires_wave: W12

- rule: GRC108
  path: src/grace_control/services/evidence_service.py
  reason: multiple evidence helpers, not yet block-split
  expires_wave: W12
```

The same paths/rules also appear earlier as `expires_wave: never`, creating duplicated policy entries.

Impact:

- The claim “W12 allowlist entries removed” is false.
- The allowlist expiry mechanism is still not meaningful.
- Future audits/tools can get contradictory policy for the same rule/path.

Required fix:

1. Remove the duplicate W12 entries entirely.
2. Keep only one entry per rule/path pair.
3. Add a test for allowlist hygiene:

```text
- no duplicate (rule, path) pairs;
- no expires_wave equal to a completed wave;
- every permanent `never` entry has a permanent ownership reason, not “to be refactored”.
```

---

### P1-2. `llm_runner.py` is still a permanent exception, not resolved

Previous audit required one of:

```text
A. delete/archive llm_runner.py if unused;
B. refactor it through UniversalCliAgentBackend;
C. keep it only as temporary exception, but then W0-W12 is not fully complete.
```

This patch instead does:

```yaml
- rule: GRC101
  path: src/grace_control/core/llm_runner.py
  reason: pre-W7 legacy LLM runner — hardcodes opencode/agy, to be refactored through UniversalCliAgentBackend
  expires_wave: never

- rule: GRC109
  path: src/grace_control/core/llm_runner.py
  reason: pre-W7 runner hardcodes opencode/agy — to be refactored
  expires_wave: never
```

This is internally inconsistent:

- `expires_wave: never` means permanent ownership / accepted design.
- “to be refactored” means temporary debt.

Impact:

- The old hardcoded CLI runner remains in runtime source.
- The revised W7 guarantee is weakened by permanent exception.
- GRC109 is immediately bypassed for the main file it was meant to catch.

Required fix:

Choose one:

#### Preferred: archive/delete

If `run_llm()` is unused, remove `src/grace_control/core/llm_runner.py` from runtime source and move historical notes to docs/archive if needed.

#### Alternative: refactor

Rewrite `run_llm()` to delegate to `UniversalCliAgentBackend` / `AgentRunService` and profiles.

#### Last resort: temporary exception

If it must stay for a short time, set an explicit future expiry, e.g.:

```yaml
expires_wave: W13
```

and do **not** claim W0-W12 fully complete until W13 removes/refactors it.

Do not use `expires_wave: never` with a “to be refactored” reason.

---

## P2 / quality notes

### P2-1. GRC109 is narrow

Current GRC109 flags a known agent name only if the same line also contains `run` or `exec`:

```python
if name in line and ("run" in line or "exec" in line):
```

This catches `opencode run`, but may miss hardcoded command construction like:

```python
cmd = ["agy", "--print", prompt_text]
cmd = ["claude", "-p", prompt]
```

If `llm_runner.py` is removed/refactored, this becomes less urgent. But for stronger canon, GRC109 should probably flag string-literal command names in runtime source regardless of whether the same line says `run`.

### P2-2. `ALLOWED_SUBPROCESS` includes `core/llm_runner.py`

This is acceptable only if the file remains as a temporary compatibility exception. It should not be a permanent allowed boundary in the final architecture.

---

## Required next patch

Title:

```text
fix: remove remaining W12 allowlist drift and resolve llm_runner exception
```

Scope:

```text
.grace/lint_allowlist.yaml
src/grace_control/core/llm_runner.py
src/grace_control/tools/grace_lint/checker.py
tests/grace_control/tools/test_grace_lint.py
```

Acceptance:

1. `.grace/lint_allowlist.yaml` has no `expires_wave: W12` entries.
2. `.grace/lint_allowlist.yaml` has no duplicate `(rule, path)` pairs.
3. Permanent `expires_wave: never` entries do not say “to be refactored”.
4. `llm_runner.py` is deleted/archived/refactored, or explicitly marked W13 temporary and W0-W12 is not claimed complete until then.
5. GRC109 has a regression test proving hardcoded CLI command names in runtime code fail.

---

## Status

Runtime architecture remains mostly ready, but final TZ/canon completion is still blocked by allowlist/llm_runner policy drift.
