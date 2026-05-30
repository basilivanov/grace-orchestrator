# ############################################################################
# AI_HEADER: parser
# ROLE: Builds the structured CLI parser with nested subcommands.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Assemble the CLI argument parser hierarchy with type conversions.
# inputs: None.
# returns: argparse.ArgumentParser.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: build_parser
# END_MODULE_MAP

from __future__ import annotations

import argparse
from pathlib import Path

from prefect_grace.models import (
    FeatureStatus,
    FrontendVisualVerdict,
    ObservabilityVerdict,
    ReasoningProfile,
    ReviewVerdict,
    TestVerdict,
    WaveVerdict,
)

from prefect_grace.cli_commands.legacy_feature import (
    _cmd_feature,
    _cmd_mark_feature,
    _cmd_packet,
    _cmd_run_codex,
    _cmd_run_verifier,
    _cmd_test_feature,
    _cmd_submit_feature,
    _cmd_submit_brief,
    _cmd_print_brief_template,
    _cmd_queue,
    _cmd_dashboard,
)
from prefect_grace.cli_commands.project_registry import (
    _cmd_validate_project,
    _cmd_scan_packets,
    _cmd_validate_packet,
    _cmd_sync_packets,
    _cmd_bootstrap_backlog,
    _cmd_registry_bootstrap_apply,
    _cmd_packet_status,
    _cmd_registry_dump,
)
from prefect_grace.cli_commands.packet_submission import (
    _cmd_submit_packets,
)
from prefect_grace.cli_commands.prefect_smokes import (
    _cmd_registry_apply_smoke,
    _cmd_registry_source_integrity_audit,
    _cmd_run_e2e_registry_seeded_smoke,
    _cmd_run_prefect_e2e_live_smoke,
    _cmd_run_prefect_e2e_batch_smoke,
    _cmd_run_prefect_e2e_real_dry_run_smoke,
    _cmd_run_nightly,
    _cmd_nightly_preflight_risk_report,
    _cmd_nightly_select_batch,
    _cmd_nightly_recheck_batch,
    _cmd_nightly_batch_execute,
    _cmd_run_nightly_controlled_batch,
)
from prefect_grace.cli_commands.queue_watcher import _cmd_queue_watcher
from prefect_grace.cli_commands.worktrees import (
    _cmd_worktree_create,
    _cmd_worktree_status,
    _cmd_worktree_cleanup,
    _cmd_worktree_scope_check,
    _cmd_run_worktree_scope_flow,
)
from prefect_grace.cli_commands.packet_execution import (
    _cmd_run_managed_packet,
    _cmd_run_e2e_packet,
    _cmd_run_e2e_packet_flow,
    _cmd_run_handoff,
    _cmd_run_single_live_packet_pilot,
    _cmd_run_single_live_prefect_packet_pilot,
    _cmd_run_single_astro_packet_pilot,
)
from prefect_grace.cli_commands.evidence import (
    _cmd_review,
    _cmd_write_review,
    _cmd_write_evidence,
    _cmd_write_rework,
    _cmd_check_scope,
    _cmd_sync_packet_yaml_sidecar,
    _cmd_audit_packet_yaml_sidecars,
    _cmd_plan_packet_yaml_sidecar_migration,
    _cmd_apply_packet_yaml_sidecar_migration,
    _cmd_validate_evidence_contract,
    _cmd_validate_evidence_manifest,
)
from prefect_grace.cli_commands.executors import (
    _cmd_list_executors,
    _cmd_select_executor,
    _cmd_synthetic_edge_matrix,
)
from prefect_grace.cli_commands.git_mutation import (
    _cmd_git_mutation_gate,
    _cmd_packet_branch_push_gate,
    _cmd_merge_steward,
)
from prefect_grace.cli_commands.git_sync import _cmd_git_sync
from prefect_grace.cli_commands.init import _cmd_init
from prefect_grace.cli_commands.prefect_worker_binding import (
    _cmd_prefect_worker_binding,
)
from prefect_grace.cli_commands.brief_intake import (
    _cmd_dynamic_plan,
)


class NoDryRunAction(argparse.Action):
    """Custom action for --no-dry-run to track explicit usage."""
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, False)
        setattr(namespace, '_no_dry_run_explicit', True)


