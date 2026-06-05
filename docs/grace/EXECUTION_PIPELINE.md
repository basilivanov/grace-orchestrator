# Execution Pipeline

The full packet execution pipeline:

```
Packet (DB row)
  → claim (PacketService.claim)
  → materialize (PacketMaterializer → EXECUTION_PACKET.md)
  → resolve executor (executor_selector.select_executor)
  → _call_legacy_runner → execution backend (ApiAgentBackend / MockBackend)
  → acceptance pipeline (run_acceptance_pipeline → T0/T1/T2)
  → evidence verifier (run_evidence_verifier)
  → reviewer gate (run_reviewer_gate — STRICT profile only)
  → finish: accepted / rejected / blocked
  → PacketRun saved with result_json
  → (on success) MergeService.merge_packet → update DB state
```

Control flow lives in `adapters/packet_executor.py:PacketExecutionAdapter.execute()`.
The adapter is stateless — it does not call mark_running / mark_accepted /
mark_rejected / mark_failed. State ownership belongs to the API endpoint.

## Agent commit

After a successful agent run, the worktree changes are committed with
`git add -A` + `git commit -m "agent: {packet_id} attempt {n}"`.
This is handled by `services/agent_commit_service.py`.

## Worktree inspection

`services/worktree_inspector.py` exposes `is_git_worktree`, `has_changes`,
`base_sha`, `collect_changed_files`, and an aggregate `inspect`. All
git subprocess calls live here.
