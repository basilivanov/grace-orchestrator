# Review: `c361fe6` follow-up after W0-W11 blockers

Date: 2026-06-05
Reviewed commit/state: current `main` after `c361fe6` push.
Previous review: `source/codex/review-2026-06-05-w0-w11-followup-still-open.md`

## Verdict

Partially accepted. Most P0/P2 items are now fixed, but W6/W10 are still not fully accepted because `packet_executor.py` still owns direct git subprocess cleanup and GraceLint now defers that debt to W12 instead of enforcing the W0-W11 completion criteria.

## Fixed items

### Fixed: default backend is no longer `legacy`

`src/grace_control/config/settings.py` now has:

```python
execution_backend: str = "api"  # "api" | "mock" — see grace_control.agent.select_backend
```

This closes the default-runtime breakage from the previous review.

### Fixed: self-evolution rollback no longer calls subprocess directly

`self_evolution_service.py` now uses:

```python
from grace_control.services.worktree_inspector import WorktreeInspector
sha = WorktreeInspector().base_sha(project_root)
```

instead of `subprocess.run(["git", "rev-parse", "HEAD"], ...)`.

### Fixed: pyproject metadata and CLI deps

`pyproject.toml` description no longer says Prefect and runtime deps no longer include `typer` / `rich`. They moved to dev dependencies, which matches the CLI removal direction.

### Improved: `packet_executor.py` naming

`_call_legacy_runner` was renamed to `_call_executor`, `legacy_runner_completed` became `executor_run_completed`, and `GRACE_BASE_REF` env read was replaced by `settings.base_branch`.

Good direction, but not enough for W6/W10 completion.

---

## Still open blocker

### P0/P1. `packet_executor.py` still owns direct subprocess/git cleanup

Current `src/grace_control/adapters/packet_executor.py` still contains:

```python
def _git_worktree_cleanup(project_root: Path, slug: str) -> None:
    import subprocess, shutil
    ...
    subprocess.run(["git", "-C", str(project_root), "worktree", "prune"], ...)
    subprocess.run(["git", "-C", str(project_root), "worktree", "remove", ...], ...)
    subprocess.run(["git", "-C", str(project_root), "branch", "-D", f"agent/{slug}"], ...)
```

And `_load_packet()` still calls:

```python
_git_worktree_cleanup(self.project_root, f"{packet_id}-{slug}")
```

This violates the W6/W10 acceptance criteria from the previous review:

- no direct `subprocess` in `packet_executor.py`;
- git cleanup must live behind `GitService` / `WorktreeInspector` / dedicated cleanup service;
- executor should orchestrate services, not shell out;
- GraceLint should catch this, not allowlist it.

### Required fix

Move this helper out of `packet_executor.py` into a service, preferably one of:

```text
src/grace_control/services/worktree_cleanup_service.py
```

or extend `GitService` / `WorktreeInspector` with a cleanup method.

Expected shape:

```python
class WorktreeCleanupService:
    def cleanup_attempt(self, project_root: Path, packet_id: str, attempt_slug: str) -> None:
        ... uses GitService ...
```

Then `packet_executor.py` should do only:

```python
self._worktree_cleanup.cleanup_attempt(self.project_root, packet_id, slug)
```

No `import subprocess`, no `shutil`, no direct `git` command lists inside `packet_executor.py`.

Required tests:

1. `packet_executor.py` contains no `subprocess` string.
2. `packet_executor.py` contains no `import os` if unused.
3. cleanup service calls GitService methods or is itself explicitly allowed by GRC101.
4. PacketExecutionAdapter still creates/reuses `PacketRun` correctly.

---

## GraceLint still too permissive

Current `checker.py` still has:

```python
ALLOWED_SUBPROCESS = {"services/git_service.py", "services/", "scripts/", "tests/"}
```

This allows `subprocess` in any service. That is broader than the architecture rule. It should be explicit, not directory-wide.

Current `.grace/lint_allowlist.yaml` also extends the old debt to W12:

```yaml
- rule: GRC101
  path: src/grace_control/adapters/packet_executor.py
  reason: _git_worktree_cleanup shells out to git worktree prune/remove
  expires_wave: W12
```

This is a deferral, not a fix. It may be acceptable only if W12 is explicitly created as a follow-up cleanup wave, but it should not be counted as W0-W11 complete.

### Required fix

1. Narrow `ALLOWED_SUBPROCESS` to:

```python
ALLOWED_SUBPROCESS = {"services/git_service.py", "scripts/", "tests/"}
```

or an exact path allowlist.

2. Remove the `packet_executor.py` GRC101 allowlist once cleanup moves out.

3. Add a test that an arbitrary service file containing `import subprocess` fails GRC101.

4. Add a test that `packet_executor.py` no longer needs GRC100/GRC101 allowlist entries.

---

## Minor notes

### `packet_executor.py` still has unused-looking `import os`

The visible code no longer uses `os.environ`, but the file still imports `os`:

```python
import os, time
```

Remove if unused. If it is used below, route that through settings/config.

### Packet registry remains inside executor

`_call_executor()` still writes `packet_registry.yaml` under `state_root / "state"`. This looks like old compatibility behavior. It is not an immediate blocker if needed by ApiAgentBackend evidence flow, but should be documented or moved into a compatibility service.

### ApiAgentBackend remains mock/structural unless real provider is added

This was already noted. It is acceptable only if docs say W7 is structural/mock MVP and a later W7.1 will wire the first real provider.

---

## Status update

Previously open items now closed:

- default backend legacy issue: closed;
- self-evolution subprocess rollback: closed;
- pyproject Prefect metadata: closed;
- runtime typer/rich deps: closed;
- env read in executor base_ref: closed.

Still open:

- executor direct subprocess/git cleanup;
- GraceLint broad subprocess allowlist;
- packet_executor GRC101 allowlist deferral.

## Required next patch

Create a small focused patch:

```text
fix: move executor git cleanup behind service and tighten GraceLint subprocess rule
```

Scope:

```text
src/grace_control/adapters/packet_executor.py
src/grace_control/services/git_service.py or src/grace_control/services/worktree_cleanup_service.py
src/grace_control/tools/grace_lint/checker.py
.grace/lint_allowlist.yaml
tests/grace_control/*
```

Acceptance:

1. `packet_executor.py` contains no `subprocess`, no `shutil`, and no direct git command arrays.
2. GraceLint GRC101 catches `import subprocess` in arbitrary services.
3. `ALLOWED_SUBPROCESS` is explicit, not all `services/`.
4. `.grace/lint_allowlist.yaml` no longer contains packet_executor GRC101.
5. Tests pass.

After that, the W0-W11 audit can be accepted, with the separate caveat that real provider support for ApiAgentBackend is a future W7.1 product capability rather than a cleanup blocker.
