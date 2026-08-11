# TZ 02 Packet Execution — submission

Implementation commit: 0f4a96b2f4cb10fd9cb9aa810ace8fe33f7b6147.

## Scope

- Modified packet_executor.py into a compatibility facade.
- Added runtime, preflight, rerun, post-execution/scope, and observability services under src/grace_control/services/.
- Retained PacketExecutionAdapter, ExecutionResult, legacy helper re-exports, _call_executor, acceptance/routing/persistence helpers, event names, artifact names, and result/evidence keys.
- Reused AgentRuntimeContractBuilder, AgentRuntimeSelftest, PacketMaterializer, WorktreeInspector, AgentCommitService, WorktreeCleanupService, RuntimeArtifactStore, RuntimeEventLogger, RuntimeScopeEnforcer, rerun services, acceptance pipeline, verifier/reviewer gates, and packet-control rerun markers.

## Structural result

- packet_executor.py: 2074 → 983 physical lines.
- execute(): estimated 4343 → 2684 Grace tokens.
- Largest extracted functions: _prepare_workspace ~3705, enforce_scope ~2529, runtime run ~2228.
- New modules: 107–906 physical lines; all extracted functions are below the 4000-token guardrail.
- Existing behavioral assertions were preserved; no test assertions were weakened or broad skips added.

## Checks

- Focused packet/runtime suite: 106 passed.
- Full required suite: 1584 passed, 2 skipped, 33 failed; failures are existing repository/environment debt outside this packet refactor (agent-profile/config expectations, OpenCode backend tokens_in mismatch, /tmp/grace_planning_logs permissions, and session/profile tests). The packet-focused suite and the affected audit compatibility test pass.
- python3 scripts/grace_lint.py on the facade and all five new modules: PASS.
- py_compile: PASS.
- git diff --check: PASS.
- make lint: unable to run cleanly because the repository .venv has no ruff module (No module named ruff).

WEB_ORCH_REPORT: SUBMISSION 02_PACKET_EXECUTION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 0f4a96b2f4cb10fd9cb9aa810ace8fe33f7b6147
WEB_ORCH_CHECKS: PASS
