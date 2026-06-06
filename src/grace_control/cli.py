# AI_HEADER: cli — grace_ctl, the user-facing CLI for the GRACE supervisor
# START_MODULE_CONTRACT
# purpose: Typer-based CLI that wraps SupervisorClient. Discovers the
#          supervisor unix socket via GRACE_SUPERVISOR_SOCK (set by
#          scripts/live_supervisor.sh) and exposes status / restart /
#          stop commands. Also bundles a `start` subcommand for spawning
#          the supervisor itself (no socket required to run it).
# inputs: GRACE_SUPERVISOR_SOCK env var (set by live_supervisor.sh) or
#         --socket-path flag.
# returns: exits 0 on success, non-zero on supervisor errors.
# side_effects: None beyond the supervisor API calls.
# emitted_logs: via SupervisorClient.
# error_behavior: Prints a friendly error and exits 2 on connection failure.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:
#   - function: main
#   - function: _resolve_socket
# END_MODULE_MAP

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import typer

from grace_control.supervisor_client import SupervisorClient, SupervisorConnectionError

app = typer.Typer(
    name="grace_ctl",
    help="Control the GRACE Control Plane supervisor.",
    no_args_is_help=True,
    add_completion=False,
)

restart_app = typer.Typer(help="Restart API or workers.")
app.add_typer(restart_app, name="restart")


def _resolve_socket(socket_path: Optional[Path]) -> Path:
    if socket_path is not None:
        return socket_path
    env = os.environ.get("GRACE_SUPERVISOR_SOCK")
    if env:
        return Path(env)
    # Fallback: try $WT/supervisor.sock
    wt = os.environ.get("GRACE_TARGET_DIR")
    if wt:
        candidate = Path(wt) / "supervisor.sock"
        if candidate.exists():
            return candidate
    raise typer.BadParameter(
        "cannot find supervisor socket: set GRACE_SUPERVISOR_SOCK or pass --socket-path"
    )


def _print_status(status: dict[str, Any], as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(status, indent=2, default=str))
        return
    api = status.get("api")
    workers = status.get("workers", [])
    typer.echo(f"supervisor pid: {status['supervisor_pid']}")
    typer.echo(f"target_dir:     {status['target_dir']}")
    typer.echo(f"source_dir:     {status['source_dir']}")
    typer.echo("")
    if api:
        typer.echo(f"api      pid={api['pid']:<8} alive={api['alive']} argv={api['argv']}")
    else:
        typer.echo("api      (not running)")
    for w in workers:
        typer.echo(f"worker   pid={w['pid']:<8} alive={w['alive']} id={w.get('worker_id','')}")


