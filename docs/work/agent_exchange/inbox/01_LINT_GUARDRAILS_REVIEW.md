# Review — TZ 01_LINT_GUARDRAILS

Status: CHANGES REQUIRED

Implementation commit reviewed: `5aab22ca6e66a9f862d16d7b50957ff487f8bd39`.

Read and fix **only this review**. Do not start another named TZ. After fixing, create only:

`docs/work/agent_exchange/outbox/01_LINT_GUARDRAILS_RESUBMISSION.md`

## Acceptance blocker

### `GRC012` must respect the existing selective-rule filter

The patch correctly moves the size calculation before the private-name guard, but the new size branch still ignores the existing `rules_enabled` parameter:

```python
est_tokens = len("\n".join(func_lines)) // 4
if est_tokens > 4000:
    v = Violation("GRC012", ...)
```

This creates a new regression for the newly covered private-function path. The CLI documents `--rules` as a selective rule filter, and the HTTP API passes `RunLintRequest.rules` into `lint_text()`/`lint_file()`. With the current patch, an oversized private helper can emit `GRC012` even when the caller selected only an unrelated rule such as `GRC100`.

Required fix:

- Gate the `GRC012` size violation with the existing `_rule_enabled("GRC012", rules_enabled)` mechanism.
- Preserve default behaviour: when all rules are enabled, public/private sync/async functions above 4000 estimated tokens still emit `GRC012`.
- Preserve private exemption from `GRC010/GRC011`.
- Add deterministic regression coverage proving an oversized private helper does **not** emit `GRC012` when `rules_enabled` excludes `GRC012`, and does emit it when `GRC012` is enabled.
- Do not broaden the task into unrelated rule/filter refactors unless strictly required for this fix.

## Verification

Re-run at minimum:

```bash
.venv/bin/python -m pytest tests/grace_control/core/test_grace_lint.py -q
.venv/bin/python scripts/grace_lint.py src/grace_control/tools/grace_lint/checker.py
git diff --check
```

Also re-attempt `make lint` using the repository-supported Python/tooling path. If the repository baseline or environment still prevents a zero exit, report the exact command and exact blocker/failures; do not hide them or add `GRC005/GRC012` suppressions. The previously reported existing oversized production functions remain follow-up debt for later named TZs.

No new task number; this remains `01_LINT_GUARDRAILS`.
