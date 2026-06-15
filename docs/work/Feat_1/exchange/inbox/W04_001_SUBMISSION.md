---
feature_id: Feat_1
wave_id: W04
kind: SUBMISSION
status: SUBMITTED
task: docs/work/Feat_1/exchange/outbox/W04_000_TASK.md
---

# Submission: W04 — Execution Packet Context Bundle for Coder

## Changed files

1. **`src/grace_control/services/packet_materializer.py`** — Enriched `EXECUTION_PACKET.md` with all 17 required sections:
   - Objective, Business Requirement, Role and Non-Goals, Allowed Write Scope, Frozen Scope
   - Relevant File Tree (file sizes, directory structure)
   - Selected File Previews (first 20 lines of each scope file)
   - Nearby Tests (auto-discovery of test files related to scope)
   - Config / Build Files Available (checklist of config files)
   - Import / Dependency Hints (extracted imports from scope files)
   - Coder Instructions, Acceptance Criteria
   - Verification Commands by T0/T1/T2
   - Full Expected Evidence Fields (structured with descriptions/formats)
   - Workspace Mode and Limitations
   - Target Repo Root Diagnostics (exists, is_git, file_count, total_size)
   - Full Spec JSON dump
   - Added `CONFIG_ALLOWLIST` constant with all required config file patterns
   - Added `target_root` parameter to `materialize()` for file tree/previews

2. **`src/grace_control/adapters/packet_executor.py`** — Added W04 features:
   - **Context gate**: NORMAL/STRICT coder packets with `skip_context_builder=true` are rejected unless `context_not_required=true` is set in spec
   - **Expanded config allowlist**: scoped copy now uses `PacketMaterializer.CONFIG_ALLOWLIST` instead of hardcoded `["pyproject.toml"]`
   - **Materializer target resolution**: `_resolve_materializer_target()` resolves effective target repo root for file tree/previews

3. **`src/grace_control/services/agent_run_service.py`** — CWD safety:
   - Replaced `cwd.mkdir(parents=True, exist_ok=True)` with explicit check that raises `RuntimeError` when cwd does not exist
   - No more silent directory creation that masks bad worktree routing

4. **`src/grace_control/config/agent_profiles.yaml`** — Profile compliance:
   - Added `input: { mode: file }` and `{packet_path}` reference to `coder_agy` profile to satisfy the "every coder profile must have input_mode or packet_arg" requirement

5. **`tests/test_w04_execution_packet_context_bundle.py`** — 7 new tests:
   - `test_execution_packet_contains_file_tree_and_previews` (§1/§6/§7)
   - `test_execution_packet_renders_full_evidence_requirements` (§14)
   - `test_normal_packet_requires_context_or_explicit_override` (§2, logic test)
   - `test_normal_packet_passes_with_context_not_required` (§2, override test)
   - `test_scoped_copy_includes_required_config_allowlist` (§3)
   - `test_agent_run_fails_if_cwd_missing_instead_of_creating_it` (§4)
   - `test_coder_profiles_all_have_input_mode_or_packet_arg` (§profile validation)

6. **`tests/grace_control/adapters/test_packet_executor_acceptance.py`** — Added `context_not_required: true` to `_make_mock_packet` spec_json so existing acceptance tests pass through the W04 context gate

## Commit SHA

`b295530`

## Test Commands and Output

```bash
python3 -m pytest tests/test_w04_execution_packet_context_bundle.py -v
```
7 passed (all tests green)

```bash
python3 -m pytest tests/test_w02_scope_contract.py tests/grace_control/services/test_agent_workspace_builder.py tests/grace_control/config/test_agent_profile_passthrough.py -v
```
36 passed (no regressions)

## Evidence: Packet Context Rendering

The enriched `EXECUTION_PACKET.md` now includes:
- **Section 6 (File Tree)**: Lists scope files with sizes in bytes, directory contents
- **Section 7 (Previews)**: First 20 lines of each source file with total line count
- **Section 8 (Nearby Tests)**: Auto-discovery of test files in `tests/` directories
- **Section 9 (Config)**: Reports which config files exist in target repo
- **Section 14 (Evidence)**: Full structured evidence fields with `description` and `format` — not just IDs
- **Section 16 (Target Diagnostics)**: Reports `is_git`, `file_count`, `total_size` of target repo

## Known Limitations

- File previews are limited to 20 lines per file
- Nearby test discovery uses simple directory heuristics (parent/tests/, sibling tests/)
- Import hints only show import statements, not full dependency trees
- Target repo `file_count`/`total_size` may be expensive for very large repos (no depth limit)
