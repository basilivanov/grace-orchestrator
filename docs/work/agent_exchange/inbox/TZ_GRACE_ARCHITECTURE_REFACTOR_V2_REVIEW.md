# REVIEW — TZ_GRACE_ARCHITECTURE_REFACTOR_V2

## Review identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2`
- Reviewed submission: `docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_SUBMISSION.md`
- Reviewed implementation commit: `46a004f4c6a7d2ac80e17bcbc53e079dc64e1abc`
- Synced implementation base: `95bfc1f0118622d07b9ff0dc84aa47a381e258f8`
- Architect decision: **REVIEW**

Before changing anything, fast-forward `main` from GitHub exactly as required by the named-packet protocol. Read only this review file plus the already-authorized named TZ context. Do not start the control-CLI packet or any later wave.

## What is accepted so far

The implementation is directionally correct and several required parts are complete:

- the seven `src/grace_control/runtime/opencode_*.py` runtime modules are physically removed;
- `PacketExecutionAdapter` no longer selects `opencode_runtime_adapter` through `agent_runtime_use_opencode_adapter`;
- OpenCode-only settings/project mapping/profile entries and active runtime docs were substantially removed;
- mini-swe profiles and `UniversalCliAgentBackend` remain;
- the unrelated `agy` execution profile remains;
- the submission file contains the required protocol markers and references a real one-commit implementation diff from the synced base.

Do not revert those correct changes.

## BLOCKER 1 — OpenCode session semantics survived under generic names

The TZ requires removal of OpenCode-only session parsing/validation, not merely removal of the word `opencode`.

### Current contradictory behavior

`src/grace_control/services/agent_run_service.py` correctly retains the supported `agy` session extraction path:

```text
Conversation ID: conv_12345 -> external session id `conv_12345`
```

and the current tests explicitly prove that extraction.

However `src/grace_control/services/session_store.py::_session_run_status_usable()` still contains the old OpenCode-shaped validity contract:

```python
sid = external_id.strip()
if not sid.startswith("ses_") or len(sid) < 6:
    return False
```

It also still treats the exact stderr text `Session not found` as part of the generic session-usability contract.

Therefore a healthy remaining `agy` session with external id such as `conv_12345` is rejected by `SessionStore.find_latest()` / `find_for_fork()` before generic resume can use it. This is an architectural/runtime mismatch created by retaining OpenCode-era semantics after removing the OpenCode backend.

`src/grace_control/services/agent_run_service.py` also still has generic `cli` fallback regexes whose only concrete format is `ses_*`:

```python
"cli": [
    re.compile(r'"session_id":\s*"(ses_\w+)"'),
    re.compile(r'Session:\s*(ses_\w+)'),
]
```

Those patterns came from the removed OpenCode session shape and must not silently become the generic CLI contract without proof of a remaining supported backend that owns that format.

### Tests currently preserve the stale contract

The current tests continue to encode `ses_*` as the generic external-session format, including in:

- `tests/grace_control/services/test_session_store.py`;
- `tests/grace_control/services/test_session_hardening.py`;
- `tests/grace_control/services/test_session_resume_phase2.py`.

At the same time `tests/grace_control/services/test_session_resume_followup.py` proves that the remaining `agy` backend extracts `conv_*`, so the test suite currently validates two incompatible halves instead of one supported end-to-end contract.

### Required correction

Follow the normative rule from `WORKER_GRACE_ARCHITECTURE_REFACTOR_V2.md`: generic resume/session compatibility may remain **only if at least one remaining supported non-OpenCode profile genuinely uses it**. Otherwise remove the dead generic-looking compatibility path too.

Choose the evidence-based result, do not guess:

1. Audit the remaining enabled profiles and actual runtime callers.
2. If session resume remains a supported non-OpenCode capability, make validation backend-neutral or backend-specific to the actual supported backend. Do not impose `ses_*` on all external session IDs.
3. If `agy` resume is the supported path, add an end-to-end focused test proving a healthy `conv_*` external ID can flow through extraction/persistence/usability lookup and reach the correct `--conversation <id>` resume injection when the profile is explicitly resume-safe.
4. If no remaining supported profile actually uses resume, remove the dead resume compatibility fields/helpers/branches/tests that exist only to preserve historical behavior. Do not keep them because old tests reference them.
5. Do not change DB schema or packet/recovery state semantics as part of this fix.
6. Internal GRACE-owned `AgentSession.id` values may remain `ses_*`; the problem is the hard-coded format assumption on **external provider session IDs**.

## BLOCKER 2 — `inject_dir` remains as an unused OpenCode-era compatibility knob

The worker TZ explicitly requires auditing `inject_dir` after OpenCode profile removal and removing it when no supported non-OpenCode path uses it.

Current `src/grace_control/config/agent_profiles.yaml` has no remaining enabled profile that requires `inject_dir: true`; the mini-swe profiles set it to `false`, while `coder_agy` does not require it. Nevertheless:

- `AgentProfile` still stores/serializes `inject_dir`;
- `AgentRunService` still contains the `inject_dir` command-mutation branch;
- multiple remaining profile entries keep explicit `inject_dir: false` boilerplate.

Required:

- either remove this field/branch/unused YAML entries and update focused tests;
- or provide concrete code/profile evidence that a currently supported non-OpenCode execution path needs `inject_dir: true`.

Tests that only exercise the old compatibility knob are not sufficient evidence of a live consumer.

## Required verification before resubmission

Run the directly affected session/profile tests plus the Packet 1 regression set. At minimum include exact results for:

```bash
PYTHONPATH=src .venv/bin/pytest -q \
  tests/grace_control/services/test_session_store.py \
  tests/grace_control/services/test_session_hardening.py \
  tests/grace_control/services/test_session_resume_followup.py \
  tests/grace_control/services/test_session_resume_phase2.py \
  tests/grace_control/config/test_agent_profile_passthrough.py \
  tests/grace_control/architecture/test_no_opencode_legacy.py

PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/runtime tests/grace_control/agent
python3 scripts/grace_lint.py src/grace_control tests scripts
python -m ruff check src/grace_control tests scripts
git diff --check
```

If repository-wide lint/Ruff still has pre-existing failures, preserve the exact baseline proof and show that this resubmission adds none.

Also rerun the active OpenCode scan from the parent TZ. Literal scans are necessary but are not sufficient; the session-format regression above must be covered behaviorally.

## Scope fence

Do **not** start:

- control CLI removal;
- Admin dependency inversion;
- Admin aggregation cycle removal;
- lifecycle/router cleanup;
- typed DTO migration;
- dead-code/repository-hygiene wave;
- CI consolidation.

This review is only completion of Packet 1 / OpenCode legacy removal.

## Required resubmission

After fixing the blockers, commit and push the correction, then create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_RESUBMISSION.md`

Include the final correction commit SHA, exact checks, and a short explanation of the chosen session-resume decision (kept with a proven non-OpenCode consumer, or removed as dead compatibility). Do not create a new task packet yourself.
