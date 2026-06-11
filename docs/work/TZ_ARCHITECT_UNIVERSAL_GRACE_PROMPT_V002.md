# TZ: Universal GRACE architect + bounded context-builder prompt v0.02

Date: 2026-06-11
Status: draft-ready for implementation
Priority: P0 orchestrator quality
Scope: GRACE context-builder prompt, architect prompt, and context-bundle handoff

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

Also, current `context-collector-flash` is too primitive. It returns only:

```json
{"relevant_files": [], "summary": "..."}
```

and its prompt does not strongly prevent broad repo crawling, reading irrelevant files, or scanning generated/vendor directories.

## 2. Goal

Add a two-stage universal planning flow:

```text
Wave 0 / Stage 1: bounded context-builder bundle
Wave 1 / Stage 2: universal GRACE architect prompt using bundle pointer
```

The context-builder should quickly produce a small context bundle file.

The architect should receive only a path/URL/summary for that bundle, not the whole bundle inline by default.

The architect should become:

```text
GRACE document maintainer + task planner + packet slicer + verification planner
```

not a coder and not a broad repo crawler.

## 3. Non-goals

Do not implement a full semantic/indexed codebase search engine.
Do not force the architect to read giant context inline in the system prompt.
Do not hard-code Solar Sage-only frontend assumptions into the universal prompt.
Do not change coder behavior in this task.
Do not change reviewer/verifier prompts unless required by tests.
Do not create a new agent runtime.
Do not make context-builder responsible for architectural decisions.

## 4. Current implementation facts

`agent_profiles.py` loads profiles from:

```text
src/grace_control/config/agent_profiles.yaml
```

Existing relevant profiles:

```text
architect-premium
context-collector-flash
```

The current `context-collector-flash` profile uses:

```text
model: deepseek/deepseek-v4-flash
effort: low
timeout_seconds: 300
```

This model class is acceptable for P0. The key improvement is not a smarter model; it is strict bounded scanning and a better output bundle.

## 5. Required wave order

Implementation must be split in this order:

```text
Wave 0: Bounded context-builder bundle
Wave 1: Universal architect prompt that consumes context bundle pointer
Wave 2: Tests, smoke checks, report
```

Architect prompt work should depend on Wave 0, because architect prompt must describe how to consume the context-builder bundle.

## 6. Wave 0 — bounded context-builder bundle

### 6.1 Role

The context-builder is a fast bounded collector.

It must:

```text
read the task/TZ packet
extract explicit paths, allowed_files, target files, mentioned symbols, routes, and tests
inspect AI_HEADER / MODULE_CONTRACT / MODULE_MAP / FUNCTION_CONTRACT / START_BLOCK markers
collect short relevant snippets
write a compact context bundle file
return JSON pointer metadata for architect
```

It must not:

```text
modify files
crawl the whole repository
read outside cwd/worktree_path
scan the whole disk
scan generated/vendor dirs
make architectural decisions
invent missing facts
```

### 6.2 Contract-first collection order

Context-builder must collect context in this priority order:

```text
1. Explicit task/TZ paths.
2. allowed_files / forbidden_files if present.
3. Files named by exact symbol/path/route/error text in the task.
4. AI_HEADER excerpts.
5. START_MODULE_CONTRACT / END_MODULE_CONTRACT excerpts.
6. START_MODULE_MAP / END_MODULE_MAP excerpts.
7. START_FUNCTION_CONTRACT / END_FUNCTION_CONTRACT excerpts.
8. START_BLOCK_* / END_BLOCK_* logical section names.
9. Nearby tests by filename/component/module convention.
10. One-hop imports only if needed.
```

Do not perform broad exploratory scans unless the task explicitly asks for discovery.

### 6.3 Hard scan boundaries

Context-builder must operate only under:

```text
cwd={worktree_path}
```

It must reject or ignore:

```text
absolute paths outside cwd
../ path escapes
symlink escapes outside cwd
```

Exclude directories/patterns by default:

```text
.git/
node_modules/
.next/
dist/
build/
coverage/
.cache/
out/
venv/
.venv/
site-packages/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
```

Project overlays may add more excludes.

### 6.4 P0 limits

Use conservative limits:

