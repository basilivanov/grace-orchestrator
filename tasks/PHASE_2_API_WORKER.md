# Phase 2: API & Worker

**Длительность:** 1 неделя (7 дней)
**Цель:** Создать FastAPI server и worker loop

---

## Task #18: Implement FastAPI Server

**Приоритет:** Критично
**Время:** 2 дня
**Зависимости:** Phase 1 complete

### Описание
Создать FastAPI server со всеми API endpoints.

### Что делать

#### 1. Создать FastAPI app

**src/grace_control/api/main.py:**
```python
"""
FastAPI server for GRACE Control Plane.
"""
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

from grace_control.db import init_db
from grace_control.api.routers import (
    features,
    packets,
    workers,
    architect,
    artifacts,
    system
)

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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(features.router, prefix="/api/features", tags=["features"])
app.include_router(packets.router, prefix="/api/packets", tags=["packets"])
app.include_router(workers.router, prefix="/api/workers", tags=["workers"])
app.include_router(architect.router, prefix="/api/architect", tags=["architect"])
app.include_router(artifacts.router, prefix="/api/artifacts", tags=["artifacts"])
app.include_router(system.router, prefix="/api/system", tags=["system"])

@app.get("/")
async def root():
    return {"message": "GRACE Control Plane API"}

@app.get("/health")
async def health():
    """Health check endpoint."""
    from grace_control.core.health import check_health
    return await check_health()

def main():
    """Run server."""
    uvicorn.run(
        "grace_control.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )

if __name__ == "__main__":
    main()
```

#### 2. Создать routers

**src/grace_control/api/routers/features.py:**
```python
"""
Features API router.
"""
from fastapi import APIRouter, HTTPException
from typing import List
from pydantic import BaseModel

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

@router.get("/", response_model=List[FeatureResponse])
async def list_features():
    """List all features."""
    with get_db() as db:
        features = db.query(Feature).all()
        return [
            FeatureResponse(
                id=f.id,
                slug=f.slug,
                title=f.title,
                description=f.description or "",
                status=f.status,
                created_at=f.created_at.isoformat()
            )
            for f in features
        ]

@router.get("/{feature_id}", response_model=FeatureResponse)
async def get_feature(feature_id: str):
    """Get feature by ID."""
    with get_db() as db:
        feature = db.query(Feature).filter_by(id=feature_id).first()
        if not feature:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        return FeatureResponse(
            id=feature.id,
            slug=feature.slug,
            title=feature.title,
            description=feature.description or "",
            status=feature.status,
            created_at=feature.created_at.isoformat()
        )
```

**src/grace_control/api/routers/packets.py:**
```python
"""
Packets API router.
"""
from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel

from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketState

router = APIRouter()

class PacketResponse(BaseModel):
    id: str
    feature_id: str
    wave_id: str
    title: str
    state: str
    acceptance_profile: str
    attempt_count: int
    created_at: str

class PacketCancelRequest(BaseModel):
    reason: Optional[str] = None

@router.get("/", response_model=List[PacketResponse])
async def list_packets(state: Optional[str] = None):
    """List packets, optionally filtered by state."""
    with get_db() as db:
        query = db.query(Packet)
        if state:
            query = query.filter_by(state=PacketState[state.upper()])
        
        packets = query.all()
        return [
            PacketResponse(
                id=p.id,
                feature_id=p.feature_id,
                wave_id=p.wave_id,
                title=p.title,
                state=p.state.value,
                acceptance_profile=p.acceptance_profile,
                attempt_count=p.attempt_count,
                created_at=p.created_at.isoformat()
            )
            for p in packets
        ]

@router.get("/{packet_id}", response_model=PacketResponse)
async def get_packet(packet_id: str):
    """Get packet by ID."""
    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            raise HTTPException(status_code=404, detail="Packet not found")
        
        return PacketResponse(
            id=packet.id,
            feature_id=packet.feature_id,
            wave_id=packet.wave_id,
            title=packet.title,
            state=packet.state.value,
            acceptance_profile=packet.acceptance_profile,
            attempt_count=packet.attempt_count,
            created_at=packet.created_at.isoformat()
        )

@router.post("/{packet_id}/cancel")
async def cancel_packet(packet_id: str, request: PacketCancelRequest):
    """Cancel running packet."""
    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            raise HTTPException(status_code=404, detail="Packet not found")
        
        if packet.state not in [PacketState.READY, PacketState.RUNNING]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel packet in state {packet.state.value}"
            )
        
        # Set cancellation flag
        packet.state = PacketState.CANCELLED
        
        return {"status": "cancelled", "reason": request.reason}
```

