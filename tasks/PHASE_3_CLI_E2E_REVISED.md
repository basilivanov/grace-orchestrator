# Phase 3: CLI & E2E Test (REVISED)

**Длительность:** 2 дня
**Цель:** Создать CLI и E2E test для MVP-0 vertical slice

**ВАЖНО:** Только CLI и E2E test. БЕЗ UI/Telegram/WebSocket.

---

## Task #19: Implement CLI

**Приоритет:** Критично
**Время:** 1 день
**Зависимости:** Phase 2 complete

### Описание
Создать CLI для управления Control Plane.

**MVP-0 scope:** Только основные команды для vertical slice.

### Что делать

#### 1. Создать CLI main

**src/grace_control/cli/main.py:**
```python
"""
GRACE Control Plane CLI.

Commands:
- grace architect plan <file>
- grace packet list
- grace packet get <packet_id>
- grace worker start
- grace api start
- grace health
"""
import click
from rich.console import Console
from rich.table import Table
import httpx
import asyncio
import yaml
from pathlib import Path

console = Console()

@click.group()
def cli():
    """GRACE Control Plane CLI."""
    pass

@cli.group()
def architect():
    """Architect commands."""
    pass

@architect.command("plan")
@click.argument("feature_file", type=click.Path(exists=True))
def architect_plan(feature_file):
    """Create execution plan from feature YAML file."""
    url = "http://localhost:8042/api/architect/plan"

    try:
        feature_spec = yaml.safe_load(Path(feature_file).read_text())
        response = httpx.post(url, json={"feature_spec": feature_spec})
        response.raise_for_status()
        data = response.json()["data"]

        console.print(f"\n[green]Plan created![/green]")
        console.print(f"[white]Feature:[/white] {data['feature_id']}")
        console.print(f"[white]Waves:[/white] {data['waves_count']}")
        console.print(f"[white]Packets:[/white] {data['packets_count']}")
        for pid in data["packets"]:
            console.print(f"  [cyan]• {pid}[/cyan]")

    except httpx.HTTPError as e:
        console.print(f"[red]Error: {e}[/red]")

@cli.group()
def packet():
    """Packet commands."""
    pass

@packet.command("list")
@click.option("--state", help="Filter by state")
@click.option("--feature", help="Filter by feature ID")
def packet_list(state, feature):
    """List packets."""
    url = "http://localhost:8042/api/packets/"
    params = {}
    if state:
        params["state"] = state
    if feature:
        params["feature_id"] = feature
    
    try:
        response = httpx.get(url, params=params)
        response.raise_for_status()
        data = response.json()["data"]
        
        if not data:
            console.print("[yellow]No packets found[/yellow]")
            return
        
        # Create table
        table = Table(title="Packets")
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="white")
        table.add_column("State", style="green")
        table.add_column("Attempts", style="yellow")
        
        for p in data:
            state_color = {
                "ready": "green",
                "running": "yellow",
                "accepted": "blue",
                "merged": "cyan",
                "rejected": "red",
                "failed": "red"
            }.get(p["state"], "white")
            
            table.add_row(
                p["id"],
                p["title"],
                f"[{state_color}]{p['state']}[/{state_color}]",
                f"{p['attempt_count']}/{p['max_attempts']}"
            )
        
        console.print(table)
    
    except httpx.HTTPError as e:
        console.print(f"[red]Error: {e}[/red]")

@packet.command("get")
@click.argument("packet_id")
def packet_get(packet_id):
    """Get packet details."""
    url = f"http://localhost:8042/api/packets/{packet_id}"
    
    try:
        response = httpx.get(url)
        response.raise_for_status()
        data = response.json()["data"]
        
        console.print(f"\n[bold cyan]Packet: {data['id']}[/bold cyan]")
        console.print(f"[white]Title:[/white] {data['title']}")
        console.print(f"[white]Description:[/white] {data['description']}")
        console.print(f"[white]State:[/white] {data['state']}")
        console.print(f"[white]Feature:[/white] {data['feature_id']}")
        console.print(f"[white]Wave:[/white] {data['wave_id']}")
        console.print(f"[white]Attempts:[/white] {data['attempt_count']}/{data['max_attempts']}")
        
        if data["runs"]:
            console.print("\n[bold]Runs:[/bold]")
            for run in data["runs"]:
                status_color = {
                    "accepted": "green",
                    "rejected": "red",
                    "failed": "red",
                    "running": "yellow"
                }.get(run["status"], "white")
                
                console.print(f"  [{status_color}]Run {run['run_number']}:[/{status_color}] {run['status']}")
                if run["evidence_path"]:
                    console.print(f"    Evidence: {run['evidence_path']}")
                if run["duration_ms"]:
                    console.print(f"    Duration: {run['duration_ms']}ms")
    
    except httpx.HTTPError as e:
        console.print(f"[red]Error: {e}[/red]")

@cli.group()
def worker():
    """Worker commands."""
    pass

@worker.command("start")
@click.option("--worker-id", help="Worker ID (auto-generated if not provided)")
@click.option("--api-url", default="http://localhost:8042", help="API URL")
def worker_start(worker_id, api_url):
    """Start worker."""
    from grace_control.worker.worker import Worker
    
    console.print(f"[green]Starting worker...[/green]")
    if worker_id:
        console.print(f"[white]Worker ID:[/white] {worker_id}")
    console.print(f"[white]API URL:[/white] {api_url}")
    
    worker_instance = Worker(worker_id=worker_id, api_url=api_url)
    
    try:
        asyncio.run(worker_instance.start())
    except KeyboardInterrupt:
        console.print("\n[yellow]Worker stopped[/yellow]")

@cli.group()
def api():
    """API server commands."""
    pass

@api.command("start")
@click.option("--host", default="127.0.0.1", help="Host to bind")
@click.option("--port", default=8042, help="Port to bind")
def api_start(host, port):
    """Start API server."""
    import uvicorn
    from grace_control.api.main import app
    
    console.print(f"[green]Starting API server...[/green]")
    console.print(f"[white]URL:[/white] http://{host}:{port}")
    
    uvicorn.run(app, host=host, port=port)

@cli.command("health")
def health():
    """Check system health."""
    url = "http://localhost:8042/health"
    
    try:
        response = httpx.get(url)
        response.raise_for_status()
        data = response.json()
        
        status_color = {
            "healthy": "green",
            "degraded": "yellow",
            "unhealthy": "red"
        }.get(data["status"], "white")
        
        console.print(f"\n[bold]System Health:[/bold] [{status_color}]{data['status']}[/{status_color}]")
        console.print(f"[white]Workers:[/white]")
        console.print(f"  Active: {data['workers']['active']}")
        console.print(f"  Idle: {data['workers']['idle']}")
        console.print(f"  Dead: {data['workers']['dead']}")
        console.print(f"[white]Queue:[/white]")
        console.print(f"  Ready: {data['queue_depth']}")
        console.print(f"  Running: {data['running']}")
    
    except httpx.HTTPError as e:
        console.print(f"[red]Error: {e}[/red]")

if __name__ == "__main__":
    cli()
```

