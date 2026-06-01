# ############################################################################
# AI_HEADER: cli_main
# ROLE: CLI entry point for GRACE Control Plane — thin wrapper over API.
# ############################################################################

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import click
import httpx
import uvicorn
import yaml
from rich.console import Console
from rich.table import Table

console = Console()
DEFAULT_API_URL = "http://localhost:8042"


@click.group()
def cli():
    """GRACE Control Plane CLI."""


@cli.command("up")
@click.option("--port", default=8042, help="API port")
@click.option("--worker-id", default="agy1", help="Worker ID")
@click.option("--project", default=".", help="Project root for worker")
@click.option("--watch", is_flag=True, help="Auto-submit new features from grace/features/")
def up(port, worker_id, project, watch):
    """Start API server + worker. With --watch, auto-submits new YAML files."""
    import asyncio
    import threading
    import uvicorn
    from pathlib import Path
    from grace_control.worker.worker import Worker

    project_root = Path(project).resolve()
    state_root = project_root / ".grace" / "state"
    worktree_root = project_root / ".grace" / "worktrees"
    features_dir = project_root / "grace" / "features"
    state_root.mkdir(parents=True, exist_ok=True)
    worktree_root.mkdir(parents=True, exist_ok=True)
    features_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("GRACE_DB_URL", f"sqlite:///{project_root / 'grace.db'}")
    os.environ.setdefault("GRACE_ALLOW_SANDBOX_BYPASS", "true")

    from grace_control.db import init_db
    init_db()

    console.print(f"[green]GRACE Control Plane[/green]")
    console.print(f"  API:  http://127.0.0.1:{port}")
    console.print(f"  Dashboard: http://127.0.0.1:{port}/")
    console.print(f"  Project: {project_root}")
    console.print(f"  Worker: {worker_id}")
    if watch:
        console.print(f"  Watch: {features_dir} [yellow](auto-submit)[/yellow]")

    def run_api():
        from grace_control.api.main import app
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

    threading.Thread(target=run_api, daemon=True).start()

    async def feature_watcher():
        if not watch:
            return
        await asyncio.sleep(3)
        import httpx, yaml
        seen = set()
        while True:
            try:
                for yf in sorted(features_dir.glob("*.yaml")):
                    if yf.name in seen:
                        continue
                    seen.add(yf.name)
                    spec = yaml.safe_load(yf.read_text())
                    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10) as c:
                        r = await c.post("/api/architect/plan", json={"feature_spec": spec})
                        if r.status_code == 200:
                            data = r.json()["data"]
                            console.print(f"[cyan]Auto-submitted: {data['feature_id']} ({data['packets_count']} packets)[/cyan]")
            except Exception:
                pass
            await asyncio.sleep(10)

    async def run_worker():
        await asyncio.sleep(2)
        while True:
            try:
                worker = Worker(worker_id=worker_id, api_url=f"http://127.0.0.1:{port}",
                                project_root=project_root, state_root=state_root,
                                worktree_root=worktree_root)
                await worker.start()
            except Exception:
                console.print(f"[red]Worker crashed, restarting in 3s...[/red]")
                await asyncio.sleep(3)

    async def main():
        await asyncio.gather(feature_watcher(), run_worker())

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")


