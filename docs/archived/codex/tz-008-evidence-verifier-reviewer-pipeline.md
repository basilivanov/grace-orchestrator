# TZ 008 — Detailed implementation plan: Evidence Verifier + staged Reviewer pipeline

Audience: **Flash coder / literal executor**.

Do not redesign the architecture. Do not rename fields unless this TZ explicitly says so. Implement exactly the staged pipeline below.

---

## 0. Target behavior

Current high-level execution must become:

```text
Architect / YAML plan
→ PacketExecutionAdapter executes coder through current runner
→ deterministic acceptance pipeline
→ cheap Evidence Verifier
→ expensive Reviewer
→ accepted result
→ worker releases packet
→ merge endpoint
```

Important rule:

```text
Reviewer must never run if deterministic acceptance failed.
Reviewer must never run if Evidence Verifier did not PASS.
```

Use existing role config:

```yaml
verifier-cheap:
  roles: [verifier]
  model: gemini-3.5-flash
```

Reviewer remains expensive `reviewer` role.

---

## 1. Files to change / add

Expected files:

```text
src/grace_control/core/evidence_verifier.py        # new
src/grace_control/core/reviewer_gate.py            # new, or reviewer.py if clearer
src/grace_control/adapters/packet_executor.py      # update pipeline orchestration
src/grace_control/core/contracts.py                # add report models if preferred here
src/prefect_grace/prompts/evidence_verifier_prompt.md  # new
src/prefect_grace/prompts/reviewer_prompt.md            # update existing if already present
tests/grace_control/core/test_evidence_verifier.py      # new
tests/grace_control/core/test_reviewer_gate.py          # new or combined
tests/grace_control/adapters/test_packet_executor_acceptance.py # update routing tests
```

Do not remove legacy runner in this task.
Do not change merge endpoint in this task unless a test already fails because of this change.
Do not change acceptance pipeline semantics except to pass its outputs into the new stages.

---

## 2. Add Evidence Verifier models

Create `src/grace_control/core/evidence_verifier.py`.

Add enum:

```python
from enum import Enum

class EvidenceVerifierVerdict(str, Enum):
    PASS = "PASS"
    REWORK_TO_CODER = "REWORK_TO_CODER"
    RETURN_TO_ARCHITECT = "RETURN_TO_ARCHITECT"
```

Add Pydantic model:

```python
from pydantic import BaseModel, Field

class EvidenceVerifierReport(BaseModel):
    verdict: EvidenceVerifierVerdict
    summary: str = ""
    missing_evidence: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    spec_conflicts: list[str] = Field(default_factory=list)
    coder_instructions: list[str] = Field(default_factory=list)
    architect_questions: list[str] = Field(default_factory=list)
    suggested_next_owner: str = "coder"
    skipped: bool = False
    reason: str = ""
```

Add helpers:

```python
def skipped_evidence_report(reason: str) -> EvidenceVerifierReport:
    return EvidenceVerifierReport(
        verdict=EvidenceVerifierVerdict.REWORK_TO_CODER,
        summary=reason,
        skipped=True,
        reason=reason,
        suggested_next_owner="coder",
    )
```

Add JSON parser:

```python
def parse_evidence_verifier_json(raw: str) -> EvidenceVerifierReport:
    # Extract first JSON object from raw text.
    # Validate verdict.
    # On invalid JSON, return REWORK_TO_CODER with failed_checks=[...]
```

Do not let invalid verifier output accidentally PASS.

---

## 3. Add `run_evidence_verifier(...)`

In `src/grace_control/core/evidence_verifier.py`, expose:

```python
async def run_evidence_verifier(
    *,
    packet,
    acceptance_report,
    worktree_path,
    run_dir,
    changed_files: list[str],
    artifacts: list[str] | None = None,
) -> EvidenceVerifierReport:
    ...
```

Implementation requirements:

1. Build prompt from:
   - packet id/title/description;
   - allowed_write_scope;
   - frozen_scope;
   - verification;
   - expected_evidence;
   - acceptance_report summary/final_verdict/stages/evidence_issues/scope_violations;
   - changed files;
   - artifact paths;
   - git diff summary if cheap to compute.

2. Load prompt template from:

```text
src/prefect_grace/prompts/evidence_verifier_prompt.md
```

3. Call LLM via existing runner:

```python
from grace_control.core.llm_runner import run_llm
raw = await run_llm(prompt, role="verifier", cli="agy")
```

If `run_llm` signature requires model, use role default if possible. If not possible, use current verifier profile/model from config: `gemini-3.5-flash`.

4. Parse strict JSON into `EvidenceVerifierReport`.

