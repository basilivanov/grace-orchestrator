# Review 013 — Admin Control Center Stage 07

Status: CHANGES REQUIRED

Implementation commit reviewed: `2518202c909d217d6c7bf93dc563e43b3c23a1c7`.

The Stage 07 submission has substantial real integration coverage: two independent project API subprocesses with separate SQLite/root/Git state, concurrent same-ID isolation, real filesystem/Git reads, selected-project mutation isolation, a deterministic failure matrix, dynamic OpenAPI discovery, a real Chromium harness, project-keyed short-TTL OpenAPI caching, and final operator documentation.

Three final acceptance blockers remain.

## Required fixes

### 1. Legacy `/api/admin/*` mutations bypass the Stage 06 control-security boundary

Stage 07 changed the legacy Admin v2 packet endpoints from planned stubs into live mutations:

```python
@router.post("/api/admin/packet/{packet_id}/resume")
def packet_resume(...):
    return _retry(...)

@router.post("/api/admin/packet/{packet_id}/delete")
def packet_delete(...):
    return _delete(...)

@router.post("/api/admin/packet/{packet_id}/stop")
def packet_stop(...):
    return _cancel(...)
```

These routes do not call `require_control_request()` and do not go through the Stage 06 `AdminMutationService` / project-local strict audit gate.

This defeats the read/control token split. `AuthMiddleware` accepts either the read token or control token as authenticated, then sets:

```python
grace_control_authorized = not control_token or token == control_token
```

The Stage 06 control endpoints enforce that flag with `require_control_request()`, but the newly-live legacy packet routes never inspect it. A valid read-only API token can therefore POST directly to `/api/admin/packet/<id>/resume` or `/stop` and mutate project state. `resume`/`stop` also have no strong server-side confirmation at all; `delete` only checks a body value but still bypasses control authorization and strict canonical requested/completed audit integrity.

The same final DoD applies to any other live mutating `/api/admin/*` endpoints (notably legacy feature archive/unarchive): a read-only credential must not be able to mutate through an alternate URL simply because the Control Center route is safe.

Required:

- inventory the final live mutating Admin endpoints exposed by the project API/OpenAPI;
- make every operator mutation use the same Stage 06 authorization/origin/control-token boundary;
- preserve domain/state/fencing behavior and strong confirmation for destructive actions;
- ensure canonical project-local `admin_action_requested` + completed/failed audit semantics are not bypassed by legacy URLs;
- do not duplicate business-state logic in the Hub;
- add deterministic auth-enabled regressions with distinct `read-token` and `control-token` proving the read token gets 403 and causes zero state change on the legacy packet routes (and other live Admin mutation routes);
- prove an authorized, confirmed legacy-compatible path either delegates through the canonical control service or is intentionally unavailable rather than providing a weaker mutation backdoor.

### 2. Stage 07 `system_logs()` breaks the accepted Global Logs `total`/cursor contract

The new safe log reader correctly stops reading a global `/tmp` glob, but it now returns:

```python
payload = reader.tail_file(...)
return {
    "lines": ...,
    "total": int(payload.get("size") or 0),
    "truncated": bool(payload.get("truncated")),
}
```

`SafeFilesystemService.tail_file()` defines `size` as `target.stat().st_size` — **bytes**, not number of log rows.

`AdminCrossProjectService.query_logs()` treats project-local `data["total"]` as a **row count**:

```python
source_total = _safe_int(data.get("total"), len(lines))
bounded_totals.append(min(source_total, _MAX_LOG_LINES_PER_PROJECT))
if bool(data.get("truncated")) or source_total > fetch_tail:
    partial = True
...
accessible_total = sum(bounded_totals)
```

So a 20-line file that is 500 bytes can advertise hundreds of accessible log rows. After the real rows have been exhausted, the Hub can continue emitting opaque Next cursors for empty pages until the byte-count-derived `accessible_total` is reached. This regresses the Stage 05 bounded continuation contract.

Required:

- restore a row-count/continuation semantic that is compatible with `query_logs()` without unboundedly reading the full file;
- do not repurpose a byte-size field as a row total;
- keep the project-local read bounded and named-root safe;
- add a deterministic integration regression using a real log file where byte size is deliberately much larger than line count;
- page Global Logs with a small tail through every opaque cursor and prove each reachable page contains the expected next rows, no duplicate/skip, no phantom empty Next pages, and continuation terminates when the bounded row domain is exhausted;
- preserve project/filter/tail cursor state.

### 3. Final Chromium acceptance does not actually exercise HTMX polling/control confirmation behavior

`test_stage07_browser_desktop_mobile_smoke()` launches a real Hub + Chromium, which is good, but its polling assertion is only:

```python
assert log_viewer.get_attribute("hx-trigger") == "every 5s"
assert "/admin/p/alpha/logs" in (log_viewer.get_attribute("hx-get") or "")
```

It never waits for or observes an actual HTMX request/swap. Therefore it does not prove the explicit Task 013 browser requirement:

- no project-context loss **after HTMX polling**;
- no duplicate Logs UI/viewer after a production poll;
- stable behavior when follow is off / when the operator is away from the bottom.

This is particularly important because Task 011 previously had a real HTMX fragment-swap defect that static attribute assertions did not catch.

The control part similarly checks only that a confirmation input/button exists; it does not exercise a confirmation interaction in the real browser harness.

Required:

- make the real Chromium test observe at least one actual production HTMX poll (waiting for the request or deterministically triggering the same production HTMX behavior);
- after the swap, assert project `alpha` remains selected, exactly one bounded log viewer/filter UI exists, the viewer content remains valid, and the URL/deep-link context is unchanged;
- verify Follow off causes no automatic poll/forced jump, and Follow on does not force a user who scrolled away from bottom back to the bottom;
- exercise the final UI's actual confirmation interaction for a safe fixture control (inline confirmation is acceptable if that is the current UI policy; do not require a modal purely for cosmetics), and prove the selected project changes state plus its canonical audit becomes visible;
- keep browser skips only for genuinely unavailable Playwright/Chromium; this environment already reports the dedicated Chromium harness as available/passing.

## Scope

Task 013 is the final stage. Do not invent Task 014.

Fix the three issues above and directly exposed regressions at their owning service/router/UI layer. Re-run the Stage 07 real topology/matrix/browser suite, relevant Task 007–012 acceptance/regressions, auth/control tests, Global Logs continuation tests and the existing Admin/packet/worker/merge/maintenance/filesystem/Git suites.

Also run Ruff, `python3 -m py_compile`, applicable changed/new-file GRACE lint and `git diff --check`.

Update/create:

`docs/work/agent_exchange/outbox/013_RESUBMISSION.md`

Include the fix commit SHA and concise proof for:

- no legacy Admin mutation backdoor with a read-only token;
- correct bounded row-based Global Logs continuation using the safe named-root reader;
- real Chromium HTMX poll + confirmation interaction;
- final regression/check results;
- any update needed to `docs/work/REPORT_GRACE_ADMIN_CONTROL_CENTER_V3.md`.
