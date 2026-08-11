# REVIEW — TZ 05_ADMIN_AGGREGATION

Status: REVIEW
Reviewed implementation: `ff8b5fd93dfd4dcf8acfd1850dba5c6bb974790d`

Read and address **only this review**. Do not start Part B or another named TZ.

## Acceptance blocker

The structural decomposition is accepted in principle, but the implementation introduces identifier-obscuring constructions to make targeted GraceLint pass:

- `AdminOverviewReadService.get_overview()` queries `Packet.__dict__["state"]` instead of the normal SQLAlchemy attribute `Packet.state`.
- shared `_packet_state()` reads via `getattr(packet, "state", "")` instead of a normal `packet.state` access.

This is a lint-evasion workaround for the current textual `GRC103` implementation. `GRC103` is documented as preventing **Packet.state mutation**, but the checker currently flags any textual `.state` / `state=` occurrence outside its allowed paths. This packet explicitly forbids obscuring normal identifiers to evade GraceLint and explicitly permits a narrow, truthful **non-size** allowlist entry for a genuine textual false positive.

## Required fix

1. Restore readable ORM/state access:
   - use `Packet.state` in SQLAlchemy queries/filters;
   - make `_packet_state()` use the normal packet state attribute rather than `getattr(..., "state", ...)` as a textual workaround.
2. If targeted GraceLint then reports `GRC103` for this read-only owner, add the narrowest truthful `GRC103` allowlist entry required for the read-only state access. Prefer one entry for the actual file containing the textual state reads. Explain that the checker is textual and these are reads/DTO serialization, not Packet state mutation.
3. Do **not** change GraceLint semantics in TZ05, do not add `GRC005`/`GRC012`, and do not introduce another spelling/string/getattr/__dict__ workaround.
4. Preserve the existing seven-file responsibility decomposition and all DTO/fallback/path-safety/public facade behavior. No Part B/block 06 work.

## Verification

Re-run at minimum:

- the same directly affected admin/API/UI test set used in the submission;
- targeted `scripts/grace_lint.py` for every touched/new TZ05 source file;
- `python3 -m py_compile` for every touched/new TZ05 source file;
- `git diff --check`;
- `make test`, with exact clean-parent comparison if non-zero;
- `make lint`, reporting the existing environment blocker truthfully if unchanged;
- `make docs-check`, with clean-parent semantic comparison if non-zero.

No existing behavioural assertion may be weakened.

After the fix, commit and push it, then create only:

`docs/work/agent_exchange/outbox/05_ADMIN_AGGREGATION_RESUBMISSION.md`

Report the exact implementation commit, the readable-state fix, any narrow non-size allowlist entry and rationale, and exact check outcomes. Do not create the next TZ.
