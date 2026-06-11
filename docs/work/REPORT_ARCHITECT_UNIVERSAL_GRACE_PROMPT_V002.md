# Report: Universal GRACE architect + bounded context-builder prompt v0.02

Date: 2026-06-11
Verdict: **PASS**

## Changed files

| File | Change |
|------|--------|
| `src/grace_control/config/agent_profiles.yaml` | Updated `context-collector-flash` and `architect-premium` prompts |
| `tests/grace_control/config/test_w3_config_cleanup.py` | Added `test_agent_profile_prompt_content` |

## Context-builder profile (`context-collector-flash`)

**Before:** Generic collector — `relevant_files` + `summary` JSON.

**After:** Bounded GRACE Context Builder — explicit hard boundaries, contract-first collection order, context bundle file with path/url/summary/scope.

Key additions:
- `"bounded GRACE Context Builder"` role definition
- `"Do not read outside cwd"` / `"Do not crawl the whole repository"` hard boundaries
- Excluded dirs: `.git, node_modules, .next, dist, build, coverage, venv, .venv, site-packages, caches`
- Contract-first collection order (AI_HEADER, MODULE_CONTRACT, FUNCTION_CONTRACT, START_BLOCK)
- Context bundle output at `/tmp/grace-context/<packet_id>/context-bundle.md`
- JSON output with `context_bundle_path`, `context_bundle_url`, `context_bundle_summary`, `selected_files`, `excluded_patterns`, `truncated`, `missing_context`, `warnings`

## Architect profile (`architect-premium`)

**Before:** Generic architect — simple title/description/waves JSON.

**After:** Universal GRACE Architect — contract-first navigation, GRACE docs maintainer, testing taxonomy, bounded packet rules.

Key additions:
- `"GRACE Architect"` role definition
- `"Do not crawl the whole repository by default"` contract-first navigation
- `context_bundle_path`/`context_bundle_url` optional pointer handling
- GRACE docs maintainer role (`knowledge-plan.xml`, `verification-matrix.xml`, `technology.xml`, `development-plan.xml`)
- Testing taxonomy and gate selection rules
- Bounded packet requirements (`allowed_files`, `forbidden_files`, `acceptance`, `verification`, `evidence_required`, `risk_level`, `suggested_executor`)
- Protect auth/payments/subscriptions/billing/API contracts/schema/deployment/lockfiles

## Approach

Option A (YAML-only P0) — prompts updated directly in `agent_profiles.yaml`. No prompt-file infrastructure needed.

## Tests

- Existing tests: **132 passed** (no regressions)
- New test `test_agent_profile_prompt_content`: asserts expected strings in both `architect-premium` and `context-collector-flash` prompts

## Prompt smoke result

```
architect/context-builder prompt smoke: PASS
```

## Risk notes

- Low risk: prompt changes only, no runtime logic changes
- `coder-deepseek-flash` and `verifier-cheap` profiles untouched
- All existing tests pass

## Next step

Use the updated architect + context-builder flow for Solar Sage pilot 002 TabBar contract planning.
