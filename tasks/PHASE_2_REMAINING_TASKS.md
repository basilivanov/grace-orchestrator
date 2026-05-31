# Task #12: Create Worker Loop with Lease Mechanism

**Приоритет:** Критично
**Время:** 2 дня
**Зависимости:** Task #11, #21

## Описание
Создать worker loop с lease mechanism и heartbeat.

## Что делать

### 1. Создать worker loop

**src/grace_control/worker/worker.py:**
```python
"""
Worker loop implementation.
"""
import asyncio
from datetime import datetime
from pathlib import Path
import uuid

from grace_control.worker.api_client import WorkerAPIClient
from grace_control.logging import GraceLogger, trace_context
from grace_control.core.executors import create_executor

logger = GraceLogger("worker")

class Worker:
    """
    Worker process.
    
    Responsibilities:
    - Register with Control Plane
    - Send heartbeat every 30s
    - Claim packets from queue
    - Execute packets
    - Release packets with results
    """
    
    def __init__(
        self,
        worker_id: Optional[str] = None,
        api_url: str = "http://localhost:8000",
        heartbeat_interval: int = 30
    ):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.api_client = WorkerAPIClient(api_url)
        self.heartbeat_interval = heartbeat_interval
        self.running = False
    
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
                    status=result["status"],
                    result=result
                )
                
                logger.info(
                    "Packet released",
                    worker_id=self.worker_id,
                    packet_id=claim.packet_id,
                    status=result["status"]
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
    
    async def _execute_packet(self, claim) -> dict:
        """
        Execute packet.
        
        Delegates to existing run_e2e_packet.
        """
        logger.info("Starting packet execution", packet_id=claim.packet_id)
        
        # Import existing execution engine
        from prefect_grace.platform.packet_executor import run_e2e_packet
        
        try:
            # Execute
            result = await run_e2e_packet(
                packet_id=claim.packet_id,
                spec=claim.spec
            )
            
            return {
                "status": "success" if result.accepted else "rejected",
                "accepted": result.accepted,
                "reason": result.reason,
                "evidence_path": result.evidence_path,
                "duration_ms": result.duration_ms
            }
        
        except Exception as e:
            logger.error(
                "Packet execution failed",
                packet_id=claim.packet_id,
                error=str(e)
            )
            
            return {
                "status": "failed",
                "accepted": False,
                "reason": f"Execution error: {str(e)}",
                "evidence_path": None,
                "duration_ms": 0
            }

async def main():
    """Run worker."""
    worker = Worker()
    await worker.start()

if __name__ == "__main__":
    asyncio.run(main())
```

### 2. Добавить lease mechanism в API

**Обновить src/grace_control/api/routers/packets.py:**
```python
from datetime import datetime, timedelta
from grace_control.db.schema import Lease

@router.post("/claim")
async def claim_packet(request: dict):
    """
    Claim next available packet.
    
    Uses lease mechanism to prevent conflicts.
    """
    worker_id = request["worker_id"]
    
    with get_db() as db:
        # Find READY packet without lease
        packet = db.query(Packet).filter_by(state=PacketState.READY).first()
        
        if not packet:
            raise HTTPException(status_code=404, detail="No packets available")
        
        # Check if already leased
        existing_lease = db.query(Lease).filter_by(packet_id=packet.id).first()
        if existing_lease:
            # Check if expired
            if existing_lease.expires_at > datetime.utcnow():
                raise HTTPException(status_code=409, detail="Packet already claimed")
            else:
                # Expired, remove
                db.delete(existing_lease)
        
        # Create lease
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
            "packet_id": packet.id,
            "spec": packet.spec_json,
            "lease_id": lease.id
        }

@router.post("/{packet_id}/release")
async def release_packet(packet_id: str, request: dict):
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
        if status == "success" and result.get("accepted"):
            packet.state = PacketState.ACCEPTED
        elif status == "success" and not result.get("accepted"):
            packet.state = PacketState.REJECTED
        else:
            packet.state = PacketState.FAILED
        
        # Update worker
        worker = db.query(Worker).filter_by(id=worker_id).first()
        if worker:
            worker.current_packet_id = None
            worker.status = "idle"
        
        return {"status": "released"}
```

### 3. Добавить lease expiration check

