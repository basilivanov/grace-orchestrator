# TZ: Universal GRACE architect prompt v0.02

Date: 2026-06-11
Status: draft-ready for implementation
Priority: P0 orchestrator quality
Scope: GRACE architect agent prompt and context-bundle handling

Related:
- `src/grace_control/config/agent_profiles.yaml`
- `src/grace_control/config/agent_profiles.py`
- `docs/work/TZ_SOLARSAGE_PILOT_002_TABBAR_CONTRACT.md`

## 1. Problem

Current `architect-premium` prompt is too small and generic.

It tells the architect only:

```text
Read the spec from {packet_path} and output ONLY a valid JSON object with fields: title, description, waves. Each wave has packets. Each packet: title, scope, depends_on, acceptance. Do not write files, do not run tools. Output JSON only, no prose.
```

This is not enough for GRACE projects because the architect must:

```text
avoid broad repository crawls
use contract-first navigation
understand GRACE canon markers
write small execution packets for coders
maintain GRACE documentation canon
choose appropriate verification gates
handle optional context-builder bundles without bloating the prompt
support project-specific overlays like Solar Sage or DeepCalm
```

## 2. Goal

Add a universal GRACE architect prompt v0.02 that works across user projects.

The architect should become:

```text
GRACE document maintainer + task planner + packet slicer + verification planner
```

not a coder and not a broad repo crawler.

## 3. Non-goals

Do not implement a full context-builder in this task.
Do not force the architect to read giant context inline in the system prompt.
Do not hard-code Solar Sage-only frontend assumptions into the universal prompt.
Do not change coder behavior in this task.
Do not change reviewer/verifier prompts unless required by tests.
Do not create a new agent runtime.

## 4. Current implementation facts

`agent_profiles.py` loads profiles from:

```text
src/grace_control/config/agent_profiles.yaml
```

The current architect profile is:

```text
architect-premium
```

This TZ should update the architect prompt in the YAML profile or move the prompt into a dedicated prompt file if that is cleaner.

Recommended prompt file path:

```text
src/grace_control/prompts/architect_universal_v002.md
```

If using a prompt file, the YAML should reference it through an existing or newly added prompt-template mechanism. If no such mechanism exists yet, keep the first implementation in YAML and create a follow-up TZ for prompt file extraction.

## 5. Architect role definition

The architect is responsible for:

```text
1. Reading the user/TZ/spec packet.
2. Understanding the intended target repo and workspace mode.
3. Planning waves and execution packets.
4. Producing small, bounded coder packets.
5. Defining allowed_files and forbidden_files.
6. Defining acceptance gates and evidence requirements.
7. Maintaining the GRACE document canon.
8. Asking questions or returning a discovery packet if the spec is underdetermined.
```

The architect must not:

```text
write production code
make broad code edits
run build/test commands unless explicitly acting as a separate evidence/verifier role
crawl the entire repository by default
silently ignore missing context
invent project facts
```

## 6. Contract-first navigation rule

Architect must use this priority order for context discovery:

```text
1. User/TZ-provided paths and constraints.
2. Context-builder bundle path/URL if provided.
3. GRACE canonical docs.
4. AI_HEADER and module contracts.
5. START_MODULE_CONTRACT / END_MODULE_CONTRACT.
6. START_MODULE_MAP / END_MODULE_MAP.
7. START_FUNCTION_CONTRACT / END_FUNCTION_CONTRACT.
8. START_BLOCK_* / END_BLOCK_* logical sections.
9. Structured log names and GraceLogger usage.
10. Targeted rg/grep only for exact symbols, paths, routes, or error text.
```

Architect must avoid:

```text
repo-wide exploratory crawl
reading many files without reason
large unbounded grep
implementation archaeology when contracts answer the question
```

If contract markers are missing, architect may create a coder packet to add/update the relevant contracts, but only if it is in scope.

## 7. Context-builder bundle handling

Context-builder output should not be pasted into the architect prompt by default.

Instead, the architect should receive a lightweight pointer:

```text
context_bundle_path: /path/to/context-bundle.md
# or
context_bundle_url: file:///path/to/context-bundle.md
# or connector/document URL when supported by runtime
```

Prompt instruction:

```text
A context-builder may have prepared a context bundle for you. Treat it as optional acceleration, not as mandatory truth. Inspect it when it is likely to help. Prefer the bundle over broad repo crawling. If the bundle is huge, skim its table of contents / headers first and read only relevant sections. If the bundle conflicts with the user/TZ, the user/TZ wins. If the bundle is stale, say so in the output and ask for refresh or create a discovery packet.
```

Architect should not receive the entire context bundle inline unless the bundle is small.

Recommended packet fields:

```json
{
  "context_bundle_path": "...",
  "context_bundle_url": "...",
  "context_bundle_summary": "short optional summary",
  "context_bundle_generated_at": "...",
  "context_bundle_scope": ["..."],
  "context_bundle_freshness": "fresh|unknown|stale"
}
```

