from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PACKET_DECISION_START = "FINAL_PACKET_DECISION_JSON"
PACKET_DECISION_END = "END_FINAL_PACKET_DECISION_JSON"
WAVE_DECISION_START = "FINAL_WAVE_DECISION_JSON"
WAVE_DECISION_END = "END_FINAL_WAVE_DECISION_JSON"
VERIFIER_EVIDENCE_START = "FINAL_VERIFIER_EVIDENCE_JSON"
VERIFIER_EVIDENCE_END = "END_FINAL_VERIFIER_EVIDENCE_JSON"
PLANNER_WAVE_PLAN_START = "FINAL_GRACE_WAVE_PLAN_JSON"
PLANNER_WAVE_PLAN_END = "END_FINAL_GRACE_WAVE_PLAN_JSON"
ARCHITECT_ARTIFACT_PLAN_START = "FINAL_ARCHITECT_ARTIFACT_PLAN_JSON"
ARCHITECT_ARTIFACT_PLAN_END = "END_FINAL_ARCHITECT_ARTIFACT_PLAN_JSON"
DIRECT_REWORK_PACKET_START = "FINAL_DIRECT_REWORK_PACKET_JSON"
DIRECT_REWORK_PACKET_END = "END_FINAL_DIRECT_REWORK_PACKET_JSON"

REVIEWER_VERDICTS = {"accepted", "rework_required", "blocked", "escalate_to_architect"}
WAVE_VERDICTS = {"accepted", "rework_required", "blocked"}
TEST_VERDICTS = {"passed", "failed", "not_run"}
OBSERVABILITY_VERDICTS = {"clean", "degraded-but-expected", "unexpected-degradation", "no-evidence-blocker"}
FRONTEND_VISUAL_VERDICTS = {"sufficient", "insufficient", "not_applicable"}
REWORK_ROUTE_CLASSIFICATIONS = {"self_resolvable_rework", "requires_user_decision", "requires_planner"}
REWORK_MODES = {"light_resume", "bounded_fresh", "decision_required"}
PACKET_TYPES = {"execution", "rework", "gate_decision"}


def read_agent_message(last_message_path: str | None, stdout_path: str | None = None) -> str:
    if last_message_path:
        path = Path(last_message_path)
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    if stdout_path:
        path = Path(stdout_path)
        if path.exists():
            last_text = None
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                item = payload.get("item")
                if payload.get("type") == "item.completed" and isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        last_text = str(text).strip()
            if last_text:
                return last_text
            raw_text = path.read_text(encoding="utf-8").strip()
            if raw_text:
                return raw_text
    return ""


def resolve_reviewer_decision(
    run_result: dict[str, Any],
    *,
    fallback_verdict: str | None = None,
    fallback_reasons: list[str] | None = None,
    prefer_agent_output: bool = True,
) -> dict[str, Any]:
    if fallback_verdict and not prefer_agent_output:
        verdict = _normalize_packet_verdict(fallback_verdict)
        return {
            "packet_verdict": verdict,
            "follow_up_action": _default_follow_up_action(verdict),
            "reasons": list(fallback_reasons or []),
            "source": "fallback",
            "parser_error": None,
            "raw_message": "",
        }
    message = read_agent_message(run_result.get("last_message_path"), run_result.get("stdout_path"))
    parser_error = None
    if message:
        try:
            parsed = parse_reviewer_message(message)
            return {
                **parsed,
                "source": "agent_output",
                "raw_message": message,
            }
        except ValueError as exc:
            parser_error = str(exc)
    if fallback_verdict:
        return {
            "packet_verdict": _normalize_packet_verdict(fallback_verdict),
            "follow_up_action": _default_follow_up_action(_normalize_packet_verdict(fallback_verdict)),
            "reasons": list(fallback_reasons or []),
            "source": "fallback",
            "parser_error": parser_error,
            "raw_message": message,
        }
    raise ValueError(f"Reviewer decision could not be parsed: {parser_error or 'empty agent output'}")