#### 2. Создать logging utilities

**src/grace_control/logging.py:**
```python
"""Logging utilities."""
import logging
import json
from datetime import datetime
from contextlib import contextmanager
from typing import Optional
import threading

# Thread-local storage for trace context
_trace_context = threading.local()

class GraceLogger:
    """
    Structured logger for GRACE Control Plane.
    
    Logs JSON-formatted messages with trace context.
    """
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(f"grace.{name}")
        self.logger.setLevel(logging.INFO)
        
        # Console handler
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(handler)
    
    def _log(self, level: str, message: str, **kwargs):
        """Log structured message."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": level,
            "message": message,
            **kwargs
        }
        
        # Add trace context if available
        trace_id = getattr(_trace_context, "trace_id", None)
        if trace_id:
            log_entry["trace_id"] = trace_id
        
        log_line = json.dumps(log_entry)
        
        if level == "ERROR":
            self.logger.error(log_line)
        elif level == "WARNING":
            self.logger.warning(log_line)
        elif level == "DEBUG":
            self.logger.debug(log_line)
        else:
            self.logger.info(log_line)
    
    def info(self, message: str, **kwargs):
        """Log info message."""
        self._log("INFO", message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """Log error message."""
        self._log("ERROR", message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning message."""
        self._log("WARNING", message, **kwargs)
    
    def debug(self, message: str, **kwargs):
        """Log debug message."""
        self._log("DEBUG", message, **kwargs)

@contextmanager
def trace_context(trace_id: str):
    """Set trace context for current thread."""
    _trace_context.trace_id = trace_id
    try:
        yield
    finally:
        _trace_context.trace_id = None
```

