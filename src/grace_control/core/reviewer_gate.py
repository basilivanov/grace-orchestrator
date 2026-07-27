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
from grace_control.core.stage_instrumentation import stage
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


# ── Reviewer evidence bundle constants ──────────────────────────────────
MAX_REVIEWER_PATCH_CHARS = 6000
MAX_ACCEPTANCE_STAGE_SUMMARY_CHARS = 500
MAX_ACCEPTANCE_STAGES = 20
MAX_SCOPE_VIOLATIONS = 10
MAX_EVIDENCE_PATHS = 20
MAX_CONTRACT_ITEMS = 30
MAX_CONTRACT_ITEM_CHARS = 1200

_SECRET_PATTERNS = [
    re.compile(r'\b(?:API_KEY|TOKEN|SECRET|PASSWORD|JWT_SECRET|SESSION_SECRET)\s*=\s*[^\s"\']+', re.IGNORECASE),
    re.compile(r'Authorization:\s*Bearer\s+\S+', re.IGNORECASE),
    re.compile(r'DATABASE_URL\s*=\s*\S+', re.IGNORECASE),
    re.compile(r'(?:sk|ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}', re.IGNORECASE),
]


def _redact_secrets(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        text = pat.sub("***REDACTED***", text)
    return text


def _bounded_contract_items(value: Any) -> list[str]:
    """Normalize reviewer contract fields without allowing prompt blow-up."""
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        return []
    result: list[str] = []
    for item in values[:MAX_CONTRACT_ITEMS]:
        text = _redact_secrets(str(item))[:MAX_CONTRACT_ITEM_CHARS]
        if text:
            result.append(text)
    return result


def _serialize_acceptance_report(report) -> dict | None:
    if report is None:
        return None
    try:
        stages = []
        for s in getattr(report, "stages", []) or []:
            try:
                name = s.name.value if hasattr(s.name, "value") else str(s.name)
            except Exception:
                name = str(getattr(s, "name", "?"))
            try:
                status = s.status.value if hasattr(s.status, "value") else str(s.status)
            except Exception:
                status = str(getattr(s, "status", "?"))
            summary = str(getattr(s, "summary", "") or "")[:MAX_ACCEPTANCE_STAGE_SUMMARY_CHARS]
            stages.append({"name": name, "status": status, "summary": summary})
            if len(stages) >= MAX_ACCEPTANCE_STAGES:
                break
        violations = []
        for v in getattr(report, "scope_violations", []) or []:
            violations.append(str(v)[:200])
            if len(violations) >= MAX_SCOPE_VIOLATIONS:
                break
        return {
            "final_verdict": report.final_verdict.value if hasattr(report.final_verdict, "value") else str(report.final_verdict),
            "stages": stages,
            "scope_violations": violations,
        }
    except Exception:
        return None


def _load_patch_preview(worktree_path: Path | None, run_dir: Path | None) -> tuple[str | None, bool]:
    if worktree_path and isinstance(worktree_path, Path):
        patch_path = worktree_path / "agent.patch"
        if patch_path.exists():
            try:
                raw = patch_path.read_text()
                raw = _redact_secrets(raw)
                truncated = len(raw) > MAX_REVIEWER_PATCH_CHARS
                return raw[:MAX_REVIEWER_PATCH_CHARS], truncated
            except Exception:
                pass
    if run_dir and isinstance(run_dir, Path):
        patch_path = run_dir / "agent.patch"
        if patch_path.exists():
            try:
                raw = patch_path.read_text()
                raw = _redact_secrets(raw)
                truncated = len(raw) > MAX_REVIEWER_PATCH_CHARS
                return raw[:MAX_REVIEWER_PATCH_CHARS], truncated
            except Exception:
                pass
    return None, False


def _build_reviewer_evidence_bundle(
    *,
    worktree_path: Path | None = None,
    run_dir: Path | None = None,
    changed_files: list[str] | None = None,
    acceptance_report=None,
    artifacts: list[str] | None = None,
    expected_evidence: list | None = None,
    verifier_route_classification: str | None = None,
) -> dict:
    bundle: dict = {}

    if worktree_path:
        bundle["worktree_path"] = str(worktree_path)
    if run_dir:
        bundle["run_dir"] = str(run_dir)

    ar = _serialize_acceptance_report(acceptance_report)
    if ar:
        bundle["acceptance_report"] = ar

    if changed_files:
        bundle["changed_files"] = changed_files[:50]

    patch_text, patch_truncated = _load_patch_preview(worktree_path, run_dir)
    if patch_text is not None:
        bundle["patch_preview"] = patch_text
        bundle["patch_truncated"] = patch_truncated

    if artifacts:
        bundle["evidence_paths"] = artifacts[:MAX_EVIDENCE_PATHS]

    # W05 rework: Include structured expected evidence in the bundle
    if expected_evidence:
        serialized_evidence = []
        for ev in expected_evidence:
            ev_dict = {
                "id": getattr(ev, "id", ""),
                "kind": getattr(ev, "kind", ""),
                "stage": getattr(ev, "stage", ""),
                "owner": getattr(ev, "owner", ""),
                "coder_blocking": getattr(ev, "coder_blocking", True),
                "artifact_patterns": getattr(ev, "artifact_patterns", []),
                "description": getattr(ev, "description", ""),
            }
            serialized_evidence.append(ev_dict)
        bundle["expected_evidence"] = serialized_evidence

    # W05 rework: Include verifier route classification
    if verifier_route_classification:
        bundle["verifier_route_classification"] = verifier_route_classification

    return bundle


def _render_reviewer_evidence_bundle(bundle: dict) -> str:
    parts: list[str] = []

    if bundle.get("worktree_path"):
        parts.append(f"Worktree path: {bundle['worktree_path']}")
    if bundle.get("run_dir"):
        parts.append(f"Run directory: {bundle['run_dir']}")

    ar = bundle.get("acceptance_report")
    if ar:
        parts.append(f"Acceptance report: {json.dumps(ar, ensure_ascii=False)}")

    cf = bundle.get("changed_files")
    if cf:
        parts.append(f"Changed files ({len(cf)}): {cf}")

    # W05 rework: Structured expected evidence
    expected_ev = bundle.get("expected_evidence")
    if expected_ev:
        parts.append("Expected evidence (structured):")
        for ev in expected_ev:
            parts.append(
                f"  - {ev['id']}: kind={ev['kind']}, owner={ev['owner']}, "
                f"stage={ev['stage']}, coder_blocking={ev['coder_blocking']}, "
                f"artifact_patterns={ev['artifact_patterns']}, "
                f"description={ev['description']}"
            )

    # W05 rework: Verifier route classification
    route_class = bundle.get("verifier_route_classification")
    if route_class:
        parts.append(f"Evidence route classification: {route_class}")

    ep = bundle.get("evidence_paths")
    if ep:
        parts.append("Evidence artifacts:")
        for p in ep:
            parts.append(f"  - {p}")

    pp = bundle.get("patch_preview")
    if pp:
        truncated = "true" if bundle.get("patch_truncated") else "false"
        parts.append(f"\nAgent diff preview (first {len(pp)} chars, truncated={truncated}):")
        parts.append(pp)
    elif not cf:
        parts.append("Agent diff preview: unavailable")

    return "\n".join(parts)


@stage("reviewer", llm=True)
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

    # ── Build evidence bundle ───────────────────────────────────────
    # W05 rework: Include structured expected evidence and verifier
    # route classification in the reviewer bundle.
    expected_ev = getattr(packet, "expected_evidence", None)
    verifier_route = getattr(evidence_verifier_report, "suggested_next_owner", None)

    bundle = _build_reviewer_evidence_bundle(
        worktree_path=worktree_path,
        run_dir=run_dir,
        changed_files=changed_files,
        acceptance_report=acceptance_report,
        artifacts=artifacts,
        expected_evidence=expected_ev,
        verifier_route_classification=verifier_route,
    )
    evidence_block = _render_reviewer_evidence_bundle(bundle)

    prompt_parts: list[str] = []
    prompt_parts.append(f"Packet: {packet.packet_id} — {getattr(packet, 'title', '')}")
    packet_metadata = getattr(packet, "metadata", {}) or {}
    contract_context = {
        "acceptance_criteria": _bounded_contract_items(
            packet_metadata.get("acceptance_criteria", [])
        ),
        "coder_instructions": _bounded_contract_items(
            packet_metadata.get("coder_instructions", [])
        ),
        "blocking_issues": _bounded_contract_items(
            packet_metadata.get("blocking_issues", [])
        ),
        "rework_summary": _redact_secrets(
            str(packet_metadata.get("rework_summary", ""))
        )[:MAX_CONTRACT_ITEM_CHARS],
    }
    prompt_parts.append(
        "Authoritative packet contract: "
        + json.dumps(contract_context, ensure_ascii=False)
    )
    prompt_parts.append(f"Evidence verifier verdict: {evidence_verifier_report.verdict.value}")
    prompt_parts.append(f"Evidence verifier summary: {evidence_verifier_report.summary}")
    prompt_parts.append(evidence_block)

    prompt_path = Path(__file__).resolve().parent / "prompts" / "reviewer_prompt.md"
    try:
        prompt_template = prompt_path.read_text()
    except Exception:
        prompt_template = "You are final Reviewer. Return JSON verdict."

    full_prompt = f"{prompt_template}\n\n## Context\n\n" + "\n".join(prompt_parts)

    try:
        from grace_control.core.executor_selector import resolve_model
        executor = resolve_model("reviewer")
        raw = await run_llm(full_prompt, role="reviewer", model=executor["model"],
                            cli=executor["executor_id"], cwd=worktree_path)
        return parse_reviewer_json(raw)
    except Exception as e:
        return skipped_reviewer_report(f"reviewer gate error: {e}")
