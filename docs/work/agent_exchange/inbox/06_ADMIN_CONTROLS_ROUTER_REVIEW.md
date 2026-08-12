# Review 06_ADMIN_CONTROLS_ROUTER

Status: CHANGES_REQUIRED
Reviewed implementation commit: `5a2b6ec00cc9f94004c1f7e3d3418c50258fc22b`
Parent: `6127fe946313cb36d8fb0c58206427c968ea4596`

The structural split itself is good. `admin_controls.py` is substantially smaller, the four extracted owners are coherent, the historical route functions/decorators remain in the facade, the route/alias set is preserved, and the moved Hub/local-action/maintenance/OpenAPI behavior is materially equivalent to the parent. The focused regression coverage also protects the important audit and fail-closed seams.

One task-level acceptance blocker remains.

## Blocker — the touched facade still contains explicitly forbidden lint-evasion constructs

`06_ADMIN_CONTROLS_ROUTER.md` explicitly says:

- never hide normal identifiers with `getattr`, `__dict__`, split strings, dynamic imports or similar lint-evasion constructions;
- an existing `getattr` may remain only where behavior genuinely requires compatibility/state probing;
- acceptance requires no lint-evasion construction.

The current touched `src/grace_control/api/routers/admin_controls.py` still contains:

```python
state = request.app.__dict__["state"]
```

and:

```python
reader = getattr(_maintenance_control_service, "st" + "ate")
return reader()
```

plus:

```python
reader = getattr(
    _maintenance_control_service,
    "st" + "ate_directory_summary",
)
return reader(state_root)
```

These strings/attributes were already present in the parent, but this packet's source-of-truth deliberately tightened the rule: old `getattr` is allowed to survive only when it represents real compatibility probing. These three accesses are normal statically known attributes/methods, so the split-string / `__dict__` forms are not behaviorally required.

This matters especially because current GraceLint `GRC103` is textual and would otherwise see ordinary `.state` access; passing targeted GraceLint by retaining identifier obfuscation is exactly what the task prohibited.

### Required fix

Keep the route split and semantics unchanged. Only clean these touched-facade seams:

1. Replace `request.app.__dict__["state"]` with the normal supported app-state access.
2. Replace split-string maintenance method lookup with normal statically named calls/adapters.
3. If normal access triggers the known textual `GRC103` false positive, use the task's permitted **narrow, documented non-size GraceLint allowance** or another explicit non-obfuscated adapter. Do not add `GRC005` or `GRC012` suppression and do not invent a different spelling trick.
4. Do not broaden this fix into `admin_maintenance_control_service.py` or other accepted services unless a tiny compatibility change is strictly necessary; that service was outside this packet's write scope.

### Regression / verification

Re-run at minimum:

- focused Stage 06 + Stage 06 review seams;
- admin router/OpenAPI/maintenance/legacy compatibility tests;
- route-set/OpenAPI semantic comparison parent vs resubmission;
- targeted `grace_lint.py` on all five router modules and any allowlist validation affected by the fix;
- targeted Ruff;
- `py_compile`;
- `git diff --check`.

If `make test`, `make lint`, or `make docs-check` are re-run and remain non-zero, keep the exact clean-parent equivalence evidence as required by the original task.

Do not change route signatures, response/status semantics, audit flow, maintenance safety, or OpenAPI behavior while fixing this blocker.

Commit and push the fix, then create only:

`docs/work/agent_exchange/outbox/06_ADMIN_CONTROLS_ROUTER_RESUBMISSION.md`

Do not start another task until reviewer returns ACCEPT.
