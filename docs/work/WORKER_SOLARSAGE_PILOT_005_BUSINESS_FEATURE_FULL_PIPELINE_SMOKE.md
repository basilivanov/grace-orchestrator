# Worker handoff: Solar Sage Pilot 005 — business-feature full pipeline smoke

**Status:** READY_FOR_WORKER
**Date:** 2026-06-11

## Goal

Test the full GRACE business-feature pipeline on a small real Solar Sage frontend feature.

This pilot must start from a business-level feature request, not from pre-defined waves or hand-written implementation steps.

The pipeline under test is:

```text
business feature -> architect plan -> context bundle -> packets/waves -> coder -> gates T0/T1/T2 -> verifier -> merge/report
```

## Target repositories

- Orchestrator/control repo: `/opt/grace-orchestrator`
- Target product repo: `/opt/solarsage-astro`

## Pilot name

`SOLARSAGE_PILOT_005_BUSINESS_FEATURE_FULL_PIPELINE_SMOKE`

## Business feature input

Use this as the only product/business feature request given to the pipeline:

```md
Пользовательская фича:

В нижней навигации Solar Sage пользователь должен лучше понимать, в каком разделе он находится.

Когда вкладка активна, она должна иметь понятную accessibility-подсказку для screen reader:
- активная вкладка: "<Название вкладки>, текущий раздел"
- неактивная вкладка: "<Название вкладки>"

Это должно работать для всех пяти вкладок:
- Сегодня
- Календарь
- Разборы
- Спросить
- Профиль

Нужно добавить автотесты, которые подтверждают это поведение.
Визуально интерфейс не должен измениться.
```

## Important constraint

Do **not** predefine the implementation wave split manually.

The orchestrator/architect must derive the plan from the business feature.

The worker may provide only the business feature, target repo, safety constraints, and required gates.

## Expected implementation shape

The expected implementation is likely around the existing bottom tab navigation, but do not hard-code this into the architect input.

The final product behavior should be equivalent to:

- active tab link gets an accessible label like `Сегодня, текущий раздел`
- inactive tab links get accessible labels equal to their visible labels
- all five tabs are covered by tests
- no visual UI change

## Safety constraints

The pilot must not modify:

- package manager files
- lockfiles
- environment files
- auth/payment/subscription code
- database/schema/migration files
- deployment/infrastructure files

The target product change should be a minimal frontend slice.

## Required gates

Each executable wave must pass explicit gates:

### T0

- `git status --short`
- `git diff --stat`
- `git diff --name-only`

### T1

- `pnpm lint`
- `pnpm typecheck`

### T2

- `pnpm test:run`

## Verifier requirements

The evidence verifier must check:

- the feature started from business-level input
- architect produced a plan rather than using pre-defined waves
- context bundle was built before coder work
- changed files are minimal and relevant
- all five tab states are tested
- active and inactive accessible labels are both tested
- visual behavior is not intentionally changed
- T0/T1/T2 passed
- no forbidden files changed

## Report requirements

Create a final report in `docs/work/` in the orchestrator repo:

`docs/work/REPORT_SOLARSAGE_PILOT_005_BUSINESS_FEATURE_FULL_PIPELINE_SMOKE.md`

The report must include:

- final status: PASS or FAIL
- date
- GRACE commit tested
- Solar Sage base SHA
- Solar Sage final SHA
- business feature input
- architect output summary
- generated waves/packets summary
- context runs count
- context bundle path
- selected files count and key selected files
- changed files by wave
- T0/T1/T2 command outputs by wave
- live log path and exit status
- verifier verdict by wave or by final result
- watchdog_restarts
- failures list
- final pass/fail verdict

## Acceptance criteria

Pilot 005 is PASS only if all of these are true:

- business feature input was the starting point
- no manual pre-defined implementation waves were supplied
- architect generated an implementation plan
- context-builder ran at least once
- coder implemented the feature in Solar Sage
- tests were added or updated for all five tabs
- T0/T1/T2 passed
- verifier accepted the result
- Solar Sage final diff is minimal and relevant
- forbidden files were not changed
- report was written to `grace-orchestrator/docs/work/`
- watchdog_restarts is `0`
- failures is `[]`

## Suggested operator command note

Use the existing GRACE runner path that supports business-feature input and architect planning. Do not use the Pilot 004 pre-defined-wave shortcut.

If the business-feature full pipeline command is missing or broken, stop and report that as the Pilot 005 result. Do not silently fall back to pre-defined waves.