def resolve_wave_decision(
    run_result: dict[str, Any],
    *,
    fallback_verdict: str | None = None,
    fallback_reasons: list[str] | None = None,
    prefer_agent_output: bool = True,
) -> dict[str, Any]:
    if fallback_verdict and not prefer_agent_output:
        return {
            "wave_verdict": _normalize_wave_verdict(fallback_verdict),
            "reasons": list(fallback_reasons or []),
            "source": "fallback",
            "parser_error": None,
            "raw_message": "",
        }
    message = read_agent_message(run_result.get("last_message_path"), run_result.get("stdout_path"))
    parser_error = None
    if message:
        try:
            parsed = parse_wave_gate_message(message)
            return {
                **parsed,
                "source": "agent_output",
                "raw_message": message,
            }
        except ValueError as exc:
            parser_error = str(exc)
    if fallback_verdict:
        return {
            "wave_verdict": _normalize_wave_verdict(fallback_verdict),
            "reasons": list(fallback_reasons or []),
            "source": "fallback",
            "parser_error": parser_error,
            "raw_message": message,
        }
    raise ValueError(f"Wave decision could not be parsed: {parser_error or 'empty agent output'}")


def resolve_verifier_result(
    run_result: dict[str, Any],
    *,
    fallback_test_verdict: str | None = None,
    fallback_observability_verdict: str | None = None,
    fallback_frontend_visual_verdict: str | None = None,
    fallback_commands_run: list[str] | None = None,
    fallback_evidence_paths: list[str] | None = None,
    fallback_blocking_issues: list[str] | None = None,
    prefer_agent_output: bool = True,
) -> dict[str, Any]:
    if fallback_test_verdict and fallback_observability_verdict and not prefer_agent_output:
        return {
            "test_verdict": _normalize_test_verdict(fallback_test_verdict),
            "observability_verdict": _normalize_observability_verdict(fallback_observability_verdict),
            "frontend_visual_verdict": _normalize_frontend_visual_verdict(
                fallback_frontend_visual_verdict or "not_applicable"
            ),
            "commands_run": _normalize_list(fallback_commands_run),
            "evidence_paths": _normalize_list(fallback_evidence_paths),
            "blocking_issues": _normalize_list(fallback_blocking_issues),
            "source": "fallback",
            "parser_error": None,
            "raw_message": "",
        }
    message = read_agent_message(run_result.get("last_message_path"), run_result.get("stdout_path"))
    parser_error = None
    if message:
        try:
            parsed = parse_verifier_message(message)
            return {
                **parsed,
                "source": "agent_output",
                "raw_message": message,
            }
        except ValueError as exc:
            parser_error = str(exc)
    if fallback_test_verdict and fallback_observability_verdict:
        return {
            "test_verdict": _normalize_test_verdict(fallback_test_verdict),
            "observability_verdict": _normalize_observability_verdict(fallback_observability_verdict),
            "frontend_visual_verdict": _normalize_frontend_visual_verdict(
                fallback_frontend_visual_verdict or "not_applicable"
            ),
            "commands_run": _normalize_list(fallback_commands_run),
            "evidence_paths": _normalize_list(fallback_evidence_paths),
            "blocking_issues": _normalize_list(fallback_blocking_issues),
            "source": "fallback",
            "parser_error": parser_error,
            "raw_message": message,
        }
    raise ValueError(f"Verifier result could not be parsed: {parser_error or 'empty agent output'}")


def parse_planner_wave_plan_message(text: str) -> dict[str, Any]:
    payload = _extract_json_payload(text, PLANNER_WAVE_PLAN_START, PLANNER_WAVE_PLAN_END)
    if payload is None:
        payload = _extract_json_from_fences(text, {"packets", "waves"})
    if payload is None:
        raise ValueError("Planner wave plan JSON markers were not found")
    if not isinstance(payload, dict):
        raise ValueError("Planner wave plan payload must be a JSON object")
    return payload


