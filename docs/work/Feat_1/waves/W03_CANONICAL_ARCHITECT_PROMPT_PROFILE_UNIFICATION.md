# W03 — Canonical Architect Prompt and Profile Unification

Status: READY

Parent TZ: `docs/work/TZ_GRACE_ORCHESTRATOR_RUNTIME_SCOPE_CONTEXT_HARDENING.md`

## Goal

Remove conflicting sources of truth for architect output. Architect prompt, profiles, compiler, materializer, and contract parser must expect one canonical schema.

## Scope

- `src/grace_control/services/feature_planning_service.py`
- `src/grace_control/config/agent_profiles.yaml`
- `src/grace_control/core/agent_profiles.py`
- `src/grace_control/prompts/`
- `docs/grace/`
- `tests/`

## Tasks

1. Create one canonical architect prompt file, for example `src/grace_control/prompts/architect_prompt.md`.
2. Make `_build_architect_prompt()` a thin renderer around the canonical prompt.
3. Define and enforce one plan schema.
4. Ensure every enabled architect profile uses the same schema.
5. Remove or disable incompatible duplicate architect prompt bodies.
6. Remove conflicting legacy fields from active runtime contracts, or map them with explicit warnings for one transition release.

## Canonical packet fields

- `title`
- `role`
- `scope`
- `frozen_scope`
- `acceptance_profile`
- `depends_on`
- `description`
- `coder_instructions`
- `acceptance_criteria`
- `verification`
- `expected_evidence`
- `workspace_requirements`

## Acceptance

- There is one canonical architect prompt source.
- Enabled architect profiles match the canonical schema.
- Legacy incompatible fields are rejected or canonicalized with visible warnings.
- Tests prove prompt/profile/schema consistency.

## Required tests

- `test_architect_prompt_file_exists_and_loads`
- `test_build_architect_prompt_uses_canonical_prompt`
- `test_architect_profiles_match_canonical_schema`
- `test_legacy_allowed_files_schema_rejected_or_canonicalized`
- `test_architect_output_schema_required_fields`

## Submission

Create `docs/work/Feat_1/exchange/inbox/W03_001_SUBMISSION.md` when done.