```text
max_candidate_files: 80
max_selected_files: 25
max_bytes_per_file: 40000
max_total_bundle_chars: 120000
max_import_depth: 1
max_snippet_lines_per_file: 120
```

If limits are hit, bundle must say:

```text
truncated: true
reason: ...
missing_context: ...
```

### 6.5 Context bundle file

Context-builder writes a markdown bundle file, for example:

```text
/tmp/grace-context/<packet_id>/context-bundle.md
```

The file must use this structure:

```markdown
# Context Bundle

## Metadata
- generated_at:
- packet_id:
- target_repo_root:
- workspace_path:
- source_task:
- truncated:

## Task summary
...

## Explicit target paths
...

## Selected files
...

## Relevant contracts
### path/to/file.py
- AI_HEADER: ...
- MODULE_CONTRACT: ...
- FUNCTION_CONTRACTS: ...
- START_BLOCKS: ...

## Relevant snippets
Short snippets only, not whole large files.

## Related tests
...

## Suggested gates
...

## Missing context / uncertainty
...

## Excluded from scan
...
```

### 6.6 JSON output to architect/runner

Context-builder returns JSON only:

```json
{
  "verdict": "BUNDLE_READY",
  "context_bundle_path": "/tmp/grace-context/<packet_id>/context-bundle.md",
  "context_bundle_url": "file:///tmp/grace-context/<packet_id>/context-bundle.md",
  "context_bundle_summary": "short summary",
  "context_bundle_scope": ["path1", "path2"],
  "selected_files": ["path1", "path2"],
  "excluded_patterns": ["node_modules/**", ".git/**"],
  "truncated": false,
  "missing_context": [],
  "warnings": []
}
```

If insufficient context:

```json
{
  "verdict": "NEEDS_DISCOVERY",
  "context_bundle_path": null,
  "context_bundle_summary": "...",
  "selected_files": [],
  "missing_context": ["..."],
  "warnings": ["..."]
}
```

### 6.7 Context-builder prompt text

Update `context-collector-flash` prompt to something like:

```text
You are the bounded GRACE Context Builder.

Role:
- You are not a coder and not an architect.
- You do not modify files.
- Read the task from {packet_path} and collect a compact context bundle for the architect.

Hard boundaries:
- Work only inside cwd={worktree_path}.
- Do not read outside cwd. Do not follow path escapes or symlink escapes.
- Do not crawl the whole repository.
- Exclude .git, node_modules, .next, dist, build, coverage, venv, .venv, site-packages, caches, generated outputs.

Collection strategy:
- Prefer explicit paths from the task, allowed_files, mentioned symbols/routes/errors, AI_HEADER, START_MODULE_CONTRACT, START_MODULE_MAP, START_FUNCTION_CONTRACT, START_BLOCK/END_BLOCK, and nearby tests.
- Use one-hop imports only when needed.
- Capture short snippets and contract excerpts, not whole large files.
- If context is insufficient, say missing_context instead of scanning broadly.

Output:
- Write a markdown context bundle file under /tmp/grace-context/<packet_id>/context-bundle.md when possible.
- Output JSON only, no prose, no markdown fences.
- Include context_bundle_path, context_bundle_url, context_bundle_summary, selected_files, excluded_patterns, truncated, missing_context, warnings.
```

If the current runtime does not allow the agent to write `/tmp/grace-context`, then P0 may instead write the bundle under the packet artifact directory. The returned JSON must still include the actual path.

## 7. Wave 1 — universal GRACE architect prompt

### 7.1 Architect role definition

The architect is responsible for:

