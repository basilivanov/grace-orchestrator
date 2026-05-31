# GRACE Control Plane — API-First Architecture

## 🎯 Новая архитектура

```text
┌─────────────────────────────────────────────────────────┐
│                     FastAPI Server                       │
│  - REST API для всех операций                           │
│  - WebSocket для real-time updates                      │
│  - Authentication & authorization                        │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                   Core Control Plane                     │
│  - State machine                                         │
│  - Worker loop                                           │
│  - Complexity router                                     │
│  - Acceptance checker                                    │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                  SQLite/Postgres DB                      │
└─────────────────────────────────────────────────────────┘

Клиенты:
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Web UI      │  │  CLI (thin)  │  │  Agents      │
│  (React)     │  │  (wrapper)   │  │  (API calls) │
└──────────────┘  └──────────────┘  └──────────────┘
       ↓                  ↓                  ↓
       └──────────────────┴──────────────────┘
                         ↓
                    REST API
```

---

## 1. FastAPI Server

### 1.1 Endpoints

#### Features & Packets

```python
# Features
POST   /api/features                    # Create feature from spec
GET    /api/features                    # List features
GET    /api/features/{feature_id}       # Get feature details
DELETE /api/features/{feature_id}       # Delete feature

# Architect
POST   /api/architect/plan              # Generate plan from spec
GET    /api/architect/status            # Architect status

# Packets
GET    /api/packets                     # List packets (with filters)
GET    /api/packets/{packet_id}         # Get packet details
POST   /api/packets/{packet_id}/enqueue # Enqueue packet
POST   /api/packets/{packet_id}/accept  # Accept packet
POST   /api/packets/{packet_id}/reject  # Reject packet
GET    /api/packets/{packet_id}/events  # Get packet events
GET    /api/packets/{packet_id}/evidence # Get packet evidence
GET    /api/packets/{packet_id}/logs    # Get packet logs

# Packet runs
GET    /api/packets/{packet_id}/runs    # List runs for packet
GET    /api/runs/{run_id}               # Get run details
GET    /api/runs/{run_id}/logs          # Stream logs
```

#### Workers

```python
# Workers
GET    /api/workers                     # List workers
GET    /api/workers/{worker_id}         # Get worker details
POST   /api/workers/{worker_id}/stop    # Stop worker
DELETE /api/workers/{worker_id}         # Remove worker

# Worker registration (called by worker process)
POST   /api/workers/register            # Register new worker
POST   /api/workers/{worker_id}/heartbeat # Send heartbeat
POST   /api/workers/{worker_id}/claim   # Claim next packet
POST   /api/workers/{worker_id}/release # Release packet
```

#### System

```python
# Health & status
GET    /api/health                      # Health check
GET    /api/status                      # System status
GET    /api/metrics                     # Metrics

# Configuration
GET    /api/config                      # Get config
POST   /api/config/validate             # Validate config

# Database
POST   /api/db/migrate                  # Run migrations
GET    /api/db/status                   # DB status
```

#### WebSocket

```python
# Real-time updates
WS     /api/ws/packets                  # Subscribe to packet updates
WS     /api/ws/workers                  # Subscribe to worker updates
WS     /api/ws/logs/{run_id}            # Stream logs for run
```

### 1.2 Request/Response models

```python
# POST /api/architect/plan
class ArchitectPlanRequest(BaseModel):
    feature_spec: str  # YAML content
    execute: bool = True

class ArchitectPlanResponse(BaseModel):
    feature_id: str
    waves: list[Wave]
    packets: list[Packet]
    total_packets: int

# GET /api/packets
class PacketListResponse(BaseModel):
    packets: list[PacketSummary]
    total: int
    page: int
    page_size: int

class PacketSummary(BaseModel):
    id: str
    title: str
    state: PacketState
    acceptance_profile: AcceptanceProfile
    created_at: datetime
    updated_at: datetime

# GET /api/packets/{packet_id}
class PacketDetail(BaseModel):
    id: str
    feature_id: str
    wave_id: str
    title: str
    description: str
    state: PacketState
    complexity: Complexity
    risk: Risk
    acceptance_profile: AcceptanceProfile
    scope: list[str]
    depends_on: list[str]
    created_at: datetime
    updated_at: datetime
    current_run: PacketRun | None
    last_events: list[Event]

# POST /api/packets/{packet_id}/accept
class AcceptPacketRequest(BaseModel):
    reason: str | None = None
    override_policy: bool = False

class AcceptPacketResponse(BaseModel):
    packet_id: str
    state: PacketState
    event_id: str
```

