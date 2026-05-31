# Phase 2: API & Worker (REVISED)

**Длительность:** 1 неделя (7 дней)
**Цель:** Создать FastAPI server и worker loop (MVP-0 scope)

**ВАЖНО:** Следуйте CANONICAL_DECISIONS.md и docs/API_CONTRACT.md

---

## Task #18: Implement FastAPI Server

**Приоритет:** Критично
**Время:** 3 дня
**Зависимости:** Phase 1 complete

### Описание
Создать FastAPI server с endpoints из API_CONTRACT.md.

**MVP-0 scope:** Только API endpoints, БЕЗ UI/WebSocket/Telegram.

### Что делать

#### 1. Создать FastAPI app

**src/grace_control/api/main.py:**
```python
"""
FastAPI server for GRACE Control Plane.

CANONICAL: See docs/API_CONTRACT.md for all endpoints.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

from grace_control.db import init_db
from grace_control.api.routers import features, packets, workers, architect

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events."""
    # Startup
    init_db()
    yield
    # Shutdown
    pass

app = FastAPI(
    title="GRACE Control Plane",
    version="0.1.0",
    lifespan=lifespan
)

# CORS - localhost only (MVP security)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:*"],  # NOT "*"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(features.router, prefix="/api/features", tags=["features"])
app.include_router(packets.router, prefix="/api/packets", tags=["packets"])
app.include_router(workers.router, prefix="/api/workers", tags=["workers"])
app.include_router(architect.router, prefix="/api/architect", tags=["architect"])

@app.get("/health")
async def health():
    """Health check endpoint."""
    from grace_control.core.health import check_health
    return await check_health()

def main():
    """Run server."""
    uvicorn.run(
        "grace_control.api.main:app",
        host="127.0.0.1",  # localhost only (NOT 0.0.0.0)
        port=8000,
        reload=True
    )

if __name__ == "__main__":
    main()
```

#### 2. Создать routers

**src/grace_control/api/routers/features.py:**
```python
"""Features API router."""
from fastapi import APIRouter, HTTPException
from typing import List
from pydantic import BaseModel
from datetime import datetime

from grace_control.db import get_db
from grace_control.db.schema import Feature

router = APIRouter()

class FeatureResponse(BaseModel):
    id: str
    slug: str
    title: str
    description: str
    status: str
    created_at: str
    updated_at: str

@router.get("/")
async def list_features() -> dict:
    """List all features."""
    with get_db() as db:
        features = db.query(Feature).all()
        return {
            "data": [
                {
                    "id": f.id,
                    "slug": f.slug,
                    "title": f.title,
                    "description": f.description or "",
                    "status": f.status,
                    "created_at": f.created_at.isoformat() + "Z",
                    "updated_at": f.updated_at.isoformat() + "Z"
                }
                for f in features
            ],
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

@router.get("/{feature_id}")
async def get_feature(feature_id: str) -> dict:
    """Get feature by ID."""
    with get_db() as db:
        feature = db.query(Feature).filter_by(id=feature_id).first()
        if not feature:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        return {
            "data": {
                "id": feature.id,
                "slug": feature.slug,
                "title": feature.title,
                "description": feature.description or "",
                "status": feature.status,
                "spec_json": feature.spec_json,
                "created_at": feature.created_at.isoformat() + "Z",
                "updated_at": feature.updated_at.isoformat() + "Z"
            },
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
```

