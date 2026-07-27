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
from grace_control.core.stage_instrumentation import stage
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


@stage("verifier", llm=True)
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
    from grace_control.core.contracts import (
        check_artifact_patterns,
        route_missing_evidence,
        AcceptanceProfile,
        SUPPORTED_EVIDENCE_KINDS,
        validate_evidence_for_profile,
    )

    # ── W05 rework: Deterministic pre-checks before LLM ──────────────
    # 1. Validate evidence shape against profile (STRICT enforcement)
    profile = getattr(packet, "acceptance_profile", None)
    if profile is None:
        profile = AcceptanceProfile.NORMAL

    evidence_errors = validate_evidence_for_profile(
        getattr(packet, "expected_evidence", []), profile
    )
    if evidence_errors:
        # STRICT evidence validation failure — fail-closed, no LLM needed
        return EvidenceVerifierReport(
            verdict=EvidenceVerifierVerdict.REWORK_TO_CODER,
            summary="Evidence validation failed for profile: " + "; ".join(evidence_errors),
            failed_checks=evidence_errors,
            suggested_next_owner="coder",
        )

    # 2. Check artifact patterns deterministically.  Callers historically
    # supplied only controller run-directory artifacts here, while packet
    # evidence commonly lives in the target worktree (for example ``src/*.py``
    # or ``verification-output/*.log``).  Build one repo-relative inventory so
    # this verifier uses the same evidence sources as the acceptance pipeline.
    available_artifacts = list(artifacts or [])
    available_artifacts.extend(changed_files or [])
    # Packets compiled before E_EVIDENCE_DIFF_HAS_PATTERN may refer to a
    # synthetic T0 stdout label for diff evidence.  The worktree is committed
    # before acceptance, so ``git diff`` stdout is normally empty; the
    # controller-captured changed-files inventory is the authoritative proof.
    if changed_files:
        for requirement in getattr(packet, "expected_evidence", []):
            if requirement.kind != "diff":
                continue
            for pattern in requirement.artifact_patterns:
                if pattern == "t0_stdout" or re.fullmatch(
                    r"t0/cmd_\d{3}_stdout\.log", pattern
                ):
                    available_artifacts.append(pattern)
    evidence_roots = (Path(worktree_path), Path(run_dir))
    verification_commands = {
        command.strip()
        for commands in (getattr(packet, "verification", {}) or {}).values()
        for command in commands
        if isinstance(command, str)
    }
    descriptive_patterns = {
        pattern
        for requirement in getattr(packet, "expected_evidence", [])
        for pattern in requirement.artifact_patterns
        if isinstance(pattern, str)
        and (
            pattern.endswith(" output")
            or pattern.startswith("run: ")
            or pattern.strip() in verification_commands
        )
    }
    # Backward compatibility for packets compiled before descriptive output
    # labels were rejected by the plan compiler.  A label such as
    # ``npm test output`` is accepted only when that exact command passed and
    # its controller-owned stdout artifact exists.
    for stage_result in getattr(acceptance_report, "stages", []) or []:
        for command_result in getattr(stage_result, "commands", []) or []:
            stdout_path = Path(getattr(command_result, "stdout_path", "") or "")
            if not getattr(command_result, "passed", False) or not stdout_path.is_file():
                continue
            try:
                available_artifacts.append(stdout_path.relative_to(run_dir).as_posix())
            except ValueError:
                pass
            command_alias = f"{command_result.command.strip()} output"
            if command_alias in descriptive_patterns:
                available_artifacts.append(command_alias)
            run_alias = f"run: {command_result.command.strip()}"
            if run_alias in descriptive_patterns:
                available_artifacts.append(run_alias)
            exact_alias = command_result.command.strip()
            if exact_alias in descriptive_patterns:
                available_artifacts.append(exact_alias)
    for requirement in getattr(packet, "expected_evidence", []):
        for pattern in requirement.artifact_patterns:
            pattern_path = Path(pattern)
            if pattern_path.is_absolute() or ".." in pattern_path.parts:
                continue
            for root in evidence_roots:
                if not root.exists():
                    continue
                try:
                    available_artifacts.extend(
                        candidate.relative_to(root).as_posix()
                        for candidate in root.glob(pattern)
                        if candidate.is_file()
                    )
                except (OSError, ValueError):
                    continue
    available_artifacts = list(dict.fromkeys(available_artifacts))

    artifact_warnings = check_artifact_patterns(
        getattr(packet, "expected_evidence", []),
        available_artifacts,
    )
    # Collect IDs of evidence whose patterns are unmatched
    missing_from_patterns: list[str] = []
    for w in artifact_warnings:
        # Extract evidence ID from warning: "Evidence 'EV-ID'..."
        m = re.search(r"Evidence '([^']+)'", w)
        if m:
            missing_from_patterns.append(m.group(1))

    unsupported_requirements = [
        req for req in getattr(packet, "expected_evidence", [])
        if req.id in missing_from_patterns and req.kind not in SUPPORTED_EVIDENCE_KINDS
    ]
    if unsupported_requirements:
        invalid = [f"{req.id}:{req.kind}" for req in unsupported_requirements]
        return EvidenceVerifierReport(
            verdict=EvidenceVerifierVerdict.RETURN_TO_ARCHITECT,
            summary="Packet contract contains unsupported evidence kinds",
            missing_evidence=[req.id for req in unsupported_requirements],
            failed_checks=[f"unsupported evidence kind: {item}" for item in invalid],
            spec_conflicts=["replace unsupported evidence kinds before coder retry"],
            architect_questions=[
                "Replace each unsupported evidence kind with a canonical kind and a run-relative artifact glob.",
            ],
            suggested_next_owner="architect",
        )

    # 3. If deterministic checks found missing required evidence, route
    if missing_from_patterns:
        next_owner = route_missing_evidence(
            missing_from_patterns,
            getattr(packet, "expected_evidence", []),
        )
        if next_owner == "architect":
            deterministic_verdict = EvidenceVerifierVerdict.RETURN_TO_ARCHITECT
        elif next_owner == "verifier":
            # Verifier-owned issue — still REWORK_TO_CODER but with
            # suggested_next_owner=verifier for downstream routing
            deterministic_verdict = EvidenceVerifierVerdict.REWORK_TO_CODER
        else:
            deterministic_verdict = EvidenceVerifierVerdict.REWORK_TO_CODER

        # Build deterministic report — the LLM may refine but cannot
        # override the deterministic routing for missing evidence.
        deterministic_report = EvidenceVerifierReport(
            verdict=deterministic_verdict,
            summary=f"Deterministic check: {len(missing_from_patterns)} evidence patterns unmatched",
            missing_evidence=missing_from_patterns,
            failed_checks=artifact_warnings,
            suggested_next_owner=next_owner,
        )
        # If ALL missing evidence is deterministic, skip the LLM call.
        # If there are also acceptance issues, let the LLM add context.
        acceptance_ok = (
            hasattr(acceptance_report, "final_verdict")
            and acceptance_report.final_verdict.value == "accepted"
        )
        if acceptance_ok:
            return deterministic_report
        # Otherwise continue to LLM for richer context, but merge
        # deterministic findings into the LLM report below.

    # ── LLM-based verification (existing path, enhanced) ─────────────
    prompt_parts: list[str] = []
    prompt_parts.append(f"Packet: {packet.packet_id} — {getattr(packet, 'title', '')}")
    prompt_parts.append(f"Allowed write scope: {packet.allowed_write_scope}")
    prompt_parts.append(f"Frozen scope: {packet.frozen_scope}")
    prompt_parts.append(f"Verification: {packet.verification}")

    # W05 rework: Include structured expected evidence in the prompt
    expected_ev = getattr(packet, "expected_evidence", [])
    if expected_ev:
        ev_lines = []
        for ev in expected_ev:
            ev_lines.append(
                f"  - {ev.id}: kind={ev.kind}, owner={ev.owner}, "
                f"stage={ev.stage}, coder_blocking={ev.coder_blocking}, "
                f"artifact_patterns={ev.artifact_patterns}, "
                f"description={ev.description}"
            )
        prompt_parts.append("Expected evidence (structured):\n" + "\n".join(ev_lines))
    else:
        prompt_parts.append(f"Expected evidence: {expected_ev}")

    prompt_parts.append(f"Acceptance verdict: {acceptance_report.final_verdict.value}")
    prompt_parts.append(f"Acceptance summary: {acceptance_report.summary}")
    prompt_parts.append(f"Stages: {[{'name': s.name.value, 'status': s.status.value, 'summary': s.summary} for s in acceptance_report.stages]}")
    prompt_parts.append(f"Evidence issues: {acceptance_report.evidence_issues}")
    prompt_parts.append(f"Scope violations: {acceptance_report.scope_violations}")
    if changed_files:
        prompt_parts.append(f"Changed files ({len(changed_files)}): {changed_files[:20]}")
    if available_artifacts:
        prompt_parts.append(f"Artifacts: {available_artifacts[:20]}")

    # W05 rework: Include deterministic artifact pattern warnings
    if artifact_warnings:
        prompt_parts.append(f"Artifact pattern warnings (deterministic): {artifact_warnings}")

    prompt_path = Path(__file__).resolve().parent / "prompts" / "evidence_verifier_prompt.md"
    try:
        prompt_template = prompt_path.read_text()
    except Exception:
        prompt_template = "You are Evidence Verifier. Return JSON verdict."

    full_prompt = f"{prompt_template}\n\n## Context\n\n" + "\n".join(prompt_parts)

    try:
        from grace_control.config.agent_profiles import get_agent_profile
        from grace_control.core.executor_selector import resolve_model

        executor = resolve_model("verifier")
        agent_profile = get_agent_profile(executor["executor_id"])
        is_multimodal = agent_profile.multimodal if agent_profile else False
        model = executor["model"] or (agent_profile.model if agent_profile else "deepseek/deepseek-v4-flash")
        # Collect multimodal evidence if available
        multimodal_ctx = ""
        if is_multimodal:
            multimodal_ctx = _build_multimodal_context(packet, acceptance_report, worktree_path, run_dir)
        full_prompt = prompt_template + "\n\n## Context\n\n" + "\n".join(prompt_parts) + multimodal_ctx
        raw = await run_llm(full_prompt, role="verifier", model=model,
                            cli=executor["executor_id"], cwd=worktree_path)
        llm_report = parse_evidence_verifier_json(raw)

        # W05 rework: Merge deterministic findings into LLM report
        if missing_from_patterns:
            # Deterministic missing evidence takes priority — the LLM
            # cannot override the routing for deterministically-missing
            # evidence, but it can add context.
            merged_missing = list(set(
                llm_report.missing_evidence + missing_from_patterns
            ))
            merged_failed = list(set(
                llm_report.failed_checks + artifact_warnings
            ))
            # Use deterministic routing for suggested_next_owner
            next_owner = route_missing_evidence(
                merged_missing,
                expected_ev,
            )
            if next_owner == "architect":
                merged_verdict = EvidenceVerifierVerdict.RETURN_TO_ARCHITECT
            else:
                merged_verdict = llm_report.verdict
            return EvidenceVerifierReport(
                verdict=merged_verdict,
                summary=llm_report.summary or f"Deterministic + LLM: {len(merged_missing)} missing",
                missing_evidence=merged_missing,
                failed_checks=merged_failed,
                spec_conflicts=llm_report.spec_conflicts,
                coder_instructions=llm_report.coder_instructions,
                architect_questions=llm_report.architect_questions,
                suggested_next_owner=next_owner,
            )

        return llm_report
    except Exception as e:
        # If LLM fails but we had deterministic findings, return those
        if missing_from_patterns:
            return deterministic_report  # type: ignore[possibly-undefined]
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
