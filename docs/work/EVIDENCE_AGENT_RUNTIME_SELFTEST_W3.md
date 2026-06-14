# W3 Evidence: AgentRuntimeContract + Runtime Selftest Gate

## What was built

### `AgentRuntimeContract`
- Pydantic BaseModel with all required fields: `runtime_run_id`, `feature_id`, `wave_id`, `packet_id`, `role`, `adapter`, `target_repo_root`, `orchestrator_repo_root`, `worktree_root`, `cwd`, `linux_user`, `home`, `shell`, `executor_id`, `agent_name`, `provider`, `model`, `packet_scope`, `frozen_scope`, `acceptance_profile`, `runtime_artifacts_dir`, `events_jsonl_path`, `timeout_seconds`, `created_at`.
- Builder (`AgentRuntimeContractBuilder.build`) populates from `packet_data`, `executor`, `RuntimeTraceContext`, and settings.

### `AgentRuntimeFailureCode`
- Constants: `AGENT_ENV_BAD_USER`, `AGENT_ENV_BAD_HOME`, `AGENT_ENV_BAD_CWD`, `AGENT_ENV_BAD_GIT_ROOT`, `AGENT_ENV_MISSING_AUTH`, `AGENT_ENV_MISSING_CONFIG`, `AGENT_MODEL_UNAVAILABLE`, `AGENT_WORKTREE_INVALID`, `AGENT_WORKTREE_DIRTY_BEFORE_RUN`, `AGENT_SCOPE_PARENT_NOT_CREATABLE`, `AGENT_ARTIFACT_DIR_NOT_WRITABLE`, `AGENT_RUNTIME_CONTRACT_INVALID`.

### `RuntimeCheck` / `AgentRuntimeSelftestResult`
- `RuntimeCheck`: `check_id`, `ok`, `expected`, `actual`, `details`, `failure_code`.
- `AgentRuntimeSelftestResult`: `ok`, `failure_code`, `summary`, `checks`.
- Persisted as `runtime_selftest.json` via `RuntimeArtifactStore`.

### `AgentRuntimeSelftest`
- 15 check IDs implemented:
  - `CHECK_CONTRACT_HAS_PACKET_ID`
  - `CHECK_CONTRACT_HAS_TARGET_REPO_ROOT`
  - `CHECK_TARGET_REPO_EXISTS`
  - `CHECK_ORCHESTRATOR_REPO_EXISTS`
  - `CHECK_WORKTREE_ROOT_EXISTS`
  - `CHECK_CWD_EQUALS_WORKTREE_ROOT`
  - `CHECK_GIT_ROOT_EQUALS_WORKTREE_ROOT`
  - `CHECK_TARGET_REPO_NOT_ORCHESTRATOR_REPO_WHEN_TARGET_MODE`
  - `CHECK_PACKET_SCOPE_RELATIVE`
  - `CHECK_SCOPE_PARENT_EXISTS_OR_CREATABLE`
  - `CHECK_FROZEN_SCOPE_NO_OVERLAP`
  - `CHECK_ARTIFACT_DIR_WRITABLE`
  - `CHECK_OPENCODE_BINARY_AVAILABLE`
  - `CHECK_OPENCODE_AUTH_VISIBLE`
  - `CHECK_OPENCODE_MODEL_CONFIG_PRESENT`
- Shell runner abstraction for CI/mockability.
- Configurable strictness via settings:
  - `agent_runtime_require_opencode_auth` (default: False)
  - `agent_runtime_require_model_config` (default: False)
  - `agent_runtime_fail_on_bad_cwd` (default: True)
  - `agent_runtime_fail_on_bad_git_root` (default: True)
  - `agent_runtime_fail_on_dirty_worktree` (default: False)

### Integration into `PacketExecutionAdapter.execute()`
- Before `_call_executor`: build contract → persist `runtime_contract.json` → run selftest → emit per-check events → persist `runtime_selftest.json` → emit `completed`/`failed` → if failed, fast reject with failure code.
- Observability events: `packet.runtime_contract_created`, `packet.runtime_selftest_started`, `packet.runtime_selftest_check_completed`, `packet.runtime_selftest_completed`, `packet.runtime_selftest_failed`.
- Both artifacts written via `RuntimeArtifactStore` with sha256/size.
- Disabled when `runtime_observability_enabled=False`.

### Tests (29 total)
- **Contract**: packet_id requirement, target_repo_root requirement, builder populates from packet data, orchestrator_repo_root, acceptance_profile, failure code values.
- **Selftest passing**: valid runtime, artifact ref, all checks present, structured payload, structured fields.
- **Selftest failures**: worktree missing, cwd mismatch (strict), git root mismatch (strict), absolute scope, dotdot scope, frozen scope overlap, artifact dir not writable.
- **Failure codes**: bad_cwd, bad_git_root, missing_worktree, scope_parent.
- **OpenCode checks**: binary available, auth missing (non-strict warning), auth missing (strict failure), model config missing (non-strict warning), model config missing (strict failure).
- **Contract artifact**: sha256/size verification.

## Evidence summary

| Requirement | Status |
|------------|--------|
| AgentRuntimeContract exists | ✅ |
| AgentRuntimeSelftest exists | ✅ |
| Packet execution builds + persists runtime_contract.json | ✅ |
| Packet execution runs selftest before _call_executor | ✅ |
| Failed critical selftest prevents agent start | ✅ |
| Selftest result persisted as runtime_selftest.json | ✅ |
| Events include packet.runtime_contract_created | ✅ |
| Events include packet.runtime_selftest_started | ✅ |
| One event per check (packet.runtime_selftest_check_completed) | ✅ |
| Events include packet.runtime_selftest_completed/failed | ✅ |
| Contract/selftest artifacts have sha256 and size_bytes | ✅ |
| Bad cwd classified as AGENT_ENV_BAD_CWD | ✅ |
| Bad git root classified as AGENT_ENV_BAD_GIT_ROOT | ✅ |
| Missing worktree classified as AGENT_WORKTREE_INVALID | ✅ |
| Bad scope parent classified as AGENT_SCOPE_PARENT_NOT_CREATABLE | ✅ |
| OpenCode auth/model checks configurable strict/soft | ✅ |
| Existing W1/W2 tests still pass | ✅ |
| New W3 tests pass (29) | ✅ |
| No OpenCode server manager introduced | ✅ |
| Existing execution behavior unchanged when selftest passes | ✅ |