### 1.3 FastAPI app structure

```python
# src/grace_control/api/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="GRACE Control Plane API",
    version="1.0.0",
    description="API for GRACE packet orchestration"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from grace_control.api.routers import (
    features,
    packets,
    workers,
    architect,
    system,
)

app.include_router(features.router, prefix="/api/features", tags=["features"])
app.include_router(packets.router, prefix="/api/packets", tags=["packets"])
app.include_router(workers.router, prefix="/api/workers", tags=["workers"])
app.include_router(architect.router, prefix="/api/architect", tags=["architect"])
app.include_router(system.router, prefix="/api", tags=["system"])

# WebSocket
from grace_control.api.websocket import router as ws_router
app.include_router(ws_router, prefix="/api/ws")

@app.get("/api/health")
def health():
    return {"status": "ok"}
```

---

## 2. Упрощённый CLI (тонкая обёртка над API)

### 2.1 CLI как API client

```python
# src/grace_control/cli/client.py
import httpx
from typing import Any

class GraceAPIClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url)
    
    def architect_plan(self, feature_spec_path: str) -> dict[str, Any]:
        """Generate plan from feature spec."""
        spec = Path(feature_spec_path).read_text()
        response = self.client.post(
            "/api/architect/plan",
            json={"feature_spec": spec, "execute": True}
        )
        response.raise_for_status()
        return response.json()
    
    def list_packets(self, state: str | None = None) -> list[dict]:
        """List packets."""
        params = {"state": state} if state else {}
        response = self.client.get("/api/packets", params=params)
        response.raise_for_status()
        return response.json()["packets"]
    
    def get_packet(self, packet_id: str) -> dict[str, Any]:
        """Get packet details."""
        response = self.client.get(f"/api/packets/{packet_id}")
        response.raise_for_status()
        return response.json()
    
    def accept_packet(self, packet_id: str, reason: str | None = None):
        """Accept packet."""
        response = self.client.post(
            f"/api/packets/{packet_id}/accept",
            json={"reason": reason}
        )
        response.raise_for_status()
        return response.json()

# src/grace_control/cli/commands.py
import click
from grace_control.cli.client import GraceAPIClient

@click.group()
@click.option("--api-url", default="http://localhost:8000", envvar="GRACE_API_URL")
@click.pass_context
def cli(ctx, api_url):
    """GRACE Control Plane CLI"""
    ctx.obj = GraceAPIClient(base_url=api_url)

@cli.group()
def architect():
    """Architect commands"""
    pass

@architect.command("plan")
@click.argument("feature_spec")
@click.pass_obj
def architect_plan(client: GraceAPIClient, feature_spec: str):
    """Generate implementation plan from feature spec."""
    result = client.architect_plan(feature_spec)
    click.echo(f"✓ Created feature {result['feature_id']}")
    click.echo(f"✓ Created {result['total_packets']} packets")
    click.echo("\nRun: grace worker start")

@cli.group()
def packet():
    """Packet commands"""
    pass

@packet.command("list")
@click.option("--state", help="Filter by state")
@click.pass_obj
def packet_list(client: GraceAPIClient, state: str | None):
    """List packets."""
    packets = client.list_packets(state=state)
    
    from rich.console import Console
    from rich.table import Table
    
    console = Console()
    table = Table(title="Packets")
    table.add_column("ID", style="cyan")
    table.add_column("Title")
    table.add_column("State", style="green")
    table.add_column("Profile")
    
    for p in packets:
        table.add_row(p["id"], p["title"], p["state"], p["acceptance_profile"])
    
    console.print(table)

@packet.command("status")
@click.argument("packet_id")
@click.pass_obj
def packet_status(client: GraceAPIClient, packet_id: str):
    """Show packet status."""
    packet = client.get_packet(packet_id)
    
    from rich.console import Console
    from rich.panel import Panel
    
    console = Console()
    
    content = f"""
[bold]Packet:[/bold] {packet['id']}
[bold]Title:[/bold] {packet['title']}
[bold]State:[/bold] {packet['state']}
[bold]Profile:[/bold] {packet['acceptance_profile']}
[bold]Complexity:[/bold] {packet['complexity']}
[bold]Risk:[/bold] {packet['risk']}
    """
    
    console.print(Panel(content, title="Packet Status"))

@cli.group()
def worker():
    """Worker commands"""
    pass

@worker.command("start")
@click.pass_obj
def worker_start(client: GraceAPIClient):
    """Start worker (connects to API)."""
    # Worker process делает API calls
    from grace_control.worker.loop import start_worker
    start_worker(api_client=client)
```