**src/grace_control/api/routers/packets.py:**
```python
"""Packets API router."""
from fastapi import APIRouter, HTTPException
from typing import Optional
from datetime import datetime, timedelta

from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketState, PacketRun, Lease, Worker

router = APIRouter()

@router.get("/")
async def list_packets(state: Optional[str] = None, feature_id: Optional[str] = None) -> dict:
    """List packets with optional filters."""
    with get_db() as db:
        query = db.query(Packet)
        
        if state:
            try:
                state_enum = PacketState[state.upper()]
                query = query.filter_by(state=state_enum)
            except KeyError:
                raise HTTPException(status_code=400, detail=f"Invalid state: {state}")
        
        if feature_id:
            query = query.filter_by(feature_id=feature_id)
        
        packets = query.all()
        
        return {
            "data": [
                {
                    "id": p.id,
                    "feature_id": p.feature_id,
                    "wave_id": p.wave_id,
                    "slug": p.slug,
                    "title": p.title,
                    "state": p.state.value,
                    "acceptance_profile": p.acceptance_profile,
                    "attempt_count": p.attempt_count,
                    "max_attempts": p.max_attempts,
                    "created_at": p.created_at.isoformat() + "Z",
                    "updated_at": p.updated_at.isoformat() + "Z"
                }
                for p in packets
            ],
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

@router.get("/{packet_id}")
async def get_packet(packet_id: str) -> dict:
    """Get packet by ID."""
    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            raise HTTPException(status_code=404, detail="Packet not found")
        
        # Get runs
        runs = db.query(PacketRun).filter_by(packet_id=packet_id).all()
        
        return {
            "data": {
                "id": packet.id,
                "feature_id": packet.feature_id,
                "wave_id": packet.wave_id,
                "slug": packet.slug,
                "title": packet.title,
                "description": packet.description or "",
                "state": packet.state.value,
                "acceptance_profile": packet.acceptance_profile,
                "attempt_count": packet.attempt_count,
                "max_attempts": packet.max_attempts,
                "spec_json": packet.spec_json,
                "runs": [
                    {
                        "id": r.id,
                        "run_number": r.run_number,
                        "status": r.status,
                        "evidence_path": r.evidence_path,
                        "started_at": r.started_at.isoformat() + "Z" if r.started_at else None,
                        "finished_at": r.finished_at.isoformat() + "Z" if r.finished_at else None,
                        "duration_ms": r.duration_ms
                    }
                    for r in runs
                ],
                "created_at": packet.created_at.isoformat() + "Z",
                "updated_at": packet.updated_at.isoformat() + "Z"
            },
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

@router.post("/claim")
async def claim_packet(request: dict) -> dict:
    """
    Claim next available packet (worker operation).
    
    SQLite-safe lease mechanism (no FOR UPDATE SKIP LOCKED).
    """
    worker_id = request["worker_id"]
    
    with get_db() as db:
        # Find READY packet without active lease
        ready_packets = db.query(Packet).filter_by(state=PacketState.READY).all()
        
        for packet in ready_packets:
            # Check if already leased
            existing_lease = db.query(Lease).filter_by(packet_id=packet.id).first()
            
            if existing_lease:
                # Check if expired
                if existing_lease.expires_at > datetime.utcnow():
                    continue  # Still active, skip
                else:
                    # Expired, remove
                    db.delete(existing_lease)
            
            # Claim this packet
            lease = Lease(
                packet_id=packet.id,
                worker_id=worker_id,
                expires_at=datetime.utcnow() + timedelta(minutes=30)
            )
            db.add(lease)
            
            # Update packet state
            packet.state = PacketState.RUNNING
            
            # Update worker
            worker = db.query(Worker).filter_by(id=worker_id).first()
            if worker:
                worker.current_packet_id = packet.id
            
            return {
                "data": {
                    "packet_id": packet.id,
                    "spec": packet.spec_json,
                    "lease_id": lease.id,
                    "expires_at": lease.expires_at.isoformat() + "Z"
                },
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        
        # No packets available
        raise HTTPException(status_code=404, detail="No packets available")

@router.post("/{packet_id}/release")
async def release_packet(packet_id: str, request: dict) -> dict:
    """Release packet after execution."""
    worker_id = request["worker_id"]
    status = request["status"]
    result = request["result"]
    
    with get_db() as db:
        # Remove lease
        lease = db.query(Lease).filter_by(packet_id=packet_id).first()
        if lease:
            db.delete(lease)
        
        # Update packet
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            raise HTTPException(status_code=404, detail="Packet not found")
        
        # Update state based on result
        if status == "accepted" and result.get("accepted"):
            packet.state = PacketState.ACCEPTED
        elif status == "rejected":
            packet.state = PacketState.REJECTED
        else:
            packet.state = PacketState.FAILED
        
        # Update worker
        worker = db.query(Worker).filter_by(id=worker_id).first()
        if worker:
            worker.current_packet_id = None
            worker.status = "idle"
        
        return {
            "data": {
                "packet_id": packet.id,
                "state": packet.state.value,
                "released": True
            },
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
```

