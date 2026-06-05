# Review: W0-W11 follow-up after recent commits

Date: 2026-06-05
Reviewed state: current `main` after these reported commits:

```text
f777589 docs: add W0-W11 completion audit
cb60317 docs: add W0-W11 completion audit review
8fe31fb fix: regenerate docs after endpoint changes
753f913 feat: SELF_EVOLUTION.md (W11 content) + GRC104 (router DB loop rule)
027d297 perf: packet_executor 667->255 lines (under 300 budget)
```

Previous review: `source/codex/review-2026-06-05-w0-w11-completion-audit.md`

## Verdict

Still not accepted.

The latest commits appear to add documentation, regenerate docs, add/update GRC104, and shrink `packet_executor.py` by line count. They do **not** close the main P0/P1 blockers from the previous audit.

The line-count target for `packet_executor.py` was achieved mechanically, but the architecture target was not. The file is smaller but still contains the same core smells: direct env read, direct subprocess/git cleanup, hardcoded legacy branch, `_call_legacy_runner`, and legacy naming. This is not a valid W6 completion.

---

## Still open blockers

### P0-1. Default backend is still `legacy`

Current `src/grace_control/config/settings.py` still has:

```python
execution_backend: str = "legacy"  # "legacy" | "api" | "mock" — see grace_control.agent.select_backend
```

But W8 removed legacy and `select_backend("legacy")` raises by design.

Impact: a clean default runtime still breaks when no env/config overrides are set.

Required fix:

```python
execution_backend: str = "api"
```

or, if real providers are intentionally not ready yet:

```python
execution_backend: str = "mock"
```

Also update comments/docs/tests so `legacy` is not advertised as a valid backend.

Required tests:

- default `settings.execution_backend != "legacy"`;
- default `select_backend()` does not raise in a clean environment;
- `select_backend("legacy")` still raises clear W8 removal error.

---

### P0-2. `packet_executor.py` is smaller but still legacy-shaped

Current file still shows:

```python
import os, time
...
base_ref = os.environ.get("GRACE_BASE_REF", settings.base_branch)
...
result = await self._call_legacy_runner(...)
_log.debug("legacy_runner_completed", ...)
```

`_load_packet()` still imports and uses subprocess/shutil directly:

```python
import subprocess, shutil
subprocess.run(["git", "-C", ..., "worktree", "prune"], ...)
subprocess.run(["git", "-C", ..., "worktree", "remove", ...], ...)
subprocess.run(["git", "-C", ..., "branch", "-D", f"agent/default/{packet_id}/{slug}"], ...)
```

This violates W3, W6, W8, and W10 intent.

Required fix:

1. Remove direct env usage from executor. Use `settings.base_branch` or injected config.
2. Remove direct subprocess/shutil/git cleanup from executor. Use `GitService` / `WorktreeInspector` / dedicated cleanup service.
3. Remove hardcoded legacy branch format `agent/default/{packet_id}/{slug}`.
4. Remove `_call_legacy_runner` and `legacy_runner_completed` naming/path.
5. Extract real services, not just compress lines:

```text
PacketLoader
AcceptanceService
EvidenceVerifierService
ReviewerService
RunResultWriter
SelfEvolutionGuardService
```

Required tests:

- grep/unit test: no `os.environ` in `packet_executor.py`;
- grep/unit test: no `subprocess` in `packet_executor.py`;
- grep/unit test: no `_call_legacy_runner`, `legacy_runner_completed`, or `agent/default/` in `packet_executor.py`;
- packet execution still works with `MockBackend`.

---

### P1-1. GraceLint still does not enforce the promised architecture

Current `checker.py` still has:

```python
ALLOWED_SUBPROCESS = {"services/git_service.py", "services/", "scripts/", "tests/"}
```

This allows subprocess in **any** service, which is exactly why `self_evolution_service.py` can still shell out.

Also `_check_subprocess()` still ignores import lines:

```python
if "subprocess" in line and "import" not in line:
```