5. Safety fallback:
   - timeout/error/invalid JSON → `REWORK_TO_CODER`, not PASS;
   - include error in `failed_checks` and `summary`.

6. This function must not run deterministic commands. Deterministic commands are already done by acceptance pipeline.

---

## 4. Evidence Verifier prompt

Create `src/prefect_grace/prompts/evidence_verifier_prompt.md` with this meaning:

```text
You are Evidence Verifier, not final reviewer.
You are cheap and factual.
Your job is only to check whether the packet contract is proven by evidence.
Do not judge architecture quality unless it directly means evidence is missing.
Do not ask for broad refactors.

Return JSON only:
{
  "verdict": "PASS | REWORK_TO_CODER | RETURN_TO_ARCHITECT",
  "summary": "...",
  "missing_evidence": [],
  "failed_checks": [],
  "spec_conflicts": [],
  "coder_instructions": [],
  "architect_questions": [],
  "suggested_next_owner": "coder | architect | reviewer"
}

Use PASS only when:
- deterministic acceptance already passed;
- expected evidence exists;
- verification logs support the packet objective;
- changed files match allowed scope and packet objective;
- no obvious missing requirement.

Use REWORK_TO_CODER for:
- tests failed or missing;
- expected evidence missing;
- artifact missing/empty;
- implementation incomplete;
- file not created;
- acceptance report incomplete;
- objective not proven.

Use RETURN_TO_ARCHITECT only for bad packet/spec:
- scope too narrow to implement objective;
- frozen scope conflicts with objective;
- verification command references impossible/non-existing target;
- expected evidence impossible to produce;
- requirements contradict each other;
- packet split is too narrow and needs replan;
- dependency packet is missing.
```

Exact wording may be improved, but these decision rules must stay.

---

## 5. Add Reviewer gate models

Create `src/grace_control/core/reviewer_gate.py`.

Add enum:

```python
class ReviewerVerdict(str, Enum):
    PASS = "PASS"
    REWORK_TO_CODER = "REWORK_TO_CODER"
    RETURN_TO_ARCHITECT = "RETURN_TO_ARCHITECT"
```

Add model:

```python
class ReviewerReport(BaseModel):
    verdict: ReviewerVerdict
    summary: str = ""
    risks: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
    architect_questions: list[str] = Field(default_factory=list)
    suggested_next_owner: str = "coder"
    skipped: bool = False
    reason: str = ""
```

Add helper:

```python
def skipped_reviewer_report(reason: str) -> ReviewerReport:
    return ReviewerReport(
        verdict=ReviewerVerdict.REWORK_TO_CODER,
        summary=reason,
        skipped=True,
        reason=reason,
        suggested_next_owner="coder",
    )
```

Add parser:

```python
def parse_reviewer_json(raw: str) -> ReviewerReport:
    # invalid JSON must never PASS
```

---

## 6. Add `run_reviewer_gate(...)`

In `src/grace_control/core/reviewer_gate.py`, expose:

```python
async def run_reviewer_gate(
    *,
    packet,
    acceptance_report,
    evidence_verifier_report,
    worktree_path,
    run_dir,
    changed_files: list[str],
    artifacts: list[str] | None = None,
) -> ReviewerReport:
    ...
```

Implementation requirements:

1. Reviewer must receive:
   - packet contract;
   - acceptance_report;
   - evidence_verifier_report;
   - changed files;
   - diff summary;
   - artifact paths;
   - relevant logs if easily available.

2. Load prompt from:

```text
src/prefect_grace/prompts/reviewer_prompt.md
```

3. Call:

```python
raw = await run_llm(prompt, role="reviewer", cli="opencode")
```

Use existing reviewer role/model config.

4. Invalid JSON/timeout/error must route to `REWORK_TO_CODER`, not PASS.

5. Reviewer must not run if evidence verifier verdict is not PASS. Enforce this in adapter, not only in tests.

---

## 7. Reviewer prompt

Update/create `src/prefect_grace/prompts/reviewer_prompt.md`.

Meaning:

```text
You are expensive final reviewer.
You run only after deterministic acceptance and Evidence Verifier PASS.
Do not repeat mechanical checks unless they reveal quality risk.
Check hidden risks, test gaming, bad shortcuts, maintainability, architecture damage, security/safety regressions.

Return JSON only:
{
  "verdict": "PASS | REWORK_TO_CODER | RETURN_TO_ARCHITECT",
  "summary": "...",
  "risks": [],
  "required_changes": [],
  "architect_questions": [],
  "suggested_next_owner": "coder | architect | merge"
}

Use REWORK_TO_CODER for fixable implementation issues.
Use RETURN_TO_ARCHITECT only when the packet/spec/scope is wrong and coder cannot safely fix it.
Use PASS only if implementation is good enough to merge.
```

