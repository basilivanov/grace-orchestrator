# Escalation Policy — Phase 1/2 Baseline

Audience: Coder (literal executor).

Status: **DONE — baseline for all future phases.**

---

## 0. What exists (do not break)

| Module | File | Status |
|--------|------|--------|
| Core models + classification + decision | `src/grace_control/core/feature_recovery.py` | ✅ 271 lines, 21 classify paths, 15+ decide actions |
| Fixture golden tests | `tests/golden_fixtures/test_fixture_recovery_scenarios.py` | ✅ 66 lines, 25 total tests pass |
| Recovery fixture YAMLs | `fixtures/golden/recovery_*.yaml` | ✅ 14 files, all pass |
| Recovery config TZ | `docs/codex/tz-017c-recovery-config-and-fixture-yaml-requirements.md` | ✅ reference |
| Recovery wiring TZ | `docs/codex/tz-017b-feature-recovery-controller-live-wiring.md` | ✅ reference |

### Models (do not rename, do not remove fields)

```python
FailureClass: RETRYABLE_CODER, RETRYABLE_VERIFIER, RETRYABLE_REVIEWER,
              ARCHITECT_REPACK_NEEDED, ARCHITECT_ESCALATION_NEEDED,
              MERGE_RETRYABLE, TRUE_BLOCKER, UNKNOWN_RETRYABLE

RecoveryAction: RETRY_SAME_CODER, SWITCH_CODER, RETURN_TO_ARCHITECT,
                ESCALATE_ARCHITECT, RETRY_VERIFIER, RETRY_REVIEWER,
                RETRY_MERGE, BLOCK_FEATURE, NO_ACTION

FailureSignal: feature_id, packet_id, packet_state, domain_status, reason,
               acceptance_verdict, evidence_verifier_verdict, reviewer_verdict,
               merge_error, blocked_reason, acceptance_profile,
               attempt_count, coder_attempt_count, architect_repair_count,
               reviewer_reject_count, verifier_reject_count, merge_attempt_count,
               current_executor_id, previous_executor_ids, changed_files

RecoveryPolicy: max_same_coder_attempts=2, max_total_coder_attempts=4,
                max_architect_repairs=2, max_reviewer_retries=2,
                max_verifier_retries=2, max_merge_retries=2,
                allow_profile_escalation=True, allow_model_switch=True
```

### Known gaps (Phase 1)

| # | Gap | Status |
|---|-----|--------|
| 1 | `RecoveryPolicy.never_downgrade_strict` missing | ⚠️ Must add before Phase 3 |
| 2 | Verifier/reviewer invalid JSON → UNKNOWN instead of RETRYABLE_VERIFIER/REVIEWER | ⚠️ Should fix |
| 3 | `no_changes_produced` no explicit classification | Low priority |
| 4 | `build_failure_signal_from_packet_run` not implemented | Needed for Phase 3 |

---

## Must NOT change

- Do NOT rename `FailureClass`, `RecoveryAction`, `FailureSignal`, `RecoveryDecision`, `RecoveryPolicy`
- Do NOT change existing classification/decision semantics
- Do NOT remove fields from any model
- Do NOT add a competing routing engine
- Do NOT hardcode executor IDs outside `agent_profiles.yaml`
- Do NOT break existing 25 tests
- Do NOT break 14 recovery fixture YAMLs
