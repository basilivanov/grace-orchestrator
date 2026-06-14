# Evidence: GRACE Runtime Observability Spine (W1)

## Summary

W1 implements the shared observability infrastructure for GRACE: trace_id propagation, structured runtime events, artifact storage with sha256/size verification, and secret redaction. Every future runtime step can now reuse these primitives.

## Components Created

| Component | File | Status |
|-----------|------|--------|
| RuntimeTraceContext | `src/grace_control/core/runtime_trace.py` | Done |
| RuntimeArtifactRef | `src/grace_control/core/runtime_artifacts.py` | Done |
| RuntimeArtifactStore | `src/grace_control/core/runtime_artifacts.py` | Done |
| RuntimeEventLogger | `src/grace_control/core/runtime_events.py` | Done |
| RuntimeRedactor | `src/grace_control/core/runtime_redaction.py` | Done |

## Modified Files

| File | Change |
|------|--------|
| `src/grace_control/config/settings.py` | Added 5 runtime observability settings |
| `src/grace_control/services/feature_planning_service.py` | Wired trace/events/artifacts into all planning stages |
| `src/grace_control/services/grace_knowledge_graph_service.py` | Optional trace/logger/store; emits KG events + artifacts |
| `src/grace_control/services/feature_path_manifest_service.py` | Optional trace/logger/store; emits manifest events + artifacts |

## Test Results

- 197 tests pass (98 existing relevant + 10 existing repair/autofix + 72 existing safety/support + 17 new W1 tests)
- All W1-specific tests pass: artifact storage, event logging, redaction

## Artifact Layout

`.grace/runs/<feature_id>/` contains:
- `feature_input.json`
- `events.jsonl`
- `context_builder/input.json`, `output.json`, `files.json`
- `knowledge_graph/extract.json`, `prompt_block.txt`
- `feature_path_manifest/output.json`, `prompt_block.txt`
- `architect/prompt.txt`, `raw_response.txt`, `parsed_plan.json`
- `plan_compiler/input_plan.json`, `output.json`, `errors.json`, `warnings.json`
- `scope_canonicalizer/input_plan.json`, `output_plan.json`, `fixes.json`
- `materializer/input_plan.json`, `packets_created.json`
- `repair_loop/compiler_errors.json`, `autofix_output.json`, `repaired_plan_attempt_N.json`

## Events Emitted

- feature.trace_started, feature.input_captured, feature.target_repo_resolved
- context_builder.started/input_captured/completed/failed/output_captured
- knowledge_graph.load_started/load_completed/load_missing/extract_completed/prompt_block_built
- feature_path_manifest.build_started/completed/source_unresolved
- architect.started/prompt_build_started/prompt_built/raw_response_captured/parsed_plan_captured/completed/failed
- plan_compiler.started/completed/failed/error_detected/warning_detected
- scope_canonicalizer.started/fix_applied/completed
- packet_materializer.started/packet_created/completed/failed
- repair_loop.attempt_started/attempt_failed/success/terminal_error/exhausted