---

## 8. Update `PacketExecutionAdapter.execute()` orchestration

File:

```text
src/grace_control/adapters/packet_executor.py
```

Current accepted path builds `execution_result` immediately after deterministic acceptance.

Change flow to this exact order:

```text
legacy/coder result
→ deterministic acceptance report
→ if deterministic report not accepted: return rejected, skip verifier/reviewer
→ run evidence verifier
→ if evidence verifier REWORK_TO_CODER: return rejected, skip reviewer
→ if evidence verifier RETURN_TO_ARCHITECT: return blocked, skip reviewer
→ run reviewer
→ if reviewer PASS: return accepted
→ if reviewer REWORK_TO_CODER: return rejected
→ if reviewer RETURN_TO_ARCHITECT: return blocked
```

### 8.1 Deterministic fail branch

When `not accept_report.is_accepted`, store:

```python
result_json = {
    "legacy_result": safe_legacy_dict,
    "acceptance_report": accept_report.to_dict(),
    "evidence_verifier_report": skipped_evidence_report("deterministic acceptance failed").model_dump(),
    "reviewer_report": skipped_reviewer_report("deterministic acceptance failed").model_dump(),
}
```

Return `ExecutionResult`:

```python
accepted=False
domain_status="rejected"
reason=accept_report.summary
acceptance_verdict=accept_report.final_verdict.value
acceptance_summary=accept_report.summary
```

No verifier call. No reviewer call.

### 8.2 Evidence verifier REWORK_TO_CODER

Store:

```python
result_json = {
    "legacy_result": safe_legacy_dict,
    "acceptance_report": accept_report.to_dict(),
    "evidence_verifier_report": evidence_report.model_dump(),
    "reviewer_report": skipped_reviewer_report("evidence verifier did not pass").model_dump(),
}
```

Return:

```python
accepted=False
domain_status="rejected"
reason=evidence_report.summary
```

### 8.3 Evidence verifier RETURN_TO_ARCHITECT

Return blocked:

```python
accepted=False
domain_status="blocked"
reason=evidence_report.summary
```

Store `spec_conflicts` and `architect_questions` in result_json.

### 8.4 Evidence verifier PASS

Only then run reviewer.

### 8.5 Reviewer PASS

Return accepted using current `_build_execution_result_from_acceptance(...)`, but make sure result_json includes all four reports.

### 8.6 Reviewer REWORK_TO_CODER

Return:

```python
accepted=False
domain_status="rejected"
reason=reviewer_report.summary
```

### 8.7 Reviewer RETURN_TO_ARCHITECT

Return:

```python
accepted=False
domain_status="blocked"
reason=reviewer_report.summary
```

---

## 9. Add a small helper to write PacketRun result_json

To avoid copy-paste in adapter, add private helper in `PacketExecutionAdapter`:

```python
def _update_packet_run_result(
    self,
    *,
    run_id: str,
    status: str,
    legacy_result: dict,
    acceptance_report,
    evidence_verifier_report,
    reviewer_report,
    evidence_path: str,
    duration_ms: int,
    executor_id: str = "",
) -> None:
    ...
```

It must set:

```python
existing.status = status
existing.result_json = {
    "legacy_result": legacy_result,
    "acceptance_report": acceptance_report.to_dict() or model_dump(),
    "evidence_verifier_report": evidence_verifier_report.model_dump(),
    "reviewer_report": reviewer_report.model_dump(),
}
existing.evidence_path = evidence_path
existing.finished_at = datetime.utcnow()
existing.duration_ms = duration_ms
existing.executor_id = executor_id
```

Use this helper in all branches.

---

## 10. Changed files and artifacts input

Inside adapter, after deterministic acceptance, prepare:

```python
changed_files = []
try:
    from grace_control.core.scope_guard import get_changed_files
    changed_files = get_changed_files(wt_path, base_ref="main")
except Exception:
    changed_files = []
```

Artifacts can be simple for first implementation:

```python
artifacts = []
if run_dir.exists():
    artifacts = [str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()]
```

Do not overbuild artifact discovery.

---

## 11. Important: keep deterministic acceptance authoritative

Never allow Evidence Verifier or Reviewer to turn a deterministic failure into PASS.

This must be true in code and tests.

---

## 12. Tests to add/update

### 12.1 Adapter routing tests

Update:

```text
tests/grace_control/adapters/test_packet_executor_acceptance.py
```