### Критерии готовности
- [ ] CLI main создан
- [ ] `grace architect plan <file>` работает
- [ ] `grace packet list` работает
- [ ] `grace packet get <id>` работает
- [ ] `grace worker start` работает
- [ ] `grace api start` работает
- [ ] `grace health` работает
- [ ] Rich formatting работает
- [ ] Logging utilities созданы

---

## Task #20: E2E Test

**Приоритет:** Критично
**Время:** 1 день
**Зависимости:** Task #19

### Описание
Создать E2E test для MVP-0 vertical slice.

**Test flow:**
1. Start API server
2. Create feature plan (architect)
3. Start worker
4. Worker claims packet
5. Worker executes packet
6. Verify packet state = ACCEPTED
7. Verify evidence saved

### Что делать

#### 1. Создать E2E test

**tests/test_e2e_mvp0.py:**
```python
"""
E2E test for MVP-0 vertical slice.

Tests full flow:
1. API server starts
2. Architect creates plan
3. Worker claims packet
4. Worker executes packet
5. Packet state = ACCEPTED
6. Evidence saved
"""
import pytest
import asyncio
import httpx
from pathlib import Path
import time

from grace_control.db import init_db
from grace_control.api.main import app
from grace_control.worker.worker import Worker

@pytest.fixture
async def api_server(tmp_path):
    """Start API server in background with shared test DB."""
    import uvicorn
    from multiprocessing import Process
    import os
    
    db_url = f"sqlite:///{tmp_path}/test.db"
    
    def run_server():
        # Передаём DB через env, чтобы server + test использовали одну базу
        os.environ["GRACE_DB_URL"] = db_url
        uvicorn.run(app, host="127.0.0.1", port=8043)
    
    server_process = Process(target=run_server)
    server_process.start()
    
    await asyncio.sleep(2)
    
    yield "http://localhost:8043", db_url
    
    server_process.terminate()
    server_process.join()

@pytest.mark.asyncio
async def test_mvp0_vertical_slice(api_server, tmp_path):
    """Test MVP-0 vertical slice."""
    api_base_url, db_url = api_server
    
    # 1. Initialize DB (shared between server and test)
    os.environ["GRACE_DB_URL"] = db_url
    from grace_control.db import init_db
    init_db(db_url)
    
    # 2. Create feature plan via architect (packets сразу READY)
    async with httpx.AsyncClient(base_url=api_base_url) as client:
        response = await client.post("/api/architect/plan", json={
            "feature_spec": {
                "title": "Test Feature",
                "description": "E2E test feature",
                "waves": [
                    {
                        "title": "Foundation",
                        "packets": [
                            {
                                "title": "Add test file",
                                "description": "Create test.py",
                                "scope": "src/test.py",
                                "acceptance_profile": "NORMAL"
                            }
                        ]
                    }
                ]
            }
        })
        assert response.status_code == 200
        data = response.json()["data"]
        feature_id = data["feature_id"]
        packet_id = data["packets"][0]
        
        print(f"✅ Feature created: {feature_id}")
        print(f"✅ Packet created (READY): {packet_id}")
    
    # 3. Start worker (in background)
    worker = Worker(
        worker_id="test-worker",
        api_url=api_base_url,
        project_root=tmp_path / "project",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "worktrees"
    )
    
    (tmp_path / "project").mkdir()
    (tmp_path / "state").mkdir()
    (tmp_path / "worktrees").mkdir()
    
    worker_task = asyncio.create_task(worker.start())
    
    # 4. Wait for packet execution
    max_wait = 60
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        async with httpx.AsyncClient(base_url=api_base_url) as client:
            response = await client.get(f"/api/packets/{packet_id}")
            data = response.json()["data"]
            
            if data["state"] in ["accepted", "rejected", "failed"]:
                break
        
        await asyncio.sleep(2)
    
    worker.running = False
    worker_task.cancel()
    
    # 5. Verify
    async with httpx.AsyncClient(base_url=api_base_url) as client:
        response = await client.get(f"/api/packets/{packet_id}")
        data = response.json()["data"]
        
        print(f"✅ Packet state: {data['state']}")
        assert data["state"] == "accepted", f"Expected accepted, got {data['state']}"
        
        assert len(data["runs"]) > 0, "No runs found"
        run = data["runs"][0]
        assert run["status"] == "accepted"
        assert run["evidence_path"] is not None
        
        print(f"✅ Evidence path: {run['evidence_path']}")
    
    print("\n✅ MVP-0 E2E test passed!")

@pytest.mark.asyncio
async def test_packet_rejection_retry(api_server, tmp_path):
    """Test packet rejection and retry."""
    # Similar to above but force rejection
    # Then verify retry mechanism
    pass
```

