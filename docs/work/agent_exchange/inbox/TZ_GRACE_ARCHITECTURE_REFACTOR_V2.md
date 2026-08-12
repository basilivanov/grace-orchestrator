# TZ_GRACE_ARCHITECTURE_REFACTOR_V2 — Packet 1: OpenCode legacy removal

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- This is the first bounded implementation packet of Architecture Refactor V2.
- Implement **only Wave 0 baseline capture + OpenCode legacy removal** in this packet.
- Do **not** start control-CLI removal, Admin dependency inversion, lifecycle cleanup, typed DTO work, dead-code cleanup, or CI consolidation. Those are later named packets and require Architect ACCEPT first.

## Mandatory sync before any work

Before reading/inspecting implementation files or changing anything:

```bash
cd /opt/grace-orchestrator
git switch main
git fetch origin main
git merge --ff-only origin/main
git status --short
git rev-parse HEAD
```

Record the synced base SHA and initial `git status --short` in your submission evidence.

Do not use `reset --hard`, `git clean`, or otherwise destroy pre-existing unrelated work. Do not create `state.json`, lock files, orchestration metadata, or any repository-side web-orch state.

## Product decisions for this packet

1. OpenCode-specific runtime is unused legacy and must be physically removed, not disabled or wrapped.
2. Mini-swe is live and must continue to work.
3. `src/grace_control/agent/universal_cli_backend.py` is a generic subprocess backend used by supported execution paths; do **not** delete it merely because its name contains `cli`.
4. `src/grace_control/services/agent_run_service.py` remains unless a specific OpenCode-only branch/helper inside it is proven dead.
5. The user/control CLI (`src/grace_control/cli.py`, `grace_ctl`) is intentionally **out of scope for this packet**. Do not modify/delete it yet.
6. Do not introduce replacement OpenCode adapters, deprecated aliases, feature flags, service locators, generic `BaseService`/`BaseRepository`, or compatibility stubs.
7. Do not change packet states, lifecycle/reviewer/verifier/recovery/merge semantics, DB schema, HTTP API field names, or mini-swe role contracts.
8. No new GRC005/GRC012 allowlist entries. No weakening/skipping of supported tests.

## Current known live OpenCode surface

At packet creation time, `main` still contains the OpenCode runtime stack under `src/grace_control/runtime/`, including:

```text
opencode_runtime_adapter.py
opencode_command_builder.py
opencode_attach_command_builder.py
opencode_event_collector.py
opencode_failure_classifier.py
opencode_server_manager.py
opencode_server_state.py
```

`src/grace_control/adapters/packet_executor.py` currently selects the OpenCode adapter through `agent_runtime_use_opencode_adapter` when no backend was injected.

`src/grace_control/config/agent_profiles.yaml` contains supported mini-swe profiles **and** legacy profiles whose command invokes `opencode`. Remove the OpenCode-command profiles while preserving mini-swe profiles and unrelated supported backends such as `agy` when still referenced.

These observations are starting points, not a substitute for the mandatory repository-wide inventory below.

## Wave 0 — baseline and dependency inventory

Run **before edits** and retain results for the submission summary:

```bash
git status --short
git rev-parse HEAD
python3 --version

git ls-files | rg '(^|/)(\.goldw|\.lw3|\.grace-live-wt)(/|$)|%2Ftmp%2F|\.db($|[-.])|src/gold-test' || true

rg -n -i 'opencode|agent_runtime_use_opencode_adapter|OPENCODE_' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true

rg -n 'grace_control\.cli|grace_ctl|python -m grace_control\.cli' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true

rg -n 'self\._facade|_facade\._hub|_hub\._registry|class .*Mixin' \
  src/grace_control/services/admin_* || true

rg -n '\._artifact_service\s*=|\._session_service\s*=|\._pipeline\s*=' \
  src/grace_control/services/admin_* || true

rg -n 'os\.environ|subprocess|get_db\(|\.query\(|supervisor\.json|supervisor\.sock' \
  src/grace_control/api/routers/lifecycle.py || true
```

The CLI/admin/lifecycle scans are baseline-only in this packet. **Do not fix those areas yet.**

Run the current targeted gates before edits and record any existing failure exactly:

```bash
python3 scripts/grace_lint.py src/grace_control tests scripts
python -m ruff check src/grace_control tests scripts
pytest -q tests/grace_control/runtime tests/grace_control/agent || true
```

Do not spend this packet fixing unrelated baseline failures. However, your final required checks for the touched OpenCode/mini-swe surface must be green before submission.

## Implementation scope

Primary allowed paths:

