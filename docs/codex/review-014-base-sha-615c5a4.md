# Codex Review 014 — Base SHA commit diff fix after `615c5a4`

Commit reviewed: `615c5a46e2248d7bb1f26e5a7440745354bf115f`

Previous review: `docs/codex/review-013-git-contract-f47d03f.md`

Verdict: **PASS FOR GOLDEN AND SELF-COMMIT DEFAULT CASE. P1 EXTERNAL HARDENING REMAINS.**

The review-013 P0 about `HEAD...HEAD` is fixed for the normal/default case: the adapter now resolves `base_ref` to a stable `base_sha` before the agent runs, then later compares `<base_sha>...HEAD` in the packet worktree.

This means an agent that commits its own changes should no longer be rejected as `Agent produced no changes` when `GRACE_BASE_REF` is unset/default `HEAD`.

---

## What changed

The adapter now resolves base SHA before `_call_legacy_runner(...)`:

```python
base_ref = os.environ.get("GRACE_BASE_REF", "HEAD")
base_sha = ""
try:
    sr = subprocess.run(["git", "-C", str(self.project_root), "rev-parse", base_ref], ...)
    base_sha = sr.stdout.strip() if sr.returncode == 0 else ""
except Exception:
    pass
```

Then commit verification uses:

```python
diff_base = base_sha if base_sha else base_ref
git diff --name-only {diff_base}...HEAD
```

This is the important correction: the base is resolved before the agent can move worktree `HEAD`.

---

## P0 from review-013 — already committed agent changes

Status: **fixed for default/local golden path.**

Previous bad behavior:

```bash
git diff --name-only HEAD...HEAD
```

After an agent self-commit, this was empty and could trigger false `Agent produced no changes`.

New behavior:

```bash
git diff --name-only <base_sha_before_agent>...HEAD
```

So already-committed agent changes should be detected.

---

## Remaining P1 — base_ref is still not wired into worktree creation

`_call_legacy_runner(...)` still calls `run_e2e_packet(...)` without passing `base_ref`:

```python
run_e2e_packet(
    project_root=self.project_root,
    packet_path=packet_path,
    state_root=state_root,
    worktree_root=worktree_root,
    dry_run=False,
    execute_agent=True,
    attempt=attempt,
    keep_worktree=True,
    runtime_state_root=state_root,
    timeout_seconds=timeout,
)
```

So `run_e2e_packet(...)` still uses its default:

```python
base_ref="HEAD"
```

This is okay for the current golden if `GRACE_BASE_REF` is unset/default `HEAD`.

But for external-project or CI usage with:

```bash
GRACE_BASE_REF=origin/main
```

the system can become inconsistent:

```text
base_sha is resolved from origin/main
but worktree is created from HEAD
```

If local `HEAD` already contains commits not in `origin/main`, the diff `<origin/main sha>...HEAD` may include pre-existing local commits and treat them as agent changes.

### Required follow-up

Pass `base_ref` into `_call_legacy_runner(...)` and then into `run_e2e_packet(...)`:

```python
base_ref = os.environ.get("GRACE_BASE_REF", "HEAD")
result = await self._call_legacy_runner(..., attempt=run_number, base_ref=base_ref)
```

and:

```python
run_e2e_packet(..., base_ref=base_ref, ...)
```

Add tests:

```text
test_adapter_passes_base_ref_to_legacy_runner
test_worktree_created_from_same_base_used_for_commit_diff
test_origin_main_base_ref_does_not_count_preexisting_head_commits_as_agent_changes
```

---

## CI status

No GitHub combined statuses were attached to `615c5a46e2248d7bb1f26e5a7440745354bf115f`, so I could not independently verify local test claims.

---

## Final verdict

**PASS FOR GOLDEN AND SELF-COMMIT DEFAULT CASE.**

The immediate P0 from review-013 is fixed enough for the current FAST golden and for local self-improvement if `GRACE_BASE_REF` remains default `HEAD`.

Before external-project mode or CI-style `origin/main` runs, wire the same `base_ref` into worktree creation so the worktree base and diff base are identical.
