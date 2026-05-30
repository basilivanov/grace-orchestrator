# Legacy Code Cleanup Summary

## Completed Actions (Low-Risk)

### 1. Cache File Cleanup ✓
- Removed all `__pycache__/` directories
- Removed all `.pyc` and `.pyo` files
- Created `.gitignore` to prevent future cache file commits

### 2. Documentation Fixes ✓
- Fixed duplicate line in README.md (state/ directory description)
- Updated "phase-1 scaffold" references to "orchestrator"
- Modernized language to reflect current architecture state

## Identified Legacy Patterns (Requires Coordination)

### High Priority - Breaking Changes Required

1. **Legacy CLI Module** (`cli_commands/legacy_feature.py`)
   - Status: IDENTIFIED
   - Action: Migrate to registry-based commands
   - Risk: Medium (may affect existing scripts)
   - Files: `cli_commands/legacy_feature.py`, `cli_commands/parser.py`

2. **Legacy Artifact Materialization** (`tasks/architect_artifacts.py`)
   - Status: IDENTIFIED
   - Pattern: `materialize_legacy_grace_docs` flag
   - Action: Remove XML artifact generation, keep packet-first only
   - Risk: High (may affect downstream consumers)
   - Lines: Multiple references throughout file

3. **Old State Store Fallbacks**
   - Status: IDENTIFIED
   - Files: `tasks/state_store.py`, `tasks/codex_launcher.py`
   - Action: Remove fallback to old packet format
   - Risk: Medium (requires migration of existing state)

### Medium Priority - Non-Breaking Refactors

4. **Executor Configuration Backward Compatibility**
   - File: `platform/executor_registry.py`
   - Lines: 188-202 (synthesize from default/command)
   - Action: Require executors list, remove synthesis

5. **Legacy Review Format Support**
   - File: `platform/review_artifact_contract.py`
   - Functions: `_read_legacy_markdown_review()`, `_legacy_markdown_status()`
   - Action: Remove after ensuring all reviews use new format

6. **TODO: ExecutorHistoryStore Loading**
   - File: `tasks/codex_launcher.py:161`
   - Action: Implement history loading for proper executor rotation
   - Current: `history=None,  # TODO: load from ExecutorHistoryStore`

### Low Priority - Code Quality

7. **Hardcoded Model Fallback**
   - File: `tasks/codex_launcher.py:174`
   - Current: `shared_model = "gpt-5.4"`
   - Action: Use config-driven approach

8. **Planner Logic Simplification**
   - File: `flows/feature_pipeline.py:485-513`
   - Function: `_should_run_planner()`
   - Action: Remove backward compatibility comments, clarify logic

9. **Agent Profiles Configuration**
   - File: `agent_profiles.yaml`
   - Issue: Mixed format (executors list + legacy roles section)
   - Action: Clarify purpose or consolidate

## Files Modified

1. `/tmp/grace-orchestrator-export/src/prefect_grace/README.md`
   - Removed duplicate state/ directory line
   - Updated phase-1 references to current architecture
   - Modernized language

2. `/tmp/grace-orchestrator-export/src/prefect_grace/.gitignore`
   - Created to prevent cache file commits

3. Cache files (deleted)
   - All `__pycache__/` directories
   - All `.pyc` and `.pyo` files

## Next Steps

### Immediate (Can be done independently)
- [ ] Implement ExecutorHistoryStore loading (TODO item)
- [ ] Add deprecation warnings to legacy code paths
- [ ] Document migration path for legacy CLI commands

### Short-term (1-2 sprints)
- [ ] Create migration guide for legacy_feature.py users
- [ ] Add feature flags for legacy artifact materialization
- [ ] Test new registry format with all existing state

### Long-term (Coordinated release)
- [ ] Remove legacy_feature.py module
- [ ] Remove old state store fallbacks
- [ ] Remove legacy artifact materialization
- [ ] Require new executor configuration format

## Risk Mitigation

1. **Before removing legacy CLI:**
   - Audit all scripts using legacy commands
   - Provide migration scripts
   - Announce deprecation timeline

2. **Before removing state fallbacks:**
   - Migrate all existing state to new format
   - Provide migration tool
   - Test with production data

3. **Before removing legacy artifacts:**
   - Identify downstream consumers
   - Provide alternative formats
   - Coordinate with dependent teams

## Metrics

- **Files cleaned:** 2 (README.md, .gitignore created)
- **Cache files removed:** ~50+ files
- **Legacy patterns identified:** 9 major areas
- **Breaking changes required:** 3 high-priority items
- **Estimated effort for full cleanup:** 3.5-5.5 days

## References

See `LEGACY_CLEANUP_REPORT.md` for detailed analysis of all legacy patterns.
