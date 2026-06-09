# TZ: Real-Loop Orchestrator Smoke / Regression

Status: draft for coder implementation  
Scope: real-condition smoke testing for GRACE orchestrator  
Target: prove the orchestrator can be attached to external projects without hardcoded paths

## 1. Problem

The current test suite is fast and useful, but it is mostly internal and mocked.

The existing project testing strategy explicitly says that regular tests use `MockBackend` or injected fake backends and do not require real `prefect_grace` or API keys.

That is good for unit/API speed, but not enough before using GRACE as a real orchestrator for other projects.

We need several real-loop smoke scenarios where the full pipeline actually runs:

```text
context builder
-> architect
-> waves/packets
-> coder
-> T0/T1/T2 acceptance
-> evidence verifier
-> reviewer where applicable
-> trace/result inspection
-> replay/resume after failure
```

The goal is not to create a huge permanent benchmark suite. The goal is to find integration bugs before connecting GRACE to production projects.

## 2. Canonical context for coder

Use these existing docs as source-of-truth before implementing or running the smoke scenarios:

```text
docs/grace/TESTING_STRATEGY.md
docs/grace/ACCEPTANCE_PIPELINE.md
docs/grace/EXECUTION_PIPELINE.md
docs/grace/API_FIRST_CONTROL_PLANE.md
docs/work/tz-dev-run-replay-checkpoints.md
docs/work/tz-dev-replay-admin-ui.md
```

Important constraints from the canon:

- Unit/API tests stay fast and mostly mocked.
- Real-loop smoke is a separate layer, not a replacement for the fast suite.
- Acceptance pipeline stages are T0/T1/T2.
- FULL/real execution must go through the packet execution pipeline, not direct service calls.
- OpenAPI/API is the runtime contract.
- CLI/scripts may be wrappers only; no runtime business logic there.
- No hardcoded project paths.
- No direct env reads outside config.
- Replay/resume tools are dev-only and disabled by default.

## 3. Goal

Create a small real-loop smoke test harness and 2-3 real scenarios that exercise GRACE in realistic conditions.

The smoke must validate:

1. One-wave feature execution.
2. Two-wave feature execution with dependency/order handling.
3. Backend + frontend feature execution where frontend/browser verification is triggered through T2/Playwright or the existing project-appropriate frontend smoke path.
4. Failure -> bugfix -> resume/replay loop without starting over from context/architect/coder every time.

## 4. Non-goals

Do not turn this into a large benchmark suite.

Do not use fixed absolute paths like `/opt/...`, `/tmp/grace-live-wt`, or a local user directory inside source code.

Do not require one specific downstream project name in code.

Do not add hidden business logic to scripts or CLI.

Do not make smoke tests run by default in the normal `pytest tests/ -q` path.

Do not call internal Python services directly to simulate success. Real-loop means going through the API/worker/pipeline surface.

Do not disable evidence verifier/reviewer just to make the smoke green, except in the explicitly marked FAST baseline scenario.

## 5. Required smoke modes

Add or document three execution modes:

### 5.1 Fast internal tests

Existing fast suite remains:

```bash
pytest tests/ -q
pytest tests/grace_control/ -q
make lint
```

This is the default development guard.

### 5.2 Real-loop smoke: lightweight

Runs one small real feature through full orchestration using configurable target/source dirs.

Example command shape:

```bash
scripts/real_loop_smoke.sh \
  --target-project /path/to/fixture-project \
  --work-root /tmp/grace-real-smoke \
  --scenario one-wave-basic \
  --profile NORMAL
```

The exact script name may differ, but it must be a thin wrapper over API calls.

### 5.3 Real-loop smoke: frontend/browser

Runs a frontend-capable fixture/project and ensures T2 invokes the project frontend verification path.

This may be:

```bash
npm test
npm run test:e2e
npx playwright test
```

or the repo's configured T2 command.

The smoke harness must not hardcode Playwright if the target project's verification contract points to another command. It should read the command from the generated packet/spec verification section.

## 6. Configuration requirements

All paths and ports must be configurable.

Required configuration inputs:

```text
GRACE_API_URL
GRACE_REAL_SMOKE_WORK_ROOT
GRACE_REAL_SMOKE_TARGET_PROJECT
GRACE_REAL_SMOKE_SOURCE_DIR
GRACE_REAL_SMOKE_PROFILE
GRACE_DEV_TOOLS_ENABLED
GRACE_DEV_KEEP_FAILED_WORKTREES
```

Rules:

- No absolute paths in source code.
- Defaults may be safe temp-dir defaults only in shell wrappers/tests, not baked into services.
- Every generated worktree/state dir must live under the configured work root.
- The target project must be replaceable with another repository later.
- Smoke artifacts must be written under a predictable run dir:

```text
<work-root>/runs/<timestamp>-<scenario>/
```

Artifacts to keep:

