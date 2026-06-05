# Review: `866509c` final canon drift cleanup

Date: 2026-06-05
Reviewed commit: `866509ce35c7bfc85717382f7cc045f847124898`
Previous review: `source/codex/review-2026-06-05-b647c8c-final-canon-drift.md`

## Verdict

Accepted for the W0-W12 audit path, with one explicit W13 follow-up.

`866509c` fixes the remaining concrete blocker from the previous review:

- duplicated allowlist entries are removed;
- no `expires_wave: W12` entries remain;
- `llm_runner.py` is no longer hidden as a permanent `never` exception with a “to be refactored” reason;
- GRC109 is strengthened and enabled;
- regression tests were added for GRC109.

The remaining `llm_runner.py` issue is now explicitly classified as W13 debt, not as completed W12 work. That is acceptable as a tracked follow-up, but it should not be forgotten.

---

## Checked items

### 1. No W12 allowlist entries remain

Accepted.

Current `.grace/lint_allowlist.yaml` has no `expires_wave: W12` entries.

The previous duplicates for:

```text
GRC103 src/grace_control/adapters/packet_executor.py
GRC108 src/grace_control/adapters/packet_executor.py
GRC108 src/grace_control/services/evidence_service.py
```

were removed or normalized.

### 2. No duplicated rule/path pairs remain in the visible allowlist

Accepted.

The current allowlist has one entry per visible rule/path pair:

```text
GRC100 settings.py
GRC100 project_config.py
GRC101 llm_runner.py
GRC103 packet_executor.py
GRC103 wave_gate.py
GRC103 acceptance_pipeline.py
GRC108 packet_executor.py
GRC108 evidence_service.py
GRC109 llm_runner.py
```

### 3. `llm_runner.py` is now explicit W13 debt

Accepted as a temporary deferral.

The previous bad state was:

```text
expires_wave: never
reason: ... to be refactored
```

That was contradictory. It is now:

```yaml
expires_wave: W13
reason: pre-W7 runner ... to be refactored through UniversalCliAgentBackend in W13
```

This is honest and auditable.

Important: this does **not** mean `llm_runner.py` is architecturally resolved. It means the project has a clear W13 cleanup item:

```text
W13: delete/archive/refactor core/llm_runner.py through UniversalCliAgentBackend
```

### 4. GRC109 strengthened

Accepted.

The previous GRC109 only flagged known agent names when the same line also contained `run` or `exec`. The rule now flags any occurrence of known CLI agent names in runtime source unless allowed by config/tests/docs/allowlist.

This catches cases like:

```python
cmd = ["agy", "--print", prompt_text]
```

instead of only catching `opencode run` style lines.

### 5. GRC109 tests added

Accepted.

New tests cover:

- hardcoded `opencode` in service code fails;
- CLI agent names in config are allowed.

---

## Remaining follow-up, not a W12 blocker

### W13-1. Resolve `core/llm_runner.py`

`src/grace_control/core/llm_runner.py` still exists and still represents the pre-W7 hardcoded CLI runner pattern. It is now explicitly tracked as W13, which is acceptable for this review.

W13 acceptance should be one of:

1. delete/archive `llm_runner.py` if unused;
2. refactor it through `UniversalCliAgentBackend` / `AgentRunService` and `agents:` profiles;
3. replace any remaining call sites with the new backend path.

Until W13 is done, do not describe the codebase as “zero legacy runner debt”. It is fair to describe W0-W12 as complete with W13 follow-up identified.

### Maintenance-1. The pre-existing failing test remains

The reported state is:

```text
401 passed, 1 pre-existing fail
```

This is outside the reviewed patch but should still be resolved or formally quarantined.

---

## Final status

For W0-W12:

```text
Runtime architecture: accepted
API-first control plane: accepted
UniversalCliAgentBackend: accepted
Legacy Prefect removal: accepted
W12 canonical evidence-dir propagation: accepted
GraceLint final drift patch: accepted
```

Known follow-ups:

```text
W13: resolve core/llm_runner.py
Maintenance: fix/quarantine the one pre-existing failing test
```

This is now a clean enough state to stop the W0-W12 refactor/audit loop and move to W13 or product work.
