# TZ 011 — Acceptance profile routing for verifier/reviewer cost control

Audience: Flash coder / literal executor.

Goal: make `acceptance_profile` control expensive LLM gates after deterministic acceptance.

Do not redesign the full pipeline. Do not remove Evidence Verifier or Reviewer modules. Do not change deterministic acceptance semantics except where needed by tests.

---

## 0. Target behavior

After coder finishes, pipeline must be:

```text
coder
→ deterministic acceptance
→ profile-based LLM gates
→ merge only if final accepted
```

Profile behavior must be exactly:

```text
FAST:
  deterministic only
  no evidence verifier
  no reviewer

NORMAL:
  deterministic
  cheap evidence verifier
  no reviewer by default

STRICT:
  deterministic
  cheap evidence verifier
  reviewer always
```

Important:

```text
Deterministic acceptance remains authoritative.
If deterministic acceptance fails, no verifier/reviewer runs for any profile.
```

---

## 1. Current problem

`acceptance_profile` currently affects deterministic T1/T2 rules, but `PacketExecutionAdapter.execute()` does not use the profile for Evidence Verifier / Reviewer routing.

Current behavior after deterministic ACCEPTED is effectively:

```text
FAST   → evidence verifier → reviewer
NORMAL → evidence verifier → reviewer
STRICT → evidence verifier → reviewer
```

This is too slow and too expensive for small packets and golden smoke.

---

## 2. Files to change

Expected files:

```text
src/grace_control/adapters/packet_executor.py
tests/grace_control/adapters/test_packet_executor_acceptance.py
grace/features/golden-smoke-live-001.yaml
```

May also add helper module if desired, but keep it simple.

---

## 3. Adapter behavior

File:

```text
src/grace_control/adapters/packet_executor.py
```

After deterministic acceptance passes and before calling `run_evidence_verifier(...)`, inspect:

```python
pkt_contract.acceptance_profile
```

Use `AcceptanceProfile` enum if already imported. Do not compare random strings if enum is available.

---

## 4. FAST behavior

If:

```python
pkt_contract.acceptance_profile == AcceptanceProfile.FAST
```

then:

1. Do **not** call `run_evidence_verifier(...)`.
2. Do **not** call `run_reviewer_gate(...)`.
3. Build skipped reports:

```python
ev_report = skipped_evidence_report("FAST profile skips evidence verifier")
rv_report = skipped_reviewer_report("FAST profile skips reviewer")
```

4. Return accepted if deterministic acceptance was accepted.
5. Store result_json with all four keys:

```text
legacy_result
acceptance_report
evidence_verifier_report
reviewer_report
```

6. `PacketRun.status` must be `accepted`.

This means FAST is deterministic-only.

---

## 5. NORMAL behavior

If:

```python
pkt_contract.acceptance_profile == AcceptanceProfile.NORMAL
```

then:

1. Run `run_evidence_verifier(...)`.
2. If Evidence Verifier returns `REWORK_TO_CODER`, return rejected.
3. If Evidence Verifier returns `RETURN_TO_ARCHITECT`, return blocked.
4. If Evidence Verifier returns `PASS`, **do not run reviewer by default**.
5. Build skipped reviewer report:

```python
rv_report = skipped_reviewer_report("NORMAL profile skips reviewer by default")
```

6. Return accepted.
7. Store all four reports.

This means NORMAL is deterministic + cheap evidence verifier only.

---

## 6. STRICT behavior

If:

```python
pkt_contract.acceptance_profile == AcceptanceProfile.STRICT
```

then keep the current full behavior:

```text
deterministic accepted
→ evidence verifier
→ reviewer
```

Reviewer PASS → accepted.
Reviewer REWORK_TO_CODER → rejected.
Reviewer RETURN_TO_ARCHITECT → blocked.

---

## 7. Future routing hook, but do not implement complex routing now

Later architect should choose profile based on risk:

```text
FAST   → tiny/sandbox/mechanical changes
NORMAL → normal product changes
STRICT → billing, auth, payments, security, migrations, destructive operations, self-evolution, infra, data loss risk
```

For this task, only add a minimal TODO/comment near architect prompt or plan creation if easy:

```text
TODO: architect should choose acceptance_profile based on risk:
FAST for tiny/sandbox, NORMAL for normal, STRICT for billing/auth/security/migrations/self-evolution.
```

Do **not** implement complex risk classifier in this task.

---

## 8. Golden smoke profile

Update:

```text
grace/features/golden-smoke-live-001.yaml
```

For the smoke packet, set:

```yaml
acceptance_profile: FAST
```