#### 2. Создать verification script

**scripts/verify_mvp0.sh:**
```bash
#!/bin/bash
set -e

echo "🚀 Verifying MVP-0 vertical slice..."

# 1. Start API server
echo "1️⃣ Starting API server..."
grace api start &
API_PID=$!
sleep 3

# 2. Check health
echo "2️⃣ Checking health..."
grace health

# 3. Create test feature (packets сразу READY)
echo "3️⃣ Creating test feature..."
grace architect plan test_feature.yaml

# 4. List packets
echo "4️⃣ Listing packets..."
grace packet list

# 5. Start worker
echo "5️⃣ Starting worker..."
grace worker start &
WORKER_PID=$!

# 6. Wait for execution
echo "6️⃣ Waiting for execution..."
sleep 30

# 7. Check packet status
echo "7️⃣ Checking packet status..."
grace packet list

# Cleanup
kill $API_PID $WORKER_PID

echo "✅ MVP-0 verification complete!"
```

### Критерии готовности
- [ ] E2E test создан
- [ ] Test проходит (full vertical slice)
- [ ] Verification script создан
- [ ] Script проходит
- [ ] Evidence сохраняется
- [ ] State transitions корректны

---

## Phase 3 Complete Checklist

### Все задачи Phase 3
- [ ] Task #19: CLI ✅
- [ ] Task #20: E2E Test ✅

### Deliverables
- ✅ CLI с основными командами (включая architect plan)
- ✅ E2E test для vertical slice
- ✅ Verification script
- ✅ Logging utilities

### MVP-0 Complete! 🎉

После Phase 3 у вас есть рабочий MVP-0:
- ✅ API server (без cancel endpoint)
- ✅ Worker loop (с lease mechanism)
- ✅ PacketExecutionAdapter (stateless bridge)
- ✅ CLI (architect plan + packet list/get + worker start + api start)
- ✅ E2E test (единая DB через GRACE_DB_URL)
- ✅ MVP-0 заканчивается на ACCEPTED (MERGED — post-MVP)

### Что НЕ в MVP-0
- ❌ UI/Dashboard
- ❌ Telegram
- ❌ WebSocket
- ❌ Cancellation
- ❌ Auto-merge (MVP-0 заканчивается на ACCEPTED)
- ❌ Multiple workers (parallel)
- ❌ GRACE Canon checker
- ❌ Complexity router

### Post-MVP Roadmap

**Wave 1:** Retry + Cancellation + Auto-merge (3 дня)
**Wave 2:** UI + Telegram (1 неделя)
**Wave 3:** GRACE Canon + Complexity Router (1 неделя)
**Wave 4:** Parallel execution (1 неделя)
