# ############################################################################
# AI_HEADER: reviewer_gate
# ROLE: Expensive final reviewer — runs after deterministic acceptance + evidence verifier PASS.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Parse ReviewerReport from LLM JSON.
#          run_reviewer_gate() calls LLM with prompt and returns structured report.
#          Invalid/timeout → REWORK_TO_CODER, never PASS.
# inputs: packet, acceptance_report, evidence_verifier_report, worktree_path,
#         run_dir, changed_files, artifacts.
# returns: ReviewerReport.
# side_effects: Calls LLM via run_llm.
# emitted_logs: None.
# error_behavior: Never raises; returns REWORK_TO_CODER on error.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - enum: ReviewerVerdict
#   - class: ReviewerReport
#   - function: skipped_reviewer_report
#   - function: parse_reviewer_json
#   - function: run_reviewer_gate
# END_MODULE_MAP

from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ReviewerVerdict(str, Enum):
    PASS = "PASS"
    REWORK_TO_CODER = "REWORK_TO_CODER"
    RETURN_TO_ARCHITECT = "RETURN_TO_ARCHITECT"


class ReviewerReport(BaseModel):
    verdict: ReviewerVerdict
    summary: str = ""
    risks: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
    architect_questions: list[str] = Field(default_factory=list)
    suggested_next_owner: str = "coder"
    skipped: bool = False
    reason: str = ""


def skipped_reviewer_report(reason: str) -> ReviewerReport:
    return ReviewerReport(
        verdict=ReviewerVerdict.REWORK_TO_CODER,
        summary=reason,
        skipped=True,
        reason=reason,
        suggested_next_owner="coder",
    )


def parse_reviewer_json(raw: str) -> ReviewerReport:
    try:
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            return ReviewerReport(
                verdict=ReviewerVerdict.REWORK_TO_CODER,
                summary="no JSON found in reviewer output",
                required_changes=["no JSON block in response"],
            )
        data = json.loads(json_match.group())
        verdict_str = data.get("verdict", "")
        try:
            verdict = ReviewerVerdict(verdict_str)
        except ValueError:
            return ReviewerReport(
                verdict=ReviewerVerdict.REWORK_TO_CODER,
                summary=f"unknown verdict: {verdict_str}",
                required_changes=[f"unrecognized verdict: {verdict_str}"],
            )
        return ReviewerReport(
            verdict=verdict,
            summary=data.get("summary", ""),
            risks=data.get("risks", []),
            required_changes=data.get("required_changes", []),
            architect_questions=data.get("architect_questions", []),
            suggested_next_owner=data.get("suggested_next_owner", "coder"),
            skipped=False,
        )
    except (json.JSONDecodeError, ValueError) as e:
        return ReviewerReport(
            verdict=ReviewerVerdict.REWORK_TO_CODER,
            summary=f"invalid reviewer JSON: {e}",
            required_changes=[f"JSON parse error: {e}"],
        )


async def run_reviewer_gate(
    *,
    packet,
    acceptance_report,
    evidence_verifier_report,
    worktree_path: Path,
    run_dir: Path,
    changed_files: list[str] | None = None,
    artifacts: list[str] | None = None,
) -> ReviewerReport:
    from grace_control.core.llm_runner import run_llm

    prompt_parts: list[str] = []
    prompt_parts.append(f"Packet: {packet.packet_id} — {getattr(packet, 'title', '')}")
    prompt_parts.append(f"Acceptance verdict: {acceptance_report.final_verdict.value}")
    prompt_parts.append(f"Acceptance summary: {acceptance_report.summary}")
    prompt_parts.append(f"Evidence verifier verdict: {evidence_verifier_report.verdict.value}")
    prompt_parts.append(f"Evidence verifier summary: {evidence_verifier_report.summary}")
    prompt_parts.append(f"Evidence verifier failed checks: {evidence_verifier_report.failed_checks}")
    prompt_parts.append(f"Evidence verifier spec conflicts: {evidence_verifier_report.spec_conflicts}")
    if changed_files:
        prompt_parts.append(f"Changed files ({len(changed_files)}): {changed_files[:20]}")
    if artifacts:
        prompt_parts.append(f"Artifacts: {artifacts[:20]}")

    prompt_path = Path(__file__).resolve().parents[3] / "src" / "prefect_grace" / "prompts" / "reviewer_prompt.md"
    try:
        prompt_template = prompt_path.read_text()
    except Exception:
        prompt_template = "You are final Reviewer. Return JSON verdict."

    full_prompt = f"{prompt_template}\n\n## Context\n\n" + "\n".join(prompt_parts)

    try:
        raw = await run_llm(full_prompt, role="reviewer", model="deepseek/deepseek-v4-pro", cli="opencode")
        return parse_reviewer_json(raw)
    except Exception as e:
        return skipped_reviewer_report(f"reviewer gate error: {e}")