def parse_architect_artifact_plan_message(text: str) -> dict[str, Any]:
    payload = _extract_json_payload(text, ARCHITECT_ARTIFACT_PLAN_START, ARCHITECT_ARTIFACT_PLAN_END)
    if payload is None:
        payload = _extract_json_from_fences(text, {"slice_id", "impacted_modules", "waves"})
    if payload is None:
        raise ValueError("Architect artifact plan JSON markers were not found")
    if not isinstance(payload, dict):
        raise ValueError("Architect artifact plan payload must be a JSON object")
    return payload


def parse_direct_rework_packet_message(text: str) -> dict[str, Any]:
    payload = _extract_json_payload(text, DIRECT_REWORK_PACKET_START, DIRECT_REWORK_PACKET_END)
    if payload is None:
        payload = _extract_json_from_fences(text, {"route_classification", "summary"})
    if payload is None:
        raise ValueError("Direct rework packet JSON markers were not found")
    if not isinstance(payload, dict):
        raise ValueError("Direct rework packet payload must be a JSON object")
    route_classification = _normalize_rework_route_classification(
        payload.get("route_classification") or payload.get("classification") or "self_resolvable_rework"
    )
    return {
        "route_classification": route_classification,
        "rework_mode": _normalize_rework_mode(payload.get("rework_mode") or "bounded_fresh"),
        "packet_type": _normalize_packet_type(payload.get("packet_type") or "rework"),
        "title": str(payload.get("title") or "").strip(),
        "summary": str(payload.get("summary") or "").strip(),
        "write_scope": _normalize_list(payload.get("write_scope")),
        "inputs": _normalize_list(payload.get("inputs")),
        "acceptance_criteria": _normalize_list(payload.get("acceptance_criteria")),
        "verification_profile": payload.get("verification_profile") if isinstance(payload.get("verification_profile"), dict) else {},
        "reviewer_gate": _normalize_list(payload.get("reviewer_gate")),
        "notes": _normalize_list(payload.get("notes")),
        "reasons": _normalize_reason_list(payload.get("reasons")),
    }


def parse_reviewer_message(text: str) -> dict[str, Any]:
    payload = _extract_json_payload(text, PACKET_DECISION_START, PACKET_DECISION_END)
    if payload is None:
        payload = _extract_json_from_fences(text, {"packet_verdict", "verdict"})
    if payload is not None:
        verdict = _normalize_packet_verdict(payload.get("packet_verdict") or payload.get("verdict"))
        follow_up_action = str(payload.get("follow_up_action") or _default_follow_up_action(verdict)).strip()
        reasons = _normalize_reason_list(payload.get("reasons") or payload.get("blockers"))
        result = {
            "packet_verdict": verdict,
            "follow_up_action": follow_up_action,
            "reasons": reasons,
            "packet_type": _normalize_packet_type(payload.get("packet_type") or "gate_decision"),
        }
        route_classification = payload.get("route_classification") or payload.get("rework_classification")
        if route_classification:
            result["route_classification"] = _normalize_rework_route_classification(route_classification)
        rework_mode = payload.get("rework_mode")
        if rework_mode:
            result["rework_mode"] = _normalize_rework_mode(rework_mode)
        return result

    sections = _parse_sections(text, ["Verdict", "Acceptance Check", "Blockers", "Follow-up Action"])
    verdict = _normalize_packet_verdict(sections.get("Verdict"))
    return {
        "packet_verdict": verdict,
        "follow_up_action": str(sections.get("Follow-up Action") or _default_follow_up_action(verdict)).strip(),
        "packet_type": "gate_decision",
        "reasons": _normalize_reason_list(sections.get("Blockers")),
    }