def _audit_limit(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return parsed


def _register_legacy_feature_commands(subparsers) -> None:
    feature = subparsers.add_parser("feature")
    feature.add_argument("feature_id")
    feature.add_argument("title")
    feature.add_argument("summary")
    feature.set_defaults(func=_cmd_feature)

    mark_feature = subparsers.add_parser("mark-feature")
    mark_feature.add_argument("feature_id")
    mark_feature.add_argument("status", choices=[item.value for item in FeatureStatus])
    mark_feature.set_defaults(func=_cmd_mark_feature)

    packet = subparsers.add_parser("packet")
    packet.add_argument("feature_id")
    packet.add_argument("wave_id")
    packet.add_argument("title")
    packet.add_argument("summary")
    packet.add_argument("--role", default="coder")
    packet.add_argument("--reasoning", choices=[item.value for item in ReasoningProfile], default=ReasoningProfile.HIGH.value)
    packet.set_defaults(func=_cmd_packet)

    run_codex = subparsers.add_parser("run-codex")
    run_codex.add_argument("packet_id")
    run_codex.add_argument("--dry-run", action="store_true")
    run_codex.add_argument("--timeout-seconds", type=int, default=3600)
    run_codex.set_defaults(func=_cmd_run_codex)

    run_verifier = subparsers.add_parser("run-verifier")
    run_verifier.add_argument("packet_id")
    run_verifier.add_argument("--dry-run", action="store_true")
    run_verifier.add_argument("--timeout-seconds", type=int, default=3600)
    run_verifier.set_defaults(func=_cmd_run_verifier)

    test_feature = subparsers.add_parser("test-feature")
    test_feature.add_argument("feature_id")
    test_feature.add_argument("title")
    test_feature.add_argument("summary")
    test_feature.add_argument(
        "--implementation-title",
        default="Test Implementation Packet",
    )
    test_feature.add_argument(
        "--implementation-summary",
        default="Run a bounded end-to-end test feature through architect, planner, coder, verifier, and reviewer packets.",
    )
    test_feature.add_argument(
        "--reviewer-verdict",
        choices=[item.value for item in ReviewVerdict],
    )
    test_feature.add_argument("--review-reason", action="append")
    test_feature.add_argument("--skip-backend-quick", action="store_true")
    test_feature.add_argument("--backend-profile")
    test_feature.add_argument("--touches-frontend", action="store_true")
    test_feature.add_argument("--frontend-profile")
    test_feature.add_argument("--frontend-command", action="append")
    test_feature.add_argument("--observability-profile")
    test_feature.add_argument("--observability-command", action="append")
    test_feature.add_argument("--artifact-glob", action="append")
    test_feature.add_argument("--include-day-live-canary", action="store_true")
    test_feature.add_argument("--agent-workdir")
    test_feature.add_argument("--agent-sandbox")
    test_feature.add_argument("--commit-hash")
    test_feature.add_argument("--planner-contract")
    test_feature.add_argument("--run-planner", action="store_true")
    test_feature.add_argument("--reviewer-verdict-script", action="append")
    test_feature.add_argument("--review-reasons-script", action="append")
    test_feature.add_argument("--wave-verdict-script", action="append")
    test_feature.add_argument("--wave-reasons-script", action="append")
    test_feature.add_argument(
        "--verifier-test-verdict",
        choices=[item.value for item in TestVerdict],
    )
    test_feature.add_argument(
        "--verifier-observability-verdict",
        choices=[item.value for item in ObservabilityVerdict],
    )
    test_feature.add_argument(
        "--verifier-frontend-visual-verdict",
        choices=[item.value for item in FrontendVisualVerdict],
    )
    test_feature.add_argument("--verifier-command", action="append")
    test_feature.add_argument("--verifier-evidence", action="append")
    test_feature.add_argument("--verifier-issue", action="append")
    test_feature.add_argument(
        "--wave-verdict",
        choices=[item.value for item in WaveVerdict],
    )
    test_feature.add_argument("--wave-reason", action="append")
    test_feature.add_argument("--no-create-rework", action="store_true")
    test_feature.add_argument("--parse-agent-output", action="store_true")
    test_feature.add_argument("--timeout-seconds", type=int, default=3600)
    test_feature.add_argument("--execute", action="store_true")
    test_feature.set_defaults(func=_cmd_test_feature)

    submit_feature = subparsers.add_parser("submit-feature")
    submit_feature.add_argument("feature_id")
    submit_feature.add_argument("title")
    submit_feature.add_argument("summary")
    submit_feature.add_argument(
        "--implementation-title",
        default="Live Implementation Packet",
    )
    submit_feature.add_argument(
        "--implementation-summary",
        default="Execute the feature through architect, planner, coder, verifier, reviewer, and architect wave gate.",
    )
    submit_feature.add_argument("--skip-backend-quick", action="store_true")
    submit_feature.add_argument("--backend-profile")
    submit_feature.add_argument("--touches-frontend", action="store_true")
    submit_feature.add_argument("--frontend-profile")
    submit_feature.add_argument("--frontend-command", action="append")
    submit_feature.add_argument("--observability-profile")
    submit_feature.add_argument("--observability-command", action="append")
    submit_feature.add_argument("--artifact-glob", action="append")
    submit_feature.add_argument("--include-day-live-canary", action="store_true")
    submit_feature.add_argument("--agent-workdir")
    submit_feature.add_argument("--agent-sandbox")
    submit_feature.add_argument("--commit-hash")
    submit_feature.add_argument("--run-planner", action="store_true")
    submit_feature.add_argument("--timeout-seconds", type=int, default=7200)
    submit_feature.add_argument("--scheduled-for")
    submit_feature.add_argument("--delay-minutes", type=int)
    submit_feature.add_argument("--execute", action="store_true")
    submit_feature.set_defaults(func=_cmd_submit_feature)

    submit_brief = subparsers.add_parser("submit-brief")
    submit_brief.add_argument("path")
    submit_brief.add_argument("--scheduled-for")
    submit_brief.add_argument("--delay-minutes", type=int)
    submit_brief.set_defaults(func=_cmd_submit_brief)

    print_brief_template = subparsers.add_parser("print-brief-template")
    print_brief_template.set_defaults(func=_cmd_print_brief_template)

    queue = subparsers.add_parser("queue")
    queue.add_argument("--limit", type=int, default=20)
    queue.set_defaults(func=_cmd_queue)

    dashboard = subparsers.add_parser("dashboard")
    dashboard.add_argument("--json", action="store_true")
    dashboard.set_defaults(func=_cmd_dashboard)


def _register_project_registry_commands(subparsers) -> None:
    validate_project = subparsers.add_parser("validate-project")
    validate_project.add_argument("--project")
    validate_project.add_argument("--json", action="store_true")
    validate_project.set_defaults(func=_cmd_validate_project)

    scan_packets = subparsers.add_parser("scan-packets")
    scan_packets.add_argument("--project")
    scan_packets.add_argument("--mode", choices=["legacy_warn", "strict"], default="legacy_warn")
    scan_packets.add_argument("--json", action="store_true")
    scan_packets.set_defaults(func=_cmd_scan_packets)

    validate_packet = subparsers.add_parser("validate-packet")
    validate_packet.add_argument("path")
    validate_packet.add_argument("--strict", action="store_true")
    validate_packet.add_argument("--json", action="store_true")
    validate_packet.set_defaults(func=_cmd_validate_packet)

    sync_packets = subparsers.add_parser("sync-packets")
    sync_packets.add_argument("--project")
    sync_packets.add_argument("--dry-run", action="store_true")
    sync_packets.add_argument("--retry-blocked", action="store_true")
    sync_packets.add_argument("--rerun-changed", action="store_true")
    sync_packets.add_argument("--json", action="store_true")
    sync_packets.set_defaults(func=_cmd_sync_packets)

    bootstrap_backlog = subparsers.add_parser("bootstrap-backlog")
    bootstrap_backlog.add_argument("--project", "--project-config", dest="project")
    bootstrap_mode = bootstrap_backlog.add_mutually_exclusive_group()
    bootstrap_mode.add_argument("--dry-run", action="store_true")
    bootstrap_mode.add_argument("--apply", action="store_true")
    bootstrap_backlog.add_argument("--json", action="store_true")
    bootstrap_backlog.set_defaults(func=_cmd_bootstrap_backlog)

    registry_bootstrap_apply = subparsers.add_parser("registry-bootstrap-apply")
    registry_bootstrap_apply.add_argument("--project", "--project-config", dest="project", required=True)
    registry_bootstrap_apply.add_argument("--packet-id", action="append", default=[])
    registry_bootstrap_mode = registry_bootstrap_apply.add_mutually_exclusive_group()
    registry_bootstrap_mode.add_argument("--dry-run", action="store_true", default=True)
    registry_bootstrap_mode.add_argument("--apply", action="store_true")
    registry_bootstrap_apply.add_argument("--json", action="store_true")
    registry_bootstrap_apply.set_defaults(func=_cmd_registry_bootstrap_apply)

    packet_status = subparsers.add_parser("packet-status")
    packet_status.add_argument("--project")
    packet_status.add_argument("--packet-id", required=True)
    packet_status.add_argument("--json", action="store_true")
    packet_status.set_defaults(func=_cmd_packet_status)

    registry_dump = subparsers.add_parser("registry-dump")
    registry_dump.add_argument("--project")
    registry_dump.add_argument("--json", action="store_true")
    registry_dump.set_defaults(func=_cmd_registry_dump)


def _register_packet_submission_commands(subparsers) -> None:
    submit_packets = subparsers.add_parser("submit-packets")
    submit_packets.add_argument("--project", "--project-config", dest="project")
    submit_packets.add_argument("--runner", choices=["e2e", "managed"], default="e2e")
    submit_packets.add_argument("--execute", action="store_true")
    submit_packets.add_argument("--dry-run", dest="execute", action="store_false")
    submit_packets.add_argument("--limit", type=int)
    submit_packets.add_argument("--base-ref", default="HEAD")
    submit_packets.add_argument("--timeout-seconds", type=int, default=3600)
    submit_packets.add_argument("--continue-on-error", action="store_true")
    submit_packets.add_argument("--json", action="store_true")
    submit_packets.set_defaults(func=_cmd_submit_packets)


def _register_prefect_smokes_commands(subparsers) -> None:
    registry_apply_smoke = subparsers.add_parser("registry-apply-smoke")
    registry_apply_smoke.add_argument("--project", required=True)
    registry_apply_smoke.add_argument("--state-root", required=True)
    registry_apply_smoke.add_argument("--packet-root")
    registry_apply_smoke.add_argument("--json", action="store_true")
    registry_apply_smoke.set_defaults(func=_cmd_registry_apply_smoke)

    registry_source_integrity_audit = subparsers.add_parser("registry-source-integrity-audit")
    registry_source_integrity_audit.add_argument("--project", "--project-config", dest="project", required=True)
    registry_source_integrity_audit.add_argument("--max-items", type=int, default=50)
    registry_source_integrity_audit.add_argument("--json", action="store_true")
    registry_source_integrity_audit.set_defaults(func=_cmd_registry_source_integrity_audit)

    e2e_registry_seeded_smoke = subparsers.add_parser("run-e2e-registry-seeded-smoke")
    e2e_registry_seeded_smoke.add_argument("--project", required=True)
    e2e_registry_seeded_smoke.add_argument("--state-root", required=True)
    e2e_registry_seeded_smoke.add_argument("--worktree-root", required=True)
    e2e_registry_seeded_smoke.add_argument("--packet-root", required=True)
    e2e_registry_seeded_smoke.add_argument("--json", action="store_true")
    e2e_registry_seeded_smoke.set_defaults(func=_cmd_run_e2e_registry_seeded_smoke)

    run_prefect_e2e_live_smoke = subparsers.add_parser("run-prefect-e2e-live-smoke", help="Run a controlled Prefect E2E live smoke")
    run_prefect_e2e_live_smoke.add_argument("--project-config", required=True, help="Project config path")
    run_prefect_e2e_live_smoke.add_argument("--state-root", required=True, help="Smoke state root")
    run_prefect_e2e_live_smoke.add_argument("--worktree-root", required=True, help="Smoke worktree root")
    run_prefect_e2e_live_smoke.add_argument("--packet-root", required=True, help="Smoke packet root")
    run_prefect_e2e_live_smoke.add_argument("--dry-run", dest="dry_run", action="store_true", default=True, help="Agent dry-run mode (default)")
    run_prefect_e2e_live_smoke.add_argument("--no-dry-run", dest="dry_run", action=NoDryRunAction, nargs=0, help="Disable agent dry-run")
    run_prefect_e2e_live_smoke.add_argument("--execute-agent", action="store_true", help="Enable live agent execution")
    run_prefect_e2e_live_smoke.add_argument("--allow-live-agent-smoke", action="store_true", help="Allow one-packet live agent smoke")
    run_prefect_e2e_live_smoke.add_argument("--offline-fake-submitter", action="store_true", help="Use fake submitter for offline validation")
    run_prefect_e2e_live_smoke.add_argument("--limit", type=int, default=1, help="Submission limit (must be 1)")
    run_prefect_e2e_live_smoke.add_argument("--json", action="store_true", help="JSON output")
    run_prefect_e2e_live_smoke.set_defaults(func=_cmd_run_prefect_e2e_live_smoke)

    run_prefect_e2e_batch_smoke = subparsers.add_parser("run-prefect-e2e-batch-smoke", help="Run a bounded Prefect E2E batch queue smoke")
    run_prefect_e2e_batch_smoke.add_argument("--project-config", required=True, help="Project config path")
    run_prefect_e2e_batch_smoke.add_argument("--state-root", required=True, help="Smoke state root")
    run_prefect_e2e_batch_smoke.add_argument("--worktree-root", required=True, help="Smoke worktree root")
    run_prefect_e2e_batch_smoke.add_argument("--packet-root", required=True, help="Smoke packet root")
    run_prefect_e2e_batch_smoke.add_argument("--batch-size", type=int, default=2, help="Batch size, must be 2 or 3")
    run_prefect_e2e_batch_smoke.add_argument("--execute-agent", action="store_true", help="Rejected in batch smoke mode")
    run_prefect_e2e_batch_smoke.add_argument("--offline-fake-submitter", action="store_true", help="Use fake submitter for offline validation")
    run_prefect_e2e_batch_smoke.add_argument("--json", action="store_true", help="JSON output")
    run_prefect_e2e_batch_smoke.set_defaults(func=_cmd_run_prefect_e2e_batch_smoke)

    run_prefect_e2e_real_dry_run_smoke = subparsers.add_parser(
        "run-prefect-e2e-real-dry-run-smoke",
        help="Run one real Prefect E2E dry-run smoke",
    )
    run_prefect_e2e_real_dry_run_smoke.add_argument("--project-config", required=True, help="Project config path")
    run_prefect_e2e_real_dry_run_smoke.add_argument("--state-root", required=True, help="Smoke state root")
    run_prefect_e2e_real_dry_run_smoke.add_argument("--worktree-root", required=True, help="Smoke worktree root")
    run_prefect_e2e_real_dry_run_smoke.add_argument("--packet-root", required=True, help="Smoke packet root")
    run_prefect_e2e_real_dry_run_smoke.add_argument("--timeout-seconds", type=int, default=900, help="Wait timeout seconds")
    run_prefect_e2e_real_dry_run_smoke.add_argument("--poll-interval-seconds", type=int, default=5, help="Wait poll interval seconds")
    run_prefect_e2e_real_dry_run_smoke.add_argument("--no-wait", action="store_true", help="Only verify Prefect flow run creation")
    run_prefect_e2e_real_dry_run_smoke.add_argument("--execute-agent", action="store_true", help="Rejected in real dry-run smoke mode")
    run_prefect_e2e_real_dry_run_smoke.add_argument("--json", action="store_true", help="JSON output")
    run_prefect_e2e_real_dry_run_smoke.set_defaults(func=_cmd_run_prefect_e2e_real_dry_run_smoke)

    run_nightly = subparsers.add_parser("run-nightly")
    run_nightly.add_argument("--project")
    run_nightly.add_argument("--dry-run", action="store_true", default=True)
    run_nightly.add_argument("--execute", action="store_true")
    run_nightly.add_argument("--until-blocked", action="store_true")
    run_nightly.add_argument("--json", action="store_true")
    run_nightly.set_defaults(func=_cmd_run_nightly)

    nightly_preflight_risk_report = subparsers.add_parser("nightly-preflight-risk-report")
    nightly_preflight_risk_report.add_argument("--project")
    nightly_preflight_risk_report.add_argument("--json", action="store_true")
    nightly_preflight_risk_report.set_defaults(func=_cmd_nightly_preflight_risk_report)

    nightly_select_batch = subparsers.add_parser("nightly-select-batch")
    nightly_select_batch.add_argument("--project")
    nightly_select_batch.add_argument("--preflight-report", help="Path to saved preflight report JSON")
    nightly_select_batch.add_argument("--max-packets", type=int, default=10, help="Maximum packets to select")
    nightly_select_batch.add_argument("--max-cost", default="live_required", help="Maximum cost level")
    nightly_select_batch.add_argument("--allow-conflicts", action="store_true", help="Allow file conflicts")
    nightly_select_batch.add_argument("--allow-risky", action="store_true", help="Allow risky packets")
    nightly_select_batch.add_argument("--json", action="store_true")
    nightly_select_batch.set_defaults(func=_cmd_nightly_select_batch)

    nightly_recheck_batch = subparsers.add_parser("nightly-recheck-batch")
    nightly_recheck_batch.add_argument("--project")
    nightly_recheck_batch.add_argument("--selection", help="Path to saved nightly selection JSON")
    nightly_recheck_batch.add_argument("--max-packets", type=int, default=10, help="Current maximum packets")
    nightly_recheck_batch.add_argument("--max-cost", default="live_required", help="Current maximum cost level")
    nightly_recheck_batch.add_argument("--allow-conflicts", action="store_true", help="Allow conflicts when generating selection")
    nightly_recheck_batch.add_argument("--allow-risky", action="store_true", help="Allow risky packets when generating selection")
    nightly_recheck_batch.add_argument("--json", action="store_true")
    nightly_recheck_batch.set_defaults(func=_cmd_nightly_recheck_batch)

    nightly_batch_execute = subparsers.add_parser("nightly-batch-execute")
    nightly_batch_execute.add_argument("--project")
    nightly_batch_execute.add_argument("--max-packets", type=int, default=10, help="Maximum packets to execute")
    nightly_batch_execute.add_argument("--concurrency", type=int, default=1, help="Maximum concurrent executions")
    nightly_batch_execute.add_argument("--timeout-seconds-per-packet", type=int, default=3600, help="Timeout per packet")
    nightly_batch_execute.add_argument("--max-failures", type=int, default=3, help="Stop after this many failures")
    nightly_batch_execute.add_argument("--no-stop-on-degradation", action="store_true", help="Do not stop on degradation")
    nightly_batch_execute.add_argument("--allow-git-commit", action="store_true", help="Request guarded commit")
    nightly_batch_execute.add_argument("--allow-git-push", action="store_true", help="Request guarded push")
    nightly_batch_execute.add_argument("--base-ref", default="origin/master", help="Git base reference")
    nightly_batch_execute.add_argument("--target-branch", default="master", help="Target branch")
    nightly_batch_execute.add_argument("--remote", default="origin", help="Remote name")
    nightly_batch_execute.add_argument("--dry-run", action="store_true", default=True, help="Dry run mode (default)")
    nightly_batch_execute.add_argument("--execute", action="store_true", help="Execute packets (requires opt-in)")
    nightly_batch_execute.add_argument("--i-understand-live-batch", action="store_true", help="Required for live execution")
    nightly_batch_execute.add_argument("--json", action="store_true")
    nightly_batch_execute.set_defaults(func=_cmd_nightly_batch_execute)

    run_nightly_controlled_batch = subparsers.add_parser("run-nightly-controlled-batch")
    run_nightly_controlled_batch.add_argument("--project")
    run_nightly_controlled_batch.add_argument("--selection", help="Path to saved nightly selection JSON")
    run_nightly_controlled_batch.add_argument("--max-packets", type=int, default=3, help="Maximum packets to execute")
    run_nightly_controlled_batch.add_argument("--concurrency", type=int, default=1, help="Must be 1 for controlled batch")
    run_nightly_controlled_batch.add_argument("--timeout-seconds-per-packet", type=int, default=1800, help="Bounded timeout per packet")
    run_nightly_controlled_batch.add_argument("--max-failures", type=int, default=1, help="Stop after this many failures")
    run_nightly_controlled_batch.add_argument("--no-stop-on-degradation", action="store_true", help="Do not stop on unexpected degradation")
    run_nightly_controlled_batch.add_argument("--allow-git-commit", action="store_true", help="Delegate guarded packet branch commit")
    run_nightly_controlled_batch.add_argument("--allow-git-push", action="store_true", help="Delegate guarded packet branch push")
    controlled_mode = run_nightly_controlled_batch.add_mutually_exclusive_group()
    controlled_mode.add_argument("--dry-run", action="store_true", default=True, help="Dry run mode (default)")
    controlled_mode.add_argument("--execute", action="store_true", help="Execute packets (requires all live gates)")
    run_nightly_controlled_batch.add_argument("--i-understand-live-batch", action="store_true", help="Required for live execution")
    run_nightly_controlled_batch.add_argument("--json", action="store_true")
    run_nightly_controlled_batch.set_defaults(func=_cmd_run_nightly_controlled_batch)


def _register_worktrees_commands(subparsers) -> None:
    worktree_create = subparsers.add_parser("worktree-create", help="Create worktree for packet")
    worktree_create.add_argument("--repo-root", type=Path, required=True, help="Repository root")
    worktree_create.add_argument("--worktree-root", type=Path, required=True, help="Worktree root directory")
    worktree_create.add_argument("--project-key", required=True, help="Project key")
    worktree_create.add_argument("--packet-id", required=True, help="Packet ID")
    worktree_create.add_argument("--attempt", type=int, required=True, help="Attempt number")
    worktree_create.add_argument("--base-ref", required=True, help="Base git ref")
    worktree_create.add_argument("--json", action="store_true", help="JSON output")
    worktree_create.set_defaults(func=_cmd_worktree_create)

    worktree_status = subparsers.add_parser("worktree-status", help="Get worktree status")
    worktree_status.add_argument("--repo-root", type=Path, required=True, help="Repository root")
    worktree_status.add_argument("--worktree-root", type=Path, required=True, help="Worktree root directory")
    worktree_status.add_argument("--project-key", required=True, help="Project key")
    worktree_status.add_argument("--packet-id", required=True, help="Packet ID")
    worktree_status.add_argument("--attempt", type=int, required=True, help="Attempt number")
    worktree_status.add_argument("--json", action="store_true", help="JSON output")
    worktree_status.set_defaults(func=_cmd_worktree_status)

    worktree_cleanup = subparsers.add_parser("worktree-cleanup", help="Clean up worktree")
    worktree_cleanup.add_argument("--repo-root", type=Path, required=True, help="Repository root")
    worktree_cleanup.add_argument("--worktree-root", type=Path, required=True, help="Worktree root directory")
    worktree_cleanup.add_argument("--project-key", required=True, help="Project key")
    worktree_cleanup.add_argument("--packet-id", required=True, help="Packet ID")
    worktree_cleanup.add_argument("--attempt", type=int, required=True, help="Attempt number")
    worktree_cleanup.add_argument("--keep-on-failure", action="store_true", help="Keep worktree if dirty")
    worktree_cleanup.add_argument("--json", action="store_true", help="JSON output")
    worktree_cleanup.set_defaults(func=_cmd_worktree_cleanup)

    worktree_scope_check = subparsers.add_parser("worktree-scope-check", help="Evaluate worktree scope lifecycle gate")
    worktree_scope_check.add_argument("--packet", type=Path, required=True, help="Path to EXECUTION_PACKET.md")
    worktree_scope_check.add_argument("--repo-root", type=Path, required=True, help="Repository root")
    worktree_scope_check.add_argument("--worktree-root", type=Path, required=True, help="Worktree root directory")
    worktree_scope_check.add_argument("--project-key", required=True, help="Project key")
    worktree_scope_check.add_argument("--packet-id", required=True, help="Packet ID")
    worktree_scope_check.add_argument("--attempt", type=int, required=True, help="Attempt number")
    worktree_scope_check.add_argument("--base-ref", required=True, help="Base git ref")
    worktree_scope_check.add_argument("--keep-on-failure", action="store_true", default=True, help="Keep worktree on block/error (default: true)")
    worktree_scope_check.add_argument("--json", action="store_true", help="JSON output")
    worktree_scope_check.set_defaults(func=_cmd_worktree_scope_check)

    run_worktree_scope_flow = subparsers.add_parser("run-worktree-scope-flow", help="Run worktree scope lifecycle Prefect flow")
    run_worktree_scope_flow.add_argument("--packet", type=Path, required=True, help="Path to EXECUTION_PACKET.md")
    run_worktree_scope_flow.add_argument("--repo-root", type=Path, required=True, help="Repository root")
    run_worktree_scope_flow.add_argument("--worktree-root", type=Path, required=True, help="Worktree root directory")
    run_worktree_scope_flow.add_argument("--project-key", required=True, help="Project key")
    run_worktree_scope_flow.add_argument("--packet-id", required=True, help="Packet ID")
    run_worktree_scope_flow.add_argument("--attempt", type=int, required=True, help="Attempt number")
    run_worktree_scope_flow.add_argument("--base-ref", required=True, help="Base git ref")
    run_worktree_scope_flow.add_argument("--keep-on-failure", action="store_true", default=True, help="Keep worktree on block/error (default: true)")
    run_worktree_scope_flow.add_argument("--json", action="store_true", help="JSON output")
    run_worktree_scope_flow.set_defaults(func=_cmd_run_worktree_scope_flow)


def _register_packet_execution_commands(subparsers) -> None:
    run_managed_packet = subparsers.add_parser("run-managed-packet", help="Run managed packet execution with worktree isolation")
    run_managed_packet.add_argument("--packet", type=Path, required=True, help="Path to EXECUTION_PACKET.md")
    run_managed_packet.add_argument("--repo-root", type=Path, required=True, help="Repository root")
    run_managed_packet.add_argument("--worktree-root", type=Path, required=True, help="Worktree root directory")
    run_managed_packet.add_argument("--project-key", required=True, help="Project key")
    run_managed_packet.add_argument("--packet-id", required=True, help="Packet ID")
    run_managed_packet.add_argument("--attempt", type=int, required=True, help="Attempt number")
    run_managed_packet.add_argument("--base-ref", required=True, help="Base git ref")
    run_managed_packet.add_argument("--dry-run", action="store_true", default=True, help="Dry run mode (no agent execution, default)")
    run_managed_packet.add_argument("--no-dry-run", dest="dry_run", action=NoDryRunAction, nargs=0, help="Disable dry run (required with --execute-agent)")
    run_managed_packet.add_argument("--execute-agent", action="store_true", help="Explicitly allow live agent execution")
    run_managed_packet.add_argument("--timeout-seconds", type=int, default=3600, help="Agent timeout in seconds")
    run_managed_packet.add_argument("--keep-worktree", action="store_true", default=True, help="Keep worktree after execution (default: true)")
    run_managed_packet.add_argument("--json", action="store_true", help="JSON output")
    run_managed_packet.set_defaults(func=_cmd_run_managed_packet)

    run_e2e_packet = subparsers.add_parser("run-e2e-packet", help="Run end-to-end packet execution")
    run_e2e_packet.add_argument("--project-root", type=Path, required=True, help="Project root directory")
    run_e2e_packet.add_argument("--packet", type=Path, required=True, help="Path to EXECUTION_PACKET.md")
    run_e2e_packet.add_argument("--state-root", type=Path, required=True, help="State root directory")
    run_e2e_packet.add_argument("--worktree-root", type=Path, required=True, help="Worktree root directory")
    run_e2e_packet.add_argument("--project-key", default="default", help="Project key (default: default)")
    run_e2e_packet.add_argument("--attempt", type=int, default=1, help="Attempt number (default: 1)")
    run_e2e_packet.add_argument("--base-ref", default="HEAD", help="Git base ref (default: HEAD)")
    run_e2e_packet.add_argument("--dry-run", action="store_true", default=True, help="Dry run mode (default: true)")
    run_e2e_packet.add_argument("--no-dry-run", dest="dry_run", action=NoDryRunAction, nargs=0, help="Disable dry run")
    run_e2e_packet.add_argument("--execute-agent", action="store_true", help="Execute live agent (requires --no-dry-run)")
    run_e2e_packet.add_argument("--fake-verifier-output", type=Path, help="Path to fake verifier output file")
    run_e2e_packet.add_argument("--fake-reviewer-output", type=Path, help="Path to fake reviewer output file")
    run_e2e_packet.add_argument("--timeout-seconds", type=int, default=3600, help="Agent timeout in seconds (default: 3600)")
    run_e2e_packet.add_argument("--keep-worktree", action="store_true", default=True, help="Keep worktree after execution (default: true)")
    run_e2e_packet.add_argument("--json", action="store_true", help="JSON output")
    run_e2e_packet.set_defaults(func=_cmd_run_e2e_packet)

    run_e2e_packet_flow = subparsers.add_parser("run-e2e-packet-flow", help="Run end-to-end packet execution through Prefect flow")
    run_e2e_packet_flow.add_argument("--project-root", type=Path, required=True, help="Project root directory")
    run_e2e_packet_flow.add_argument("--packet", type=Path, required=True, help="Path to EXECUTION_PACKET.md")
    run_e2e_packet_flow.add_argument("--state-root", type=Path, required=True, help="State root directory")
    run_e2e_packet_flow.add_argument("--worktree-root", type=Path, required=True, help="Worktree root directory")
    run_e2e_packet_flow.add_argument("--project-key", required=True, help="Project key")
    run_e2e_packet_flow.add_argument("--packet-id", required=True, help="Packet ID")
    run_e2e_packet_flow.add_argument("--attempt", type=int, default=1, help="Attempt number (default: 1)")
    run_e2e_packet_flow.add_argument("--base-ref", default="HEAD", help="Git base ref (default: HEAD)")
    run_e2e_packet_flow.add_argument("--dry-run", action="store_true", default=True, help="Dry run mode (default: true)")
    run_e2e_packet_flow.add_argument("--no-dry-run", dest="dry_run", action=NoDryRunAction, nargs=0, help="Disable dry run")
    run_e2e_packet_flow.add_argument("--execute-agent", action="store_true", help="Execute live agent (requires --no-dry-run)")
    run_e2e_packet_flow.add_argument("--fake-verifier-output", type=Path, help="Path to fake verifier output file")
    run_e2e_packet_flow.add_argument("--fake-reviewer-output", type=Path, help="Path to fake reviewer output file")
    run_e2e_packet_flow.add_argument("--timeout-seconds", type=int, default=3600, help="Agent timeout in seconds (default: 3600)")
    run_e2e_packet_flow.add_argument("--keep-worktree", action="store_true", default=True, help="Keep worktree after execution (default: true)")
    run_e2e_packet_flow.add_argument("--json", action="store_true", help="JSON output")
    run_e2e_packet_flow.set_defaults(func=_cmd_run_e2e_packet_flow)

    run_handoff = subparsers.add_parser("run-handoff", help="Run verifier-reviewer handoff")
    run_handoff.add_argument("--packet-dir", type=Path, required=True, help="Path to packet directory")
    run_handoff.add_argument("--packet", type=Path, required=True, help="Path to EXECUTION_PACKET.md")
    run_handoff.add_argument("--attempt", type=int, required=True, help="Attempt number")
    run_handoff.add_argument("--coder-result", type=Path, required=True, help="Path to coder result JSON file")
    run_handoff.add_argument("--dry-run", action="store_true", default=True, help="Dry run mode (default: true)")
    run_handoff.add_argument("--fake-verifier-output", type=Path, help="Path to fake verifier output file (required in dry-run)")
    run_handoff.add_argument("--fake-reviewer-output", type=Path, help="Path to fake reviewer output file (required in dry-run)")
    run_handoff.add_argument("--json", action="store_true", help="JSON output")
    run_handoff.set_defaults(func=_cmd_run_handoff)

    run_single_live_packet_pilot = subparsers.add_parser("run-single-live-packet-pilot", help="Run single live packet pilot with managed runner and Git mutation gate")
    run_single_live_packet_pilot.add_argument("--packet", type=Path, required=True, help="Path to EXECUTION_PACKET.md")
    run_single_live_packet_pilot.add_argument("--repo-root", type=Path, required=True, help="Repository root")
    run_single_live_packet_pilot.add_argument("--worktree-root", type=Path, required=True, help="Worktree root directory")
    run_single_live_packet_pilot.add_argument("--project-key", required=True, help="Project key")
    run_single_live_packet_pilot.add_argument("--attempt", type=int, default=1, help="Attempt number (default: 1)")
    run_single_live_packet_pilot.add_argument("--base-ref", required=True, help="Base git ref")
    run_single_live_packet_pilot.add_argument("--target-branch", required=True, help="Target branch for merge (not used in pilot)")
    run_single_live_packet_pilot.add_argument("--remote", default="origin", help="Remote name for push (default: origin)")
    run_single_live_packet_pilot.add_argument("--dry-run", action="store_true", default=True, help="Dry run mode (no agent execution, no Git mutations, default)")
    run_single_live_packet_pilot.add_argument("--no-dry-run", dest="dry_run", action=NoDryRunAction, nargs=0, help="Disable dry run (required with --execute-agent)")
    run_single_live_packet_pilot.add_argument("--execute-agent", action="store_true", help="Explicitly allow live agent execution")
    run_single_live_packet_pilot.add_argument("--i-understand-live-agent", action="store_true", help="Required acknowledgement for live agent execution")
    run_single_live_packet_pilot.add_argument("--commit", action="store_true", help="Request guarded commit")
    run_single_live_packet_pilot.add_argument("--push", action="store_true", help="Request guarded push")
    run_single_live_packet_pilot.add_argument("--merge", action="store_true", help="Request guarded merge to target branch")
    run_single_live_packet_pilot.add_argument("--apply-git-mutations", action="store_true", help="Allow Git mutations to be applied (requires evidence and review)")
    run_single_live_packet_pilot.add_argument("--timeout-seconds", type=int, default=3600, help="Agent timeout in seconds (default: 3600)")
    run_single_live_packet_pilot.add_argument("--json", action="store_true", help="JSON output")
    run_single_live_packet_pilot.set_defaults(func=_cmd_run_single_live_packet_pilot)

    run_single_live_prefect_packet_pilot = subparsers.add_parser(
        "run-single-live-prefect-packet-pilot",
        help="Run one synthetic scratch packet through managed Prefect submission",
    )
    run_single_live_prefect_packet_pilot.add_argument("--project", required=True, help="Project config path")
    run_single_live_prefect_packet_pilot.add_argument("--state-root", type=Path, required=True, help="Pilot state root")
    run_single_live_prefect_packet_pilot.add_argument("--worktree-root", type=Path, required=True, help="Pilot worktree root")
    run_single_live_prefect_packet_pilot.add_argument("--packet-root", type=Path, required=True, help="Synthetic packet root")
    run_single_live_prefect_packet_pilot.add_argument("--dry-run", action="store_true", default=True, help="Plan only, default")
    run_single_live_prefect_packet_pilot.add_argument("--no-dry-run", dest="dry_run", action=NoDryRunAction, nargs=0, help="Disable dry run")
    run_single_live_prefect_packet_pilot.add_argument("--execute-agent", action="store_true", help="Allow live managed runner agent execution")
    run_single_live_prefect_packet_pilot.add_argument("--i-understand-live-agent", action="store_true", help="Required live-agent acknowledgement gate")
    run_single_live_prefect_packet_pilot.add_argument("--timeout-seconds", type=int, default=1800, help="Submission/status timeout seconds")
    run_single_live_prefect_packet_pilot.add_argument("--json", action="store_true", help="JSON output")
    run_single_live_prefect_packet_pilot.set_defaults(func=_cmd_run_single_live_prefect_packet_pilot)

    run_single_astro_packet_pilot = subparsers.add_parser(
        "run-single-astro-packet-pilot",
        help="Run one low-risk Astro packet through managed Prefect submission",
    )
    run_single_astro_packet_pilot.add_argument("--project", required=True, help="Project config path")
    run_single_astro_packet_pilot.add_argument("--state-root", type=Path, required=True, help="Pilot state root")
    run_single_astro_packet_pilot.add_argument("--worktree-root", type=Path, required=True, help="Pilot worktree root")
    run_single_astro_packet_pilot.add_argument("--packet-root", type=Path, required=True, help="Pilot packet temp root")
    run_single_astro_packet_pilot.add_argument("--packet", help="Explicit packet ID to select")
    run_single_astro_packet_pilot.add_argument("--dry-run", action="store_true", default=True, help="Plan only, default")
    run_single_astro_packet_pilot.add_argument("--no-dry-run", dest="dry_run", action=NoDryRunAction, nargs=0, help="Disable dry run")
    run_single_astro_packet_pilot.add_argument("--execute-agent", action="store_true", help="Allow live managed runner agent execution")
    run_single_astro_packet_pilot.add_argument("--i-understand-live-agent", action="store_true", help="Required live-agent acknowledgement gate")
    run_single_astro_packet_pilot.add_argument("--timeout-seconds", type=int, default=1800, help="Submission/status timeout seconds")
    run_single_astro_packet_pilot.add_argument("--json", action="store_true", help="JSON output")
    run_single_astro_packet_pilot.set_defaults(func=_cmd_run_single_astro_packet_pilot)


def _register_evidence_commands(subparsers) -> None:
    review = subparsers.add_parser("review")
    review.add_argument("packet_id")
    review.add_argument("verdict", choices=[item.value for item in ReviewVerdict])
    review.add_argument("--reason", action="append")
    review.add_argument("--follow-up-action", default="none")
    review.add_argument("--create-rework", action="store_true")
    review.set_defaults(func=_cmd_review)

    write_review = subparsers.add_parser("write-review")
    write_review.add_argument("packet_dir")
    write_review.add_argument("--verdict", required=True, choices=["accepted", "rework_required", "blocked"])
    write_review.add_argument("--body", help="Path to review body file")
    write_review.add_argument("--body-text", help="Review body text (alternative to --body)")
    write_review.add_argument("--reviewer", help="Reviewer name")
    write_review.add_argument("--json", action="store_true")
    write_review.set_defaults(func=_cmd_write_review)

    write_evidence = subparsers.add_parser("write-evidence")
    write_evidence.add_argument("packet_dir")
    write_evidence.add_argument("--attempt", type=int, required=True)
    write_evidence.add_argument("--manifest", required=True, help="Path to evidence manifest JSON file")
    write_evidence.add_argument("--json", action="store_true")
    write_evidence.set_defaults(func=_cmd_write_evidence)

    write_rework = subparsers.add_parser("write-rework")
    write_rework.add_argument("packet_dir")
    write_rework.add_argument("--attempt", type=int, required=True)
    write_rework.add_argument("--body", help="Path to rework body file")
    write_rework.add_argument("--body-text", help="Rework body text (alternative to --body)")
    write_rework.add_argument("--blocker", action="append", help="Blocker description (can be repeated)")
    write_rework.add_argument("--json", action="store_true")
    write_rework.set_defaults(func=_cmd_write_rework)

    check_scope = subparsers.add_parser("check-scope", help="Check scope violations")
    check_scope.add_argument("--packet", required=True, help="Path to EXECUTION_PACKET.md")
    check_scope.add_argument("--changed-file", action="append", dest="changed_files", help="Changed file path (repeatable)")
    check_scope.add_argument("--changed-files-file", help="File with newline-delimited changed files")
    check_scope.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Repository root")
    check_scope.add_argument("--json", action="store_true", help="JSON output")
    check_scope.set_defaults(func=_cmd_check_scope)

    sync_sidecar = subparsers.add_parser(
        "sync-packet-yaml-sidecar",
        help="Plan or apply canonical EXECUTION_PACKET.yaml sidecar sync",
    )
    sync_sidecar.add_argument(
        "--packet",
        action="append",
        required=True,
        help="Path to EXECUTION_PACKET.md (repeatable)",
    )
    sync_sidecar_mode = sync_sidecar.add_mutually_exclusive_group()
    sync_sidecar_mode.add_argument("--dry-run", action="store_true", help="Plan only; default")
    sync_sidecar_mode.add_argument("--apply", action="store_true", help="Write adjacent EXECUTION_PACKET.yaml files")
    sync_sidecar.add_argument("--json", action="store_true", help="JSON output")
    sync_sidecar.set_defaults(func=_cmd_sync_packet_yaml_sidecar)

    audit_sidecars = subparsers.add_parser(
        "audit-packet-yaml-sidecars",
        help="Audit canonical EXECUTION_PACKET.yaml sidecars without writing",
    )
    audit_sidecars.add_argument(
        "--packet-root",
        default="prefect_grace/packets",
        help="Root to search for strict EXECUTION_PACKET.md files",
    )
    audit_sidecars.add_argument("--json", action="store_true", help="JSON output")
    audit_sidecars.add_argument(
        "--limit",
        type=_audit_limit,
        default=20,
        help="Maximum examples/errors per class, capped at 100",
    )
    audit_sidecars.set_defaults(func=_cmd_audit_packet_yaml_sidecars)

    migration_plan = subparsers.add_parser(
        "plan-packet-yaml-sidecar-migration",
        help="Plan canonical EXECUTION_PACKET.yaml sidecar migration source-hash impact without writing",
    )
    migration_plan.add_argument(
        "--packet-root",
        default="prefect_grace/packets",
        help="Root to search for strict EXECUTION_PACKET.md files",
    )
    migration_plan.add_argument(
        "--project",
        default="prefect_grace/project.yaml",
        help="Project config path used to read runtime registry status",
    )
    migration_plan.add_argument("--json", action="store_true", help="JSON output")
    migration_plan.add_argument(
        "--limit",
        type=_audit_limit,
        default=20,
        help="Maximum displayed plan items/findings, capped at 100",
    )
    migration_plan.set_defaults(func=_cmd_plan_packet_yaml_sidecar_migration)

    migration_apply = subparsers.add_parser(
        "apply-packet-yaml-sidecar-migration",
        help="Plan or apply selected EXECUTION_PACKET.yaml sidecar migrations with source-hash gates",
    )
    migration_apply.add_argument(
        "--packet-root",
        default="prefect_grace/packets",
        help="Root to search for strict EXECUTION_PACKET.md files",
    )
    migration_apply.add_argument(
        "--project",
        default="prefect_grace/project.yaml",
        help="Project config path used to read runtime registry status",
    )
    migration_apply.add_argument(
        "--stale-only",
        action="store_true",
        help="Select only stale EXECUTION_PACKET.yaml sidecars; combines with --packet-id as a filter",
    )
    migration_apply.add_argument(
        "--packet-id",
        action="append",
        help="Explicit packet id to select (repeatable)",
    )
    migration_apply_mode = migration_apply.add_mutually_exclusive_group()
    migration_apply_mode.add_argument("--dry-run", action="store_true", help="Plan only; default")
    migration_apply_mode.add_argument("--apply", action="store_true", help="Write selected adjacent sidecars")
    migration_apply.add_argument(
        "--limit",
        type=_audit_limit,
        default=None,
        help="Dry-run display limit or apply hard item limit; apply max is 10",
    )
    migration_apply.add_argument(
        "--i-understand-source-hash-change",
        action="store_true",
        help="Acknowledge source-hash-changing sidecar writes",
    )
    migration_apply.add_argument("--json", action="store_true", help="JSON output")
    migration_apply.set_defaults(func=_cmd_apply_packet_yaml_sidecar_migration)

    # validate-evidence-contract
    validate_contract = subparsers.add_parser("validate-evidence-contract", help="Validate evidence contract from packet")
    validate_contract.add_argument("packet_path", type=Path, help="Path to EXECUTION_PACKET.md")
    validate_contract.add_argument("--json", action="store_true", help="JSON output")
    validate_contract.set_defaults(func=_cmd_validate_evidence_contract)

    # validate-evidence-manifest
    validate_manifest = subparsers.add_parser("validate-evidence-manifest", help="Validate evidence manifest against contract")
    validate_manifest.add_argument("manifest_path", type=Path, help="Path to evidence_manifest.json")
    validate_manifest.add_argument("--packet", type=Path, required=True, help="Path to EXECUTION_PACKET.md")
    validate_manifest.add_argument("--artifact-root", type=Path, help="Artifact root directory")
    validate_manifest.add_argument("--json", action="store_true", help="JSON output")
    validate_manifest.set_defaults(func=_cmd_validate_evidence_manifest)


def _register_executors_commands(subparsers) -> None:
    # list-executors
    list_executors = subparsers.add_parser("list-executors", help="List executor specs from project config")
    list_executors.add_argument("--project", type=Path, default=Path.cwd(), help="Project root directory")
    list_executors.add_argument("--json", action="store_true", help="JSON output")
    list_executors.set_defaults(func=_cmd_list_executors)

    # select-executor
    select_executor = subparsers.add_parser("select-executor", help="Select executor for packet")
    select_executor.add_argument("--project", type=Path, default=Path.cwd(), help="Project root directory")
    select_executor.add_argument("--packet-id", required=True, help="Packet ID")
    select_executor.add_argument("--role", help="Packet role (default: coder)")
    select_executor.add_argument("--requested-executor", help="Requested executor ID")
    select_executor.add_argument("--json", action="store_true", help="JSON output")
    select_executor.set_defaults(func=_cmd_select_executor)

    synthetic_edge_matrix = subparsers.add_parser("synthetic-edge-matrix")
    synthetic_edge_matrix.add_argument("--profile", choices=["smoke", "full"], default="smoke")
    synthetic_edge_matrix.add_argument("--seed", type=int, default=1)
    synthetic_edge_matrix.add_argument("--json", action="store_true")
    synthetic_edge_matrix.set_defaults(func=_cmd_synthetic_edge_matrix)


def _register_git_mutation_commands(subparsers) -> None:
    git_gate = subparsers.add_parser("git-mutation-gate", help="Plan or apply guarded packet Git mutations")
    git_gate.add_argument("--packet", type=Path, required=True, help="Path to EXECUTION_PACKET.md")
    git_gate.add_argument("--repo-root", type=Path, required=True, help="Main repository root")
    git_gate.add_argument("--worktree-root", type=Path, required=True, help="Allowed worktree root")
    git_gate.add_argument("--worktree-path", type=Path, required=True, help="Packet worktree path")
    git_gate.add_argument("--project-key", required=True, help="Project key")
    git_gate.add_argument("--packet-id", required=True, help="Packet ID")
    git_gate.add_argument("--attempt", type=int, required=True, help="Attempt number")
    git_gate.add_argument("--base-ref", required=True, help="Base ref used for the packet branch")
    git_gate.add_argument("--target-branch", required=True, help="Explicit merge target branch")
    git_gate.add_argument("--remote", default="origin", help="Remote name for packet branch push")
    git_gate.add_argument("--dry-run", action="store_true", help="Plan only; default when --apply is omitted")
    git_gate.add_argument("--apply", action="store_true", help="Allow requested Git mutations")
    git_gate.add_argument("--commit", action="store_true", help="Request guarded commit")
    git_gate.add_argument("--push", action="store_true", help="Request guarded packet branch push")
    git_gate.add_argument("--merge", action="store_true", help="Request guarded fast-forward merge")
    git_gate.add_argument("--i-understand-merge", action="store_true", help="Required for merge apply")
    git_gate.add_argument("--json", action="store_true", help="JSON output")
    git_gate.set_defaults(func=_cmd_git_mutation_gate)

    branch_push = subparsers.add_parser("packet-branch-push-gate", help="Plan or apply guarded packet branch commit/push")
    branch_push.add_argument("--packet", type=Path, required=True, help="Path to EXECUTION_PACKET.md")
    branch_push.add_argument("--repo-root", type=Path, required=True, help="Main repository root")
    branch_push.add_argument("--worktree-root", type=Path, required=True, help="Allowed worktree root")
    branch_push.add_argument("--worktree-path", type=Path, required=True, help="Packet worktree path")
    branch_push.add_argument("--project-key", required=True, help="Project key")
    branch_push.add_argument("--packet-id", required=True, help="Packet ID")
    branch_push.add_argument("--attempt", type=int, required=True, help="Attempt number")
    branch_push.add_argument("--base-ref", required=True, help="Base ref used for the packet branch")
    branch_push.add_argument("--remote", default="origin", help="Remote name for packet branch push")
    branch_push.add_argument("--dry-run", action="store_true", help="Plan only; default when --apply is omitted")
    branch_push.add_argument("--apply", action="store_true", help="Allow requested Git commit/push mutations")
    branch_push.add_argument("--commit", action="store_true", help="Request guarded packet worktree commit")
    branch_push.add_argument("--push", action="store_true", help="Request guarded packet branch push")
    branch_push.add_argument("--allow-git-commit", action="store_true", help="Approve commit application")
    branch_push.add_argument("--allow-git-push", action="store_true", help="Approve push application")
    branch_push.add_argument("--json", action="store_true", help="JSON output")
    branch_push.set_defaults(func=_cmd_packet_branch_push_gate)

    merge_steward = subparsers.add_parser("merge-steward", help="Plan or apply operator-approved fast-forward merges")
    merge_steward.add_argument("--repo-root", type=Path, required=True, help="Target repository root")
    merge_steward.add_argument("--target-branch", required=True, help="Target branch for merges")
    merge_steward.add_argument("--packet-branch", action="append", dest="packet_branches", help="Packet branch name (repeatable)")
    merge_steward.add_argument("--packet-path", action="append", help="Branch:path mapping (e.g., branch:path/to/EXECUTION_PACKET.md)")
    merge_steward.add_argument("--remote", default="origin", help="Remote name")
    merge_steward.add_argument("--dry-run", action="store_true", help="Plan only; default when --apply is omitted")
    merge_steward.add_argument("--apply", action="store_true", help="Allow merge application")
    merge_steward.add_argument("--merge", action="store_true", help="Request merge operation")
    merge_steward.add_argument("--i-understand-merge", action="store_true", help="Required for merge apply")
    merge_steward.add_argument("--json", action="store_true", help="JSON output")
    merge_steward.set_defaults(func=_cmd_merge_steward)


def _register_prefect_worker_binding_commands(subparsers) -> None:
    """Register Prefect worker binding commands."""
    prefect_binding = subparsers.add_parser("prefect-worker-binding", help="Validate Prefect infrastructure readiness")
    prefect_binding.add_argument("--project", type=Path, required=True, help="Path to grace.yaml project config")

    # Mutually exclusive group for dry-run vs apply mode
    mode_group = prefect_binding.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", default=False, help="Dry-run mode (default if neither flag specified)")
    mode_group.add_argument("--apply", action="store_true", help="Apply mode (requires --apply-deployment and approval gates)")

    prefect_binding.add_argument("--apply-deployment", action="store_true", help="Apply deployment registration (requires --apply and approval)")
    prefect_binding.add_argument("--i-understand-prefect-mutation", action="store_true", help="Acknowledge Prefect mutation")
    prefect_binding.add_argument("--run-worker-smoke", action="store_true", help="Run worker runtime smoke test")
    prefect_binding.add_argument("--json", action="store_true", help="JSON output")
    prefect_binding.set_defaults(func=_cmd_prefect_worker_binding)


def _register_dynamic_planning_commands(subparsers) -> None:
    """Register Dynamic Planning commands."""
    dynamic_plan = subparsers.add_parser("dynamic-plan", help="Parse feature brief markdown and generate execution packet")
    dynamic_plan.add_argument("--brief", required=True, help="Path to feature-brief.md file")
    dynamic_plan.add_argument("--output-dir", help="Output directory for generated files (defaults to prefect_grace/packets/<feature_id>)")
    dynamic_plan.add_argument("--apply", action="store_true", help="Apply and write the files (defaults to dry-run)")
    dynamic_plan.add_argument("--json", action="store_true", help="JSON output")
    dynamic_plan.set_defaults(func=_cmd_dynamic_plan)



def _register_git_sync_commands(subparsers) -> None:
    """Register Git Sync commands."""
    git_sync = subparsers.add_parser("git-sync", help="Automatically isolate and commit/push packet branch upon acceptance")
    git_sync.add_argument("--packet", type=Path, required=True, help="Path to EXECUTION_PACKET.md")
    git_sync.add_argument("--repo-root", type=Path, required=True, help="Main repository root")
    git_sync.add_argument("--worktree-root", type=Path, required=True, help="Allowed worktree root")
    git_sync.add_argument("--project-key", required=True, help="Project key")
    git_sync.add_argument("--packet-id", required=True, help="Packet ID")
    git_sync.add_argument("--attempt", type=int, required=True, help="Attempt number")
    git_sync.add_argument("--base-ref", required=True, help="Base Git reference")
    git_sync.add_argument("--remote", default="origin", help="Remote name")
    git_sync.add_argument("--dry-run", action="store_true", help="Plan only; default when --apply is omitted")
    git_sync.add_argument("--apply", action="store_true", help="Allow Git mutations")
    git_sync.add_argument("--json", action="store_true", help="JSON output")
    git_sync.set_defaults(func=_cmd_git_sync)


def _register_queue_watcher_commands(subparsers) -> None:
    """Register Queue Watcher daemon commands."""
    queue_watcher = subparsers.add_parser("queue-watcher", help="Run the background queue watcher daemon loop")
    queue_watcher.add_argument("--project", "--project-config", dest="project")
    queue_watcher.add_argument("--interval", type=float, default=5.0, help="Poll interval in seconds")
    queue_watcher.add_argument("--once", action="store_true", help="Run only one iteration and exit")
    queue_watcher.add_argument("--launch-drafts", action="store_true", help="Launch draft packets when runnable")
    queue_watcher.add_argument("--runner", choices=["e2e", "managed"], default="e2e", help="Submitter runner kind")
    queue_watcher.add_argument("--json", action="store_true", help="JSON output")
    queue_watcher.set_defaults(func=_cmd_queue_watcher)


def _register_init_commands(subparsers) -> None:
    """Register init command for bootstrapping new projects."""
    init = subparsers.add_parser("init", help="Bootstrap a new project workspace with GRACE configuration")
    init.add_argument("project_key", help="Unique identifier for the project (e.g., MY-PROJECT)")
    init.add_argument("--root", help="Root directory for the project (defaults to current directory)")
    init.add_argument("--json", action="store_true", help="JSON output")
    init.set_defaults(func=_cmd_init)


# START_FUNCTION_CONTRACT
# name: build_parser
# purpose: Assemble and return the complete argument parser.
# inputs: None.
# returns: The configured ArgumentParser instance.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prefect-grace")
    subparsers = parser.add_subparsers(required=True)

    _register_legacy_feature_commands(subparsers)
    _register_project_registry_commands(subparsers)
    _register_packet_submission_commands(subparsers)
    _register_prefect_smokes_commands(subparsers)
    _register_worktrees_commands(subparsers)
    _register_packet_execution_commands(subparsers)
    _register_evidence_commands(subparsers)
    _register_executors_commands(subparsers)
    _register_git_mutation_commands(subparsers)
    _register_prefect_worker_binding_commands(subparsers)
    _register_dynamic_planning_commands(subparsers)
    _register_git_sync_commands(subparsers)
    _register_init_commands(subparsers)

    _register_queue_watcher_commands(subparsers)
    return parser