**src/grace_control/api/routers/workers.py:**
```python
"""Workers API router."""
from fastapi import APIRouter, HTTPException
from datetime import datetime

from grace_control.db import get_db
from grace_control.db.schema import Worker

router = APIRouter()

@router.get("/")
async def list_workers() -> dict:
    """List all workers."""
    with get_db() as db:
        workers = db.query(Worker).all()
        return {
            "data": [
                {
                    "id": w.id,
                    "status": w.status,
                    "current_packet_id": w.current_packet_id,
                    "last_heartbeat": w.last_heartbeat.isoformat() + "Z" if w.last_heartbeat else None,
                    "started_at": w.started_at.isoformat() + "Z"
                }
                for w in workers
            ],
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

@router.post("/register")
async def register_worker(request: dict) -> dict:
    """Register new worker."""
    worker_id = request["worker_id"]
    
    with get_db() as db:
        # Check if exists
        existing = db.query(Worker).filter_by(id=worker_id).first()
        if existing:
            # Update
            existing.status = "active"
            existing.last_heartbeat = datetime.utcnow()
        else:
            # Create
            worker = Worker(
                id=worker_id,
                status="active",
                last_heartbeat=datetime.utcnow()
            )
            db.add(worker)
        
        return {
            "data": {
                "worker_id": worker_id,
                "status": "registered"
            },
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

@router.post("/heartbeat")
async def worker_heartbeat(request: dict) -> dict:
    """Worker heartbeat."""
    worker_id = request["worker_id"]
    
    with get_db() as db:
        worker = db.query(Worker).filter_by(id=worker_id).first()
        if not worker:
            raise HTTPException(status_code=404, detail="Worker not found")
        
        worker.last_heartbeat = datetime.utcnow()
        worker.status = "active"
        
        return {
            "data": {
                "worker_id": worker_id,
                "status": "ok",
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        }
```

**src/grace_control/api/routers/architect.py:**
```python
"""Architect API router."""
from fastapi import APIRouter
from datetime import datetime

from grace_control.db import get_db
from grace_control.db.schema import Feature, Wave, Packet, PacketState

router = APIRouter()

@router.post("/plan")
async def create_plan(request: dict) -> dict:
    """
    Create execution plan from feature spec.
    
    Generates hierarchical IDs and creates packets.
    """
    feature_spec = request["feature_spec"]
    
    # Generate feature ID
    feature_slug = _slugify(feature_spec["title"])
    feature_id = f"FEAT-{feature_slug.upper()}"
    
    packets_created = []
    
    with get_db() as db:
        # Create feature
        feature = Feature(
            id=feature_id,
            slug=feature_slug,
            title=feature_spec["title"],
            description=feature_spec.get("description", ""),
            spec_json=feature_spec,
            status="NOT_STARTED"
        )
        db.add(feature)
        
        # Create waves and packets
        for i, wave_spec in enumerate(feature_spec.get("waves", []), 1):
            wave_slug = _slugify(wave_spec["title"])
            wave_id = f"W{i:02d}-{wave_slug.upper()}"
            
            wave = Wave(
                id=wave_id,
                feature_id=feature_id,
                slug=wave_slug,
                title=wave_spec["title"],
                description=wave_spec.get("description", ""),
                order=i,
                status="NOT_STARTED"
            )
            db.add(wave)
            
            # Create packets
            for j, packet_spec in enumerate(wave_spec.get("packets", []), 1):
                packet_slug = _slugify(packet_spec["title"])
                action = _extract_action(packet_spec["title"])
                packet_id = f"{feature_id}-{wave_id}-P{j:02d}-{action}"
                
                packet = Packet(
                    id=packet_id,
                    feature_id=feature_id,
                    wave_id=wave_id,
                    slug=packet_slug,
                    title=packet_spec["title"],
                    description=packet_spec.get("description", ""),
                    spec_json=packet_spec,
                    state=PacketState.DRAFT,
                    acceptance_profile=packet_spec.get("acceptance_profile", "NORMAL")
                )
                db.add(packet)
                packets_created.append(packet_id)
    
    return {
        "data": {
            "feature_id": feature_id,
            "waves_count": len(feature_spec.get("waves", [])),
            "packets_count": len(packets_created),
            "packets": packets_created
        },
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

def _slugify(text: str) -> str:
    """Convert text to slug."""
    return text.lower().replace(" ", "-").replace("_", "-")

def _extract_action(title: str) -> str:
    """Extract action from title."""
    words = title.split()
    if len(words) > 0:
        action = words[0].upper()
        rest = "-".join(words[1:3]).upper().replace(" ", "-") if len(words) > 1 else ""
        return f"{action}-{rest}" if rest else action
    return "ACTION"
```

#### 3. Создать health check

**src/grace_control/core/health.py:**
```python
"""Health check implementation."""
from datetime import datetime, timedelta
from grace_control.db import get_db
from grace_control.db.schema import Worker, Packet, PacketState

async def check_health() -> dict:
    """Check system health."""
    with get_db() as db:
        # Check workers
        workers = db.query(Worker).all()
        active_workers = [w for w in workers if w.status == "active"]
        dead_workers = [
            w for w in workers
            if w.last_heartbeat and
            datetime.utcnow() - w.last_heartbeat > timedelta(minutes=5)
        ]
        
        # Check queue
        ready_packets = db.query(Packet).filter_by(state=PacketState.READY).count()
        running_packets = db.query(Packet).filter_by(state=PacketState.RUNNING).count()
        
        # Overall status
        status = "healthy"
        if len(dead_workers) > 0:
            status = "degraded"
        if len(active_workers) == 0:
            status = "unhealthy"
        
        return {
            "status": status,
            "workers": {
                "active": len(active_workers),
                "idle": len([w for w in active_workers if not w.current_packet_id]),
                "dead": len(dead_workers)
            },
            "queue_depth": ready_packets,
            "running": running_packets,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
```