## 8. GRACE document maintainer role

Architect must maintain these canonical documents when task scope changes them:

```text
docs/grace/knowledge-plan.xml
docs/grace/verification-matrix.xml
docs/grace/technology.xml
docs/grace/development-plan.xml
```

Rules:

```text
If architecture changes, update technology.xml and/or knowledge-plan.xml.
If verification strategy changes, update verification-matrix.xml.
If roadmap/scope/waves change, update development-plan.xml.
If none of these change, explicitly output docs_update_required=false.
If uncertain, create a small docs-audit packet instead of mixing docs edits into production-code packet.
```

The architect should keep docs synchronized, but not overload every coder packet with documentation work.

## 9. Testing taxonomy

Architect must choose the smallest sufficient verification gates.

Universal test/check categories:

```text
lint/static checks
typecheck
unit tests
integration tests
contract/API tests
migration/schema checks
browser/e2e tests
smoke tests
security/safety checks
GRACE evidence/reviewer checks
```

Gate selection rules:

```text
docs-only change: usually no app test gates, but require diff/report check
small UI unit-level change: lint + typecheck + focused unit test + normal unit suite if cheap
route/user journey change: add browser/e2e or route smoke
backend behavior change: unit + integration + API contract checks
DB/schema change: migration/schema checks + rollback story
orchestrator/runtime change: GRACE unit tests + relevant live/smoke runner if safe
high-risk domain: reviewer/evidence gates must be stricter
```

## 10. Universal hard constraints

Every architect packet should include:

```text
allowed_files
forbidden_files
acceptance_gates
evidence_requirements
rollback_or_cleanup_notes when relevant
```

Architect must explicitly protect:

```text
auth
payments
subscriptions
billing
API contracts
database schema/migrations
production deployment config
.env/secrets
package manager lockfiles
large refactors
broad formatting changes
new dependencies
```

Unless the user/TZ explicitly asks to change one of these areas.

## 11. Project overlay support

The universal prompt must allow project-specific overlays without hard-coding them.

Recommended optional packet fields:

```json
{
  "project_overlay": "solarsage|deepcalm|grace|custom",
  "project_test_gates": ["..."],
  "project_forbidden_zones": ["..."],
  "project_runtime_notes": ["..."]
}
```

### 11.1 Solar Sage overlay example

```text
Project: Solar Sage
Likely gates: pnpm lint, pnpm typecheck, pnpm test:run
UI route/journey changes may require focused component tests or browser/e2e smoke.
Forbidden by default: auth, payments, subscriptions, billing, database/schema, production deployment config, env files, lockfile changes.
```

### 11.2 DeepCalm overlay example

```text
Project: DeepCalm / Avito Growth
Likely gates: pytest, deterministic table-driven tests, PostgreSQL/testcontainers when DB behavior changes.
Forbidden by default: live Avito in CI, unsafe real bid apply, microservice/event-bus sprawl, SQLite replacement of PostgreSQL decisions.
```

## 12. Required architect output schema

Architect must output JSON only.

Recommended schema:

```json
{
  "title": "string",
  "description": "string",
  "assumptions": ["string"],
  "open_questions": ["string"],
  "context_strategy": {
    "mode": "contract_first",
    "do_not_crawl_repo": true,
    "context_bundle_path": "string|null",
    "context_bundle_url": "string|null",
    "files_to_read": ["string"],
    "contract_markers_to_use": ["AI_HEADER", "START_MODULE_CONTRACT", "START_FUNCTION_CONTRACT", "START_BLOCK"]
  },
  "docs_update_required": false,
  "docs_to_update": [],
  "waves": [
    {
      "title": "string",
      "packets": [
        {
          "title": "string",
          "scope": "string",
          "target_repo_root": "string|null",
          "workspace_mode": "target_repo_worktree|scoped_copy|full_git_worktree|null",
          "depends_on": [],
          "allowed_files": [],
          "forbidden_files": [],
          "context_hints": [],
          "acceptance": [],
          "verification": [],
          "evidence_required": [],
          "risk_level": "low|medium|high",
          "suggested_executor": "coder-opencode|coder-deepseek-flash|coder-sonnet|null"
        }
      ]
    }
  ]
}
```

If the task is under-specified, architect should return:

```json
{
  "title": "Need clarification or discovery",
  "description": "...",
  "assumptions": [],
  "open_questions": ["..."],
  "context_strategy": {"mode": "discovery_first", "do_not_crawl_repo": true},
  "docs_update_required": false,
  "docs_to_update": [],
  "waves": [
    {
      "title": "Discovery",
      "packets": [
        {
          "title": "Bounded discovery packet",
          "scope": "Read only specific contracts/files and return findings",
          "allowed_files": [],
          "forbidden_files": ["* writes"],
          "acceptance": ["Discovery report produced"],
          "verification": ["No files modified"],
          "risk_level": "low"
        }
      ]
    }
  ]
}
```

## 13. Prompt text to install

Install a concise version of this instruction in `architect-premium`.

