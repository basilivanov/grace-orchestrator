---
feature_id: Feat_1
wave_id: W09
submission_attempt: 1
reviewer: active_reviewer_architect
decision: REWORK_REQUIRED
reviewed_commit: 31f852d
created_at: 2026-06-16T00:00:00Z
---

# Review: W09 attempt 1

Decision: REWORK_REQUIRED

Reviewed submission: `docs/work/Feat_1/exchange/inbox/W09_001_SUBMISSION.md`
Reviewed commit: `31f852d`

Good progress:

- `AgentProfile.disabled` was added and disabled profiles skip profile validation.
- Enabled coder profiles now fail load-time validation when they have no explicit packet input mode.
- File-input profiles must reference `{packet_path}` in the command.
- Stdin-input profiles must include `{packet_markdown}` in the input template.
- Normal executor selection, escalation, and model resolution paths filter disabled profiles.
- `AgentRunService` rejects unresolved command placeholders after render.
- `AgentRunService` rejects cwd values that escape the intended worktree.
- `coder_agy` is verified as file-input with `{packet_path}`.
- The generic `opencode` profile is marked disabled.

Blocking issue:

1. `GRACE_LIVE_EXECUTOR_PROFILE` can still select a disabled profile.

   In `select_executor()`, the live override branch runs before the disabled-profile filter:

   ```python
   if role == "coder":
       live_profile = os.environ.get("GRACE_LIVE_EXECUTOR_PROFILE")
       if live_profile:
           match = get_agent_profile(live_profile)
           if match:
               return match.to_dict()
   ```

   This means setting `GRACE_LIVE_EXECUTOR_PROFILE=opencode` will return the disabled `opencode` profile. That profile is explicitly disabled in `agent_profiles.yaml`, but the live override bypasses the W09 disabled skip path.

   This violates W09 acceptance:

   - disabled or invalid profiles must be skipped by executor selection;
   - invalid profiles must fail during loading/selection, not later during execution;
   - experimental/unused profiles marked disabled must not be runnable by hidden override.

   Required fix:

   - In the live override branch, reject or skip disabled profiles before returning them.
   - Prefer fail-closed behavior for an explicitly requested disabled profile, for example raise `ValueError` / return a structured selection error, rather than silently falling back to another executor.
   - Add a regression test, for example:

     `test_live_executor_profile_cannot_select_disabled_profile`

   The test should set `GRACE_LIVE_EXECUTOR_PROFILE=opencode` and assert that `select_executor("coder")` does not return the disabled `opencode` profile.

Non-blocking notes:

1. `_profile_matches_role()` still uses keyword heuristics, so profile role identity remains implicit. This is already noted in the submission and can be handled later with explicit `roles:` metadata.
2. `load_agent_profiles()` still returns disabled profiles in the loaded dictionary. That is acceptable if every runtime selection path filters or rejects them consistently.
3. The fallback executor path still returns a default `input_mode=none` if no profiles exist. This is not the normal runtime path, but later hardening should either make the fallback explicit/test-only or fail closed.

Required next submission:

`docs/work/Feat_1/exchange/inbox/W09_002_SUBMISSION.md`