### Критерии готовности
- [ ] FastAPI app создан
- [ ] Все routers реализованы (features, packets, workers, architect)
- [ ] Health check работает
- [ ] CORS настроен (localhost only)
- [ ] Bind на 127.0.0.1 (NOT 0.0.0.0)
- [ ] SQLite-safe lease mechanism
- [ ] Тесты проходят
- [ ] Server запускается: `grace-api`

---

## Task #21: Implement Worker Loop

**Приоритет:** Критично
**Время:** 4 дня
**Зависимости:** Task #18, Phase 1 complete

### Описание
Создать worker loop с lease mechanism и интеграцией с PacketExecutionAdapter.

### Что делать

#### 1. Создать API client

**src/grace_control/worker/api_client.py:**
```python
"""API client for worker."""
import httpx
from typing import Optional
from pydantic import BaseModel

class PacketClaim(BaseModel):
    """Claimed packet."""
    packet_id: str
    spec: dict
    lease_id: int
    expires_at: str

class WorkerAPIClient:
    """API client for worker to communicate with Control Plane."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
    
    async def register(self, worker_id: str):
        """Register worker."""
        response = await self.client.post("/api/workers/register", json={
            "worker_id": worker_id
        })
        response.raise_for_status()
        return response.json()
    
    async def heartbeat(self, worker_id: str):
        """Send heartbeat."""
        response = await self.client.post("/api/workers/heartbeat", json={
            "worker_id": worker_id
        })
        response.raise_for_status()
        return response.json()
    
    async def claim_packet(self, worker_id: str) -> Optional[PacketClaim]:
        """Claim next available packet."""
        try:
            response = await self.client.post("/api/packets/claim", json={
                "worker_id": worker_id
            })
            response.raise_for_status()
            data = response.json()["data"]
            return PacketClaim(**data)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None  # No packets available
            raise
    
    async def release_packet(self, packet_id: str, worker_id: str, status: str, result: dict):
        """Release packet after execution."""
        response = await self.client.post(f"/api/packets/{packet_id}/release", json={
            "worker_id": worker_id,
            "status": status,
            "result": result
        })
        response.raise_for_status()
        return response.json()
    
    async def close(self):
        """Close client."""
        await self.client.aclose()
```

#### 2. Создать worker loop

