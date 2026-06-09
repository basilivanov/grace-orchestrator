# TZ: Real-Agent Wave Resume Testing Harness

Status: draft for coder implementation  
Scope: live/dev regression testing with real agents, not mocks  
Depends on:

- `docs/work/tz-dev-run-replay-checkpoints.md`
- `docs/work/tz-dev-replay-admin-ui.md`

## 1. Problem

Current automated tests mostly prove control-plane behavior with mocks/fakes. That is useful, but it does not catch failures that only happen with real CLI agents, real session resume, real worktrees, real frontend/backend edits, and real acceptance commands.

The project needs a fast live-regression harness that can run real agents through small controlled GRACE waves:

```text
1 wave: backend-only or frontend-only
2 waves: backend + frontend
3 waves: backend + frontend + integration/fullstack polish
```

The important requirement is speed after failure. If a real run fails in a stage, the developer must be able to resume/replay from that exact stage instead of restarting the whole pipeline.

## 2. What we already have

This TZ must reuse the already implemented mechanisms instead of reinventing them.

### 2.1 Agent session resume

The orchestrator already tracks agent sessions in `agent_sessions` and supports resume behavior through agent profiles.

Conceptual flow:

```text
agent role + executor_id + packet_id + attempt
-> external CLI session id is captured
-> later retry can pass resume/fork flag to the same CLI agent
```

This handles LLM-side continuation:

```text
architect/coder conversation can continue from previous session
```

It does not by itself rerun only T1/T2/verifier. That part is handled by dev replay.

### 2.2 Dev run replay / checkpoints

The dev replay feature stores failed run metadata:

```text
worktree_path
branch_name
base_sha
agent_commit_sha
changed_files
failed_stage
agent.patch
```

and exposes:

```http
POST /api/dev/runs/{run_id}/replay-acceptance
POST /api/dev/runs/{run_id}/rerun-verifier
POST /api/dev/runs/{run_id}/rerun-reviewer
```

This handles deterministic stage replay:

```text
T0/T1/T2/verifier/reviewer can rerun without context builder, architect, or coder
```

### 2.3 Combined model

The live testing harness must combine both mechanisms:

```text
agent_sessions resume -> when we need the real agent to continue/fix code

dev replay endpoints -> when we only need to rerun failed acceptance/verifier/reviewer stage
```

This is how fast real-agent testing is implemented.

## 3. Goal

Build a live/dev test harness that runs real GRACE packets/waves against controlled fixture applications using real agents and validates that resume/replay works across failures.

The harness must support:

```text
backend-only live run
frontend-only live run
fullstack live run
1-wave scenario
2-wave scenario
3-wave scenario
failure injection at T0/T1/T2/verifier/reviewer
resume from same stage
agent resume when code fix is needed
```

This is not a CI-default test suite. It is a deliberate live/dev regression suite for real agents.

## 4. Non-goals

Do not replace unit/API/mock tests.

Do not run real-agent tests in normal CI by default.

Do not require API keys for regular test runs.

Do not call live agents from tests named `unit` or from the default `pytest` path.

Do not create large product features in fixture apps.

Do not benchmark model quality. This harness validates orchestration, resume, replay, artifacts, and acceptance flow.

Do not auto-merge live-agent results into `main`.

## 5. Proposed command surface

Add a dedicated command or script. Prefer API-first architecture, but a thin script/CLI may be acceptable if it only orchestrates existing API calls.

Suggested command:

```bash
python -m grace_control.live_tests.run_wave_resume \
  --scenario backend-1w \
  --target-dir /tmp/grace-live-test \
  --source-dir /path/to/grace-orchestrator \
  --agent-profile coder_opencode \
  --max-waves 1
```

Alternative if project has existing script style:

```bash
scripts/live_agent_wave_test.sh --scenario backend-1w --max-waves 1
```

Required scenarios:

```text
backend-1w
frontend-1w
fullstack-2w
fullstack-3w
resume-t2-failure
resume-verifier-failure
resume-coder-fix
```

## 6. Environment flags

Live tests must be opt-in.

Required env:

```bash
export GRACE_LIVE_AGENT_TESTS=1
export GRACE_DEV_TOOLS_ENABLED=1
export GRACE_DEV_KEEP_FAILED_WORKTREES=1
```

Optional env:

```bash
export GRACE_LIVE_TEST_AGENT_PROFILE=coder_opencode
export GRACE_LIVE_TEST_ARCHITECT_PROFILE=architect-premium
export GRACE_LIVE_TEST_TARGET_DIR=/tmp/grace-live-test
export GRACE_LIVE_TEST_TIMEOUT_SECONDS=1800
export GRACE_LIVE_TEST_KEEP_ARTIFACTS=1
```

Rules:

- If `GRACE_LIVE_AGENT_TESTS` is not enabled, live tests must skip with a clear message.
- Dev replay flags must be required for resume/replay scenarios.
- Do not read env directly outside the existing config/settings boundary if implemented inside app code.

## 7. Fixture applications

Create small controlled fixture apps for real changes.

Suggested location:

```text
tests_live/fixtures/apps/backend_fastapi_todo/
tests_live/fixtures/apps/frontend_static_counter/
tests_live/fixtures/apps/fullstack_todo_admin/
```

Fixture apps must be tiny but realistic.

### 7.1 Backend fixture

Minimal FastAPI app:

```text
GET /health
GET /items
POST /items
```

Live task examples:

```text
Wave 1: add PATCH /items/{id}/done
Wave 1: add validation error for empty title
Wave 1: add tests for new endpoint
```

Acceptance:

```text
pytest
ruff or equivalent lint
```

### 7.2 Frontend fixture

Minimal static or HTMX UI.

Live task examples:

```text
Wave 1: add a filter button
Wave 1: add empty-state text
Wave 1: add client-side validation
```

Acceptance:

```text
node --check changed JS files
HTML/template smoke check
optional Playwright smoke if already available
```

Important:

Previous admin UI bugs happened because JavaScript broke only at runtime. Frontend live tests must include a JS syntax check.

### 7.3 Fullstack fixture

Tiny backend + frontend integration.

Live task examples:

```text
Wave 1: backend endpoint
Wave 2: frontend calls endpoint
Wave 3: integration smoke / UX polish / error state
```

Acceptance:

```text
backend tests
frontend JS syntax check
integration smoke command
```

## 8. Scenario definitions

Create declarative scenario files rather than hardcoding everything.

Suggested location:

```text
tests_live/scenarios/backend-1w.yaml
tests_live/scenarios/frontend-1w.yaml
tests_live/scenarios/fullstack-2w.yaml
tests_live/scenarios/fullstack-3w.yaml
tests_live/scenarios/resume-t2-failure.yaml
tests_live/scenarios/resume-verifier-failure.yaml
tests_live/scenarios/resume-coder-fix.yaml
```

Example:

```yaml
id: backend-1w
fixture_app: backend_fastapi_todo
real_agent_required: true
waves:
  - id: W1
    title: Add done endpoint
    packets:
      - id: P1
        role: coder
        prompt: |
          Add PATCH /items/{id}/done and tests.
        verification:
          t0:
            commands:
              - ruff check .
          t1:
            commands:
              - pytest -q
          t2:
            commands: []
expected:
  final_state: accepted
  min_real_agent_runs: 1
  max_context_runs_after_resume: 0
  max_architect_runs_after_resume: 0
```

## 9. Resume/replay semantics

The harness must use the right recovery path depending on failure kind.

### 9.1 Failure in deterministic stage

If failure is in:

```text
T0
T1
T2
```

then first action is replay, not agent rerun:

```http
POST /api/dev/runs/{run_id}/replay-acceptance
```

This verifies that a transient/environmental/deterministic check can be rerun without LLM cost.

### 9.2 Failure in verifier/reviewer

If failure is in:

```text
evidence verifier
reviewer
```

then first action is stage replay:

```http
POST /api/dev/runs/{run_id}/rerun-verifier
POST /api/dev/runs/{run_id}/rerun-reviewer
```

No coder/architect/context call is allowed.

### 9.3 Failure requiring code change

If acceptance or reviewer says the implementation itself is wrong, then the harness may trigger a real agent retry.

Required behavior:

```text
same packet -> retry/next attempt -> coder resumes from previous agent session if profile resume_mode allows it
```

The harness must verify:

```text
previous external session id exists
new agent request includes resume_session_id or fork_session when expected
new run stores a new session or linked session
```

### 9.4 New architect only after recovery ladder threshold

The harness must not invoke architect again during normal stage replay.