**src/grace_control/core/lease_manager.py:**
```python
"""
Lease expiration checker.
"""
import asyncio
from datetime import datetime
from grace_control.db import get_db
from grace_control.db.schema import Lease, Packet, PacketState
from grace_control.logging import GraceLogger

logger = GraceLogger("lease_manager")

async def check_expired_leases():
    """
    Check for expired leases and release them.
    
    Run this periodically (e.g., every minute).
    """
    with get_db() as db:
        expired = db.query(Lease).filter(
            Lease.expires_at < datetime.utcnow()
        ).all()
        
        for lease in expired:
            logger.warning(
                "Lease expired",
                packet_id=lease.packet_id,
                worker_id=lease.worker_id
            )
            
            # Release packet back to READY
            packet = db.query(Packet).filter_by(id=lease.packet_id).first()
            if packet and packet.state == PacketState.RUNNING:
                packet.state = PacketState.READY
            
            # Remove lease
            db.delete(lease)

async def lease_expiration_loop():
    """Run lease expiration check loop."""
    while True:
        try:
            await check_expired_leases()
        except Exception as e:
            logger.error("Lease expiration check failed", error=str(e))
        
        await asyncio.sleep(60)  # Check every minute
```

### 4. Создать тесты

**tests/test_worker.py:**
```python
import pytest
from grace_control.worker.worker import Worker
from grace_control.worker.api_client import WorkerAPIClient

@pytest.mark.asyncio
async def test_worker_register():
    worker = Worker(worker_id="test-worker")
    await worker.api_client.register(worker.worker_id)
    # Check registered

@pytest.mark.asyncio
async def test_worker_heartbeat():
    worker = Worker(worker_id="test-worker")
    await worker.api_client.register(worker.worker_id)
    await worker.api_client.heartbeat(worker.worker_id)
    # Check heartbeat recorded

@pytest.mark.asyncio
async def test_claim_packet():
    # Create test packet
    # Worker claims it
    # Check lease created
    pass
```

### Критерии готовности
- [ ] Worker loop реализован
- [ ] Heartbeat mechanism работает
- [ ] Lease mechanism работает
- [ ] Claim/release работают
- [ ] Expired leases обрабатываются
- [ ] Интеграция с run_e2e_packet работает
- [ ] Тесты проходят

---

## Task #27: Implement Architect Agent Integration

**Приоритет:** Высокий
**Время:** 2 дня
**Зависимости:** Task #18

### Описание
Интегрировать architect agent для создания packets из feature specs.

### Что делать

#### 1. Создать architect API endpoint

**src/grace_control/api/routers/architect.py:**
```python
"""
Architect API router.
"""
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional
import yaml

from grace_control.core.architect import ArchitectAgent
from grace_control.db import get_db
from grace_control.db.schema import Feature, Wave, Packet

router = APIRouter()

class PlanRequest(BaseModel):
    """Plan request."""
    feature_spec: dict
    xml_artifacts: Optional[dict] = None

class PlanResponse(BaseModel):
    """Plan response."""
    feature_id: str
    waves_count: int
    packets_count: int
    packets: list

@router.post("/plan", response_model=PlanResponse)
async def create_plan(request: PlanRequest):
    """
    Create execution plan from feature spec.
    
    Architect agent reads feature spec and XML artifacts,
    generates hierarchical IDs and creates packets.
    """
    architect = ArchitectAgent()
    
    # Generate plan
    plan = await architect.generate_plan(
        feature_spec=request.feature_spec,
        xml_artifacts=request.xml_artifacts
    )
    
    # Save to DB
    with get_db() as db:
        # Create feature
        feature = Feature(
            id=plan["feature_id"],
            slug=plan["slug"],
            title=plan["title"],
            description=plan["description"],
            spec_json=request.feature_spec,
            status="NOT_STARTED"
        )
        db.add(feature)
        
        # Create waves
        for wave_data in plan["waves"]:
            wave = Wave(
                id=wave_data["id"],
                feature_id=plan["feature_id"],
                slug=wave_data["slug"],
                title=wave_data["title"],
                description=wave_data["description"],
                order=wave_data["order"],
                status="NOT_STARTED"
            )
            db.add(wave)
            
            # Create packets
            for packet_data in wave_data["packets"]:
                packet = Packet(
                    id=packet_data["id"],
                    feature_id=plan["feature_id"],
                    wave_id=wave_data["id"],
                    slug=packet_data["slug"],
                    title=packet_data["title"],
                    description=packet_data["description"],
                    spec_json=packet_data["spec"],
                    state=PacketState.DRAFT,
                    acceptance_profile=packet_data["acceptance_profile"]
                )
                db.add(packet)
    
    return PlanResponse(
        feature_id=plan["feature_id"],
        waves_count=len(plan["waves"]),
        packets_count=sum(len(w["packets"]) for w in plan["waves"]),
        packets=[p["id"] for w in plan["waves"] for p in w["packets"]]
    )

@router.post("/plan/from-file")
async def create_plan_from_file(file: UploadFile = File(...)):
    """Create plan from uploaded YAML file."""
    content = await file.read()
    feature_spec = yaml.safe_load(content)
    
    return await create_plan(PlanRequest(feature_spec=feature_spec))
```