Add mocks for:

```python
run_acceptance_pipeline
run_evidence_verifier
run_reviewer_gate
```

Required tests:

#### Test 1 — deterministic fail skips verifier and reviewer

Setup:

```text
acceptance_report.is_accepted = False
```

Assert:

```text
run_evidence_verifier not called
run_reviewer_gate not called
result.accepted is False
result.domain_status == "rejected"
result_json has skipped evidence_verifier_report
result_json has skipped reviewer_report
```

#### Test 2 — evidence verifier REWORK_TO_CODER skips reviewer

Setup:

```text
acceptance_report.is_accepted = True
evidence_verifier.verdict = REWORK_TO_CODER
```

Assert:

```text
reviewer not called
result.accepted is False
result.domain_status == "rejected"
result.reason == evidence summary
```

#### Test 3 — evidence verifier RETURN_TO_ARCHITECT skips reviewer

Setup:

```text
evidence_verifier.verdict = RETURN_TO_ARCHITECT
spec_conflicts = ["scope too narrow"]
```

Assert:

```text
reviewer not called
result.accepted is False
result.domain_status == "blocked"
result_json.evidence_verifier_report.spec_conflicts contains conflict
```

#### Test 4 — evidence verifier PASS calls reviewer

Setup:

```text
evidence_verifier.verdict = PASS
reviewer.verdict = PASS
```

Assert:

```text
reviewer called once
result.accepted is True
```

#### Test 5 — reviewer REWORK_TO_CODER rejects

Setup:

```text
evidence_verifier.verdict = PASS
reviewer.verdict = REWORK_TO_CODER
```

Assert:

```text
result.accepted is False
result.domain_status == "rejected"
```

#### Test 6 — reviewer RETURN_TO_ARCHITECT blocks

Setup:

```text
evidence_verifier.verdict = PASS
reviewer.verdict = RETURN_TO_ARCHITECT
```

Assert:

```text
result.accepted is False
result.domain_status == "blocked"
```

#### Test 7 — result_json always has four keys

For accepted and rejected branches assert:

```text
legacy_result
acceptance_report
evidence_verifier_report
reviewer_report
```

---

### 12.2 Core Evidence Verifier tests

Create:

```text
tests/grace_control/core/test_evidence_verifier.py
```

Test parser:

```text
valid PASS JSON parses
valid REWORK_TO_CODER JSON parses
valid RETURN_TO_ARCHITECT JSON parses
invalid JSON returns REWORK_TO_CODER
unknown verdict returns REWORK_TO_CODER
skipped_evidence_report has skipped=true
```

Do not call real LLM in tests.

---

### 12.3 Core Reviewer tests

Create:

```text
tests/grace_control/core/test_reviewer_gate.py
```

Test parser:

```text
valid PASS JSON parses
valid REWORK_TO_CODER JSON parses
valid RETURN_TO_ARCHITECT JSON parses
invalid JSON returns REWORK_TO_CODER
unknown verdict returns REWORK_TO_CODER
skipped_reviewer_report has skipped=true
```

Do not call real LLM in tests.

---

## 13. Update reports / UI compatibility

Do not break current UI/API if it reads `PacketRun.result_json`.

The new shape extends existing JSON. It must still include old keys:

```text
legacy_result
acceptance_report
```

Only add:

```text
evidence_verifier_report
reviewer_report
```

---

## 14. Do not do in this task

Do not remove legacy `prefect_grace` runner.
Do not refactor worktree manager.
Do not change merge endpoint.
Do not add new DB columns unless absolutely necessary.
Do not make reviewer mandatory if verifier fails.
Do not call real LLM in unit tests.
Do not rename `verifier` role.
Do not invent new verdict names.

Allowed verdicts are exactly:

```text
PASS
REWORK_TO_CODER
RETURN_TO_ARCHITECT
```

---

## 15. Acceptance commands

Run:

```bash
pytest tests/grace_control/core/test_evidence_verifier.py -q
pytest tests/grace_control/core/test_reviewer_gate.py -q
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
pytest tests/grace_control/core/test_acceptance_pipeline.py -q
pytest tests/grace_control -q
pytest tests/api -q
pytest tests -q
```

Do not claim done unless these pass.

---

## 16. Final answer format from coder

Coder must report:

```text
Files changed
New pipeline order implemented
Evidence verifier branches covered
Reviewer branches covered
Tests run
Remaining blockers, if any
```

If any LLM integration is stubbed/mocked in production code, say so explicitly. Unit tests may mock LLM; production code must call existing `run_llm` through verifier/reviewer roles.