```text
1. Reading the user/TZ/spec packet.
2. Inspecting optional context-builder bundle path/URL only if useful.
3. Understanding the intended target repo and workspace mode.
4. Planning waves and execution packets.
5. Producing small, bounded coder packets.
6. Defining allowed_files and forbidden_files.
7. Defining acceptance gates and evidence requirements.
8. Maintaining the GRACE document canon.
9. Asking questions or returning a discovery packet if the spec is underdetermined.
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

### 7.2 Architect context-bundle handling

Context-builder output should not be pasted into the architect prompt by default.

Instead, the architect receives lightweight fields:

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

Architect prompt instruction:

```text
A context-builder may have prepared a context bundle for you. Treat it as optional acceleration, not as mandatory truth. Inspect it when it is likely to help. Prefer the bundle over broad repo crawling. If the bundle is huge, skim headings/TOC first and read only relevant sections. If the bundle conflicts with the user/TZ, the user/TZ wins. If the bundle is stale, say so in the output and ask for refresh or create a discovery packet.
```

### 7.3 Architect contract-first navigation rule

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

## 9. Testing taxonomy for architect

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

If the task is under-specified, architect should return a bounded discovery packet rather than wide repo crawl.

## 13. Prompt text to install for architect

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

Update `src/grace_control/config/agent_profiles.yaml`:

```text
context-collector-flash prompt
architect-premium prompt
```

Pros: simplest.

### Option B — prompt-file P1

Add:

```text
src/grace_control/prompts/context_builder_bounded_v001.md
src/grace_control/prompts/architect_universal_v002.md
```

and modify profile loading/executor prompt assembly to support prompt file references.

For this task, Option A is acceptable for P0 if prompt-file support is not already present.

## 15. Tests

Add/update tests proving:

```text
context-collector-flash profile loads successfully
context-builder prompt forbids whole-repo crawl
context-builder prompt forbids reading outside cwd
context-builder prompt mentions AI_HEADER / MODULE_CONTRACT / FUNCTION_CONTRACT / START_BLOCK
context-builder prompt mentions bundle output path/url
architect-premium profile loads successfully
architect prompt contains contract-first navigation instruction
architect prompt mentions context_bundle_path/context_bundle_url handling
architect prompt mentions GRACE docs maintainer role
architect prompt requires JSON only
command fields remain list[str], not string
```

If there are existing profile loader tests, extend them.

Do not add brittle full-prompt snapshot tests.

## 16. Acceptance criteria

This task passes if:

1. Context-builder becomes Wave 0 / Stage 1 in this prompt-upgrade work.
2. `context-collector-flash` prompt is bounded and contract-first.
3. Context-builder prompt forbids whole-repo crawl and reading outside cwd.
4. Context-builder prompt excludes generated/vendor/cache directories.
5. Context-builder output includes context bundle path/url/summary/scope.
6. Architect prompt consumes context bundle as optional pointer, not huge inline context.
7. `architect-premium` prompt contains universal GRACE architect instructions.
8. Architect prompt tells architect not to crawl the entire repo by default.
9. Architect prompt tells architect to use contract-first navigation.
10. Architect prompt defines GRACE docs maintainer responsibility.
11. Architect prompt defines testing taxonomy / gate selection responsibility.
12. Architect prompt requires bounded packets with allowed_files/forbidden_files/acceptance/verification/evidence.
13. Architect prompt still outputs JSON only.
14. Profile loader tests pass.
15. No coder/reviewer behavior is regressed.

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
for profile_id in ['architect-premium', 'context-collector-flash']:
    p = get_agent_profile(profile_id)
    assert p is not None, profile_id
    cmd = '\n'.join(p.command)
    assert 'JSON' in cmd, profile_id

architect = '\n'.join(get_agent_profile('architect-premium').command)
for text in [
    'GRACE Architect',
    'Do not crawl the whole repository',
    'contract-first',
    'context_bundle_path',
    'knowledge-plan.xml',
    'verification-matrix.xml',
]:
    assert text in architect, text

collector = '\n'.join(get_agent_profile('context-collector-flash').command)
for text in [
    'bounded GRACE Context Builder',
    'Do not read outside cwd',
    'Do not crawl the whole repository',
    'AI_HEADER',
    'START_MODULE_CONTRACT',
    'START_FUNCTION_CONTRACT',
    'context_bundle_path',
]:
    assert text in collector, text

print('architect/context-builder prompt smoke: PASS')
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
context-builder profile before/after summary
architect profile before/after summary
whether YAML-only or prompt-file approach was used
tests run
prompt smoke result
risk notes
verdict
```

## 19. Next step after pass

After this lands, use the updated flow for Solar Sage pilot 002 planning.

Expected behavior:

```text
context-builder reads TZ_SOLARSAGE_PILOT_002_TABBAR_CONTRACT.md
context-builder writes bounded bundle with relevant headers/contracts/snippets/tests
architect receives only bundle path/url + short summary
architect emits tiny bounded coder packet
coder edits only Solar Sage target worktree
verifier/reviewer gates stay strict
```