Architect rerun is allowed only for scenarios explicitly testing recovery ladder behavior.

## 10. Live test runner responsibilities

Add a runner service/module, for example:

```text
src/grace_control/live_tests/wave_resume_runner.py
```

or keep it outside package if project prefers test-only code:

```text
tests_live/runner/wave_resume_runner.py
```

Responsibilities:

1. Copy fixture app to an isolated temp target dir.
2. Start GRACE API/supervisor or connect to an existing local API.
3. Submit explicit waves to `/api/architect/plan` or equivalent API so context/architect can be skipped when desired.
4. Run packets/waves through real configured agent profiles.
5. Capture run IDs and trace data.
6. Detect failed stage from trace/result JSON.
7. Trigger dev replay endpoint for stage-level failures.
8. Trigger packet retry for code-fix failures and verify agent session resume.
9. Save a live test report.
10. Never merge live test changes into the source repo by default.

## 11. Explicit waves mode

The harness should prefer explicit waves for speed.

Reason:

```text
If waves are supplied explicitly, architect/context can be skipped or minimized.
```

This makes the live tests deterministic enough for regression use.

Scenario YAML must define waves/packets directly.

Optional separate scenario may test real architect generation, but that is not part of MVP.

## 12. Failure injection

Add controlled failure injection so resume/replay can be tested reliably.

### 12.1 T2 failure once

A command fails the first time and passes the second time:

```bash
python tests_live/helpers/fail_once.py --key t2-smoke
```

Expected:

```text
first run -> T2 failed
replay T2 -> passed
no coder rerun
```

### 12.2 Verifier failure once

A fake/real verifier wrapper or fixture condition causes a one-time verifier failure.

Expected:

```text
first verifier -> failed
rerun-verifier -> passed
no coder rerun
```

### 12.3 Code bug requiring coder resume

Scenario asks coder to implement a tiny feature. The first attempt intentionally has a likely failing acceptance or the scenario injects a review issue requiring code fix.

Expected:

```text
first run -> rejected
retry same packet -> coder resumes from previous session
second run -> accepted
```

Do not make this flaky. Keep the requested feature tiny and acceptance explicit.

## 13. Artifacts

Each live test run must write a report under:

```text
.grace/live-tests/<scenario-id>/<timestamp>/
```

Required artifacts:

```text
scenario.yaml
summary.json
trace.json
runs/<run_id>.json
agent_sessions.json
replay_attempts.json
commands.log
stdout.log
stderr.log
```

Summary JSON shape:

```json
{
  "scenario_id": "fullstack-2w",
  "status": "passed",
  "waves_requested": 2,
  "packets_total": 3,
  "real_agent_runs": 3,
  "context_runs": 0,
  "architect_runs": 0,
  "coder_runs": 3,
  "acceptance_replays": 1,
  "verifier_replays": 0,
  "reviewer_replays": 0,
  "agent_session_resumes": 1,
  "packet_state_changed_by_replay": false,
  "artifacts_dir": "..."
}
```

## 14. Guardrails

The harness must enforce:

```text
No live agent tests unless GRACE_LIVE_AGENT_TESTS=1
No replay endpoints unless GRACE_DEV_TOOLS_ENABLED=1
No cleanup of failed worktrees during live resume scenarios
No merge to main by default
No destructive git operations outside temp target dir
No real-agent calls in default pytest suite
No hidden fallback to mocks unless scenario explicitly says mock
```

If a scenario says `real_agent_required: true`, the runner must fail if it detects mock backend.

## 15. Tests for the harness itself

Even though the harness runs real agents only in opt-in mode, the harness code still needs normal tests with fakes.

Required normal tests:

```text
tests/grace_control/live_tests/test_scenario_loader.py
tests/grace_control/live_tests/test_wave_resume_runner_routing.py
tests/grace_control/live_tests/test_replay_decision_logic.py
tests/grace_control/live_tests/test_live_test_guards.py
```

These may use fake API clients because they test runner logic, not agent quality.

Required coverage:

- scenario YAML validation;
- disabled by default unless `GRACE_LIVE_AGENT_TESTS=1`;
- T0/T1/T2 failures route to `replay-acceptance`;
- verifier failure routes to `rerun-verifier`;
- reviewer failure routes to `rerun-reviewer`;
- code-fix failure routes to packet retry and expects agent session resume;
- explicit waves skip context/architect;
- no mock backend allowed when `real_agent_required=true`.

