# ############################################################################
# AI_HEADER: evidence_verifier
# ROLE: Cheap evidence verifier — checks packet contract is proven by evidence.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Parse EvidenceVerifierReport from LLM JSON.
#          run_evidence_verifier() calls LLM with prompt and returns structured report.
#          Invalid/timeout → REWORK_TO_CODER, never PASS.
# inputs: packet, acceptance_report, worktree_path, run_dir, changed_files, artifacts.
# returns: EvidenceVerifierReport.
# side_effects: Calls LLM via run_llm.
# emitted_logs: None.
# error_behavior: Never raises; returns REWORK_TO_CODER on error.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - enum: EvidenceVerifierVerdict
#   - class: EvidenceVerifierReport
#   - function: skipped_evidence_report
#   - function: parse_evidence_verifier_json
#   - function: run_evidence_verifier
# END_MODULE_MAP

from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class EvidenceVerifierVerdict(str, Enum):
    PASS = "PASS"
    REWORK_TO_CODER = "REWORK_TO_CODER"
    RETURN_TO_ARCHITECT = "RETURN_TO_ARCHITECT"


class EvidenceVerifierReport(BaseModel):
    verdict: EvidenceVerifierVerdict
    summary: str = ""
    missing_evidence: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    spec_conflicts: list[str] = Field(default_factory=list)
    coder_instructions: list[str] = Field(default_factory=list)
    architect_questions: list[str] = Field(default_factory=list)
    suggested_next_owner: str = "coder"
    skipped: bool = False
    reason: str = ""


def skipped_evidence_report(reason: str) -> EvidenceVerifierReport:
    return EvidenceVerifierReport(
        verdict=EvidenceVerifierVerdict.REWORK_TO_CODER,
        summary=reason,
        skipped=True,
        reason=reason,
        suggested_next_owner="coder",
    )


def parse_evidence_verifier_json(raw: str) -> EvidenceVerifierReport:
    try:
        # Try markdown code fences first (```json ... ```)
        fence_match = re.search(r"```(?:json)?\s*\n(.+?)\n```", raw, re.DOTALL)
        if fence_match:
            candidate = fence_match.group(1).strip()
            try:
                data = json.loads(candidate)
                return _build_report_from_json(data)
            except (json.JSONDecodeError, ValueError):
                pass
        # Try to find a standalone JSON object
        json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return _build_report_from_json(data)
            except (json.JSONDecodeError, ValueError):
                pass
        return EvidenceVerifierReport(
            verdict=EvidenceVerifierVerdict.REWORK_TO_CODER,
            summary="no JSON found in verifier output",
            failed_checks=["no JSON block in response"],
        )
    except Exception as e:
        return EvidenceVerifierReport(
            verdict=EvidenceVerifierVerdict.REWORK_TO_CODER,
            summary=f"verifier parse error: {e}",
            failed_checks=[str(e)[:200]],
        )


def _build_report_from_json(data: dict) -> EvidenceVerifierReport:
    verdict_str = data.get("verdict", "").upper()
    try:
        verdict = EvidenceVerifierVerdict(verdict_str)
    except ValueError:
        return EvidenceVerifierReport(
            verdict=EvidenceVerifierVerdict.REWORK_TO_CODER,
            summary=f"unknown verdict: {verdict_str}",
            failed_checks=[f"unrecognized verdict: {verdict_str}"],
        )
    return EvidenceVerifierReport(
        verdict=verdict,
        summary=data.get("summary", ""),
        missing_evidence=data.get("missing_evidence", []),
        failed_checks=data.get("failed_checks", []),
        spec_conflicts=data.get("spec_conflicts", []),
        coder_instructions=data.get("coder_instructions", []),
        architect_questions=data.get("architect_questions", []),
        suggested_next_owner=data.get("suggested_next_owner", "coder"),
        skipped=False,
    )


