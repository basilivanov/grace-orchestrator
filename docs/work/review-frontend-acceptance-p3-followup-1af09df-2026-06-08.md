# Follow-up Review: `1af09df` TZ_FRONTEND_ACCEPTANCE P3 manifest

Date: 2026-06-08
Reviewer: ChatGPT
Commit reviewed: `1af09df690ab960fa1e6760285749df69f4f914c`
Previous review: `docs/work/review-frontend-acceptance-p3-c1f9aa9-2026-06-08.md`

## Verdict

**REQUEST CHANGES — very close.**

Most of the manifest gaps are closed: `artifact_manifest` evidence kind exists, manifest metadata extraction was added, and `_run_frontend_stages()` now accepts `run_id` and passes it down to browser/visual/a11y stage functions.

The remaining concern is that the real `AcceptancePipeline.run()` call path does not appear to pass a real `run_id` into `_run_frontend_stages()`. The commit only changes `_run_frontend_stages()` signature and downstream propagation. I did not see the upstream call changed to provide a real run id. This means production manifests may still fall back to `packet_id` as `run_id`.

## Confirmed fixed

### Fixed: `artifact_manifest` evidence kind

`EvidenceRequirement.kind` now documents `artifact_manifest`, and `_check_evidence_kind()` calls `validate_artifact_manifest()` for that kind.

This means a packet can now require manifest validation through expected evidence, and a broken/missing manifest can affect the final verdict through the existing evidence path.

### Fixed: Manifest metadata extraction

`write_artifact_manifest()` now calls `_extract_metadata(...)` per entry.

The new `_extract_metadata()` parses:

- `diff-report.json` → `diff_pct`, `max_diff_pct`;
- `a11y-report.json` → `violations_count`, `critical_count`, `passed`.

This closes the previous “manifest is only inventory, not useful evidence summary” gap.

### Fixed: Downstream run_id plumbing exists

`_run_frontend_stages()` now accepts `run_id: str = ""` and passes it to:

- `run_t2_browser_e2e()`;
- `run_t3_visual_regression()`;
- `run_a11y_check()`.

Those already forward to `PlaywrightRunner`, so the lower-level path is ready.

## Remaining issue

### MAJOR — Real pipeline still may not pass a real run_id

The commit diff shows `_run_frontend_stages(..., run_id="")` added, but I did not see the call from `AcceptancePipeline.run()` changed to pass a real `run_id`.

Earlier the call was:

```python
browser_routing = _run_frontend_stages(
    packet, worktree_root=worktree_root, run_dir=Path(run_dir) if run_dir else worktree_root,
)
```

If this remains true, the production path still sends `run_id=""`, and `PlaywrightRunner` will keep falling back to:

```python
run_id=self._run_id or self._packet_id
```

Impact:

- manifests can still write `run_id == packet_id` in real runs;
- the manifest cannot reliably distinguish attempts/runs for the same packet;
- trace/admin correlation by actual run id remains weak.

Recommended fix:

- Extend `AcceptancePipeline.run()` or its input context to know the real `run_id` / `PacketRun.id`.
- Pass that into `_run_frontend_stages(..., run_id=run_id)`.
- Add a regression test proving a non-empty run id, e.g. `pkt_abc-R02`, appears in `artifacts-manifest.json` after pipeline-level frontend execution.

## Non-blocking notes

1. `artifact_manifest` now influences verdict only if included in `expected_evidence`. That is acceptable if this is the intended contract, but consider auto-injecting it for `frontend.enabled=true` to make manifest validation mandatory for all frontend packets.
2. The metadata extraction for a11y assumes `violations_count` and `critical_count` fields exist. If actual reports only contain a `violations` list, compute the counts from that list too.
3. I still did not see CI/statuses for this commit through the connector.

## Acceptance bar for final P3

Accept once either:

- the real pipeline passes actual `run_id` into `_run_frontend_stages()`, with test evidence, or
- the project explicitly decides that `run_id == packet_id` is acceptable for frontend manifest correlation and documents that choice.