#### 2. Создать architect agent

**src/grace_control/core/architect.py:**
```python
"""
Architect agent implementation.
"""
from typing import Dict, List
from grace_control.logging import GraceLogger

logger = GraceLogger("architect")

class ArchitectAgent:
    """
    Architect agent.
    
    Responsibilities:
    - Read feature spec (YAML)
    - Read XML artifacts (requirements, technology, etc.)
    - Generate hierarchical IDs (FEAT-X-W01-P01-ACTION)
    - Generate waves and packets
    - Determine acceptance profiles
    """
    
    async def generate_plan(
        self,
        feature_spec: dict,
        xml_artifacts: Optional[dict] = None
    ) -> dict:
        """
        Generate execution plan.
        
        Args:
            feature_spec: Feature specification (YAML)
            xml_artifacts: XML artifacts (requirements.xml, etc.)
        
        Returns:
            Plan with feature, waves, and packets
        """
        logger.info("Generating plan", feature=feature_spec.get("title"))
        
        # Generate feature ID
        feature_slug = self._slugify(feature_spec["title"])
        feature_id = f"FEAT-{feature_slug.upper()}"
        
        # Generate waves
        waves = []
        for i, wave_spec in enumerate(feature_spec.get("waves", []), 1):
            wave_slug = self._slugify(wave_spec["title"])
            wave_id = f"W{i:02d}-{wave_slug.upper()}"
            
            # Generate packets
            packets = []
            for j, packet_spec in enumerate(wave_spec.get("packets", []), 1):
                packet_slug = self._slugify(packet_spec["title"])
                action = self._extract_action(packet_spec["title"])
                packet_id = f"{feature_id}-{wave_id}-P{j:02d}-{action}"
                
                # Determine acceptance profile
                profile = self._determine_profile(packet_spec)
                
                packets.append({
                    "id": packet_id,
                    "slug": packet_slug,
                    "title": packet_spec["title"],
                    "description": packet_spec.get("description", ""),
                    "spec": packet_spec,
                    "acceptance_profile": profile
                })
            
            waves.append({
                "id": wave_id,
                "slug": wave_slug,
                "title": wave_spec["title"],
                "description": wave_spec.get("description", ""),
                "order": i,
                "packets": packets
            })
        
        return {
            "feature_id": feature_id,
            "slug": feature_slug,
            "title": feature_spec["title"],
            "description": feature_spec.get("description", ""),
            "waves": waves
        }
    
    def _slugify(self, text: str) -> str:
        """Convert text to slug."""
        return text.lower().replace(" ", "-").replace("_", "-")
    
    def _extract_action(self, title: str) -> str:
        """Extract action from title."""
        # "Add JWT utilities" → "ADD-JWT-UTILS"
        words = title.split()
        if len(words) > 0:
            action = words[0].upper()  # ADD, CREATE, UPDATE, etc.
            rest = "-".join(words[1:]).upper().replace(" ", "-")
            return f"{action}-{rest}"
        return "ACTION"
    
    def _determine_profile(self, packet_spec: dict) -> str:
        """Determine acceptance profile."""
        # Check if critical
        if packet_spec.get("critical", False):
            return "STRICT"
        
        # Check scope
        scope = packet_spec.get("scope", "")
        if "auth" in scope or "security" in scope:
            return "STRICT"
        
        # Default
        return "NORMAL"
```

### Критерии готовности
- [ ] Architect API endpoint работает
- [ ] ArchitectAgent реализован
- [ ] Hierarchical IDs генерируются
- [ ] Waves и packets создаются
- [ ] Acceptance profiles определяются
- [ ] Интеграция с DB работает
- [ ] Тесты проходят

---

## Phase 2 Complete Checklist

### Все задачи Phase 2
- [ ] Task #18: FastAPI Server ✅
- [ ] Task #21: Worker API Client ✅
- [ ] Task #12: Worker Loop ✅
- [ ] Task #27: Architect Integration ✅

### Deliverables
- ✅ FastAPI server с всеми endpoints
- ✅ Worker loop с lease mechanism
- ✅ Architect agent integration
- ✅ Health checks

### Готовность к Phase 3
После завершения Phase 2 можно начинать Phase 3: UI & CLI