**src/grace_control/api/routers/workers.py:**
```python
"""
Workers API router.
"""
from fastapi import APIRouter, HTTPException
from typing import List
from pydantic import BaseModel
from datetime import datetime

from grace_control.db import get_db
from grace_control.db.schema import Worker

router = APIRouter()

class WorkerResponse(BaseModel):
    id: str
    status: str
    current_packet_id: Optional[str]
    last_heartbeat: str
    started_at: str

class WorkerRegisterRequest(BaseModel):
    worker_id: str
    capabilities: Optional[List[str]] = None

class WorkerHeartbeatRequest(BaseModel):
    worker_id: str

@router.get("/", response_model=List[WorkerResponse])
async def list_workers():
    """List all workers."""
    with get_db() as db:
        workers = db.query(Worker).all()
        return [
            WorkerResponse(
                id=w.id,
                status=w.status,
                current_packet_id=w.current_packet_id,
                last_heartbeat=w.last_heartbeat.isoformat() if w.last_heartbeat else "",
                started_at=w.started_at.isoformat()
            )
            for w in workers
        ]

@router.post("/register")
async def register_worker(request: WorkerRegisterRequest):
    """Register new worker."""
    with get_db() as db:
        # Check if exists
        existing = db.query(Worker).filter_by(id=request.worker_id).first()
        if existing:
            # Update
            existing.status = "active"
            existing.last_heartbeat = datetime.utcnow()
        else:
            # Create
            worker = Worker(
                id=request.worker_id,
                status="active",
                capabilities=request.capabilities or [],
                last_heartbeat=datetime.utcnow()
            )
            db.add(worker)
        
        return {"status": "registered"}

@router.post("/heartbeat")
async def worker_heartbeat(request: WorkerHeartbeatRequest):
    """Worker heartbeat."""
    with get_db() as db:
        worker = db.query(Worker).filter_by(id=request.worker_id).first()
        if not worker:
            raise HTTPException(status_code=404, detail="Worker not found")
        
        worker.last_heartbeat = datetime.utcnow()
        worker.status = "active"
        
        return {"status": "ok"}
```

#### 3. Создать health check

**src/grace_control/core/health.py:**
```python
"""
Health check implementation.
"""
from datetime import datetime, timedelta
from grace_control.db import get_db
from grace_control.db.schema import Worker, Packet, PacketState

async def check_health() -> dict:
    """
    Check system health.
    
    Returns:
        Health status
    """
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
            "timestamp": datetime.utcnow().isoformat()
        }
```

#### 4. Создать тесты

**tests/test_api.py:**
```python
import pytest
from fastapi.testclient import TestClient
from grace_control.api.main import app
from grace_control.db import init_db

client = TestClient(app)

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert "status" in response.json()

def test_list_features():
    response = client.get("/api/features/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_register_worker():
    response = client.post("/api/workers/register", json={
        "worker_id": "test-worker-1"
    })
    assert response.status_code == 200
    assert response.json()["status"] == "registered"
```

### Критерии готовности
- [ ] FastAPI app создан
- [ ] Все routers реализованы (features, packets, workers, architect, artifacts, system)
- [ ] Health check работает
- [ ] CORS настроен
- [ ] Тесты проходят
- [ ] Server запускается: `grace-api serve`

---

## Task #21: Implement Worker API Client

**Приоритет:** Критично
**Время:** 1 день
**Зависимости:** Task #18

### Описание
Создать API client для worker.

### Что делать

#### 1. Создать API client

**src/grace_control/worker/api_client.py:**
```python
"""
API client for worker.
"""
import httpx
from typing import Optional, List
from pydantic import BaseModel

class PacketClaim(BaseModel):
    """Claimed packet."""
    packet_id: str
    spec: dict
    lease_id: int

class WorkerAPIClient:
    """
    API client for worker to communicate with Control Plane.
    """
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
    
    async def register(self, worker_id: str, capabilities: Optional[List[str]] = None):
        """Register worker."""
        response = await self.client.post("/api/workers/register", json={
            "worker_id": worker_id,
            "capabilities": capabilities or []
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
        """
        Claim next available packet.
        
        Returns:
            PacketClaim if packet available, None otherwise
        """
        response = await self.client.post("/api/packets/claim", json={
            "worker_id": worker_id
        })
        
        if response.status_code == 404:
            return None
        
        response.raise_for_status()
        data = response.json()
        return PacketClaim(**data)
    
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

### Критерии готовности
- [ ] WorkerAPIClient реализован
- [ ] Register работает
- [ ] Heartbeat работает
- [ ] Claim/release работают
- [ ] Error handling работает

---

Продолжить с Task #12 (Worker Loop)?