def parse_wave_gate_message(text: str) -> dict[str, Any]:
    payload = _extract_json_payload(text, WAVE_DECISION_START, WAVE_DECISION_END)
    if payload is None:
        payload = _extract_json_from_fences(text, {"wave_verdict", "verdict"})
    if payload is not None:
        return {
            "wave_verdict": _normalize_wave_verdict(payload.get("wave_verdict") or payload.get("verdict")),
            "packet_type": _normalize_packet_type(payload.get("packet_type") or "gate_decision"),
            "reasons": _normalize_reason_list(payload.get("reasons") or payload.get("required_rework")),
        }

    sections = _parse_sections(text, ["Wave Verdict", "Business Fit", "UX / Visual Review", "Required Rework", "Reasons"])
    reasons = _normalize_reason_list(sections.get("Required Rework")) or _normalize_reason_list(sections.get("Reasons"))
    return {
        "wave_verdict": _normalize_wave_verdict(sections.get("Wave Verdict")),
        "packet_type": "gate_decision",
        "reasons": reasons,
    }


def parse_verifier_message(text: str) -> dict[str, Any]:
    payload = _extract_json_payload(text, VERIFIER_EVIDENCE_START, VERIFIER_EVIDENCE_END)
    if payload is None:
        payload = _extract_json_from_fences(text, {"test_verdict", "observability_verdict"})
    if payload is not None:
        return {
            "test_verdict": _normalize_test_verdict(payload.get("test_verdict")),
            "observability_verdict": _normalize_observability_verdict(payload.get("observability_verdict")),
            "frontend_visual_verdict": _normalize_frontend_visual_verdict(
                payload.get("frontend_visual_verdict") or "not_applicable"
            ),
            "commands_run": _normalize_list(payload.get("commands_run")),
            "evidence_paths": _normalize_list(payload.get("evidence_paths")),
            "blocking_issues": _normalize_list(payload.get("blocking_issues")),
        }

    sections = _parse_sections(
        text,
        [
            "Verification Scope",
            "Commands Run",
            "Test Verdict",
            "Evidence Reviewed",
            "Observability Verdict",
            "Frontend Visual Verdict",
            "Blocking Issues",
        ],
    )
    return {
        "test_verdict": _normalize_test_verdict(sections.get("Test Verdict")),
        "observability_verdict": _normalize_observability_verdict(sections.get("Observability Verdict")),
        "frontend_visual_verdict": _normalize_frontend_visual_verdict(
            sections.get("Frontend Visual Verdict") or "not_applicable"
        ),
        "commands_run": _normalize_list(sections.get("Commands Run")),
        "evidence_paths": _normalize_list(sections.get("Evidence Reviewed")),
        "blocking_issues": _normalize_list(sections.get("Blocking Issues")),
    }


def _extract_json_payload(text: str, start_marker: str, end_marker: str) -> dict[str, Any] | None:
    pattern = re.compile(re.escape(start_marker) + r"\s*(\{.*?\})\s*" + re.escape(end_marker), re.DOTALL)
    match = pattern.search(text)
    if not match:
        return None
    return json.loads(match.group(1))


def _extract_json_from_fences(text: str, required_keys: set[str]) -> dict[str, Any] | None:
    for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE):
        block = match.group(1).strip()
        if not block.startswith("{"):
            continue
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        if required_keys.intersection(payload.keys()):
            return payload
    return None


def _parse_sections(text: str, headings: list[str]) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    normalized_to_heading = {heading.casefold(): heading for heading in headings}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current is not None:
                sections.setdefault(current, []).append("")
            continue
        candidate = line.lstrip("#").strip()
        matched_heading = None
        inline_value = None
        for heading_key, heading in normalized_to_heading.items():
            if candidate.casefold() == heading_key:
                matched_heading = heading
                break
            prefix = f"{heading}:"
            if candidate.casefold().startswith(prefix.casefold()):
                matched_heading = heading
                inline_value = candidate[len(prefix):].strip()
                break
        if matched_heading:
            current = matched_heading
            sections.setdefault(current, [])
            if inline_value:
                sections[current].append(inline_value)
            continue
        if current is not None:
            sections.setdefault(current, []).append(raw_line.rstrip())
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def _normalize_packet_verdict(value: Any) -> str:
    verdict = str(value or "").strip().casefold()
    if verdict not in REVIEWER_VERDICTS:
        raise ValueError(f"Unsupported packet verdict: {value!r}")
    return verdict


