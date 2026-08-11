# TZ 03_PLAN_COMPILER submission

Implementation commit: `cb101fa80e2195f4e758d4e274a7ef142ee22d5d`.

## Result

- `plan_compiler.py`: 1701 → 302 physical lines.
- `PlanCompiler.compile_plan()`: ~4152 → ~1349 Grace-estimated tokens (`len(source) // 4`).
- All touched/new Python modules are below 1000 physical lines and all extracted functions are below 4000 estimated tokens.
- No Part B feature-planning refactor or unrelated product/API/DB/config/state-machine change was made.

## Ownership

- command segmentation, executable/module/script discovery, shell/venv checks, grep and one-liner rules → `plan_validation/command.py`;
- scope type/path, Python-file limits, frozen-scope overlap, acceptance feasibility, and role consistency → `plan_validation/scope.py`;
- evidence kinds/patterns, diff/deletion rules, and instruction contradictions → `plan_validation/evidence.py`;
- dependency issue mapping → `plan_validation/dependencies.py`, reusing the existing `grace_control.core.dag_validator.validate_dag` owner;
- source-split intent, origin checks, import detection, and migration scope → `plan_validation/source_split.py`;
- shared `CompileError`, `CompileResult`, and diagnostic append helpers → `plan_validation/models.py`;
- ordered coordination and compatibility facade → `grace_control.core.plan_compiler`.

The existing `validate_dag`, `ExecutionEnvironment`, `_normalize_conflict_keys`, and `SUPPORTED_EVIDENCE_KINDS` helpers remain authoritative and were reused rather than copied.

## Compatibility and behaviour

`PlanCompiler`, module-level `compile_plan`, `CompileError`, `CompileResult`, `SourceSplitIntent`, `RepoReference`, `detect_source_split_intents`, `collect_repo_references`, `_import_path_to_source_path`, and `_SOURCE_SPLIT_KEYWORDS` remain importable from `grace_control.core.plan_compiler`.

No test assertion was weakened and no test file required changes. Existing validation order is retained: dependency checks, source-split preflight, conflict-key normalization, scope, command, acceptance, evidence, contradiction, and role checks. Error/warning codes, messages, paths, severity, legacy verification-list handling, source-split rules, and `conflict_keys` semantics remain unchanged.

Largest functions by module (Grace estimate):

- `plan_compiler.py`: `PlanCompiler.compile_plan` ~1349; `_plan_bootstraps_venv` ~294.
- `plan_validation/command.py`: `validate_command` ~2870; `_python_module_exists` ~284; `_validate_script_path` ~263.
- `plan_validation/dependencies.py`: `validate_dependencies` ~490.
- `plan_validation/evidence.py`: `validate_evidence` ~1368; `validate_evidence_contradiction` ~897.
- `plan_validation/models.py`: `_add_error` ~129; `_add_warning` ~110.
- `plan_validation/scope.py`: `validate_packet_scope` ~1562; `validate_scope_acceptance` ~1135; `validate_role_scope` ~205.
- `plan_validation/source_split.py`: `validate_source_split` ~868; `detect_source_split_intents` ~381; `collect_repo_references` ~362.

## Verification

- `.venv/bin/python -m pytest tests/grace_control/core/test_plan_compiler.py -q` — 68 passed.
- `.venv/bin/python -m pytest tests/grace_control/core/test_plan_compiler.py tests/grace_control/services/test_plan_autofix.py -q` — 92 passed.
- Directly affected targeted tests — 78 passed, 3 baseline/environment failures outside compiler scope.
- `.venv/bin/python -m py_compile src/grace_control/core/plan_compiler.py src/grace_control/core/plan_validation/*.py` — passed.
- `.venv/bin/python scripts/grace_lint.py src/grace_control/core/plan_compiler.py` — passed.
- `.venv/bin/python scripts/grace_lint.py src/grace_control/core/plan_validation` — passed.
- `python3 scripts/grace_lint.py` on touched compiler files — passed.
- `git diff --check` — passed.
- `make test` — 1585 passed, 2 skipped, 32 failed. A clean parent checkout at `fad70d8a` with the same command/environment produced the identical 32 failure-node set and the same 1585/2/32 summary; no compiler or plan-autofix failure was introduced.
- `make lint` — environment blocker before project lint: `.venv/bin/python -m ruff` reports `No module named ruff`. Full `python3 scripts/grace_lint.py src/` reports the repository's existing unrelated canon violations; targeted touched-file GraceLint is green.
- `git push origin main` — succeeded.

WEB_ORCH_REPORT: SUBMISSION 03_PLAN_COMPILER
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: cb101fa80e2195f4e758d4e274a7ef142ee22d5d
WEB_ORCH_CHECKS: PASS
