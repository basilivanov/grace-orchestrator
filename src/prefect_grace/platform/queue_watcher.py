# ############################################################################
# AI_HEADER: queue_watcher
# ROLE: Background daemon loop to monitor and submit ready GRACE packets.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Monitor draft/ready packets and automatically launch runnable packets.
# inputs: ProjectAdapterConfig, interval_seconds, once flag, launch_drafts flag, runner_kind.
# returns: dict[str, Any] with statistics and execution results.
# side_effects: Synchronizes backlog and submits flow runs to Prefect queue.
# emitted_logs: Writes structured JSONL entries to logs/queue_watcher.jsonl.
# error_behavior: Fail-safe; handles exceptions gracefully and keeps running.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: QueueWatcherDaemon
# END_MODULE_MAP

from __future__ import annotations

import json
import time
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from prefect_grace.platform.backlog_controller import BacklogController
from prefect_grace.platform.state_store import PacketRegistryStore
from prefect_grace.platform.status_model import RegistryStatus
from prefect_grace.platform.prefect_native_submission import submit_ready_packets_to_prefect
from prefect_grace.platform.runtime_adapter import E2EPacketSubmitter, ManagedPacketSubmitter


@dataclass
class QueueWatcherStats:
    iterations: int = 0
    packets_synced: int = 0
    draft_monitored: int = 0
    ready_monitored: int = 0
    submitted_count: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "iterations": self.iterations,
            "packets_synced": self.packets_synced,
            "draft_monitored": self.draft_monitored,
            "ready_monitored": self.ready_monitored,
            "submitted_count": self.submitted_count,
            "errors": self.errors,
        }


class QueueWatcherDaemon:
    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Initialize daemon configuration.
    # inputs:
    #   project: ProjectAdapterConfig.
    #   interval_seconds: float.
    #   once: bool.
    #   launch_drafts: bool.
    #   runner_kind: Literal["e2e", "managed"].
    # returns: None.
    # side_effects: Sets config attributes.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        project: Any,
        interval_seconds: float = 5.0,
        once: bool = False,
        launch_drafts: bool = False,
        runner_kind: Literal["e2e", "managed"] = "e2e",
    ) -> None:
        self.project = project
        self.interval_seconds = interval_seconds
        self.once = once
        self.launch_drafts = launch_drafts
        self.runner_kind = runner_kind
        self.stats = QueueWatcherStats()

        project_root = Path(project.repo_root)
        self.log_file = project_root / "logs" / "queue_watcher.jsonl"

    # START_FUNCTION_CONTRACT
    # name: _write_log
    # purpose: Write structured JSONL entry to log file and sys.stdout.
    # inputs:
    #   event: str.
    #   details: dict[str, Any].
    # returns: None.
    # side_effects: Writes to file and stdout.
    # emitted_logs: JSONL log entry.
    # error_behavior: None (fail-safe).
    # END_FUNCTION_CONTRACT
    def _write_log(self, event: str, details: dict[str, Any]) -> None:
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "event": event,
                "project_key": self.project.project_key,
                **details,
            }
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

            sys.stdout.write(f"[{entry['timestamp']}] {event.upper()}: {json.dumps(details, ensure_ascii=False)}\n")
            sys.stdout.flush()
        except Exception:
            pass

    # START_FUNCTION_CONTRACT
    # name: run_iteration
    # purpose: Run one sync and submit iteration.
    # inputs: None.
    # returns: bool - True if success, False otherwise.
    # side_effects: Syncs registry and submits ready packets.
    # emitted_logs: None.
    # error_behavior: Captures exceptions and increments error stats.
    # END_FUNCTION_CONTRACT
    def run_iteration(self) -> bool:
        self.stats.iterations += 1
        try:
            sync_result = BacklogController.sync(self.project, dry_run=False)
            self.stats.packets_synced = sync_result.packets_total

            registry = PacketRegistryStore(Path(self.project.runtime_state_root) / "state")
            all_packets = registry.list_packets()

            drafts = [p for p in all_packets if p.get("status") == "draft"]
            readies = [p for p in all_packets if p.get("status") == "ready"]

            self.stats.draft_monitored = len(drafts)
            self.stats.ready_monitored = len(readies)

            self._write_log(
                "daemon_iteration_sync",
                {
                    "iteration": self.stats.iterations,
                    "packets_total": sync_result.packets_total,
                    "draft_count": len(drafts),
                    "ready_count": len(readies),
                }
            )

            submission_plan = BacklogController.plan_submission(self.project)

            runnable_packets = []
            for packet_id in submission_plan.packets_to_submit:
                record = registry.load_packet(packet_id)
                if record:
                    is_draft = record.get("status") == "draft"
                    if is_draft and not self.launch_drafts:
                        continue
                    runnable_packets.append(packet_id)

            if not runnable_packets:
                return True

            submitter = E2EPacketSubmitter() if self.runner_kind == "e2e" else ManagedPacketSubmitter()
            
            self._write_log(
                "daemon_submission_start",
                {
                    "runnable_packets": runnable_packets,
                    "runner_kind": self.runner_kind,
                }
            )

            submission_result = submit_ready_packets_to_prefect(
                project=self.project,
                dry_run=False,
                limit=None,
                execute_agent=False,
                timeout_seconds=3600,
                base_ref="HEAD",
                worktree_root=None,
                scheduled_for=None,
                continue_on_error=True,
                submitter=submitter,
                runner_kind=self.runner_kind,
            )

            for rec in submission_result.records:
                if rec.status == "submitted":
                    self.stats.submitted_count += 1
                    self._write_log(
                        "packet_submitted",
                        {
                            "packet_id": rec.packet_id,
                            "flow_run_id": rec.flow_run_id,
                            "flow_run_name": rec.flow_run_name,
                        }
                    )
                elif rec.status == "failed":
                    self._write_log(
                        "packet_submission_failed",
                        {
                            "packet_id": rec.packet_id,
                            "error": rec.error,
                        }
                    )

            return len(submission_result.errors) == 0

        except Exception as err:
            self.stats.errors.append(str(err))
            self._write_log("daemon_iteration_error", {"error": str(err)})
            return False

    # START_FUNCTION_CONTRACT
    # name: start
    # purpose: Start the daemon main loop.
    # inputs: None.
    # returns: dict[str, Any] - execution stats.
    # side_effects: Runs loop, sleeps between iterations.
    # emitted_logs: Log daemon lifecycle events.
    # error_behavior: Keeps running on iteration failure.
    # END_FUNCTION_CONTRACT
    def start(self) -> dict[str, Any]:
        self._write_log(
            "daemon_started",
            {
                "interval_seconds": self.interval_seconds,
                "once": self.once,
                "launch_drafts": self.launch_drafts,
                "runner_kind": self.runner_kind,
            }
        )

        if self.once:
            self.run_iteration()
        else:
            try:
                while True:
                    self.run_iteration()
                    time.sleep(self.interval_seconds)
            except KeyboardInterrupt:
                self._write_log("daemon_stopped_by_user", {})

        self._write_log("daemon_finished", {"stats": self.stats.to_dict()})
        return self.stats.to_dict()
