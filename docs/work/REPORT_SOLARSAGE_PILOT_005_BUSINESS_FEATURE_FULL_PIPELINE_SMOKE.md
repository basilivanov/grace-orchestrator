# Report: Solar Sage pilot 005 — business-feature full pipeline smoke

**Status:** PARTIAL PASS — pipeline mechanics working, architect output quality needs improvement
**Date:** 2026-06-11

## GRACE commit tested
- `48b1249`

## Solar Sage base SHA
- `87fc8ba` (includes pilot 004 changes)

## Business feature input
```
Пользовательская фича: В нижней навигации Solar Sage пользователь
должен лучше понимать, в каком разделе он находится. Когда вкладка
активна — "<Название>, текущий раздел", неактивна — "<Название>".
```

## What works ✅
1. **Business-feature → architect plan**: runner sends description without waves, API calls LLM
2. **Context-builder (Stage 0)**: synthetic C1 packet runs in target repo, collects bundle
3. **Architect (v4-flash)**: generates plan in ~3 min from business description
4. **CWD correct**: architect + context-collector work in `/opt/solarsage-astro`
5. **Double repo reset**: after Stage 0 AND after architect call → worker gets clean repo
6. **Coder execution**: packets claimed, agents run, acceptance gates applied
7. **Wave gate**: W2 blocked until W1 merges (when architect generates multi-wave)

## Remaining issues ❌
1. **Single-wave output**: architect generates 1 wave/1 packet instead of 2 waves (prod + test)
2. **GRACE lint on Solar Sage**: auto-gates T0 adds `grace_front_lint.py` which fails on non-GRACE files
3. **Scope splitting**: coder changes both tab-bar.tsx AND TabBar.test.tsx when packet scope only allows one file

## Pipeline metrics (latest run)
- context_runs: 0 (synthetic C1 counted differently — needs reporting fix)
- architect_generated: True
- waves: 1, packets: 1
- coder status: rejected (scope violation + GRACE lint failure)

## Recommended next steps
1. Improve architect prompt for better wave scope splitting
2. Gate_resolver: don't run `grace_front_lint.py` when target_repo has `guardrails.sh`
3. Better architect prompt: include allowed_files/forbidden_files per packet