```text
request payloads
OpenAPI endpoint responses
packet ids
run ids
trace responses
acceptance reports
replay responses
logs
screenshots/video if frontend/browser smoke creates them
```

## 7. Bugfix workflow during real-loop smoke

When a real-loop scenario fails, coder must use the replay/resume tooling instead of restarting the full loop blindly.

Required workflow:

1. Inspect trace:

```bash
GET /api/trace/packets/{packet_id}
GET /api/trace/runs/{run_id}
```

2. Determine failed stage:

```text
context builder
architect
coder
T0
T1
T2
verifier
reviewer
merge/state
```

3. If failure is in T0/T1/T2/verifier/reviewer:

Use dev replay endpoint or admin replay button:

```http
POST /api/dev/runs/{run_id}/replay-acceptance
POST /api/dev/runs/{run_id}/rerun-verifier
POST /api/dev/runs/{run_id}/rerun-reviewer
```

4. If the bug is in GRACE itself:

- fix GRACE code in a normal feature branch/packet;
- rerun the smallest failing replay first;
- only then rerun the full scenario.

5. If the bug is in the generated target project code:

- allow coder/recovery loop to repair it through normal packet retry/resume;
- do not manually patch the target project unless the smoke scenario explicitly requires manual diagnosis.

6. Preserve evidence:

Every bugfix must record:

```text
packet_id
run_id
failed_stage
root cause
fix summary
replay command/button used
before/after result
```

Put this into the scenario run report under `docs/work` or the smoke artifact dir.

## 8. Resume / CSC requirement

The real-loop smoke must verify that session/checkpoint recovery works.

Use the existing agent session resume mechanism where available.

For this TZ, treat `CSC` as the Context/Session Checkpoint state required to continue a real orchestration run without losing previous agent context. If the repo already has a stricter term for CSC, coder must align wording with the existing implementation and update this document/report accordingly.

Required checks:

- retry after coder failure should reuse/fork the expected agent session according to profile `resume_mode`;
- replay after T0/T1/T2 failure should reuse existing worktree/run metadata and must not call coder;
- retry after verifier/reviewer `REWORK_TO_CODER` should preserve prior context and not force new context builder unless recovery ladder requires architect return;
- attempt 7+ behavior may create a new architect context if that is the documented recovery ladder.

Evidence to capture:

```text
agent_session ids before/after retry
resume_session_id or fork_session evidence if exposed
run_id sequence
attempt_count sequence
trace timeline
whether context builder/architect/coder were called again
```

## 9. Scenario 1: One-wave backend-only feature

Name:

```text
one-wave-basic-backend
```

Purpose:

Validate the simplest real feature path.

Input feature idea:

```text
Add a tiny backend utility endpoint or service behavior in the target fixture project. Include unit tests and a deterministic smoke command.
```

Requirements:

- context builder runs;
- architect creates one wave;
- wave creates one or more packets;
- coder implements change;
- T0 runs lint/type/compile command;
- T1 runs unit/integration command;
- T2 runs small smoke command;
- evidence verifier runs in NORMAL profile;
- trace shows successful result;
- no hardcoded target project path appears in generated specs, scripts, or source code.

Acceptance:

```text
packet accepted
run result saved
trace endpoint shows no blocking issues
acceptance report includes T0/T1/T2
```

## 10. Scenario 2: Two-wave dependency feature with recovery

Name:

```text
two-wave-recovery-resume
```

Purpose:

Validate multi-wave order plus failure/retry/resume behavior.

Input feature idea:

```text
Wave 1: add backend state/model/API needed by Wave 2.
Wave 2: add a consumer endpoint or small UI/API integration depending on Wave 1.
```

Injected failure:

At least one run must intentionally fail in T1 or T2.

Examples:

```text
missing test fixture
wrong expected response shape
frontend smoke expects a label that coder initially omits
```

Requirements:

- architect creates two waves;
- Wave 2 must not run before Wave 1 is accepted/merged or otherwise made available according to project semantics;
- failure is captured in trace;
- bugfix uses retry/resume or replay;
- repeated debugging uses replay button/API for T1/T2 instead of rerunning full context/architect/coder loop;
- final run succeeds.

Acceptance:

```text
both waves complete
attempt_count increments correctly
session/checkpoint evidence exists
failed stage is visible in trace
replay result is visible in run metadata/admin UI
final trace shows accepted/merged path as appropriate
```

## 11. Scenario 3: Backend + frontend with browser/T2 verification

Name:

```text
backend-frontend-browser-smoke
```

Purpose:

Validate that GRACE can orchestrate a feature touching backend and frontend and that frontend verification runs in T2.

Input feature idea:

```text
Backend: add or expose a small API field.
Frontend: render that field in a tiny page/component.
T2: run browser/frontend smoke to confirm the UI shows the value.
```

Requirements:

- architect may create 2 or 3 waves if needed;
- packet verification must include frontend/browser T2 command;
- T2 must run the configured project frontend command;
- if Playwright is configured, collect its report/screenshot/video artifact paths;
- admin UI replay buttons must allow rerunning T2 without recoding;
- no browser-specific absolute path assumptions;
- no hardcoded port except configurable env/default in test fixture.

Acceptance:

```text
backend change accepted
frontend change accepted
T2 frontend/browser smoke executed
browser artifacts preserved if produced
trace/run report links or records T2 output
Replay T2 works from admin UI or API
```

## 12. Optional Scenario 4: Three-wave feature

Name:

```text
three-wave-full-strict
```

Run this only after scenarios 1-3 are stable.

Purpose:

Validate a larger real-loop path with STRICT profile.

Expected path:

```text
context builder -> architect -> 3 waves -> coder -> T0/T1/T2 -> verifier -> reviewer -> merge path
```

This scenario is optional for this TZ because the immediate need is 2-3 reliable real smoke cases.

## 13. Harness implementation requirements

Coder should implement the minimum reusable harness needed to run the scenarios.

Possible shape:

```text
scripts/real_loop_smoke.sh
scripts/real_loop_smoke.py
docs/work/real-loop-smoke-runbook.md
```

But scripts must remain wrappers only.

Business logic must live in services/API if any new runtime logic is needed.

Harness responsibilities:

- start or target an existing GRACE API;
- submit feature spec through `/api/architect/plan` or the canonical feature endpoint;
- create/claim/run packets through canonical API/worker flow;
- wait/poll trace endpoints;
- collect artifacts;
- write markdown/JSON summary;
- never directly call internal Python service methods.

## 14. Reporting requirement

After running the scenarios, create a report:

```text
docs/work/report-real-loop-orchestrator-smoke-YYYY-MM-DD.md
```

Report must include:

```text
commit sha
GRACE env/config summary without secrets
target fixture project path/name
scenario names
packet ids
run ids
wave count
profile FAST/NORMAL/STRICT
T0/T1/T2 results
verifier/reviewer results
failures found
bugs fixed
replay/resume evidence
remaining blockers
final verdict
```

Do not include API keys, tokens, or secret env values.

## 15. Tests to add for the harness itself

Do not make real-loop smoke part of normal fast test suite.

Add lightweight tests for the harness/report code only:

```text
- command builder does not hardcode absolute paths
- smoke config requires target project/work root
- report writer redacts secrets
- scenario definitions include T0/T1/T2 expectations
- Playwright/frontend command is read from scenario/spec config, not hardcoded globally
```

If JS/admin replay code is touched again, run:

```bash
node --check <changed-js-file>
```

## 16. Commands coder should run

Fast guard first:

```bash
pytest tests/ -q
make lint
```

Then real-loop smoke:

```bash
export GRACE_DEV_TOOLS_ENABLED=1
export GRACE_DEV_KEEP_FAILED_WORKTREES=1

# Example only. Use actual script/API wiring implemented by coder.
scripts/real_loop_smoke.sh \
  --scenario one-wave-basic-backend \
  --target-project "$TARGET_PROJECT" \
  --work-root "$WORK_ROOT" \
  --profile NORMAL

scripts/real_loop_smoke.sh \
  --scenario two-wave-recovery-resume \
  --target-project "$TARGET_PROJECT" \
  --work-root "$WORK_ROOT" \
  --profile NORMAL

scripts/real_loop_smoke.sh \
  --scenario backend-frontend-browser-smoke \
  --target-project "$TARGET_PROJECT" \
  --work-root "$WORK_ROOT" \
  --profile NORMAL
```

## 17. Acceptance criteria

This TZ is accepted only if all are true:

1. A real-loop smoke runbook or harness exists.
2. All paths are configurable; no source-code hardcoded local project paths.
3. Fast internal tests still run as before.
4. Scenario 1 completes one-wave backend-only real-loop flow.
5. Scenario 2 exercises two-wave flow and at least one failure/retry/resume or replay path.
6. Scenario 3 exercises backend+frontend flow and T2/frontend/browser verification.
7. Replay/resume is used during debugging instead of restarting the whole loop for T0/T1/T2/verifier/reviewer failures.
8. Trace evidence is captured for packet/run ids and failed stages.
9. Smoke artifacts are written under configured work root.
10. A report is written to `docs/work/report-real-loop-orchestrator-smoke-YYYY-MM-DD.md`.
11. Report contains bugs found/fixed and remaining blockers.
12. No secrets are written to report or artifacts.

## 18. Notes for coder model

Keep this small and practical.

The immediate goal is confidence that GRACE can drive other projects, not perfect benchmark infrastructure.

If something fails, do not restart from zero by habit. Use trace + replay + resume.

Every bugfix should prove the smallest failed stage first, then rerun the full scenario.

Prefer boring evidence over optimistic claims.
