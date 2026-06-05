# ############################################################################
# AI_HEADER: pipeline_tasks.execution_tasks
# ROLE: Packet execution and status Prefect tasks for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run coder/verifier packets and update feature or packet statuses for feature_pipeline.
# inputs: Feature ids, packet ids, statuses, dry-run flags, and timeout values.
# returns: Packet run results and updated state records.
# side_effects: May launch Codex, update packet/feature state, and send notifications through existing task APIs.
# emitted_logs: Prefect task logs.
# error_behavior: Propagates launcher, status validation, state update, and notification errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: mark_feature_in_progress_task
#   - function: run_packet_task
#   - function: run_verifier_packet_task
#   - function: mark_packet_status_task
# END_MODULE_MAP

from __future__ import annotations

import sys
from pathlib import Path

from prefect_grace.models import FeatureStatus, PacketStatus
from prefect_grace.prefect_compat import get_run_logger, task
from prefect_grace.tasks.codex_launcher import launch_codex_for_packet
from prefect_grace.tasks.feature_bootstrap import mark_feature_status
from prefect_grace.tasks.state_store import update_record
from prefect_grace.tasks.telegram_notify import notify_feature_event, notify_packet_event


def _facade_attr(name: str, default):
    facade = sys.modules.get("prefect_grace.flows.feature_pipeline")
    return getattr(facade, name, default) if facade is not None else default


# START_FUNCTION_CONTRACT
# name: mark_feature_in_progress_task
# purpose: Mark a feature as in progress and notify observers.
# inputs:
#   feature_id: Feature identifier.
#   state_root: State root directory path.
# returns: Updated feature record.
# side_effects: Updates feature state and sends notification.
# emitted_logs: Prefect task log line.
# error_behavior: Propagates status and notification errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="feature-status:{feature_id}:in-progress")
def mark_feature_in_progress_task(feature_id: str, *, state_root: Path | str):
    logger = get_run_logger()
    logger.info("Marking feature %s as in progress", feature_id)
    record = mark_feature_status(feature_id, FeatureStatus.IN_PROGRESS, state_root=state_root)
    notify_feature_event(
        feature_id=feature_id,
        title=str(record.get("title") or ""),
        status=FeatureStatus.IN_PROGRESS.value,
        summary=str(record.get("summary") or ""),
    )
    return record


# START_FUNCTION_CONTRACT
# name: run_packet_task
# purpose: Launch a coder packet through the existing Codex launcher.
# inputs:
#   packet_id: Packet identifier.
#   dry_run: Whether to run in dry-run mode.
#   timeout_seconds: Launcher timeout.
# returns: Launcher result dictionary.
# side_effects: May launch Codex depending on dry_run.
# emitted_logs: Prefect task log line.
# error_behavior: Propagates launcher errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="packet:{packet_id}")
def run_packet_task(packet_id: str, dry_run: bool, timeout_seconds: int):
    logger = get_run_logger()
    logger.info("Running packet %s dry_run=%s", packet_id, dry_run)
    launcher = _facade_attr("launch_codex_for_packet", launch_codex_for_packet)
    return launcher(packet_id, dry_run=dry_run, timeout_seconds=timeout_seconds, logger=logger)


# START_FUNCTION_CONTRACT
# name: run_verifier_packet_task
# purpose: Launch a verifier packet through the existing Codex launcher.
# inputs:
#   packet_id: Verifier packet identifier.
#   dry_run: Whether to run in dry-run mode.
#   timeout_seconds: Launcher timeout.
# returns: Launcher result dictionary.
# side_effects: May launch Codex depending on dry_run.
# emitted_logs: Prefect task log line.
# error_behavior: Propagates launcher errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="verifier:{packet_id}")
def run_verifier_packet_task(packet_id: str, dry_run: bool, timeout_seconds: int):
    logger = get_run_logger()
    logger.info("Running verifier packet %s dry_run=%s", packet_id, dry_run)
    launcher = _facade_attr("launch_codex_for_packet", launch_codex_for_packet)
    return launcher(packet_id, dry_run=dry_run, timeout_seconds=timeout_seconds, logger=logger)


# START_FUNCTION_CONTRACT
# name: mark_packet_status_task
# purpose: Update a packet status and notify observers.
# inputs:
#   packet_id: Packet identifier.
#   status: PacketStatus value string.
#   state_root: State root directory path.
# returns: Updated packet record.
# side_effects: Updates packet state and sends notification.
# emitted_logs: Prefect task log line.
# error_behavior: Raises for invalid status and propagates state/notification errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="packet-status:{packet_id}:{status}")
def mark_packet_status_task(packet_id: str, status: str, *, state_root: Path | str):
    logger = get_run_logger()
    PacketStatus(status)
    logger.info("Packet %s status=%s", packet_id, status)
    record = update_record("packets", "packets", "packet_id", packet_id, {"status": status}, state_root=state_root)
    notify_packet_event(
        feature_id=str(record.get("feature_id") or ""),
        packet_id=packet_id,
        role=str(record.get("role") or ""),
        status=status,
        wave_id=str(record.get("wave_id") or ""),
        title=str(record.get("title") or ""),
    )
    return record
