# ############################################################################
# AI_HEADER: legacy_feature
# ROLE: Feature management and test-run submission CLI commands.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Manage features, packets, and test runs.
# inputs: CLI argparse Namespace.
# returns: None.
# side_effects: Prints outputs to stdout, boots features and schedules Prefect runs.
# emitted_logs: None.
# error_behavior: Raises Exceptions on failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
# END_MODULE_MAP

from __future__ import annotations

import argparse
import json

from prefect_grace.models import (
    FeatureStatus,
    FrontendVisualVerdict,
    ObservabilityVerdict,
    ReasoningProfile,
    ReviewVerdict,
    TestVerdict,
    WaveVerdict,
)
from prefect_grace.tasks.feature_bootstrap import bootstrap_feature, create_packet, mark_feature_status
from prefect_grace.tasks.review_router import create_rework_from_review, record_review
from prefect_grace.tasks.codex_launcher import launch_codex_for_packet
from prefect_grace.tasks.grace_dashboard import build_grace_dashboard_snapshot, render_grace_dashboard
from prefect_grace.tasks.business_intake import TEMPLATE_PATH as BUSINESS_BRIEF_TEMPLATE_PATH, submit_feature_run_from_brief
from prefect_grace.tasks.prefect_runs import list_recent_feature_flow_runs
from prefect_grace.tasks.prefect_submitter import feature_flow_parameters, submit_feature_flow_run
from prefect_grace.cli_commands.common import _scheduled_for_from_args


def _cmd_feature(args: argparse.Namespace) -> None:
    record = bootstrap_feature(args.feature_id, args.title, args.summary)
    print(record["feature_dir"])


def _cmd_mark_feature(args: argparse.Namespace) -> None:
    record = mark_feature_status(args.feature_id, FeatureStatus(args.status))
    print(record)


def _cmd_packet(args: argparse.Namespace) -> None:
    record = create_packet(
        feature_id=args.feature_id,
        wave_id=args.wave_id,
        title=args.title,
        role=args.role,
        reasoning=ReasoningProfile(args.reasoning),
        summary=args.summary,
    )
    print(record["packet_path"])


def _cmd_run_codex(args: argparse.Namespace) -> None:
    result = launch_codex_for_packet(
        args.packet_id,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout_seconds,
    )
    print(result)


def _cmd_run_verifier(args: argparse.Namespace) -> None:
    result = launch_codex_for_packet(
        args.packet_id,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout_seconds,
    )
    print(result)


def _cmd_review(args: argparse.Namespace) -> None:
    reasons = args.reason or []
    record = record_review(
        packet_id=args.packet_id,
        verdict=ReviewVerdict(args.verdict),
        reasons=reasons,
        follow_up_action=args.follow_up_action,
    )
    print(record["review_path"])
    if args.verdict == ReviewVerdict.REWORK_REQUIRED.value and args.create_rework:
        rework = create_rework_from_review(args.packet_id, reasons)
        print(rework["packet_path"])


