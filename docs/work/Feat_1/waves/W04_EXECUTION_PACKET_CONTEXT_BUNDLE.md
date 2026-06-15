# W04 — Execution Packet Context Bundle for Coder

Status: READY

Parent TZ: `docs/work/TZ_GRACE_ORCHESTRATOR_RUNTIME_SCOPE_CONTEXT_HARDENING.md`

## Goal

Coder must not work blindly. `EXECUTION_PACKET.md` must include enough target-repo context, constraints, tests, and evidence requirements for reliable execution.

## Scope

- `src/grace_control/services/packet_materializer.py`
- `src/grace_control/services/agent_workspace_builder.py`
- `src/grace_control/services/packet_executor.py`
- `src/grace_control/services/agent_run_service.py`
- `src/grace_control/services/context_collector.py`
- `tests/`

## Required packet sections

1. Objective
2. Business requirement
3. Role and non-goals
4. Allowed write scope
5. Frozen scope
6. Relevant file tree
7. Selected file previews
8. Nearby tests
9. Config/build files available
10. Import/dependency hints
11. Coder instructions
12. Acceptance criteria
13. Verification commands by T0/T1/T2
14. Full expected evidence fields
15. Workspace mode and limitations
16. Target repo root diagnostics
17. Full spec JSON dump

## Tasks

- Enrich `EXECUTION_PACKET.md` with the sections above.
- Block NORMAL/STRICT code packets if context is missing, unless explicitly marked `context_not_required: true`.
- Ensure scoped copy includes required source, tests, and config files.
- Expand config allowlist: `pyproject.toml`, pytest/ruff/mypy/tox config, package locks, tsconfig/vite/vitest/playwright configs, `conftest.py`, `.env.example`; never copy `.env`.
- Stop silently creating missing cwd in execution path.

## Acceptance

- NORMAL/STRICT coder packets get actionable context.
- Missing context blocks code packets instead of launching blind coder work.
- Scoped workspace includes config needed for targeted tests.
- No silent cwd creation masks bad worktree routing.

## Required tests

- `test_execution_packet_contains_file_tree_and_previews`
- `test_execution_packet_renders_full_evidence_requirements`
- `test_normal_packet_requires_context_or_explicit_override`
- `test_scoped_copy_includes_required_config_allowlist`
- `test_agent_run_fails_if_cwd_missing_instead_of_creating_it`
- `test_coder_profiles_all_have_input_mode_or_packet_arg`

## Submission

Create `docs/work/Feat_1/exchange/inbox/W04_001_SUBMISSION.md` when done.