@cli.command("init")
@click.option("--project", default=".", help="Project root directory")
def init_project(project):
    """Initialize a new GRACE project."""
    root = Path(project).resolve()
    grace_dir = root / "grace"
    packets_dir = grace_dir / "packets"
    features_dir = grace_dir / "features"

    for d in [grace_dir, packets_dir, features_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Create sample feature
    sample = features_dir / "hello.yaml"
    if not sample.exists():
        sample.write_text("""title: Hello GRACE
description: Sample feature to verify GRACE pipeline.
waves:
  - title: Foundation
    packets:
      - title: Create hello module
        scope:
          - src/hello.py
        acceptance_profile: NORMAL
""")

    console.print(f"[green]GRACE project initialized at {root}[/green]")
    console.print(f"  grace/features/hello.yaml — sample feature")
    console.print(f"  grace/packets/ — execution packet directory")
    console.print()
    console.print("Next: [cyan]grace architect plan grace/features/hello.yaml[/cyan]")


# ── Architect ────────────────────────────────────────────────────────────────
@cli.group()
def architect():
    """Architect commands."""


@architect.command("plan")
@click.argument("feature_file", type=click.Path(exists=True))
@click.option("--api-url", default=DEFAULT_API_URL, help="API URL")
@click.option("--json", "json_out", is_flag=True, help="JSON output")
def architect_plan(feature_file, api_url, json_out):
    """Create execution plan from feature YAML."""
    spec = yaml.safe_load(Path(feature_file).read_text())
    try:
        r = httpx.post(f"{api_url}/api/architect/plan", json={"feature_spec": spec}, timeout=10)
        r.raise_for_status()
        data = r.json()["data"]
        if json_out:
            click.echo(json.dumps({"ok": True, "result": data, "warnings": [], "errors": []}))
        else:
            console.print(f"\n[green]Plan created![/green]")
            console.print(f"Feature: {data['feature_id']}  Waves: {data['waves_count']}  Packets: {data['packets_count']}")
            for pid in data["packets"]:
                console.print(f"  [cyan]• {pid}[/cyan]")
    except httpx.HTTPError as e:
        _handle_error(e, json_out)


# ── Packet ───────────────────────────────────────────────────────────────────
@cli.group()
def packet():
    """Packet commands."""


@packet.command("list")
@click.option("--state", default=None, help="Filter by state")
@click.option("--feature", "feature_id", default=None, help="Filter by feature ID")
@click.option("--api-url", default=DEFAULT_API_URL, help="API URL")
@click.option("--json", "json_out", is_flag=True, help="JSON output")
def packet_list(state, feature_id, api_url, json_out):
    """List packets."""
    params = {}
    if state: params["state"] = state
    if feature_id: params["feature_id"] = feature_id
    try:
        r = httpx.get(f"{api_url}/api/packets/", params=params, timeout=10)
        r.raise_for_status()
        data = r.json()["data"]
        if json_out:
            click.echo(json.dumps({"ok": True, "result": data, "warnings": [], "errors": []}))
        else:
            if not data:
                console.print("[yellow]No packets found[/yellow]")
                return
            table = Table(title="Packets")
            table.add_column("ID", style="cyan")
            table.add_column("Title", style="white")
            table.add_column("State", style="green")
            table.add_column("Attempts", style="yellow")
            colors = {"ready": "green", "running": "yellow", "accepted": "blue", "merged": "cyan", "rejected": "red", "failed": "red"}
            for p in data:
                table.add_row(p["id"], p["title"], f"[{colors.get(p['state'], 'white')}]{p['state']}[/{colors.get(p['state'], 'white')}]", f"{p['attempt_count']}/{p['max_attempts']}")
            console.print(table)
    except httpx.HTTPError as e:
        _handle_error(e, json_out)


@packet.command("get")
@click.argument("packet_id")
@click.option("--api-url", default=DEFAULT_API_URL, help="API URL")
@click.option("--json", "json_out", is_flag=True, help="JSON output")
def packet_get(packet_id, api_url, json_out):
    """Get packet details."""
    try:
        r = httpx.get(f"{api_url}/api/packets/{packet_id}", timeout=10)
        r.raise_for_status()
        data = r.json()["data"]
        if json_out:
            click.echo(json.dumps({"ok": True, "result": data, "warnings": [], "errors": []}))
        else:
            console.print(f"\n[bold cyan]Packet: {data['id']}[/bold cyan]")
            console.print(f"Title: {data['title']}")
            console.print(f"State: {data['state']}  Feature: {data['feature_id']}  Wave: {data['wave_id']}")
            console.print(f"Attempts: {data['attempt_count']}/{data['max_attempts']}")
            if data["runs"]:
                console.print("\n[bold]Runs:[/bold]")
                for run in data["runs"]:
                    console.print(f"  Run {run['run_number']}: {run['status']}  duration={run['duration_ms']}ms  evidence={run['evidence_path']}")
    except httpx.HTTPError as e:
        _handle_error(e, json_out)


# ── Worker ───────────────────────────────────────────────────────────────────
@cli.group()
def worker():
    """Worker commands."""


@worker.command("start")
@click.option("--worker-id", default=None, help="Worker ID")
@click.option("--api-url", default=DEFAULT_API_URL, help="API URL")
def worker_start(worker_id, api_url):
    """Start worker."""
    from grace_control.worker.worker import Worker
    console.print(f"[green]Starting worker...[/green]")
    if worker_id: console.print(f"Worker ID: {worker_id}")
    console.print(f"API URL: {api_url}")
    w = Worker(worker_id=worker_id, api_url=api_url)
    try:
        asyncio.run(w.start())
    except KeyboardInterrupt:
        console.print("\n[yellow]Worker stopped[/yellow]")


# ── API ──────────────────────────────────────────────────────────────────────
@cli.group()
def api():
    """API server commands."""


@api.command("start")
@click.option("--host", default="127.0.0.1", help="Host to bind")
@click.option("--port", default=8042, help="Port to bind")
def api_start(host, port):
    """Start API server."""
    console.print(f"[green]Starting API server on {host}:{port}...[/green]")
    os.environ.setdefault("GRACE_API_PORT", str(port))
    uvicorn.run("grace_control.api.main:app", host=host, port=port)


# ── Health ───────────────────────────────────────────────────────────────────
@cli.command("health")
@click.option("--api-url", default=DEFAULT_API_URL, help="API URL")
@click.option("--json", "json_out", is_flag=True, help="JSON output")
def health(api_url, json_out):
    """Check system health."""
    try:
        r = httpx.get(f"{api_url}/health", timeout=10)
        r.raise_for_status()
        data = r.json()
        if json_out:
            click.echo(json.dumps({"ok": True, "result": data, "warnings": [], "errors": []}))
        else:
            colors = {"healthy": "green", "degraded": "yellow", "unhealthy": "red"}
            console.print(f"\n[bold]System:[/bold] [{colors.get(data['status'], 'white')}]{data['status']}[/{colors.get(data['status'], 'white')}]")
            console.print(f"Workers: active={data['workers']['active']} idle={data['workers']['idle']} dead={data['workers']['dead']}")
            console.print(f"Queue: ready={data['queue_depth']} running={data['running']}")
    except httpx.HTTPError as e:
        _handle_error(e, json_out)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _handle_error(e, json_out):
    if json_out:
        click.echo(json.dumps({"ok": False, "result": None, "warnings": [], "errors": [str(e)]}))
    else:
        console.print(f"[red]Error: {e}[/red]")


if __name__ == "__main__":
    cli()