def _cmd_test_feature(args: argparse.Namespace) -> None:
    from prefect_grace.flows.feature_pipeline import feature_pipeline

    prefer_agent_output = args.parse_agent_output or args.execute
    reviewer_verdict = args.reviewer_verdict
    verifier_test_verdict = args.verifier_test_verdict
    verifier_observability_verdict = args.verifier_observability_verdict
    verifier_frontend_visual_verdict = args.verifier_frontend_visual_verdict
    wave_verdict = args.wave_verdict
    planner_contract = json.loads(args.planner_contract) if args.planner_contract else None
    review_reasons_script = [item.split("||") for item in args.review_reasons_script or []]
    wave_reasons_script = [item.split("||") for item in args.wave_reasons_script or []]
    if not prefer_agent_output:
        reviewer_verdict = reviewer_verdict or (
            ReviewVerdict.BLOCKED.value
            if (
                verifier_test_verdict == TestVerdict.FAILED.value
                or verifier_observability_verdict in {
                    ObservabilityVerdict.NO_EVIDENCE_BLOCKER.value,
                    ObservabilityVerdict.UNEXPECTED_DEGRADATION.value,
                }
                or verifier_frontend_visual_verdict == FrontendVisualVerdict.INSUFFICIENT.value
            )
            else ReviewVerdict.ACCEPTED.value
        )
        reviewer_verdict = reviewer_verdict or ReviewVerdict.ACCEPTED.value
        verifier_test_verdict = verifier_test_verdict or TestVerdict.PASSED.value
        verifier_observability_verdict = verifier_observability_verdict or ObservabilityVerdict.CLEAN.value
        verifier_frontend_visual_verdict = (
            verifier_frontend_visual_verdict or FrontendVisualVerdict.NOT_APPLICABLE.value
        )
        wave_verdict = wave_verdict or WaveVerdict.ACCEPTED.value
    result = feature_pipeline(
        feature_id=args.feature_id,
        title=args.title,
        summary=args.summary,
        implementation_title=args.implementation_title,
        implementation_summary=args.implementation_summary,
        dry_run=not args.execute,
        timeout_seconds=args.timeout_seconds,
        verifier_backend_profile=args.backend_profile if args.backend_profile is not None else (None if args.skip_backend_quick else "backend_quick"),
        verifier_frontend_profile=args.frontend_profile if args.frontend_profile is not None else ("frontend_quick" if args.touches_frontend and not args.frontend_command else None),
        verifier_frontend_commands=args.frontend_command,
        verifier_observability_profile=args.observability_profile,
        verifier_observability_commands=args.observability_command,
        verifier_artifact_globs=args.artifact_glob,
        verifier_touches_frontend=args.touches_frontend or bool(args.frontend_command),
        verifier_requires_frontend_visual=args.touches_frontend or bool(args.frontend_command),
        verifier_include_day_live_canary=args.include_day_live_canary,
        agent_workdir=args.agent_workdir,
        agent_sandbox=args.agent_sandbox,
        commit_hash=args.commit_hash,
        planner_contract=planner_contract,
        run_planner=args.run_planner,
        reviewer_verdict=reviewer_verdict,
        review_reasons=args.review_reason,
        reviewer_verdict_script=args.reviewer_verdict_script,
        review_reasons_script=review_reasons_script or None,
        verifier_test_verdict=verifier_test_verdict,
        verifier_observability_verdict=verifier_observability_verdict,
        verifier_frontend_visual_verdict=verifier_frontend_visual_verdict,
        verifier_commands_run=args.verifier_command,
        verifier_evidence_paths=args.verifier_evidence,
        verifier_blocking_issues=args.verifier_issue,
        wave_verdict=wave_verdict,
        wave_reasons=args.wave_reason,
        wave_verdict_script=args.wave_verdict_script,
        wave_reasons_script=wave_reasons_script or None,
        create_rework=not args.no_create_rework,
        prefer_agent_output=prefer_agent_output,
    )
    print(result)


def _cmd_submit_feature(args: argparse.Namespace) -> None:
    parameters = feature_flow_parameters(
        feature_id=args.feature_id,
        title=args.title,
        summary=args.summary,
        implementation_title=args.implementation_title,
        implementation_summary=args.implementation_summary,
        execute=args.execute,
        timeout_seconds=args.timeout_seconds,
        verifier_backend_profile=args.backend_profile if args.backend_profile is not None else (None if args.skip_backend_quick else "backend_quick"),
        verifier_frontend_profile=args.frontend_profile if args.frontend_profile is not None else ("frontend_quick" if args.touches_frontend and not args.frontend_command else None),
        verifier_frontend_commands=args.frontend_command,
        verifier_observability_profile=args.observability_profile,
        verifier_observability_commands=args.observability_command,
        verifier_artifact_globs=args.artifact_glob,
        verifier_touches_frontend=args.touches_frontend or bool(args.frontend_command),
        verifier_requires_frontend_visual=args.touches_frontend or bool(args.frontend_command),
        verifier_include_day_live_canary=args.include_day_live_canary,
        prefer_agent_output=True,
        run_planner=args.run_planner,
        agent_workdir=args.agent_workdir,
        agent_sandbox=args.agent_sandbox,
        commit_hash=args.commit_hash,
    )
    record = submit_feature_flow_run(
        parameters=parameters,
        scheduled_for=_scheduled_for_from_args(args),
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))


def _cmd_submit_brief(args: argparse.Namespace) -> None:
    record = submit_feature_run_from_brief(args.path, scheduled_for=_scheduled_for_from_args(args))
    print(json.dumps(record, ensure_ascii=False, indent=2))


def _cmd_print_brief_template(args: argparse.Namespace) -> None:
    print(BUSINESS_BRIEF_TEMPLATE_PATH.read_text(encoding="utf-8"))


def _cmd_queue(args: argparse.Namespace) -> None:
    print(json.dumps({"runs": list_recent_feature_flow_runs(limit=args.limit)}, ensure_ascii=False, indent=2))


def _cmd_dashboard(args: argparse.Namespace) -> None:
    snapshot = build_grace_dashboard_snapshot()
    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return
    print(render_grace_dashboard(snapshot))
