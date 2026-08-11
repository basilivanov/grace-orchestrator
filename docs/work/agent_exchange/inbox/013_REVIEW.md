# Review 013 — Admin Control Center Stage 07 resubmission

Status: CHANGES REQUIRED

Implementation commit reviewed: `98b5037d1ef12115761988598a53378818a28bc1`.

The legacy Admin mutation security boundary and the real Chromium HTMX/control requirements from the previous review are now addressed. One acceptance blocker remains.

## Required fix

### Global Logs continuation still terminates early for one selected project

`system_logs()` no longer confuses bytes with rows, which fixes the original phantom-page failure mode, but the replacement row total is only the size of the current returned tail:

```python
lines = str(payload.get("content") or "").splitlines()
return {
    "lines": lines,
    "total": len(lines),
    "total_bytes": int(payload.get("size") or 0),
    "truncated": bool(payload.get("truncated")),
}
```

`AdminCrossProjectService.query_logs()` still uses `total` to decide the reachable continuation domain:

```python
fetch_tail = min(_MAX_LOG_LINES_PER_PROJECT, max(page_limit, page_offset + page_limit))
...
source_total = _safe_int(data.get("total"), len(lines))
bounded_totals.append(min(source_total, _MAX_LOG_LINES_PER_PROJECT))
...
accessible_total = sum(bounded_totals)
if page_offset + page_limit < accessible_total and (
    len(rows) > page_offset + page_limit or partial
):
    next_offset = page_offset + page_limit
```

For one selected project with 20 real log rows and `tail=10`, the first project-local request returns 10 rows, `total=10`, `truncated=true`. The Hub therefore computes `accessible_total=10`; `0 + 10 < 10` is false, so it emits no `next_cursor`. The older 10 rows are unreachable even though the local response explicitly says it was truncated.

The new regression accidentally masks this because it selects both `alpha` and `beta`. On the first fetch each contributes `total=10`, so the summed `accessible_total=20` is enough to produce the next cursor; later enlarged tails then expose all 40 rows. The same algorithm fails with exactly one selected project.

Required:

- restore a bounded row-count/continuation semantic that can represent "more rows are reachable" when the named-root tail is truncated, without using byte size and without an unbounded full-file read;
- add a deterministic regression for exactly one selected project whose real log file contains more rows than the requested page (for example 20 rows with `tail=10`), then follow every opaque cursor and prove all reachable bounded rows appear exactly once and continuation terminates;
- keep the existing two-project no-duplicate/no-skip regression, cursor project/filter/tail state checks, named-root containment and byte/read bounds;
- rerun the Stage 07 log/topology regressions and relevant lint/check suite, then update `docs/work/agent_exchange/outbox/013_RESUBMISSION.md` with the fix commit and proof.

The security inventory/control-audit fix and the real Chromium HTMX/follow/typed-confirmation fix do not need to be reworked unless the log correction directly affects them.

Task 013 remains the final stage; do not invent Task 014.
