# W09 — Profile Cleanup and Agent Input Validation

Status: READY

Parent TZ: `docs/work/TZ_GRACE_ORCHESTRATOR_RUNTIME_SCOPE_CONTEXT_HARDENING.md`

## Goal

No executor profile should run without task input, valid cwd, and compatible runtime contract.

## Scope

- `src/grace_control/config/agent_profiles.yaml`
- `src/grace_control/core/agent_profiles.py`
- `src/grace_control/services/agent_run_service.py`
- `tests/`

## Tasks

1. Validate all enabled coder profiles have a packet input path, stdin template, or equivalent explicit input mode.
2. For file input, command must reference `{packet_path}` or backend must read default packet path deterministically.
3. For stdin input, template must include `{packet_markdown}`.
4. Reject unresolved placeholders after render.
5. Ensure cwd is inside the intended worktree.
6. Fix or disable `coder_agy` if it has no valid packet input.
7. Mark experimental/unused profiles disabled until covered by tests.
8. Make executor selection skip disabled or invalid profiles.

## Acceptance

- Every enabled coder profile receives packet input.
- Invalid profiles fail during loading/selection, not during execution.
- No enabled profile relies on hidden defaults for task context.
- Profile schema matches runtime expectations.

## Required tests

- `test_all_enabled_coder_profiles_receive_packet_input`
- `test_coder_agy_has_valid_input_mode`
- `test_profile_loader_rejects_unresolved_packetless_coder`
- `test_select_executor_skips_disabled_invalid_profiles`
- `test_architect_profiles_use_canonical_schema`

## Submission

Create `docs/work/Feat_1/exchange/inbox/W09_001_SUBMISSION.md` when done.