## 16. Opt-in live tests

Add opt-in live tests under:

```text
tests_live/test_backend_1w_real_agent.py
tests_live/test_frontend_1w_real_agent.py
tests_live/test_fullstack_2w_real_agent.py
tests_live/test_fullstack_3w_real_agent.py
tests_live/test_resume_t2_failure_real_agent.py
tests_live/test_resume_verifier_failure_real_agent.py
tests_live/test_resume_coder_fix_real_agent.py
```

These tests must skip unless:

```text
GRACE_LIVE_AGENT_TESTS=1
```

Suggested command:

```bash
GRACE_LIVE_AGENT_TESTS=1 \
GRACE_DEV_TOOLS_ENABLED=1 \
GRACE_DEV_KEEP_FAILED_WORKTREES=1 \
pytest tests_live -q -m live_agent
```

## 17. Post-implementation verification ladder

After the coder implements this TZ, do not start with all live tests. The verifier must run checks in the following order.

### 17.1 Fast harness tests without agents

Run:

```bash
pytest tests/grace_control/live_tests -q
pytest tests_live --collect-only -q
```

Expected:

```text
harness unit tests pass
all live tests are importable/collectable
no real agent is called
```

### 17.2 Verify live tests skip without env

Run:

```bash
pytest tests_live -q
```

Expected:

```text
all live-agent tests are skipped
no API key is required
no real agent process starts
```

If any live test runs without `GRACE_LIVE_AGENT_TESTS=1`, this is a blocker.

### 17.3 JavaScript and frontend fixture checks

Run:

```bash
find tests_live/fixtures/apps -name "*.js" -print -exec node --check {} \;
```

Expected:

```text
all JS syntax checks pass
```

If `node` is not available, the report must say that JS syntax check was not executed and why. Do not silently skip it.

### 17.4 First live smoke: controlled T2 replay

Run this first, before backend/frontend/fullstack scenarios:

```bash
GRACE_LIVE_AGENT_TESTS=1 \
GRACE_DEV_TOOLS_ENABLED=1 \
GRACE_DEV_KEEP_FAILED_WORKTREES=1 \
pytest tests_live/test_resume_t2_failure_real_agent.py -q -m live_agent
```

Expected:

```text
real coder run happens once
T2 fails through controlled fail-once injection
runner calls replay-acceptance {stage: t2}
T2 replay passes
coder is not called again during replay
architect/context are not called during replay
summary.json shows acceptance_replays=1 and coder_runs=1
```

This is the most important live smoke. If it fails, do not continue to fullstack live tests.

### 17.5 Backend 1-wave live test

Run:

```bash
GRACE_LIVE_AGENT_TESTS=1 \
GRACE_DEV_TOOLS_ENABLED=1 \
GRACE_DEV_KEEP_FAILED_WORKTREES=1 \
pytest tests_live/test_backend_1w_real_agent.py -q -m live_agent
```

Expected:

```text
backend fixture change is implemented by real coder
T0/T1 pass
summary.json proves real_agent_runs >= 1
```

### 17.6 Frontend 1-wave live test

Run:

```bash
GRACE_LIVE_AGENT_TESTS=1 \
GRACE_DEV_TOOLS_ENABLED=1 \
GRACE_DEV_KEEP_FAILED_WORKTREES=1 \
pytest tests_live/test_frontend_1w_real_agent.py -q -m live_agent
```

Expected:

```text
frontend fixture change is implemented by real coder
JS syntax check passes
summary.json proves real_agent_runs >= 1
```

### 17.7 Fullstack 2-wave live test

Run only after previous live tests pass:

```bash
GRACE_LIVE_AGENT_TESTS=1 \
GRACE_DEV_TOOLS_ENABLED=1 \
GRACE_DEV_KEEP_FAILED_WORKTREES=1 \
pytest tests_live/test_fullstack_2w_real_agent.py -q -m live_agent
```

Expected:

```text
backend wave passes
frontend wave passes
integration smoke passes
summary.json includes all run IDs and sessions
```

### 17.8 Fullstack 3-wave live test

Run last because it is the most expensive/noisy scenario:

