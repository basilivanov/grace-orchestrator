# Legacy Code Cleanup Checklist

## ✅ Completed (Low-Risk, Non-Breaking)

- [x] Remove all Python cache files (__pycache__, *.pyc, *.pyo)
- [x] Create .gitignore to prevent cache file commits
- [x] Fix duplicate line in README.md
- [x] Update "phase-1 scaffold" references to "orchestrator"
- [x] Modernize README.md language
- [x] Create comprehensive legacy code analysis report
- [x] Create cleanup summary document
- [x] Create migration guide for users

## 🔄 In Progress / Requires Coordination

### High Priority - Breaking Changes

- [ ] **Remove legacy_feature.py module**
  - Location: `cli_commands/legacy_feature.py`
  - Impact: Scripts using old CLI commands will break
  - Prerequisites:
    - [ ] Audit all scripts using legacy commands
    - [ ] Create migration scripts
    - [ ] Announce deprecation timeline (3+ months)
    - [ ] Add deprecation warnings
  - Estimated effort: 1 day

- [ ] **Remove legacy artifact materialization**
  - Location: `tasks/architect_artifacts.py`
  - Pattern: `materialize_legacy_grace_docs` flag
  - Impact: Downstream consumers of XML artifacts affected
  - Prerequisites:
    - [ ] Identify all XML artifact consumers
    - [ ] Provide alternative formats
    - [ ] Coordinate with dependent teams
    - [ ] Add feature flag for gradual rollout
  - Estimated effort: 1-2 days

- [ ] **Remove old state store fallbacks**
  - Locations: `tasks/state_store.py`, `tasks/codex_launcher.py`
  - Impact: Old format state files won't load
  - Prerequisites:
    - [ ] Migrate all existing state to new format
    - [ ] Create and test migration tool
    - [ ] Backup existing state
    - [ ] Test with production data
  - Estimated effort: 1 day

### Medium Priority - Non-Breaking Refactors

- [ ] **Remove executor backward compatibility**
  - Location: `platform/executor_registry.py` lines 188-202
  - Impact: Old config format won't work
  - Prerequisites:
    - [ ] Update all agent_profiles.yaml files
    - [ ] Test executor selection
    - [ ] Document new format
  - Estimated effort: 0.5 days

- [ ] **Remove legacy review format support**
  - Location: `platform/review_artifact_contract.py`
  - Functions: `_read_legacy_markdown_review()`, `_legacy_markdown_status()`
  - Impact: Old review files won't parse
  - Prerequisites:
    - [ ] Verify all reviews use new format
    - [ ] Convert any remaining old format reviews
  - Estimated effort: 0.5 days

- [ ] **Implement ExecutorHistoryStore loading**
  - Location: `tasks/codex_launcher.py:161`
  - Current: `history=None,  # TODO: load from ExecutorHistoryStore`
  - Impact: Enables proper executor rotation
  - Prerequisites:
    - [ ] Design history loading strategy
    - [ ] Implement loading logic
    - [ ] Test rotation behavior
  - Estimated effort: 0.5 days

### Low Priority - Code Quality

- [ ] **Replace hardcoded model fallback**
  - Location: `tasks/codex_launcher.py:174`
  - Current: `shared_model = "gpt-5.4"`
  - Action: Use config-driven approach
  - Estimated effort: 0.25 days

- [ ] **Simplify planner logic**
  - Location: `flows/feature_pipeline.py:485-513`
  - Function: `_should_run_planner()`
  - Action: Remove backward compatibility comments, clarify logic
  - Estimated effort: 0.25 days

- [ ] **Consolidate agent profiles configuration**
  - Location: `agent_profiles.yaml`
  - Issue: Mixed format (executors list + legacy roles section)
  - Action: Clarify purpose or consolidate
  - Estimated effort: 0.25 days

## 📊 Metrics

### Completed
- Files modified: 3 (README.md, .gitignore, documentation)
- Cache files removed: ~50+ files
- Documentation pages created: 3

### Remaining
- High priority items: 3 (2-4 days effort)
- Medium priority items: 3 (1.5 days effort)
- Low priority items: 3 (0.75 days effort)
- **Total remaining effort: 4.25-6.25 days**

## 🎯 Success Criteria

- [ ] All legacy_feature.py functionality migrated or removed
- [ ] No fallback to old state store format
- [ ] Single artifact materialization mode (packet-first)
- [ ] No Python cache files in repository
- [ ] All TODO comments resolved or documented
- [ ] Documentation updated and accurate
- [ ] All tests passing
- [ ] No deprecation warnings in normal operation
- [ ] Migration guide available for users
- [ ] Rollback plan documented

## 📅 Recommended Timeline

### Week 1-2: Preparation
- Add deprecation warnings to all legacy code paths
- Create and test migration tools
- Audit usage of legacy features
- Communicate deprecation timeline

### Week 3-8: Deprecation Period
- Monitor deprecation warnings
- Assist users with migration
- Fix issues in new code paths
- Update documentation

### Week 9+: Removal
- Remove legacy code (breaking changes)
- Update tests
- Release new version
- Monitor for issues

## 🔗 Related Documents

- `LEGACY_CLEANUP_REPORT.md` - Detailed analysis of all legacy patterns
- `LEGACY_CLEANUP_SUMMARY.md` - Executive summary of cleanup status
- `MIGRATION_GUIDE.md` - User guide for migrating from legacy patterns
- `README.md` - Updated project documentation
