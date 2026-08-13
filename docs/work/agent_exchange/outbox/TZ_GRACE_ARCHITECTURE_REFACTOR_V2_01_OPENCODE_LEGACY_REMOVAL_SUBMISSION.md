WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_01_OPENCODE_LEGACY_REMOVAL
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 6f3e4f8d8e733e56ccf633e958704742233d433e
WEB_ORCH_CHECKS: PASS

# Verified no-op submission

## Synchronization and implementation status

- Initial \`git status --short --branch\`: \`## main...origin/main\`.
- \`git fetch origin --prune\`: PASS.
- \`git pull --ff-only origin main\`: PASS — \`Already up to date\`.
- Synced base and current implementation SHA:
  \`6f3e4f8d8e733e56ccf633e958704742233d433e\`.
- Current \`main\` already satisfies the complete OpenCode-removal contract.
  The implementation delta for this packet is therefore zero: no source,
  config, profile, test, or active-doc implementation edits were manufactured.
- Existing untracked files were preserved and not modified:
  \`.env.bak-mini-endpoint-20260705170600\`,
  \`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CI_SINGLE_SOURCE_OF_TRUTH_ACCEPTED.md\`,
  and \`parse_list.py\`.
- No reset, clean, destructive checkout, or repo-side orchestration metadata
  operation was used.

## OpenCode inventory and target-state evidence

The current active repository has:

- no \`src/grace_control/runtime/opencode_*.py\` modules;
- no \`agent_runtime_use_opencode_adapter\` setting;
- no OpenCode-specific settings or \`OPENCODE_\` environment mapping in
  \`GraceSettings\` or active project configuration;
- no OpenCode command/profile in
  \`src/grace_control/config/agent_profiles.yaml\`;
- no \`opencode_runtime_adapter\` or OpenCode selection branch in
  \`src/grace_control/adapters/packet_executor.py\`;
- no active Python import of an OpenCode runtime module;
- no tracked runtime-artifact paths from the packet inventory patterns.

The durable guard already present at
\`tests/grace_control/architecture/test_no_opencode_legacy.py\` directly checks
runtime module absence, settings fields, profile content, executor selection,
resume/injection compatibility, and active source/test/script imports. It passes
without modification.

The user/control CLI remains out of scope and was not changed. No later-wave
control-CLI, Admin, lifecycle, dead-code, CI, API, schema, or migration work
was mixed into this packet.

## Generic and mini-swe preservation

The supported non-OpenCode execution paths remain intact:

- \`src/grace_control/runtime/mini_swe_runner.py\` remains the command used by
  the architect/coder/reviewer/verifier mini-swe profiles.
- \`select_backend()\` retains only the canonical \`cli\`, \`api\`, and
  \`mock\` backend choices.
- \`UniversalCliAgentBackend\` still delegates generic profile-rendered
  commands to \`AgentRunService\`.
- \`AgentRunService\` retains generic command rendering, isolated worktree/cwd
  checks, environment construction, process supervision, artifact collection,
  and the proven Agy session extraction. It has no OpenCode binary/session/env
  assumption.
- Mini-swe/profile passthrough and packet-executor behavior were tested directly
  below; no runtime behavior was changed by this packet.

## Remaining active-scan hits

The required active scan completed with only allowed classes:

\`\`\`text
rg -n -i 'opencode|agent_runtime_use_opencode_adapter|OPENCODE_' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md \
  pyproject.toml docker
\`\`\`

Remaining matches are:

1. Negative architecture assertions and guard naming in
   \`tests/grace_control/architecture/test_no_opencode_legacy.py\`. These are
   deliberate regression checks proving the forbidden runtime/config/profile
   cannot return.
2. Active documentation statements in \`README.md\`,
   \`docs/SUPERVISOR.md\`, and \`docs/grace/{ARCHITECTURE,CANON,EXECUTION_BACKENDS,RUNBOOK_LOCAL_DEV}.md\`.
   Each explicitly says OpenCode is removed or unsupported and directs users to
   the supported HTTP/OpenAPI, mini-swe, or generic execution surfaces; none
   presents OpenCode as supported.
3. Historical evidence outside the active scan, including
   \`docs/work/\` and older retained TZ/evidence documents. These were not
   edited, as required by the packet's historical-evidence rule.

There are no remaining active implementation, configuration, profile, or
runtime-selection hits.

## Checks

- \`PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/runtime tests/grace_control/agent\`: PASS —
  \`122 passed\`.
- Direct guard/profile/executor suite:
  \`tests/grace_control/architecture/test_no_opencode_legacy.py\`,
  \`tests/grace_control/config/test_mini_swe_profiles.py\`,
  \`tests/grace_control/config/test_agent_profile_passthrough.py\`,
  \`tests/grace_control/adapters/test_packet_executor_acceptance.py\`, and
  \`tests/grace_control/adapters/test_packet_executor_workspace.py\`: PASS —
  \`61 passed\`.
- \`make lint\`: PASS — full baseline-aware scope
  \`src/grace_control tests scripts\`; Ruff baseline count 1020 and GraceLint
  baseline count 3249 match exactly.
- \`make docs-check\`: PASS — \`docs freshness OK — 3 files in sync\`.
- \`make hygiene\`: PASS — \`OK: repo-hygiene passed\`.
- \`python3 scripts/grace_lint.py src/grace_control tests scripts\`: raw audit
  exit 1 with 3249 pre-existing diagnostics; this is truthfully reported and
  is accepted by the canonical unchanged-baseline gate.
- \`python -m ruff check src/grace_control tests scripts\`: raw audit exit 1
  with 1020 pre-existing errors; the repository has no system \`python\`
  executable, so the exact argument invocation was run with the project
  virtualenv first on \`PATH\`. The canonical unchanged-baseline gate passes.
- \`py_compile\` for the directly relevant runtime, config, profile, executor,
  backend, and guard files: PASS.
- \`git diff --check\`: PASS; no implementation diff exists.
- \`git rev-parse HEAD\` and \`git rev-parse origin/main\`: both
  \`6f3e4f8d8e733e56ccf633e958704742233d433e\`.

## Changed files

Implementation files changed for this packet: none — verified no-op.
The only new file is this required submission report. No next packet was
created or started.
