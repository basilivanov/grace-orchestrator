---
feature_id: Feat_1
wave_id: W09
submission_attempt: 1
status: READY_FOR_REVIEW
created_at: 2026-06-16T15:00:00Z
---

# W09 Submission: Profile Cleanup and Agent Input Validation

## Changes

### 1. `AgentProfile.disabled` field + W09 input mode validation

**File:** `src/grace_control/config/agent_profiles.py`

Added `disabled` field to `AgentProfile` (reads from YAML `disabled: true`, defaults to `False`). Disabled profiles skip all validation since they are not used at runtime.

Added W09 input mode validation in `_validate()`:

| Check | Rule |
|-------|------|
| Coder profiles with `input_mode: none` | Rejected — must be `file` or `stdin` |
| File-input profiles without `{packet_path}` in command | Rejected — file mode requires packet path reference |
| Stdin-input profiles without `{packet_markdown}` in template | Rejected — stdin mode requires packet markdown in template |
| Disabled profiles | Skip validation entirely |

Invalid profiles fail during `AgentProfile.__init__()` (load time), not during execution. The error message suggests either fixing the profile or setting `disabled: true`.

### 2. Disabled the generic `opencode` profile

**File:** `src/grace_control/config/agent_profiles.yaml`

Added `disabled: true` to the `opencode` profile. This is a generic profile without a specific role prefix that overlaps with dedicated coder profiles (`coder-deepseek-flash`, `coder-sonnet`, etc.). It is disabled until covered by tests.

### 3. Executor selection skips disabled profiles

**File:** `src/grace_control/core/executor_selector.py`

All three selection functions now filter out disabled profiles:

- `select_executor()` — disabled profiles never selected for execution
- `get_escalation()` — disabled profiles excluded from escalation lists
- `resolve_model()` — disabled profiles excluded from model resolution

### 4. Unresolved placeholder rejection after render

**File:** `src/grace_control/services/agent_run_service.py`

After rendering the command template, the service checks each rendered part for remaining `{word}` patterns using regex `\{([a-z_]+)\}`. If any unresolved placeholders are found, a `RuntimeError` is raised immediately — fail-closed, not at subprocess spawn time.

This prevents cases where a profile template references a variable that isn't in the render context (e.g., a typo like `{pacet_path}` or a missing context key).

### 5. CWD containment check — prevents path-escape attacks

**File:** `src/grace_control/services/agent_run_service.py`

After resolving the CWD template, the service verifies that the resolved CWD path is inside the intended worktree using `Path.is_relative_to()`. If the CWD escapes the worktree (e.g., `cwd: /tmp` or `cwd: ../../etc`), a `RuntimeError` is raised.

This prevents path-escape attacks where a crafted cwd template in a profile could cause agent execution outside the intended worktree directory.

### 6. `coder_agy` verification — valid input mode confirmed

The `coder_agy` profile was flagged as potentially packetless. Investigation confirmed it has `input: mode: file` and references `{packet_path}` in its command — it is valid and not disabled.

### 7. Tests

**File:** `tests/test_w09_profile_cleanup.py` — 7 tests (5 required + 2 additional):

| Test | Description |
|------|-------------|
| `test_all_enabled_coder_profiles_receive_packet_input` | Every enabled coder has file/stdin mode with proper placeholders |
| `test_coder_agy_has_valid_input_mode` | coder_agy has valid file input with {packet_path} |
| `test_profile_loader_rejects_unresolved_packetless_coder` | 3 rejection cases + 1 disabled-allowed case |
| `test_select_executor_skips_disabled_invalid_profiles` | Disabled profiles never returned by select_executor |
| `test_architect_profiles_use_canonical_schema` | Architect commands reference scope, frozen_scope, acceptance_profile, coder_instructions, expected_evidence |
| `test_agent_run_service_rejects_unresolved_placeholders` | RuntimeError on unresolved {unknown_var} in command |
| `test_agent_run_service_rejects_cwd_escaping_worktree` | RuntimeError when cwd resolves outside worktree |

## Acceptance Checklist

- [x] Every enabled coder profile receives packet input
- [x] Invalid profiles fail during profile load or executor selection, not during execution
- [x] No enabled profile relies on hidden defaults for task context
- [x] Profile schema matches runtime expectations
- [x] coder_agy has valid input mode (verified, not disabled)
- [x] Generic opencode profile disabled until covered by tests
- [x] Unresolved placeholders rejected after render
- [x] CWD containment enforced inside worktree

## Test Results

```
tests/test_w05_evidence_contract.py .............. (14 passed)
tests/test_w06_process_command_hardening.py ........... (11 passed)
tests/test_w07_worker_error_handling.py ................ (16 passed)
tests/test_w08_stuck_scanner.py .......... (10 passed)
tests/test_w09_profile_cleanup.py ....... (7 passed)
Total: 58 passed
```

## Profile Validation Evidence

All enabled profiles in `agents:` section pass W09 validation:

| Profile | Input Mode | Key Reference | Status |
|---------|-----------|---------------|--------|
| deepseek-v4-pro | file | {packet_path} | ✓ |
| architect-premium | file | {packet_path} | ✓ |
| reviewer-premium | file | {packet_path} | ✓ |
| coder-deepseek-flash | file | {packet_path} | ✓ |
| coder-sonnet | file | {packet_path} | ✓ |
| coder_agy | file | {packet_path} | ✓ |
| coder-opencode | stdin | {packet_markdown} | ✓ |
| coder-opencode-fixture | stdin | {packet_markdown} | ✓ |
| context-collector-flash | file | {packet_path} | ✓ |
| context-json-flash | stdin | {packet_markdown} | ✓ |
| verifier-cheap | file | {packet_path} | ✓ |
| opencode | **DISABLED** | — | skipped |

## Changed Files

- `src/grace_control/config/agent_profiles.yaml` — `opencode` profile: added `disabled: true`
- `src/grace_control/config/agent_profiles.py` — `disabled` field + W09 input mode validation in `_validate()` + `disabled` in `to_dict()`
- `src/grace_control/core/executor_selector.py` — `select_executor()`, `get_escalation()`, `resolve_model()` skip disabled profiles
- `src/grace_control/services/agent_run_service.py` — unresolved placeholder rejection + CWD containment check
- `tests/test_w09_profile_cleanup.py` — NEW: 7 tests (5 required + 2 additional)

## Known Limitations

- The `coder-shell` profile under the `verification:` section is not loaded by `load_agent_profiles()` (reads only from `agents:` key). It remains in the YAML but is inert. Future cleanup should either remove it or move it under `agents:` with `disabled: true`.
- The `_profile_matches_role()` heuristic uses keyword matching on executor_id. A more robust approach would be an explicit `roles:` field in the profile YAML.
- The CWD containment check uses `Path.is_relative_to()` which requires Python 3.9+. This is acceptable given the project's Python 3.12 baseline.
