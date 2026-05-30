# Prefect Grace Scaffold

This directory contains a phase-1 file-backed scaffold for Prefect-driven GRACE execution.

## Structure

- `flows/` — Prefect flows.
- `tasks/` — task helpers for file-backed orchestration.
- `prompts/` — role prompts in English.
- `roles/` — role contracts and responsibility docs.
- `templates/` — feature and packet templates.
- `packets/` — generated packet workspace placeholder.
- `state/` — YAML/JSON state for features, packets, reviews, and decisions.
- `state/` — YAML/JSON state for features, packets, reviews, verifications, and decisions.

## Current purpose

Phase 1 is intentionally conservative:
- define the operating model;
- define role contracts;
- define prompt templates;
- define file-backed state layout;
- provide Prefect entry scaffold;
- provide a Codex subprocess launcher wired through `codexN` and cliproxy.

The scaffold can already dry-run or execute a packet through a configured `codexN` wrapper.
It now parses verifier, reviewer, and architect-wave outputs and injects dependency context into downstream agent prompts.
It also supports live Prefect deployments, a scheduled state dashboard artifact, a YAML business-feature intake contract, and an LLM-driven verifier that executes packet contracts through Codex.

## Evidence architecture

GRACE evidence is split into distinct layers and must not be collapsed into one generic "observability" gate:
- `packet_local` evidence: logs, traces, reports, screenshots, rendered artifacts, and targeted runtime proof that are local to one packet's scope;
- `wave_final` evidence: canonical business-flow proof for the whole wave, produced only by the final verifier lane that intentionally exercises the required flow;
- `none`: packets that do not own an evidence gate.

The planner must treat evidence as a typed contract, not as free text:
- planner assigns `execution.observability_scope`;
- planner may attach `execution.canonical_flow_commands` only to the final verifier lane;
- canonical gates such as `today-week` are forbidden on coder, reviewer, architect, and packet-local verifier packets.

This avoids the main failure mode we hit in practice:
- a packet changes code correctly;
- targeted tests pass;
- but the packet never emitted the canonical Today/Week flow that `post_test_review.py --profile today-week` expects;
- reviewer then rejects a technically correct packet on impossible evidence.

The fix is architectural, not prompt-strength based:
- strict evidence taxonomy;
- pattern library for reusable verification lanes;
- schema validation on planner output;
- capability matrix that states which roles and packet types may produce which evidence;
- canonical business-flow gates only in the final verifier lane.

Reasoning level can improve decomposition quality, but it must not be relied on as the control plane for evidence correctness.

## Runtime portability

The orchestration layer is portable across projects if you keep the runtime boundary explicit:
- Prefect server/API/UI can stay shared infrastructure;
- the project gets its own process worker, work pool, queues, and working directory;
- project-specific values can be overridden through `prefect_grace/runtime.yaml` or environment variables.

See `prefect_grace/runtime.yaml.example` for the minimal knobs.