### 2.2 CLI для агентов (agent-friendly)

Агенты могут вызывать CLI команды, которые делают API calls:

```bash
# Агент может вызвать:
grace packet list --state READY --format json
grace packet status PKT-001 --format json
grace packet accept PKT-001 --reason "All tests passed"

# CLI возвращает JSON для парсинга агентом
```

Или агенты могут напрямую вызывать API:

```bash
curl -X POST http://localhost:8000/api/packets/PKT-001/accept \
  -H "Content-Type: application/json" \
  -d '{"reason": "All tests passed"}'
```

---

## 3. Worker как API client

### 3.1 Worker loop

```python
# src/grace_control/worker/loop.py
import time
from grace_control.cli.client import GraceAPIClient
from grace_control.platform.e2e_packet_runner import run_e2e_packet

def start_worker(api_client: GraceAPIClient):
    """Start worker loop."""
    
    # Register worker
    worker_id = register_worker(api_client)
    
    print(f"Worker {worker_id} started")
    
    # Start heartbeat thread
    import threading
    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        args=(api_client, worker_id),
        daemon=True
    )
    heartbeat_thread.start()
    
    # Main loop
    while True:
        try:
            # Claim next packet via API
            packet = claim_packet(api_client, worker_id)
            
            if not packet:
                time.sleep(5)
                continue
            
            print(f"Claimed packet {packet['id']}")
            
            # Execute packet (используем существующий код)
            result = run_e2e_packet(
                packet_id=packet['id'],
                project_root=config.project_root,
                state_root=config.state_root,
                worktree_root=config.worktree_root,
            )
            
            # Report result via API
            report_result(api_client, packet['id'], result)
            
        except KeyboardInterrupt:
            print("Stopping worker...")
            unregister_worker(api_client, worker_id)
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

def register_worker(client: GraceAPIClient) -> str:
    """Register worker via API."""
    response = client.client.post("/api/workers/register", json={
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
    })
    response.raise_for_status()
    return response.json()["worker_id"]

def claim_packet(client: GraceAPIClient, worker_id: str) -> dict | None:
    """Claim next packet via API."""
    response = client.client.post(f"/api/workers/{worker_id}/claim")
    if response.status_code == 404:
        return None  # No packets available
    response.raise_for_status()
    return response.json()

def heartbeat_loop(client: GraceAPIClient, worker_id: str):
    """Send heartbeat every 30s."""
    while True:
        try:
            client.client.post(f"/api/workers/{worker_id}/heartbeat")
        except Exception as e:
            print(f"Heartbeat failed: {e}")
        time.sleep(30)
```

---

## 4. Web UI (будущее)

### 4.1 React dashboard

```typescript
// src/ui/components/PacketList.tsx
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

export function PacketList() {
  const { data, isLoading } = useQuery({
    queryKey: ['packets'],
    queryFn: () => api.get('/api/packets').then(r => r.data)
  });
  
  if (isLoading) return <div>Loading...</div>;
  
  return (
    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>Title</th>
          <th>State</th>
          <th>Profile</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {data.packets.map(packet => (
          <tr key={packet.id}>
            <td>{packet.id}</td>
            <td>{packet.title}</td>
            <td><Badge>{packet.state}</Badge></td>
            <td>{packet.acceptance_profile}</td>
            <td>
              <Button onClick={() => viewPacket(packet.id)}>View</Button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

### 4.2 Real-time updates via WebSocket

```typescript
// src/ui/hooks/usePacketUpdates.ts
import { useEffect, useState } from 'react';

export function usePacketUpdates() {
  const [packets, setPackets] = useState([]);
  
  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/api/ws/packets');
    
    ws.onmessage = (event) => {
      const update = JSON.parse(event.data);
      setPackets(prev => updatePacket(prev, update));
    };
    
    return () => ws.close();
  }, []);
  
  return packets;
}
```

---

## 5. Преимущества API-first

### 5.1 Гибкость

✅ **Множество клиентов:**
- Web UI (React)
- CLI (thin wrapper)
- Agents (прямые API calls)
- CI/CD integrations
- Monitoring tools

✅ **Независимая разработка:**
- Backend API развивается отдельно
- Frontend развивается отдельно
- CLI — просто обёртка

✅ **Тестирование:**
- API легко тестировать (pytest + httpx)
- Можно мокировать API для UI тестов
- E2E тесты через API

### 5.2 Масштабируемость

✅ **Horizontal scaling:**
- API server можно масштабировать (load balancer)
- Workers могут быть на разных машинах
- DB — единая точка истины

✅ **Async operations:**
- Long-running operations через WebSocket
- Background tasks через worker queue
- Real-time updates для UI

### 5.3 Agent-friendly

✅ **Агенты могут:**
- Вызывать CLI команды (возвращают JSON)
- Делать прямые API calls (curl/httpx)
- Подписываться на WebSocket для updates
- Парсить structured responses

```python
# Агент может сделать:
import httpx