def _normalize_wave_verdict(value: Any) -> str:
    verdict = str(value or "").strip().casefold()
    if verdict not in WAVE_VERDICTS:
        raise ValueError(f"Unsupported wave verdict: {value!r}")
    return verdict


def _normalize_test_verdict(value: Any) -> str:
    verdict = str(value or "").strip().casefold()
    if verdict not in TEST_VERDICTS:
        raise ValueError(f"Unsupported test verdict: {value!r}")
    return verdict


def _normalize_observability_verdict(value: Any) -> str:
    verdict = str(value or "").strip().casefold()
    if verdict not in OBSERVABILITY_VERDICTS:
        raise ValueError(f"Unsupported observability verdict: {value!r}")
    return verdict


def _normalize_frontend_visual_verdict(value: Any) -> str:
    verdict = str(value or "").strip().casefold()
    if verdict not in FRONTEND_VISUAL_VERDICTS:
        raise ValueError(f"Unsupported frontend visual verdict: {value!r}")
    return verdict


def _normalize_rework_route_classification(value: Any) -> str:
    classification = str(value or "").strip().casefold().replace("-", "_")
    aliases = {
        "self_resolvable": "self_resolvable_rework",
        "localized_rework": "self_resolvable_rework",
        "direct_rework": "self_resolvable_rework",
        "architect_direct_rework": "self_resolvable_rework",
        "user_decision": "requires_user_decision",
        "product_decision": "requires_user_decision",
        "architect_decision": "requires_user_decision",
        "planner": "requires_planner",
        "planner_required": "requires_planner",
    }
    classification = aliases.get(classification, classification)
    if classification not in REWORK_ROUTE_CLASSIFICATIONS:
        raise ValueError(f"Unsupported rework route classification: {value!r}")
    return classification


def _normalize_rework_mode(value: Any) -> str:
    mode = str(value or "").strip().casefold().replace("-", "_")
    aliases = {
        "light": "light_resume",
        "resume": "light_resume",
        "packet_local_resume": "light_resume",
        "small_fix": "light_resume",
        "smallfix": "light_resume",
        "fresh": "bounded_fresh",
        "bounded": "bounded_fresh",
        "fresh_packet": "bounded_fresh",
        "decision": "decision_required",
        "architect_decision": "decision_required",
    }
    mode = aliases.get(mode, mode)
    if mode not in REWORK_MODES:
        raise ValueError(f"Unsupported rework mode: {value!r}")
    return mode


def _normalize_packet_type(value: Any) -> str:
    packet_type = str(value or "").strip().casefold().replace("-", "_")
    aliases = {
        "gate": "gate_decision",
        "decision": "gate_decision",
        "gate-decision": "gate_decision",
        "review": "gate_decision",
        "verdict": "gate_decision",
        "direct_rework": "rework",
        "bounded_fresh": "rework",
        "light_resume": "rework",
        "small_fix": "rework",
        "smallfix": "rework",
        "basic": "execution",
        "light": "execution",
    }
    packet_type = aliases.get(packet_type, packet_type)
    if packet_type not in PACKET_TYPES:
        raise ValueError(f"Unsupported packet type: {value!r}")
    return packet_type


def _default_follow_up_action(verdict: str) -> str:
    if verdict == "rework_required":
        return "localized_rework"
    if verdict == "escalate_to_architect":
        return "architect_decision"
    return "none"


def _normalize_reason_list(value: Any) -> list[str]:
    return _normalize_list(value)


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    normalized_text = text
    if normalized_text.startswith(("-", "*")):
        normalized_text = normalized_text[1:].strip()
    if not normalized_text or normalized_text.casefold() in {"none", "n/a", "not applicable"}:
        return []
    reasons: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("-", "*")):
            line = line[1:].strip()
        if line and line.casefold() not in {"none", "n/a", "not applicable"}:
            reasons.append(line)
    return reasons or [normalized_text]