Draft prompt:

```text
You are the GRACE Architect.

Role:
- You are not a coder.
- You are the maintainer of GRACE planning documents and the planner of small execution packets.
- Read the user/spec packet from {packet_path} and output ONLY valid JSON.

Context strategy:
- Do not crawl the whole repository by default.
- Use contract-first navigation: user/TZ paths, optional context bundle, GRACE docs, AI_HEADER, START_MODULE_CONTRACT, START_MODULE_MAP, START_FUNCTION_CONTRACT, START_BLOCK/END_BLOCK, structured log names.
- If a context_bundle_path or context_bundle_url is provided, treat it as optional acceleration. Inspect it when useful. Prefer it over broad repo crawling. If it is huge, skim headings/TOC first and read only relevant sections. If it conflicts with the spec, the spec wins.
- If context is insufficient, return open_questions or a bounded discovery packet. Do not invent facts.

GRACE docs maintainer:
- Keep docs/grace/knowledge-plan.xml, docs/grace/verification-matrix.xml, docs/grace/technology.xml, and docs/grace/development-plan.xml synchronized when the task changes architecture, verification, technology, or roadmap.
- If docs do not need updates, set docs_update_required=false.

Packet rules:
- Slice work into small safe waves and packets.
- Every coder packet must include allowed_files, forbidden_files, acceptance, verification, evidence_required, risk_level, and suggested_executor.
- Protect auth, payments, subscriptions, billing, API contracts, database/schema/migrations, production deployment config, env/secrets, lockfiles, broad formatting, and new dependencies unless explicitly requested.

Testing taxonomy:
- Choose the smallest sufficient gates: lint/static, typecheck, unit, integration, API/contract, migration/schema, e2e/browser, smoke, GRACE evidence/reviewer.
- Do not require heavy e2e for docs-only or tiny unit-level work.

Output:
- Output JSON only, no prose, no markdown fences.
- Required top-level fields: title, description, assumptions, open_questions, context_strategy, docs_update_required, docs_to_update, waves.
```

## 14. Implementation requirements

Implement one of these approaches:

### Option A — YAML-only P0

Update `src/grace_control/config/agent_profiles.yaml` `architect-premium.command` prompt text directly.

Pros: simplest.

### Option B — prompt-file P1

Add:

```text
src/grace_control/prompts/architect_universal_v002.md
```

and modify profile loading/executor prompt assembly to support prompt file references.

Pros: cleaner long-term.

For this task, Option A is acceptable for P0 if prompt-file support is not already present.

## 15. Tests

Add/update tests proving:

```text
architect-premium profile loads successfully
command remains list[str], not a string
architect prompt contains contract-first navigation instruction
architect prompt mentions context_bundle_path/context_bundle_url handling
architect prompt mentions GRACE docs maintainer role
architect prompt requires JSON only
```

If there are existing profile loader tests, extend them.

Do not add brittle full-prompt snapshot tests.

## 16. Acceptance criteria

This task passes if:

1. `architect-premium` prompt contains universal GRACE architect instructions.
2. Prompt tells architect not to crawl the entire repo by default.
3. Prompt tells architect to use contract-first navigation.
4. Prompt supports optional context bundle pointer/path/URL rather than inline huge context.
5. Prompt defines GRACE docs maintainer responsibility.
6. Prompt defines testing taxonomy / gate selection responsibility.
7. Prompt requires bounded packets with allowed_files/forbidden_files/acceptance/verification/evidence.
8. Prompt still outputs JSON only.
9. Profile loader tests pass.
10. No coder/reviewer behavior is regressed.

## 17. Verification commands

Run in GRACE repo:

```bash
pytest tests -q
```

If there is a narrower test target for config/profile loading, run that first, then full relevant suite.

Also inspect:

```bash
python - <<'PY'
from grace_control.config.agent_profiles import get_agent_profile, reset_cache
reset_cache()
p = get_agent_profile('architect-premium')
assert p is not None
cmd = '\n'.join(p.command)
for text in [
    'GRACE Architect',
    'Do not crawl the whole repository',
    'contract-first',
    'context_bundle_path',
    'knowledge-plan.xml',
    'verification-matrix.xml',
    'JSON only',
]:
    assert text in cmd, text
print('architect prompt smoke: PASS')
PY
```

## 18. Report

Create report:

```text
docs/work/REPORT_ARCHITECT_UNIVERSAL_GRACE_PROMPT_V002.md
```

Report must include:

```text
changed files
architect profile before/after summary
whether YAML-only or prompt-file approach was used
tests run
prompt smoke result
risk notes
verdict
```

## 19. Next step after pass

After this lands, use the updated architect for Solar Sage pilot 002 planning.

Expected behavior:

```text
architect reads TZ_SOLARSAGE_PILOT_002_TABBAR_CONTRACT.md
architect optionally consumes context bundle pointer if provided
architect emits tiny bounded coder packet
coder edits only Solar Sage target worktree
verifier/reviewer gates stay strict
```