```bash
GRACE_LIVE_AGENT_TESTS=1 \
GRACE_DEV_TOOLS_ENABLED=1 \
GRACE_DEV_KEEP_FAILED_WORKTREES=1 \
pytest tests_live/test_fullstack_3w_real_agent.py -q -m live_agent
```

Expected:

```text
all three waves accepted
summary.json includes all run IDs, sessions, replay attempts, and counters
```

### 17.9 Report requirement after every live run

After every live run, the coder/verifier must show the generated `summary.json`.

Acceptance must not rely on the phrase `test passed` alone.

Required report fields to show:

```text
scenario_id
status
real_agent_runs
context_runs
architect_runs
coder_runs
acceptance_replays
verifier_replays
reviewer_replays
agent_session_resumes
packet_state_changed_by_replay
artifacts_dir
```

## 18. Success criteria for each live scenario

### backend-1w

- Real coder agent runs once.
- Backend fixture feature is implemented.
- T0/T1 pass.
- No architect/context rerun after initial setup.

### frontend-1w

- Real coder agent runs once.
- Frontend fixture feature is implemented.
- JS syntax check passes.
- UI smoke check passes if available.

### fullstack-2w

- Wave 1 backend change accepted.
- Wave 2 frontend change accepted.
- Final integration smoke passes.
- Packet dependencies/order respected.

### fullstack-3w

- Wave 1 backend.
- Wave 2 frontend.
- Wave 3 integration/polish.
- All waves accepted.
- Report includes all run IDs and sessions.

### resume-t2-failure

- First run fails at T2.
- Replay T2 is invoked.
- Replay passes.
- No coder/architect/context invocation occurs during replay.

### resume-verifier-failure

- First verifier fails.
- `rerun-verifier` is invoked.
- Verifier replay passes.
- No coder/architect/context invocation occurs during replay.

### resume-coder-fix

- First run needs code fix.
- Same packet is retried.
- Coder resumes from previous session.
- Second run accepts.
- Report proves session resume happened.

## 19. Acceptance criteria

Implementation is accepted only if all are true:

1. Real-agent live tests are opt-in and skipped by default.
2. The harness supports backend, frontend, and fullstack scenarios.
3. The harness supports 1-wave, 2-wave, and 3-wave scenarios.
4. Scenarios use explicit waves to avoid unnecessary context/architect work.
5. T0/T1/T2 failures route to dev replay, not coder rerun.
6. Verifier/reviewer failures route to dev replay, not coder rerun.
7. Code-fix failures route to packet retry with agent session resume.
8. The runner verifies that real agents are used when required.
9. The runner writes a structured report with run IDs, sessions, replay attempts, and counters.
10. Replay never mutates packet state.
11. Failed worktrees are preserved during resume/replay scenarios.
12. Frontend scenarios include JS syntax checks.
13. Normal CI/default `pytest` does not call real agents.
14. Harness logic has regular fake-client tests.
15. At least one live scenario is documented with exact command to run locally.
16. The verification ladder in section 17 is followed before accepting implementation.
17. Every live run includes displayed `summary.json` evidence.

## 20. Gitignore and repository hygiene

The implementation report mentioned removing `sandbox/` from `.gitignore` so coder can commit files further.

This must be reviewed carefully.

Rules:

- Do not commit runtime sandboxes, generated worktrees, `.grace/live-tests` artifacts, caches, logs, or temporary state.
- Do not commit API keys, env files, local config, browser profiles, screenshots with secrets, or agent stdout/stderr that may contain secrets.
- If `.gitignore` was changed, reviewer must inspect the diff and confirm the change is intentional and safe.
- If the project needs a commit-friendly fixture sandbox, create a narrowly scoped path such as `tests_live/fixtures/...`, not a broad runtime `sandbox/` exception.

Acceptance blocker:

```text
Any accidental runtime artifact committed to the repository blocks acceptance.
```

## 21. Notes for coder model

This is not another mock suite.

The whole point is to test the actual expensive path, but make reruns cheap through the mechanisms already implemented:

```text
LLM continuation -> agent session resume
stage rerun -> dev replay/checkpoints
```

Keep fixture tasks tiny. We are validating orchestration behavior, not asking agents to build a big product.

If a live test fails, the report must make it obvious where to continue:

```text
same packet + same run_id + same worktree + same stage
```

Do not hide real-agent failures. They are the signal this harness is supposed to catch.