async def run_evidence_verifier(
    *,
    packet,
    acceptance_report,
    worktree_path: Path,
    run_dir: Path,
    changed_files: list[str] | None = None,
    artifacts: list[str] | None = None,
) -> EvidenceVerifierReport:
    from grace_control.core.llm_runner import run_llm

    prompt_parts: list[str] = []
    prompt_parts.append(f"Packet: {packet.packet_id} — {getattr(packet, 'title', '')}")
    prompt_parts.append(f"Allowed write scope: {packet.allowed_write_scope}")
    prompt_parts.append(f"Frozen scope: {packet.frozen_scope}")
    prompt_parts.append(f"Verification: {packet.verification}")
    prompt_parts.append(f"Expected evidence: {packet.expected_evidence}")
    prompt_parts.append(f"Acceptance verdict: {acceptance_report.final_verdict.value}")
    prompt_parts.append(f"Acceptance summary: {acceptance_report.summary}")
    prompt_parts.append(f"Stages: {[{'name': s.name.value, 'status': s.status.value, 'summary': s.summary} for s in acceptance_report.stages]}")
    prompt_parts.append(f"Evidence issues: {acceptance_report.evidence_issues}")
    prompt_parts.append(f"Scope violations: {acceptance_report.scope_violations}")
    if changed_files:
        prompt_parts.append(f"Changed files ({len(changed_files)}): {changed_files[:20]}")
    if artifacts:
        prompt_parts.append(f"Artifacts: {artifacts[:20]}")

    prompt_path = Path(__file__).resolve().parent / "prompts" / "evidence_verifier_prompt.md"
    try:
        prompt_template = prompt_path.read_text()
    except Exception:
        prompt_template = "You are Evidence Verifier. Return JSON verdict."

    full_prompt = f"{prompt_template}\n\n## Context\n\n" + "\n".join(prompt_parts)

    try:
        from grace_control.config.agent_profiles import get_agent_profile
        executor = get_agent_profile("verifier-cheap")
        is_multimodal = executor.multimodal if executor else False
        model = executor.model if executor else "deepseek/deepseek-v4-flash"
        # Collect multimodal evidence if available
        multimodal_ctx = ""
        if is_multimodal:
            multimodal_ctx = _build_multimodal_context(packet, acceptance_report, worktree_path, run_dir)
        full_prompt = prompt_template + "\n\n## Context\n\n" + "\n".join(prompt_parts) + multimodal_ctx
        raw = await run_llm(full_prompt, role="verifier", model=model,
                            cli="verifier-cheap")
        return parse_evidence_verifier_json(raw)
    except Exception as e:
        return skipped_evidence_report(f"evidence verifier error: {e}")


def _build_multimodal_context(
    packet,
    acceptance_report,
    worktree_path: "Path",
    run_dir: "Path",
) -> str:
    """Collect visual/browser evidence for the multimodal verifier prompt.

    TZ_FRONTEND_ACCEPTANCE P1 — when executor has multimodal:true,
    includes screenshot paths and visual diff results.
    Otherwise returns empty string.
    """
    from pathlib import Path as _P
    parts: list[str] = []
    parts.append("\n\n## Visual Evidence\n")

    # Check run_dir first (where PlaywrightRunner writes), then worktree
    browser_dir = _P(run_dir) / "browser" if run_dir else _P(worktree_path) / "browser"
    if not browser_dir.exists():
        parts.append("No browser artifacts found.")
        return "\n".join(parts)

    screenshots = list(browser_dir.rglob("*.png"))
    if screenshots:
        parts.append(f"Screenshots ({len(screenshots)}):")
        for s in sorted(screenshots)[:8]:  # Limit to 8 for token budget
            rel = s.relative_to(_P(run_dir) if run_dir else _P(worktree_path))
            parts.append(f"  <image>{rel}</image>")

    # Diff reports
    diff_reports = list(browser_dir.rglob("*diff-report*.json"))
    if diff_reports:
        for dr in diff_reports[:2]:
            try:
                import json
                data = json.loads(dr.read_text())
                parts.append(f"Visual diff: {data.get('diff_pct', '?')}% (threshold {data.get('max_diff_pct', '?')})")
            except Exception:
                pass

    # Console logs
    console_logs = list(browser_dir.rglob("console*.log"))
    if console_logs:
        parts.append(f"\nConsole log ({len(console_logs)} files):")
        for cl in console_logs[:2]:
            content = cl.read_text()[:500]
            if "error" in content.lower():
                parts.append(f"  {cl.name}: has errors")

    return "\n".join(parts)