So `import subprocess` is not flagged.

`.grace/lint_allowlist.yaml` still contains W11-expiring entries for packet_executor and llm_runner:

```yaml
expires_wave: W11
```

But W11 is reported complete. These entries should now be invalid or removed.

Required fix:

1. Change allowed subprocess paths to explicit allowlist:

```text
src/grace_control/services/git_service.py
scripts/
tests/
```

Do not allow all `services/`.

2. Flag import-only subprocess usage outside allowlist.
3. Enforce expired allowlist entries. Since current program is W11-complete, `expires_wave: W11` entries must fail.
4. Remove/replace the W11-expired entries for:

```text
src/grace_control/adapters/packet_executor.py
src/grace_control/core/llm_runner.py
```

Required tests:

- direct `import subprocess` in an arbitrary service fails GRC101;
- expired allowlist entry fails;
- packet_executor no longer needs GRC100/GRC101/GRC103 W11 exceptions.

---

### P1-2. Self-evolution still shells out directly

Current `self_evolution_service.py`:

```python
def _build_rollback(project_root: Path) -> SelfEvolutionRollbackPlan:
    import subprocess
    r = subprocess.run(["git", "rev-parse", "HEAD"], ...)
```

This should use `GitService.current_sha()` or a rollback service based on GitService.

Required fix:

- inject/use `GitService`;
- remove direct subprocess import/use;
- add test proving `self_evolution_service.py` has no subprocess usage;
- keep rollback metadata behavior.

---

### P1-3. ApiAgentBackend remains mock-only / structural only

`AgentGatewayService._call_provider()` still supports only `mock`; real providers return unsupported.

This may be acceptable only if explicitly called `mock-only MVP`. But it is not enough to claim that real CLI/legacy execution has been replaced by API agents.

Required next decision:

Option A — make this honest:

- default backend = `mock`;
- docs say W7 is mock-only structural MVP;
- create W7.1 for first real provider.

Option B — make it actually usable:

- implement one real provider adapter;
- make default backend = `api`;
- add fake-provider tests and artifact persistence tests.

---

## P2 still open

### P2-1. `pyproject.toml` still says Prefect

Current metadata:

```toml
description = "GRACE methodology orchestrator — LLM-driven development with Prefect"
```

After W8 this is stale.

Required:

```toml
description = "GRACE methodology orchestrator — API-first LLM-driven development control plane"
```

### P2-2. Runtime deps still include CLI-only deps

Current runtime deps include:

```toml
typer>=0.12.0
rich>=13.7.0
```

If public CLI is removed, these should be moved to `dev` unless runtime code still needs them.

---

## What the recent commits did close

- Documentation was added/regenerated.
- W11 documentation improved.
- GRC104 exists conceptually.
- `packet_executor.py` was reduced to 255 lines.

But line count is not the same as architectural split. The blockers above remain visible in current code.

---

## Required next patch

Create one focused patch:

```text
fix: actually close W0-W11 audit blockers
```

Scope:

```text
src/grace_control/config/settings.py
src/grace_control/adapters/packet_executor.py
src/grace_control/services/* execution split services
src/grace_control/tools/grace_lint/checker.py
.grace/lint_allowlist.yaml
src/grace_control/services/self_evolution_service.py
pyproject.toml
tests/grace_control/*
```

Acceptance:

1. Default backend is not `legacy` and clean default backend selection does not raise.
2. `packet_executor.py` contains no `os.environ`, no `subprocess`, no hardcoded `agent/default/`, no `_call_legacy_runner`, no `legacy_runner_completed`.
3. GraceLint catches direct `import subprocess` outside explicit allowlist.
4. Expired allowlist entries fail lint.
5. Self-evolution rollback uses GitService, not subprocess.
6. pyproject metadata no longer mentions Prefect.
7. CLI-only deps moved out of runtime unless runtime usage is proven by grep/test.

Do not submit another docs-only or line-count-only patch for these findings.
