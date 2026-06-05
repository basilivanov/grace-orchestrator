# Legacy Code Migration Guide

This guide helps migrate from legacy patterns to current architecture.

## 1. Legacy CLI Commands → Registry-Based Commands

### Old Pattern (legacy_feature.py)
```bash
# Old way
grace feature FEAT-123 "Title" "Summary"
grace packet FEAT-123 W01 "Packet Title" coder high "Summary"
grace run-codex PACKET-001
```

### New Pattern (project_registry.py)
```bash
# New way
grace validate-project
grace scan-packets
grace submit-packets --feature-id FEAT-123
grace run-managed-packet PACKET-001
```

### Migration Steps
1. Audit scripts using old commands
2. Replace with registry-based equivalents
3. Test with dry-run flag
4. Update documentation

## 2. State Store Format Migration

### Old Format
```yaml
packets:
  - packet_id: PACKET-001
    feature_id: FEAT-123
    # ... other fields
```

### New Format (Registry)
```yaml
# Stored in packet registry with source hash tracking
packet_id: PACKET-001
feature_id: FEAT-123
source_hash: abc123...
last_executed_source_hash: abc123...
# ... other fields
```

### Migration Tool
```bash
# Use built-in migration
grace scan-packets --mode strict
grace sync-packets
```

## 3. Artifact Materialization

### Old Pattern (Legacy XML)
```python
architect_payload = {
    "materialize_legacy_grace_docs": True,
    # Generates: requirements.slice.xml, development-plan.slice.xml, etc.
}
```

### New Pattern (Packet-First)
```python
architect_payload = {
    # No flag needed - packet-first is default
    # Generates: packet markdown files only
}
```

### Migration Steps
1. Identify consumers of XML artifacts
2. Provide alternative packet-based formats
3. Update downstream tooling
4. Remove legacy flag

## 4. Executor Configuration

### Old Format
```yaml
codex:
  binary: agy
  default: codex-cli
  command: agy
```

### New Format
```yaml
codex:
  binary: agy
  executors:
    - executor_id: coder-cheap
      kind: codex
      command: agy
      model: gemini-3.5-flash
      roles: [coder]
      priority: 100
```

### Migration Steps
1. Add executors list to agent_profiles.yaml
2. Test executor selection
3. Remove old default/command fields

## 5. Review Format

### Old Format (Legacy Markdown)
```markdown
# Review
Status: ACCEPTED
Reasons: ...
```

### New Format (Structured)
```yaml
verdict: ACCEPTED
reasons: []
review_target_packet_id: PACKET-001
```

### Migration Steps
1. Ensure all reviews use new format
2. Remove legacy parser functions
3. Update review templates

## 6. Resume Strategy

### Old Pattern
```python
# Legacy/none strategy with fail-open
resume_strategy = "legacy"
```

### New Pattern
```python
# Explicit strategies with source hash gating
resume_strategy = "feature_role"  # or "packet_parent"
# Automatically gates on source_hash changes
```

### Migration Steps
1. Update packet execution hints
2. Test resume behavior
3. Remove legacy strategy support

## Breaking Changes Timeline

### Phase 1: Deprecation Warnings (Current)
- Add warnings to legacy code paths
- Document migration paths
- Provide migration tools

### Phase 2: Parallel Support (1-2 months)
- Both old and new formats work
- Encourage migration
- Monitor usage metrics

### Phase 3: Legacy Removal (3+ months)
- Remove legacy_feature.py
- Remove old format fallbacks
- Remove legacy artifact generation
- Require new configuration format

## Support

For migration assistance:
1. Check LEGACY_CLEANUP_REPORT.md for detailed analysis
2. Review LEGACY_CLEANUP_SUMMARY.md for status
3. Test changes with dry-run flags
4. Report issues with legacy code paths

## Rollback Plan

If issues arise:
1. Legacy code paths remain available during deprecation period
2. State format is backward compatible
3. Configuration supports both formats temporarily
4. Rollback by reverting configuration changes
