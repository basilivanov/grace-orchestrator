# Report: Solar Sage pilot 005 — business-feature full pipeline smoke

**Status:** BLOCKERS FOUND — pipeline not ready for business-feature mode
**Date:** 2026-06-11

## GRACE commit tested
- `70948b5`

## Solar Sage base SHA
- `5846a95` (head of main including pilot 004 merges)

## Business feature input
```
Пользовательская фича: В нижней навигации Solar Sage пользователь должен лучше
понимать, в каком разделе он находится. Когда вкладка активна, она должна иметь
понятную accessibility-подсказку для screen reader...
```

## Blocker 1: Architect works from wrong CWD

`_call_architect_llm()` → `run_llm()` sets `worktree_path=Path.cwd()` — the
API's CWD. The API was started by the runner from `/tmp/grace-orchestrator-export`.
So the architect sees GRACE orchestrator files, NOT Solar Sage files.

The business feature is about Solar Sage's bottom navigation, but the architect
can only explore `src/grace_control/`, `tests_live/scenarios/`, etc.

**Required fix**: the architect must receive `worktree_path` pointing to the
target repo (`/opt/solarsage-astro`), and the context collection must use
target repo scope.

## Blocker 2: v4-pro multi-round LLM calls exceed reasonable timeout

`architect-premium` uses `deepseek/deepseek-v4-pro`. The architect prompt
(~4000 characters) triggers multiple LLM rounds (context exploration → code
reading → plan generation). Each round is a separate API call (~10-60s each).

With the business-feature flow, the architect completed 3+ rounds in ~8 minutes
before the first attempt failed. The retry adds another round. Total runtime
exceeds 1200s (the profile timeout).

The `/api/architect/plan` endpoint is synchronous — the HTTP call blocks until
the architect finishes. With v4-pro, this can exceed 20 minutes.

**Required fixes**:
- Either use a faster model for business-feature architect (e.g. flash)
- Or make `/api/architect/plan` async (return task ID, poll for completion)
- Or reduce architect prompt size and exploration scope

## Blocker 3: Context collection uses wrong scope

`_warm_context()` defaults to `src/grace_control/` when no waves are provided.
For Solar Sage target-repo pilots, this should be the target repo, not the
orchestrator.

## What's working
- `business_feature` scenario YAML loads correctly
- Runner submits business description to API (no pre-defined waves)
- Scenario validation accepts `business_feature: true` without waves
- API's `/api/architect/plan` receives the description and attempts LLM generation
- v4-pro model works (slow but functional)

## Verdict: NOT READY for business-feature pipeline
- architect/context must use target repo CWD, not orchestrator CWD
- v4-pro is too slow for synchronous endpoint with multi-round prompts

## Recommended next steps
1. Pass `worktree_path` from runner → feature_spec → API → `_call_architect_llm` / `run_llm`
2. Make `_warm_context` use the target repo for context, not `src/grace_control/`
3. Use faster model or async plan endpoint for business-feature flow