**src/grace_control/worker/worker.py:**
```python
"""Worker loop implementation."""
import asyncio
from pathlib import Path
import uuid
from typing import Optional

from grace_control.worker.api_client import WorkerAPIClient
from grace_control.adapters.packet_executor import PacketExecutionAdapter
from grace_control.logging import GraceLogger, trace_context

logger = GraceLogger("worker")

class Worker:
    """
    Worker process.
    
    Responsibilities:
    - Register with Control Plane
    - Send heartbeat every 30s
    - Claim packets from queue
    - Execute packets via PacketExecutionAdapter
    - Release packets with results
    """
    
    def __init__(
        self,
        worker_id: Optional[str] = None,
        api_url: str = "http://localhost:8000",
        heartbeat_interval: int = 30,
        project_root: Optional[Path] = None,
        state_root: Optional[Path] = None,
        worktree_root: Optional[Path] = None
    ):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.api_client = WorkerAPIClient(api_url)
        self.heartbeat_interval = heartbeat_interval
        self.running = False
        
        # Paths for PacketExecutionAdapter
        self.project_root = project_root or Path.cwd()
        self.state_root = state_root or Path.cwd() / ".grace"
        self.worktree_root = worktree_root or Path.cwd() / ".grace/worktrees"
        
        # Create adapter
        self.executor = PacketExecutionAdapter(
            project_root=self.project_root,
            state_root=self.state_root,
            worktree_root=self.worktree_root
        )
    
    async def start(self):
        """Start worker loop."""
        logger.info("Worker starting", worker_id=self.worker_id)
        
        # Register
        await self.api_client.register(self.worker_id)
        logger.info("Worker registered", worker_id=self.worker_id)
        
        self.running = True
        
        # Start heartbeat task
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        # Main loop
        try:
            await self._main_loop()
        finally:
            self.running = False
            heartbeat_task.cancel()
            await self.api_client.close()
    
    async def _main_loop(self):
        """Main worker loop."""
        while self.running:
            try:
                # Claim packet
                claim = await self.api_client.claim_packet(self.worker_id)
                
                if not claim:
                    # No packets available, wait
                    logger.debug("No packets available", worker_id=self.worker_id)
                    await asyncio.sleep(5)
                    continue
                
                logger.info(
                    "Packet claimed",
                    worker_id=self.worker_id,
                    packet_id=claim.packet_id
                )
                
                # Execute packet
                with trace_context(claim.packet_id):
                    result = await self._execute_packet(claim)
                
                # Release packet
                await self.api_client.release_packet(
                    claim.packet_id,
                    self.worker_id,
                    status="accepted" if result.accepted else "rejected",
                    result=result.dict()
                )
                
                logger.info(
                    "Packet released",
                    worker_id=self.worker_id,
                    packet_id=claim.packet_id,
                    accepted=result.accepted
                )
            
            except Exception as e:
                logger.error(
                    "Error in worker loop",
                    worker_id=self.worker_id,
                    error=str(e)
                )
                await asyncio.sleep(10)
    
    async def _heartbeat_loop(self):
        """Send heartbeat periodically."""
        while self.running:
            try:
                await self.api_client.heartbeat(self.worker_id)
                logger.debug("Heartbeat sent", worker_id=self.worker_id)
            except Exception as e:
                logger.error("Heartbeat failed", error=str(e))
            
            await asyncio.sleep(self.heartbeat_interval)
    
    async def _execute_packet(self, claim):
        """Execute packet via PacketExecutionAdapter."""
        logger.info("Starting packet execution", packet_id=claim.packet_id)
        
        try:
            result = await self.executor.execute(claim.packet_id, self.worker_id)
            return result
        
        except Exception as e:
            logger.error(
                "Packet execution failed",
                packet_id=claim.packet_id,
                error=str(e)
            )
            raise

async def main():
    """Run worker."""
    worker = Worker()
    await worker.start()

if __name__ == "__main__":
    asyncio.run(main())
```

#### 3. Создать CLI command

**src/grace_control/worker/__main__.py:**
```python
"""Worker CLI entry point."""
import asyncio
from grace_control.worker.worker import main

if __name__ == "__main__":
    asyncio.run(main())
```

#### 4. Создать тесты

**tests/test_worker.py:**
```python
"""Test worker."""
import pytest
from grace_control.worker.api_client import WorkerAPIClient

@pytest.mark.asyncio
async def test_worker_register():
    """Test worker registration."""
    client = WorkerAPIClient()
    
    try:
        result = await client.register("test-worker-1")
        assert result["data"]["status"] == "registered"
    finally:
        await client.close()

@pytest.mark.asyncio
async def test_worker_heartbeat():
    """Test worker heartbeat."""
    client = WorkerAPIClient()
    
    try:
        # Register first
        await client.register("test-worker-1")
        
        # Send heartbeat
        result = await client.heartbeat("test-worker-1")
        assert result["data"]["status"] == "ok"
    finally:
        await client.close()

@pytest.mark.asyncio
async def test_claim_no_packets():
    """Test claiming when no packets available."""
    client = WorkerAPIClient()
    
    try:
        await client.register("test-worker-1")
        claim = await client.claim_packet("test-worker-1")
        assert claim is None  # No packets
    finally:
        await client.close()
```

### Критерии готовности
- [ ] WorkerAPIClient реализован
- [ ] Worker loop реализован
- [ ] Heartbeat mechanism работает
- [ ] Claim/release работают
- [ ] PacketExecutionAdapter интегрирован
- [ ] Тесты проходят
- [ ] Worker запускается: `grace-worker`

---

## Phase 2 Complete Checklist

### Все задачи Phase 2
- [ ] Task #18: FastAPI Server ✅
- [ ] Task #21: Worker Loop ✅

### Deliverables
- ✅ FastAPI server с canonical API endpoints
- ✅ Worker loop с lease mechanism
- ✅ PacketExecutionAdapter интегрирован
- ✅ Health checks работают
- ✅ SQLite-safe locking

### Что НЕ в MVP-0
- ❌ UI/Dashboard
- ❌ Telegram notifications
- ❌ WebSocket
- ❌ Image viewer
- ❌ Cancellation (post-MVP)
- ❌ Multiple workers (работает, но не тестируется)

### Готовность к Phase 3
После завершения Phase 2 можно начинать Phase 3: CLI & E2E Test
