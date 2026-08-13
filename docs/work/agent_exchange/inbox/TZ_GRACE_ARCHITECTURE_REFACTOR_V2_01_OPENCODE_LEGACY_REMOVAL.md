# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_01_OPENCODE_LEGACY_REMOVAL — Packet 01: OpenCode legacy removal

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_01_OPENCODE_LEGACY_REMOVAL`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent source: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
- Normative detail: Architecture Refactor V2 Wave 0 baseline/inventory + the OpenCode-removal portion of Wave 1.
- This is a new-cycle packet. Historical `docs/work/agent_exchange/*` files from earlier cycles are evidence only and MUST NOT be edited, renamed, reused as output, or treated as authorization for later packets.

Implement only the work in this named packet. Do not start control-CLI removal, Admin dependency inversion, lifecycle extraction, typed read models, dead-code cleanup, or CI consolidation. Those require a later named TZ created by Architect after ACCEPT.

## Mandatory fast-forward sync before work

Before inspecting implementation files or editing anything:

```bash
cd /opt/grace-orchestrator
git switch main
git fetch origin --prune
git pull --ff-only origin main
git status --short --branch
git rev-parse HEAD
```

Record synced base SHA and initial status in the submission.

Do not use `git reset --hard`, `git clean`, destructive checkout, or repo-side orchestration metadata. Preserve unrelated untracked files.

## Current-state rule for this new cycle

The repository may already contain implementation from an earlier Architecture Refactor V2 cycle. Current `main` is authoritative.

Therefore:

1. Do not recreate deleted OpenCode files merely because the parent TZ names them as historical starting-state files.
2. Do not manufacture source edits if the complete packet contract is already satisfied.
3. If current `main` already satisfies every acceptance criterion, perform the required audit/checks and submit a **verified no-op** using the synced `HEAD` as `WEB_ORCH_COMMIT`; state explicitly that the implementation delta for this packet is zero because the required target state already exists.
4. If gaps exist, make only the smallest changes necessary to satisfy this packet and commit/push them before submission.
5. Do not use earlier-cycle submission text as proof; re-check the current repository yourself.

## Product decisions

1. OpenCode-specific runtime is unsupported legacy and must not exist in active source/config/tests/runbooks.
2. Mini-swe remains supported and must continue working.
3. `UniversalCliAgentBackend` and generic subprocess execution are internal execution infrastructure, not the removed operator CLI; preserve them.
4. The user/control CLI is out of scope for this packet. Do not remove or refactor it here even if references are found during baseline inventory.
5. Packet lifecycle, reviewer/verifier/acceptance/recovery/merge semantics, DB schema, API routes/field names and persisted state values are frozen.
6. No new `GRC005`/`GRC012` allowlist entries and no test weakening.
7. No compatibility stub, disabled adapter, alias, feature flag or replacement OpenCode wrapper may be introduced.

## Wave 0 — baseline and dependency inventory

Run before edits and retain concise evidence:

```bash
git status --short
git rev-parse HEAD
python3 --version

git ls-files | rg '(^|/)(\.goldw|\.lw3|\.grace-live-wt)(/|$)|%2Ftmp%2F|\.db($|[-.])|src/gold-test' || true

rg -n -i 'opencode|agent_runtime_use_opencode_adapter|OPENCODE_' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true

rg -n 'grace_control\.cli|grace_ctl|python -m grace_control\.cli' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true
```

The control-CLI scan is inventory only. Do not fix it in this packet.

Also inspect current OpenCode-related file/reference ownership rather than assuming the historical file layout is still present.

## Required target state

### 1. No active OpenCode runtime stack

There must be no live `src/grace_control/runtime/opencode_*.py` implementation.

If any such files exist, remove them and remove active imports/exports. Do not leave stubs or re-export aliases.

### 2. No OpenCode backend-selection branch

Inspect `src/grace_control/adapters/packet_executor.py` and related backend selection.

Required behavior:

```text
backend injected -> use injected backend
backend not injected -> use the current canonical non-OpenCode backend selection path
```

There must be no `agent_runtime_use_opencode_adapter` branch and no dynamic/static import of an OpenCode runtime adapter.

Do not alter surrounding packet execution, worktree, acceptance, recovery, observability or merge behavior.

### 3. No OpenCode-only settings/config

Inspect current config/settings/project config and remove any live setting/schema/mapping owned only by OpenCode, including equivalents of:

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

Search each candidate before deleting. Preserve settings used by mini-swe, Agy, OpenAI-compatible proxies, or other proven live non-OpenCode paths.

### 4. No OpenCode-command agent profile

Inspect `src/grace_control/config/agent_profiles.yaml` and related profile model.

- preserve mini-swe profiles;
- preserve unrelated proven live providers/backends;
- remove any profile or command invoking `opencode`;
- remove legacy profile fields only when no remaining non-OpenCode profile/runtime consumer needs them.

Do not turn profile cleanup into a broad model rewrite.

### 5. Generic execution remains generic

Inspect at least:

```text
src/grace_control/agent/universal_cli_backend.py
src/grace_control/services/agent_run_service.py
src/grace_control/runtime/mini_swe_runner.py
```

Remove only OpenCode-specific env/session/binary assumptions if any remain. Preserve generic command rendering, process execution, cwd/worktree safety, session capability used by another provider, artifacts/stdout/stderr and mini-swe behavior.

### 6. Tests/guards

Delete only tests whose sole contract is removed OpenCode behavior.

A durable architecture guard must prove, directly or equivalently:

1. no OpenCode runtime implementation modules exist;
2. settings/config expose no OpenCode runtime switch/fields;
3. active profiles contain no OpenCode command/profile;
4. packet executor/backend selection has no OpenCode runtime branch;
5. active source/tests/scripts do not import OpenCode runtime modules.

Historical `docs/work/` evidence must not be scanned as a failure condition.

If an equivalent strong guard already exists and passes, do not duplicate it just to create a diff.

### 7. Active docs only

Active docs/runbooks must not present OpenCode as supported. Inspect current relevant docs discovered by search, including as applicable:

```text
docs/grace/RUNBOOK_AGENT_PROFILES.md
docs/grace/RUNBOOK_LOCAL_DEV.md
docs/grace/RUNBOOK_DEBUG_PACKET.md
docs/grace/EXECUTION_BACKENDS.md
docs/SUPERVISOR.md
README.md
AGENTS.md
```

Do not rewrite historical `docs/work/` evidence solely to remove the word `opencode`.

## Frozen/out-of-scope areas

Do not intentionally modify in this packet:

```text
control/user CLI removal
scripts/live_supervisor.sh for CLI migration
Admin Control Center dependency inversion
cross-project service composition
admin aggregation cycle removal
lifecycle router/service extraction
typed admin read models
dead-code/repo-hygiene programme
Makefile / CI single-source-of-truth work
DB schema/Alembic
public HTTP/OpenAPI contracts
```

A directly affected test/import adjustment is allowed only when required by an OpenCode deletion and must be explained.

## Required verification

Run the current relevant tests discovered in the repository plus at minimum:

```bash
rg -n -i 'opencode|agent_runtime_use_opencode_adapter|OPENCODE_' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true
```

Allowed remaining hits: deliberate negative guard assertions and clearly historical/non-runtime evidence outside active docs. Any active implementation/config/profile/runbook support hit is a failure.

Then run:

```bash
pytest -q tests/grace_control/runtime tests/grace_control/agent
python3 scripts/grace_lint.py src/grace_control tests scripts
python -m ruff check src/grace_control tests scripts
git diff --check
```

Also run the specific architecture guard and directly affected packet-executor/profile/config tests that exist on current `main`.

If canonical repository lint is baseline-aware/non-zero underneath, report both the canonical gate result and raw audit result exactly; do not claim a raw exit 1 is exit 0.

## Implementation and submission

If changes are required:

1. keep the diff inside this packet's scope;
2. commit implementation;
3. push implementation commit to `origin/main`;
4. capture full 40-character implementation SHA.

If no changes are required because current `main` already satisfies the packet, do not create fake edits; use the synced `HEAD` SHA and report verified no-op explicitly.

After implementation/audit create **only**:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_01_OPENCODE_LEGACY_REMOVAL_SUBMISSION.md`

Do not create another task, review, state, lock, progress or metadata file.

The submission MUST begin with these exact lines:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_01_OPENCODE_LEGACY_REMOVAL
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-40-char-commit-sha>
WEB_ORCH_CHECKS: PASS
```

Then include concise evidence:

- synced base SHA;
- implementation SHA or explicit verified-no-op statement;
- current OpenCode inventory and what was removed/already absent;
- mini-swe/generic execution preservation proof;
- exact tests/checks with results;
- remaining `opencode` hits and why each class is negative-guard/historical only;
- changed-file list, or `none` for a verified no-op.

Do not start the next packet. Wait for Architect ACCEPT/REVIEW.

## Acceptance criteria

Architect will ACCEPT only if all are true:

1. OpenCode runtime implementation is absent from active source.
2. No OpenCode feature flag/config/profile/runtime selection remains.
3. Generic mini-swe/subprocess execution remains supported.
4. No unsupported OpenCode session/env/binary compatibility survives in generic services.
5. Strong negative architecture coverage exists and passes.
6. Active docs do not recommend OpenCode.
7. No control-CLI/admin/lifecycle/dead-code/CI later-wave work is mixed into the delta.
8. Frozen API/DB/lifecycle semantics did not change.
9. Required focused checks and repository gates are truthfully reported.
10. Submission follows the exact named-file protocol and uses a full 40-character SHA.
