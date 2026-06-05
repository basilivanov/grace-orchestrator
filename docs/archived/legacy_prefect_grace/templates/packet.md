# Execution Packet: {{ packet_id }}

## Objective

{{ objective }}

## Slice

- slice_id: `{{ slice_id }}`
- slice_slug: `{{ slice_slug }}`
- feature_id: `{{ feature_id }}`
- packet_id: `{{ packet_id }}`
- wave_id: `{{ wave_id }}`
- status: `{{ status }}`
- phase: `{{ phase }}`
- depends_on: `{{ depends_on }}`
- feature_dir: `{{ feature_dir }}`

## Source Of Truth

{{ source_of_truth }}

## Impacted Modules

{{ impacted_modules }}

## Allowed Write Scope

{{ allowed_write_scope }}

## Frozen Scope

{{ frozen_scope }}

## Must Preserve

{{ must_preserve }}

### GRACE Canon Compliance (обязательно)

Весь новый код должен соответствовать GRACE Canon (полный текст: `prompts/canon_digest_prompt.md`). Кратко:

- **AI_HEADER**: первая строка файла `# AI_HEADER: <имя>` + `# ROLE: <описание>`
- **MODULE_CONTRACT**: `# START_MODULE_CONTRACT` / `# END_MODULE_CONTRACT` с purpose, inputs, returns, side_effects, error_behavior
- **MODULE_MAP**: `# START_MODULE_MAP` с перечнем всех классов/функций
- **FUNCTION_CONTRACT**: у каждой функции `# START_FUNCTION_CONTRACT` / `# END_FUNCTION_CONTRACT`
- **Блоки**: `#START_BLOCK_<NAME>` / `#END_BLOCK_<NAME>` для логических секций
- **Лимиты**: файл ≤ 1000 строк, функция ≤ 4000 токенов
- **Логирование**: `log_event()` вместо `print()`, `trace_context()` для сквозного trace_id
- **T0-проверка**: `python3 scripts/grace_lint.py` (Канон), `python3 -m ruff check src/` — обе должны проходить (T0 жестко прописан в пайплайне, не переопределяется архитектором)

## Required Design Decisions

{{ required_design_decisions }}

## Implementation Requirements

{{ implementation_requirements }}

## Acceptance Criteria

{{ acceptance_criteria }}

## Verification

{{ verification }}

## Expected Evidence

{{ expected_evidence }}

## Escalation Triggers

{{ escalation_triggers }}

## Reviewer Gate

{{ reviewer_gate }}