response = httpx.post(
    "http://localhost:8000/api/architect/plan",
    json={"feature_spec": spec_yaml}
)
plan = response.json()

for packet in plan["packets"]:
    print(f"Created packet: {packet['id']}")
```

---

## 6. Упрощённая архитектура проекта

```
grace-control/
├── src/
│   └── grace_control/
│       ├── api/                    # FastAPI server
│       │   ├── main.py
│       │   ├── routers/
│       │   │   ├── features.py
│       │   │   ├── packets.py
│       │   │   ├── workers.py
│       │   │   ├── architect.py
│       │   │   └── system.py
│       │   ├── websocket.py
│       │   └── models.py           # Pydantic models
│       │
│       ├── core/                   # Core logic
│       │   ├── state_machine.py
│       │   ├── complexity_router.py
│       │   ├── acceptance_checker.py
│       │   └── db.py               # SQLAlchemy models
│       │
│       ├── worker/                 # Worker process
│       │   ├── loop.py
│       │   └── executor.py
│       │
│       ├── cli/                    # Thin CLI wrapper
│       │   ├── client.py           # API client
│       │   └── commands.py         # Click commands
│       │
│       ├── platform/               # Existing code (reuse)
│       │   ├── e2e_packet_runner.py
│       │   ├── worktree_manager.py
│       │   └── ...
│       │
│       └── models.py               # Domain models
│
├── ui/                             # Future: React UI
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   └── api/
│   └── package.json
│
├── tests/
│   ├── api/                        # API tests
│   ├── core/                       # Core logic tests
│   └── integration/                # E2E tests
│
└── pyproject.toml
```

---

## 7. Запуск системы

### 7.1 Development

```bash
# Terminal 1: Start API server
grace-api serve --reload

# Terminal 2: Start worker
grace worker start

# Terminal 3: Use CLI
grace architect plan my-feature.yaml
grace packet list
```

### 7.2 Production

```bash
# API server (uvicorn)
uvicorn grace_control.api.main:app --host 0.0.0.0 --port 8000 --workers 4

# Workers (systemd service)
systemctl start grace-worker@1
systemctl start grace-worker@2

# CLI (connects to API)
export GRACE_API_URL=http://api.grace.internal:8000
grace packet list
```

### 7.3 Docker Compose

```yaml
version: '3.8'

services:
  api:
    build: .
    command: uvicorn grace_control.api.main:app --host 0.0.0.0
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://grace:pass@db/grace
    depends_on:
      - db
  
  worker:
    build: .
    command: grace worker start
    environment:
      GRACE_API_URL: http://api:8000
      DATABASE_URL: postgresql://grace:pass@db/grace
    depends_on:
      - api
    deploy:
      replicas: 2
  
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: grace
      POSTGRES_USER: grace
      POSTGRES_PASSWORD: pass
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

---

## 8. Migration path

### Phase 1: API server (1 неделя)

```text
✓ FastAPI app structure
✓ Basic endpoints (packets, workers)
✓ DB integration (SQLAlchemy)
✓ API tests
```

### Phase 2: Worker (1 неделя)

```text
✓ Worker loop as API client
✓ Claim/release via API
✓ Heartbeat via API
✓ Integration with existing run_e2e_packet
```

### Phase 3: CLI wrapper (2-3 дня)

```text
✓ API client class
✓ Click commands
✓ Rich output formatting
✓ JSON output for agents
```

### Phase 4: Web UI (опционально, 2-3 недели)

```text
✓ React app
✓ Packet list/detail pages
✓ Worker status page
✓ Real-time updates via WebSocket
```

---

## 9. Обновлённое ТЗ

Нужно обновить `GRACE_CONTROL_PLANE_SPEC.md`:

1. ✅ Заменить CLI-first на API-first
2. ✅ Добавить FastAPI endpoints
3. ✅ Упростить CLI до thin wrapper
4. ✅ Добавить WebSocket для real-time
5. ✅ Добавить Web UI roadmap

Хотите чтобы я обновил основное ТЗ?