```text
src/grace_control/runtime/opencode_*.py              # delete
src/grace_control/runtime/__init__.py                # remove deleted exports/imports if present
src/grace_control/adapters/packet_executor.py        # remove OpenCode selection branch only
src/grace_control/config/settings.py                 # remove OpenCode-only settings
src/grace_control/config/project_config.py           # remove OpenCode-only config mapping if present
src/grace_control/config/agent_profiles.yaml         # remove OpenCode-command profiles
src/grace_control/config/agent_profiles.py           # remove fields only when proven OpenCode-only/dead
src/grace_control/agent/universal_cli_backend.py     # remove OpenCode-only env/branches; preserve generic backend
src/grace_control/services/agent_run_service.py      # remove OpenCode-only session/compat logic; preserve generic live behavior
src/grace_control/config/                            # only directly related OpenCode config cleanup
src/grace_control/runtime/                           # only directly related import/export cleanup
tests/grace_control/                                 # delete OpenCode-only tests; add focused architecture guards
docs/grace/                                          # active docs only
README.md
AGENTS.md
docs/SUPERVISOR.md
pyproject.toml                                       # only if OpenCode-only dependency/config is proven
scripts/                                             # only OpenCode-specific active references, not control CLI bootstrap
docker/                                              # only OpenCode-specific active references
```

Frozen/out of scope for this packet unless a test import must be adjusted solely because an OpenCode module was deleted:

```text
src/grace_control/cli.py
scripts/live_supervisor.sh
src/grace_control/api/routers/lifecycle.py
src/grace_control/services/admin_*
.github/workflows/ci.yml
Makefile
high-confidence hello/demo/dead-code candidates
tracked runtime-artifact cleanup
Architecture Refactor later-wave implementation
```

Do not modify historical `docs/work/EVIDENCE_OPENCODE_*.md` simply to erase the word OpenCode. Historical evidence may remain.

## Required implementation

### 1. Inventory every live OpenCode dependency before deleting

Run:

```bash
rg -n -i 'opencode|agent_runtime_use_opencode_adapter|OPENCODE_' src tests scripts pyproject.toml docker
```

Classify every hit while working as one of:

- implementation to delete;
- generic code containing an OpenCode-only branch to simplify;
- active profile/config to remove;
- OpenCode-only test to delete/replace;
- historical/non-runtime false positive.

Do not delete files first and then blindly chase import errors.

### 2. Physically delete the OpenCode runtime stack

Delete all existing `src/grace_control/runtime/opencode_*.py` runtime implementation files, including the seven known files listed above.

Inspect `src/grace_control/runtime/__init__.py` and remove exports/imports referring to deleted modules.

Do not leave stubs, aliases, disabled adapters, compatibility re-exports, or feature-flagged dead implementations.

### 3. Remove OpenCode backend selection from PacketExecutionAdapter

In `src/grace_control/adapters/packet_executor.py`, remove the current `agent_runtime_use_opencode_adapter` branch and dynamic import of `grace_control.runtime.opencode_runtime_adapter`.

Required behavior:

```text
backend injected -> use injected backend
backend not injected -> use canonical existing generic backend selection (`select_backend()`)
```

Do not change surrounding packet execution, acceptance, recovery, observability, worktree, or merge behavior.

### 4. Remove OpenCode-only settings and config mapping

Search each field before removal. Remove settings/config fields used only by the deleted OpenCode runtime or its compatibility branches, including current families equivalent to:

```text
agent_runtime_use_opencode_adapter
opencode_binary
opencode_direct_timeout_seconds
opencode_process_kill_grace_seconds
opencode_json_events_required
opencode_capture_raw_events
opencode_runtime_mode
opencode_server_host
opencode_server_port
opencode_server_url
opencode_server_password
opencode_server_start_timeout_seconds
opencode_server_health_timeout_seconds
opencode_server_restart_on_unhealthy
opencode_server_log_path
opencode_server_pid_path
opencode_server_kill_grace_seconds
```

If `project_config.py` has an OpenCode-only schema/mapping, remove it too.

Do not remove OpenAI-compatible proxy settings used by mini-swe merely because they are adjacent to old OpenCode settings.

### 5. Remove OpenCode-command profiles, preserve mini-swe

In `src/grace_control/config/agent_profiles.yaml`:

- preserve profiles invoking `python -m grace_control.runtime.mini_swe_runner`;
- delete every profile whose execution command invokes `opencode`;
- delete disabled OpenCode profiles too;
- do not rename/reorder supported mini-swe profiles except where removal naturally closes gaps;
- keep unrelated non-OpenCode supported profiles when still referenced.

After editing:

```bash
rg -n -i 'opencode' src/grace_control/config/agent_profiles.yaml
```

Expected: zero live hits.

### 6. Simplify AgentProfile only with proof

In `src/grace_control/config/agent_profiles.py`, inspect legacy-looking fields such as `resume_flag`, `fork_flag`, `inject_dir`, `resume_mode`, `resume_safe`, `validate_session_before_use` and similar knobs.

For each candidate:

1. search remaining non-OpenCode profiles;
2. search remaining runtime consumers/tests;
3. remove it only if no supported non-OpenCode path uses it;
4. otherwise keep the generic field and remove only OpenCode-specific assumptions/comments.

Do not turn this into a generic profile-model rewrite.

### 7. Remove OpenCode-specific logic from generic execution services