@app.command()
def status(
    socket_path: Optional[Path] = typer.Option(None, "--socket-path", help="Supervisor unix socket path."),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show supervisor, API, and worker status."""
    try:
        client = SupervisorClient(_resolve_socket(socket_path))
        _print_status(client.status_sync(), as_json=as_json)
    except SupervisorConnectionError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=2)


@restart_app.command("api")
def restart_api(
    socket_path: Optional[Path] = typer.Option(None, "--socket-path"),
) -> None:
    """Restart only the API process."""
    try:
        client = SupervisorClient(_resolve_socket(socket_path))
        typer.echo(client.restart_sync("api"))
    except SupervisorConnectionError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=2)


@restart_app.command("workers")
def restart_workers(
    socket_path: Optional[Path] = typer.Option(None, "--socket-path"),
) -> None:
    """Restart all worker processes."""
    try:
        client = SupervisorClient(_resolve_socket(socket_path))
        typer.echo(client.restart_sync("workers"))
    except SupervisorConnectionError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=2)


@restart_app.command("all")
def restart_all(
    socket_path: Optional[Path] = typer.Option(None, "--socket-path"),
) -> None:
    """Restart everything: API + workers."""
    try:
        client = SupervisorClient(_resolve_socket(socket_path))
        typer.echo(client.restart_sync("all"))
    except SupervisorConnectionError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=2)


@app.command()
def stop(
    socket_path: Optional[Path] = typer.Option(None, "--socket-path"),
) -> None:
    """Stop the supervisor and all children (graceful)."""
    try:
        client = SupervisorClient(_resolve_socket(socket_path))
        typer.echo(client.stop_sync() if hasattr(client, "stop_sync") else json.dumps(client.status_sync()))
    except SupervisorConnectionError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=2)


@app.command()
def cleanup(
    socket_path: Optional[Path] = typer.Option(None, "--socket-path"),
    worktrees: bool = typer.Option(True, "--worktrees/--no-worktrees", help="Clean orphaned git worktrees."),
    state_files: bool = typer.Option(True, "--state-files/--no-state-files", help="Clean .grace_state/ entries older than threshold."),
    stale_leases: bool = typer.Option(True, "--stale-leases/--no-stale-leases", help="Release DB leases older than threshold."),
    stale_lease_minutes: int = typer.Option(30, "--stale-lease-minutes", help="Lease age threshold in minutes."),
    stale_state_days: int = typer.Option(7, "--stale-state-days", help="State-file age threshold in days."),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Idempotent cleanup of supervisor-owned state.

    Removes orphaned git worktrees, old .grace_state/ entries, and DB leases
    that have been held longer than the threshold (and marks their packets
    FAILED). Safe to run repeatedly; never raises.
    """
    try:
        client = SupervisorClient(_resolve_socket(socket_path))
        result = client.cleanup_sync(
            worktrees=worktrees,
            state_files=state_files,
            stale_leases=stale_leases,
            stale_lease_minutes=stale_lease_minutes,
            stale_state_days=stale_state_days,
        )
        if as_json:
            typer.echo(json.dumps(result, indent=2))
            return
        report = result.get("report", {})
        typer.echo(f"worktrees_removed:    {len(report.get('worktrees_removed', []))}")
        typer.echo(f"worktrees_kept:       {len(report.get('worktrees_kept', []))}")
        typer.echo(f"state_files_removed:  {len(report.get('state_files_removed', []))}")
        typer.echo(f"state_files_kept:     {len(report.get('state_files_kept', []))}")
        typer.echo(f"stale_leases:         {report.get('stale_leases_released', 0)}")
        typer.echo(f"errors:               {len(report.get('errors', []))}")
        typer.echo(f"duration_seconds:     {report.get('duration_seconds', 0)}")
    except SupervisorConnectionError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=2)


@app.command()
def reload(
    socket_path: Optional[Path] = typer.Option(None, "--socket-path"),
) -> None:
    """Re-prime the mtime watcher (useful after git pull).

    Does NOT restart children — use `grace_ctl restart <target>` for that.
    """
    try:
        client = SupervisorClient(_resolve_socket(socket_path))
        typer.echo(client.reload_sync())
    except SupervisorConnectionError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=2)


@app.command()
def start(
    target_dir: Path = typer.Option(..., "--target-dir", help="Project working directory."),
    source_dir: Path = typer.Option(..., "--source-dir", help="Repository source root."),
    workers: int = typer.Option(1, "--workers", help="Number of worker processes."),
    api_url: str = typer.Option("http://127.0.0.1:8042", "--api-url"),
    no_watch: bool = typer.Option(False, "--no-watch", help="Disable mtime auto-reload."),
) -> None:
    """Start the supervisor in the foreground. (Normally invoked by scripts/live_supervisor.sh.)"""
    # Defer import so `grace_ctl status` doesn't require supervisor.py deps.
    from grace_control.supervisor import main as supervisor_main
    rc = supervisor_main([
        "--target-dir", str(target_dir),
        "--source-dir", str(source_dir),
        "--workers", str(workers),
        "--api-url", api_url,
        *(["--no-watch"] if no_watch else []),
    ])
    raise typer.Exit(code=rc)


def main() -> None:
    try:
        app()
    except SupervisorConnectionError as e:
        typer.echo(f"error: {e}", err=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
