from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

from prefect_grace.models import FeatureStatus
from prefect_grace.tasks.feature_bootstrap import bootstrap_feature, mark_feature_status
from prefect_grace.tasks.prefect_submitter import feature_flow_parameters, submit_feature_flow_run
from prefect_grace.tasks.telegram_notify import notify_submission_event
from prefect_grace.tasks.workdir import resolve_execution_workdir

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "business_feature_brief.yaml"


def _as_list(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return [str(value).strip()]


def _normalize_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)


def load_business_feature_brief(path: str | Path) -> dict[str, Any]:
    brief_path = Path(path)
    payload = yaml.safe_load(brief_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("Business feature brief must be a YAML mapping")

    required_fields = ["feature_id", "title", "summary"]
    missing = [field for field in required_fields if not str(payload.get(field) or "").strip()]
    if missing:
        raise ValueError(f"Missing required brief fields: {', '.join(missing)}")

    acceptance_criteria = _as_list(payload.get("acceptance_criteria"))
    non_goals = _as_list(payload.get("non_goals"))
    scope = _as_list(payload.get("scope"))
    visual_expectations = _as_list(payload.get("visual_expectations"))
    frontend_commands = _as_list(payload.get("verifier", {}).get("frontend_commands"))
    observability_commands = _as_list(payload.get("verifier", {}).get("observability_commands"))
    artifact_globs = _as_list(payload.get("verifier", {}).get("artifact_globs"))
    planner_contract = payload.get("planner_contract")
    run_planner = payload.get("run_planner")

    touches_frontend = _normalize_bool(payload.get("touches_frontend"), default=bool(visual_expectations or frontend_commands))
    requires_frontend_visual = _normalize_bool(
        payload.get("requires_frontend_visual"),
        default=touches_frontend or bool(visual_expectations),
    )
    execute = _normalize_bool(payload.get("execute"), default=True)
    include_day_live_canary = _normalize_bool(payload.get("verifier", {}).get("include_day_live_canary"), default=False)

    implementation_title = str(
        payload.get("implementation_title")
        or payload.get("implementation", {}).get("title")
        or "Live Implementation Packet"
    ).strip()
    implementation_summary_parts = [
        str(payload.get("implementation_summary") or payload.get("implementation", {}).get("summary") or "").strip(),
    ]
    if scope:
        implementation_summary_parts.append(f"Scope: {'; '.join(scope)}.")
    if acceptance_criteria:
        implementation_summary_parts.append(f"Acceptance: {'; '.join(acceptance_criteria)}.")
    if non_goals:
        implementation_summary_parts.append(f"Non-goals: {'; '.join(non_goals)}.")
    if visual_expectations:
        implementation_summary_parts.append(f"Visual expectations: {'; '.join(visual_expectations)}.")
    implementation_summary = " ".join(part for part in implementation_summary_parts if part)
    if not implementation_summary:
        implementation_summary = "Execute the feature through architect, planner, coder, verifier, reviewer, and architect wave gate."

    requested_agent_workdir = str(payload.get("agent_workdir") or "").strip() or None

    return {
        "feature_id": str(payload["feature_id"]).strip(),
        "title": str(payload["title"]).strip(),
        "summary": str(payload["summary"]).strip(),
        "scope": scope,
        "acceptance_criteria": acceptance_criteria,
        "non_goals": non_goals,
        "touches_frontend": touches_frontend,
        "requires_frontend_visual": requires_frontend_visual,
        "visual_expectations": visual_expectations,
        "implementation_title": implementation_title,
        "implementation_summary": implementation_summary,
        "execute": execute,
        "timeout_seconds": int(payload.get("timeout_seconds") or 7200),
        "agent_workdir": str(resolve_execution_workdir(requested_agent_workdir)),
        "agent_sandbox": str(payload.get("agent_sandbox") or "").strip() or None,
        "impacted_surfaces": _as_list(payload.get("impacted_surfaces")),
        "impacted_grace_artifacts": _as_list(payload.get("impacted_grace_artifacts")),
        "wave_proposal": _as_list(payload.get("wave_proposal")),
        "open_decisions": _as_list(payload.get("open_decisions")),
        "verifier_backend_profile": str(payload.get("verifier", {}).get("backend_profile") or "").strip() or "backend_quick",
        "verifier_frontend_profile": str(payload.get("verifier", {}).get("frontend_profile") or "").strip() or None,
        "verifier_frontend_commands": frontend_commands,
        "verifier_observability_profile": str(payload.get("verifier", {}).get("observability_profile") or "").strip() or None,
        "verifier_observability_commands": observability_commands,
        "verifier_artifact_globs": artifact_globs,
        "verifier_include_day_live_canary": include_day_live_canary,
        "run_planner": _normalize_bool(run_planner) if run_planner is not None else None,
        "planner_contract": planner_contract if isinstance(planner_contract, dict) else None,
        "raw_brief": payload,
    }


def submit_feature_run_from_brief(path: str | Path, *, scheduled_for: str | None = None) -> dict[str, Any]:
    brief = load_business_feature_brief(path)
    business_context = {
        "brief_path": str(Path(path)),
        "scope": brief["scope"],
        "acceptance_criteria": brief["acceptance_criteria"],
        "non_goals": brief["non_goals"],
        "visual_expectations": brief["visual_expectations"],
        "impacted_surfaces": brief["impacted_surfaces"],
        "impacted_grace_artifacts": brief["impacted_grace_artifacts"],
        "wave_proposal": brief["wave_proposal"],
        "open_decisions": brief["open_decisions"]
        or [
            "Confirm GRACE wave slicing against the supplied business brief.",
            "Escalate if decomposition requires more than one W01 implementation packet.",
        ],
    }
    bootstrap_feature(
        feature_id=brief["feature_id"],
        title=brief["title"],
        summary=brief["summary"],
        business_context=business_context,
    )
    mark_feature_status(brief["feature_id"], FeatureStatus.PLANNED)
    parameters = feature_flow_parameters(
        feature_id=brief["feature_id"],
        title=brief["title"],
        summary=brief["summary"],
        implementation_title=brief["implementation_title"],
        implementation_summary=brief["implementation_summary"],
        execute=brief["execute"],
        timeout_seconds=brief["timeout_seconds"],
        verifier_backend_profile=brief["verifier_backend_profile"],
        verifier_frontend_profile=brief["verifier_frontend_profile"],
        verifier_frontend_commands=brief["verifier_frontend_commands"],
        verifier_observability_profile=brief["verifier_observability_profile"],
        verifier_observability_commands=brief["verifier_observability_commands"],
        verifier_artifact_globs=brief["verifier_artifact_globs"],
        verifier_touches_frontend=brief["touches_frontend"],
        verifier_requires_frontend_visual=brief["requires_frontend_visual"],
        verifier_include_day_live_canary=brief["verifier_include_day_live_canary"],
        prefer_agent_output=True,
        run_planner=brief.get("run_planner"),
        agent_workdir=brief["agent_workdir"],
        agent_sandbox=brief["agent_sandbox"],
        business_context=business_context,
        planner_contract=brief.get("planner_contract"),
    )
    record = submit_feature_flow_run(
        parameters=parameters,
        scheduled_for=scheduled_for,
        tags=[f"brief:{Path(path).name}"],
    )
    record["brief_path"] = str(Path(path))
    record["brief_summary"] = {
        "scope": brief["scope"],
        "acceptance_criteria": brief["acceptance_criteria"],
        "non_goals": brief["non_goals"],
        "visual_expectations": brief["visual_expectations"],
    }
    notify_submission_event(
        feature_id=record["feature_id"],
        title=record["title"],
        execute=bool(brief.get("execute")),
        brief_path=str(Path(path)),
        flow_run_id=record["flow_run_id"],
    )
    return record
