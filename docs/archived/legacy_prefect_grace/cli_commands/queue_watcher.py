# ############################################################################
# AI_HEADER: cli_queue_watcher
# ROLE: CLI command to run the GRACE Queue Watcher Daemon.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: CLI command interface for QueueWatcherDaemon.
# inputs: argparse Namespace with daemon configuration.
# returns: None.
# side_effects: Runs the daemon loop, syncing and executing packets.
# emitted_logs: Writes queue watcher activity logs.
# error_behavior: Exits with non-zero code on startup errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: _cmd_queue_watcher
# END_MODULE_MAP

from __future__ import annotations

import argparse
import sys
import json

from prefect_grace.cli_commands.common import _load_adapter_from_args, _json_envelope, _print_json
from prefect_grace.platform.queue_watcher import QueueWatcherDaemon


# START_FUNCTION_CONTRACT
# name: _cmd_queue_watcher
# purpose: Run the queue watcher daemon from CLI args.
# inputs:
#   args: argparse.Namespace.
# returns: None.
# side_effects: Launches queue watcher loop, exits process on failure.
# emitted_logs: Logs daemon iteration events.
# error_behavior: Exits with status 1 on exceptions.
# END_FUNCTION_CONTRACT
def _cmd_queue_watcher(args: argparse.Namespace) -> None:
    command = "queue-watcher"
    try:
        project = _load_adapter_from_args(args)
        interval = float(getattr(args, "interval", 5.0))
        once = bool(getattr(args, "once", False))
        launch_drafts = bool(getattr(args, "launch_drafts", False))
        runner_kind = getattr(args, "runner", "e2e")

        daemon = QueueWatcherDaemon(
            project=project,
            interval_seconds=interval,
            once=once,
            launch_drafts=launch_drafts,
            runner_kind=runner_kind,
        )

        stats = daemon.start()

        if args.json:
            _print_json(_json_envelope(
                ok=True,
                command=command,
                project_key=project.project_key,
                result=stats,
            ))
        else:
            print("Queue Watcher finished successfully.")
            print(f"Stats: {stats}")

    except Exception as err:
        if getattr(args, "json", False):
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "DAEMON_FAILED", "message": str(err)}],
            ))
        else:
            print(f"Queue watcher failed: {err}", file=sys.stderr)
        sys.exit(1)