`src/grace_control/agent/universal_cli_backend.py`:

- remove OpenCode server URL/password environment injection and helpers used solely for those variables;
- preserve generic executor env handling, command rendering, `AgentRunService`, artifacts/stdout/stderr, and mini-swe behavior.

`src/grace_control/services/agent_run_service.py`:

- remove OpenCode-specific session-id patterns/validators/helpers;
- remove binary-name fallbacks that special-case `opencode`;
- remove comments/contracts presenting OpenCode as a supported runtime;
- preserve generic resume/session capability only where a remaining non-OpenCode profile genuinely uses it;
- preserve cwd/worktree safety.

### 8. Delete OpenCode-only tests and add durable architecture guards

Find all relevant tests:

```bash
find tests -type f | sort | rg -i 'opencode' || true
rg -l -i 'opencode' tests || true
```

Delete tests whose sole purpose is preserving removed OpenCode behavior. Do not rewrite them to preserve a stub.

Add a focused guard test, preferably:

`tests/grace_control/architecture/test_no_opencode_legacy.py`

It must prove at least:

1. no `src/grace_control/runtime/opencode_*.py` exists;
2. settings do not define `agent_runtime_use_opencode_adapter` or `opencode_*` fields;
3. active `agent_profiles.yaml` has no OpenCode command/profile;
4. `packet_executor.py` has no OpenCode runtime import/feature-flag branch;
5. active source/tests/scripts do not import OpenCode runtime modules.

Do not scan historical `docs/work/` in this guard.

### 9. Update active docs only

Remove claims/instructions that present OpenCode as supported from active docs, inspecting at least:

```text
docs/grace/RUNBOOK_AGENT_PROFILES.md
docs/grace/RUNBOOK_LOCAL_DEV.md
docs/grace/RUNBOOK_DEBUG_PACKET.md
docs/grace/EXECUTION_BACKENDS.md
docs/SUPERVISOR.md
README.md
AGENTS.md
```

Do not rewrite unrelated documentation and do not edit historical evidence solely for keyword cleanliness.

## Required verification before commit

Run all of the following after implementation:

```bash
rg -n -i 'opencode|agent_runtime_use_opencode_adapter|OPENCODE_' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true
```

Allowed remaining hits in this scan: deliberate negative architecture-guard assertions only. Any active implementation/config/profile/runbook hit is a failure.

Then run:

```bash
pytest -q tests/grace_control/runtime tests/grace_control/agent
pytest -q tests/grace_control/architecture/test_no_opencode_legacy.py
python3 scripts/grace_lint.py src/grace_control tests scripts
python -m ruff check src/grace_control tests scripts
git diff --check
```

Also run the narrow packet-executor tests that cover default/injected backend selection and any directly affected profile/config tests discovered during implementation.

Mini-swe must remain operational; deleting `UniversalCliAgentBackend`, `mini_swe_runner.py`, or generic process/env execution is an automatic failure.

## Commit and submission protocol

1. Review `git diff` and ensure only this packet's scope is present.
2. Commit the implementation.
3. Push the implementation commit to `origin/main`.
4. Capture the exact implementation commit SHA.
5. Create **only**:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_SUBMISSION.md`

Do not create any other outbox/report/state/lock file.

The submission file MUST begin with these exact lines, replacing only the SHA placeholder:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <implementation-commit-sha>
WEB_ORCH_CHECKS: PASS
```

After those lines, include concise evidence:

- synced base SHA;
- implementation commit SHA;
- deleted OpenCode runtime files;
- removed settings/profile/generic compatibility branches;
- preserved mini-swe/generic execution paths;
- exact verification commands and pass results;
- any intentionally retained `opencode` text and why it is historical/negative-test-only.

Commit and push the submission file to `origin/main` as a separate documentation commit if necessary so the submission can truthfully reference the already-created implementation SHA.

Do not start the control-CLI packet or any other Architecture Refactor V2 work. Wait for Architect decision.

## Acceptance criteria for this packet

Architect will ACCEPT only if all are true:

1. OpenCode runtime implementation files are physically gone.
2. No OpenCode runtime compatibility alias/stub/feature flag remains.
3. `PacketExecutionAdapter` default selection no longer has an OpenCode branch.
4. OpenCode-only settings/config are removed without deleting live mini-swe/OpenAI-compatible proxy settings.
5. `agent_profiles.yaml` contains no OpenCode-command profile and retains supported mini-swe profiles.
6. Generic execution services contain no OpenCode-specific env/session/binary behavior.
7. OpenCode-only tests are removed and durable negative architecture guards exist.
8. Active docs do not recommend OpenCode; historical `docs/work/` evidence was not needlessly rewritten.
9. Mini-swe/runtime/agent regression tests pass.
10. GRACE lint, Ruff, and `git diff --check` pass for the required scope.
11. No control-CLI/admin/lifecycle/dead-code/CI later-wave work was started.
12. Submission file follows the exact WEB_ORCH protocol and references a real pushed implementation commit.