This golden is intended to test the basic coder + deterministic + merge path first, not live `agy`/`opencode` reviewer gates.

If TZ-010 has not yet moved golden into sandbox, do not fight it here. But if editing the same YAML anyway, prefer the TZ-010 sandbox version.

---

## 9. Implementation hint — avoid copy-paste accepted branch

There is already accepted-result logic after reviewer PASS.

Prefer extracting a private helper in `PacketExecutionAdapter`, for example:

```python
def _accepted_execution_result(...):
    ...
```

or:

```python
def _finalize_accepted(...):
    ...
```

But do not over-refactor. If helper becomes too large, keep changes localized.

Acceptance requirement is behavior, not helper shape.

---

## 10. Tests required

Update:

```text
tests/grace_control/adapters/test_packet_executor_acceptance.py
```

Add or update tests with mocks for:

```python
run_evidence_verifier
run_reviewer_gate
run_acceptance_pipeline
```

### Test 1 — FAST skips verifier and reviewer

Setup:

```text
packet.acceptance_profile = FAST
acceptance_report.is_accepted = True
```

Assert:

```text
run_evidence_verifier not called
run_reviewer_gate not called
result.accepted is True
PacketRun.status == accepted
result_json.evidence_verifier_report.skipped == true
result_json.reviewer_report.skipped == true
```

### Test 2 — NORMAL runs verifier but skips reviewer on verifier PASS

Setup:

```text
packet.acceptance_profile = NORMAL
acceptance_report.is_accepted = True
evidence_verifier.verdict = PASS
```

Assert:

```text
run_evidence_verifier called once
run_reviewer_gate not called
result.accepted is True
result_json.reviewer_report.skipped == true
```

### Test 3 — NORMAL verifier rework rejects and skips reviewer

Setup:

```text
packet.acceptance_profile = NORMAL
evidence_verifier.verdict = REWORK_TO_CODER
```

Assert:

```text
reviewer not called
result.accepted is False
result.domain_status == rejected
```

### Test 4 — NORMAL verifier architect return blocks and skips reviewer

Setup:

```text
packet.acceptance_profile = NORMAL
evidence_verifier.verdict = RETURN_TO_ARCHITECT
```

Assert:

```text
reviewer not called
result.accepted is False
result.domain_status == blocked
PacketRun.status == blocked
```

### Test 5 — STRICT runs verifier and reviewer

Setup:

```text
packet.acceptance_profile = STRICT
evidence_verifier.verdict = PASS
reviewer.verdict = PASS
```

Assert:

```text
run_evidence_verifier called once
run_reviewer_gate called once
result.accepted is True
```

### Test 6 — deterministic fail still skips both for all profiles

Parametrize over:

```text
FAST
NORMAL
STRICT
```

Setup:

```text
acceptance_report.is_accepted = False
```

Assert:

```text
verifier not called
reviewer not called
result.accepted is False
```

---

## 11. result_json requirements

All branches must still store:

```text
legacy_result
acceptance_report
evidence_verifier_report
reviewer_report
```

For skipped stages:

```json
"skipped": true
```

and a clear reason:

```text
FAST profile skips evidence verifier
FAST profile skips reviewer
NORMAL profile skips reviewer by default
```

---

## 12. Do not do in this task

Do not add risk classifier.
Do not make architect auto-select profiles yet.
Do not remove verifier/reviewer modules.
Do not remove STRICT reviewer path.
Do not call real LLM in tests.
Do not make NORMAL reviewer run by default.
Do not change `AcceptanceProfile` enum names.

Allowed profiles remain exactly:

```text
FAST
NORMAL
STRICT
```

---

## 13. Tests to run

Run:

```bash
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
pytest tests/grace_control/core/test_acceptance_pipeline.py -q
pytest tests/grace_control/core/test_evidence_verifier.py -q
pytest tests/grace_control/core/test_reviewer_gate.py -q
pytest tests -q
```

---

## 14. Acceptance criteria

Done only if:

1. FAST accepted deterministic packets do not call verifier/reviewer.
2. NORMAL accepted deterministic packets call verifier but not reviewer by default.
3. STRICT accepted deterministic packets call verifier and reviewer.
4. Deterministic fail skips verifier/reviewer for all profiles.
5. result_json includes skipped reports for skipped stages.
6. golden smoke packet uses FAST.
7. all targeted tests pass.

---

## 15. After this task

After TZ-010 and TZ-011 are both fixed, the first golden smoke should be cheap:

```text
coder
→ deterministic acceptance
→ no verifier
→ no reviewer
→ merge
```

This is intentional. Later we will add architect-side risk/profile selection.
