# ############################################################################
# AI_HEADER: planning_recovery_service
# ROLE: Architect repair loop — handles Plan Compiler rejection by sending
#        feedback to architect with previous plan and compiler errors.
# ############################################################################

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from grace_control.core.agent_session_adapter import (
    AgentSessionHandle,
    AgentSessionAdapter,
    AgentRunResult,
    OpenCodeSessionAdapter,
)
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("planning_recovery")

# ── Errors that the architect CAN repair (scope, import, split issues) ──
REPAIRABLE_COMPILER_ERRORS = {
    "E_SOURCE_SPLIT_ORIGIN_MISSING",
    "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
    "E_SCOPE_ACCEPTANCE_IMPOSSIBLE",
    "E_VERIFICATION_ONLY_CODER",
    "E_CODER_EMPTY_SCOPE",
    "E_EVIDENCE_DIFF_EMPTY_SCOPE",
    "E_EVIDENCE_DIFF_VERIFICATION_ONLY",
    "E_SCOPE_PATH_NOT_CANONICAL",
    "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS",
    "E_SCOPE_PYTHON_FILE_LIMIT",
    "E_EVIDENCE_ABSOLUTE_PATTERN",
    "E_EVIDENCE_DESCRIPTIVE_PATTERN",
}

# ── Errors that CANNOT be repaired (shell env, venv, syntax) ────────────
TERMINAL_COMPILER_ERRORS = {
    "E_SHELL_SOURCE_UNDER_DASH",
    "E_VENV_MISSING",
    "E_BASH_SYNTAX_UNDER_SH",
    "E_PYTHON_INVALID_ONELINER",
}


def is_repairable_error(code: str) -> bool:
    return code in REPAIRABLE_COMPILER_ERRORS


def classify_compiler_result(errors: list[dict]) -> str:
    """Classify compiler result as repairable or terminal."""
    if not errors:
        return "ok"

    all_repairable = all(
        e.get("code", "") in REPAIRABLE_COMPILER_ERRORS for e in errors
    )
    has_terminal = any(
        e.get("code", "") in TERMINAL_COMPILER_ERRORS for e in errors
    )

    if has_terminal:
        return "terminal"
    if all_repairable:
        return "repairable"
    return "review"


def build_repair_prompt(
    feature_description: str,
    feature_title: str,
    previous_plan: dict,
    compiler_errors: list[dict],
) -> str:
    """Build a compact repair prompt for the architect."""
    errors_text = ""
    for e in compiler_errors:
        msg = e.get("message", "")
        sug = e.get("suggestion", "")
        errors_text += f"- {e.get('code', '?')}: {msg}\n"
        if sug:
            errors_text += f"  Suggestion: {sug}\n"

    plan_json = json.dumps(previous_plan, separators=(",", ":"), ensure_ascii=False)[:120000]
    feature_description = feature_description[:6000]

    prompt = f"""Your previous plan was rejected by Plan Compiler.
Do NOT regenerate the whole plan from scratch.
Patch the previous JSON plan minimally.
Preserve valid packets unless the compiler error requires changing them.

CRITICAL: Your response must be ONLY valid JSON. Start with {{ and end with }}.
NO markdown fences. NO backticks. NO explanation text before or after.
NO code blocks. NO multi-line comments. JUST the JSON object.

## Original feature
Title: {feature_title}
Description: {feature_description}

## Compiler errors
{errors_text}
## Previous plan (JSON, bounded for repair)
{plan_json}

## Required corrections
- Fix every compiler error listed above.
- If E_SOURCE_SPLIT_ORIGIN_MISSING: add the original source file path to
  the implementation packet's scope. Creating only new module files is
  not enough.
- If E_IMPORT_MIGRATION_SCOPE_INCOMPLETE: include active reference files
  in scope, or split import migration into a separate packet.
- If migration is too large, create phased plan:
   1. create new modules;
   2. convert original source file to shim/delegator;
   3. migrate consumers;
   4. remove shim later.
- If E_EVIDENCE_CONTRADICTS_INSTRUCTIONS: evidence expects a file to exist,
  but instructions say to delete/remove that same file. Change the evidence
  expectation to 'deleted' (or 'absent'), or remove the delete instruction
  from coder_instructions if the file must be kept.
- If E_SCOPE_PYTHON_FILE_LIMIT: split the named coder packet into bounded
  dependent coder packets, or remove a redundant broad cleanup packet when
  its files are already covered by bounded packets. Preserve the final
  repository-wide commands in a bounded evidence packet.
- Keep ALL other parts unchanged.

Respond with the corrected JSON plan now. Start with {{"waves":"""
    return prompt


async def run_architect_repair(
    feature_title: str,
    feature_description: str,
    previous_plan: dict,
    compiler_errors: list[dict],
    previous_session: AgentSessionHandle | None = None,
    adapter: AgentSessionAdapter | None = None,
    cwd: Path | None = None,
) -> tuple[dict | None, str | None]:
    """Run architect repair: attempt resume, build prompt, call LLM, parse result."""
    if adapter is None:
        adapter = OpenCodeSessionAdapter(
            default_model="openai/gpt-5.5",
            default_executor_id="architect-mini-swe",
            runner_name="mini-swe",
        )

    prompt = build_repair_prompt(
        feature_description=feature_description,
        feature_title=feature_title,
        previous_plan=previous_plan,
        compiler_errors=compiler_errors,
    )

    result: AgentRunResult
    if previous_session and previous_session.session_id:
        result = await adapter.resume(previous_session, prompt)
    else:
        from grace_control.core.agent_session_adapter import AgentRunRequest
        request = AgentRunRequest(prompt=prompt, role="architect", cwd=cwd)
        result = await adapter.run_new(request)

    if not result.accepted or not result.output.strip():
        return None, result.error or "architect repair returned empty"

    # Parse JSON from output. Try several strategies:
    # 1. Find outermost { ... } block
    # 2. Try to parse entire output as JSON (in case it's pure JSON without fences)
    import re
    parsed = None
    json_match = re.search(r"\{.*\}", result.output, re.DOTALL)

    if json_match:
        try:
            parsed = json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    if parsed is None:
        try:
            parsed = json.loads(result.output.strip())
        except json.JSONDecodeError:
            pass

    if parsed is None:
        return None, "no valid JSON found in architect repair output"

    return parsed, None
