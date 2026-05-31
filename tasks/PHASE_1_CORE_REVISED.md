# Phase 1: Core Infrastructure

**Длительность:** 1 неделя (7 дней)
**Цель:** Создать ядро системы — DB, state machine, PacketExecutionAdapter

**ВАЖНО:** Следуйте CANONICAL_DECISIONS.md — единственному источнику правды.

---

## Task #10: Design & Implement DB Schema

**Приоритет:** Критично
**Время:** 2 дня
**Зависимости:** Phase 0 complete

### Описание
Создать SQLite schema с 7 таблицами (canonical set).

### Что делать

#### 1. Создать SQLAlchemy models

**src/grace_control/db/schema.py:**
```python
"""
Database schema for GRACE Control Plane.

CANONICAL: 7 tables, 8 states.
See CANONICAL_DECISIONS.md for details.
"""
from sqlalchemy import Column, String, Integer, DateTime, JSON, Text, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import enum

Base = declarative_base()

class PacketState(enum.Enum):
    """Canonical packet states (8 total)."""
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    ACCEPTED = "accepted"
    MERGED = "merged"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"

class Feature(Base):
    """Feature table."""
    __tablename__ = "features"
    
    id = Column(String, primary_key=True)  # FEAT-USER-AUTH
    slug = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    spec_json = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default="NOT_STARTED")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class Wave(Base):
    """Wave table."""
    __tablename__ = "waves"
    
    id = Column(String, primary_key=True)  # W01-FOUNDATION
    feature_id = Column(String, nullable=False, index=True)
    slug = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    order = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="NOT_STARTED")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class Packet(Base):
    """Packet table."""
    __tablename__ = "packets"
    
    id = Column(String, primary_key=True)  # FEAT-USER-AUTH-W01-P01-ADD-JWT-UTILS
    feature_id = Column(String, nullable=False, index=True)
    wave_id = Column(String, nullable=False, index=True)
    slug = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    spec_json = Column(JSON, nullable=False)
    state = Column(SQLEnum(PacketState), nullable=False, default=PacketState.DRAFT, index=True)
    acceptance_profile = Column(String, nullable=False, default="NORMAL")
    attempt_count = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class PacketRun(Base):
    """Packet run table."""
    __tablename__ = "packet_runs"
    
    id = Column(String, primary_key=True)  # FEAT-USER-AUTH-W01-P01-ADD-JWT-UTILS-R01
    packet_id = Column(String, nullable=False, index=True)
    run_number = Column(Integer, nullable=False)
    executor_id = Column(String)
    worker_id = Column(String, index=True)
    status = Column(String, nullable=False)  # running, accepted, rejected, failed
    result_json = Column(JSON)
    evidence_path = Column(String)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration_ms = Column(Integer)

class Worker(Base):
    """Worker table."""
    __tablename__ = "workers"
    
    id = Column(String, primary_key=True)  # worker-abc123
    status = Column(String, nullable=False, default="active")  # active, idle, dead
    current_packet_id = Column(String, index=True)
    last_heartbeat = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class Lease(Base):
    """Lease table (SQLite-safe locking)."""
    __tablename__ = "leases"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    packet_id = Column(String, nullable=False, unique=True, index=True)
    worker_id = Column(String, nullable=False, index=True)
    acquired_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    heartbeat_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class Event(Base):
    """Event log table."""
    __tablename__ = "events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)
    payload_json = Column(JSON)
    trace_id = Column(String, index=True)
```

#### 2. Создать database helper

**src/grace_control/db/__init__.py:**
```python
"""
Database utilities.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from pathlib import Path
from .schema import Base

engine = None
SessionLocal = None

def init_db(db_url: str = None):
    """
    Initialize database.
    
    Args:
        db_url: Database URL (default: sqlite:///./grace.db)
    """
    global engine, SessionLocal
    
    if db_url is None:
        # Default: SQLite in project root
        db_path = Path.cwd() / "grace.db"
        db_url = f"sqlite:///{db_path}"
    
    engine = create_engine(
        db_url,
        echo=False,
        # SQLite-specific settings
        connect_args={"check_same_thread": False} if "sqlite" in db_url else {}
    )
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    
    # Create tables
    Base.metadata.create_all(engine)

@contextmanager
def get_db() -> Session:
    """
    Get database session.
    
    Usage:
        with get_db() as db:
            packet = db.query(Packet).filter_by(id="PKT-001").first()
    """
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

#### 3. Создать тесты

**tests/test_db_schema.py:**
```python
"""Test database schema."""
import pytest
from pathlib import Path
from grace_control.db import init_db, get_db
from grace_control.db.schema import Feature, Packet, PacketState, Worker, Lease
from datetime import datetime, timedelta

@pytest.fixture
def test_db():
    """Create test database."""
    init_db("sqlite:///:memory:")
    yield
    # Cleanup handled by in-memory DB

def test_create_feature(test_db):
    """Test creating feature."""
    with get_db() as db:
        feature = Feature(
            id="FEAT-TEST",
            slug="test",
            title="Test Feature",
            description="Test description",
            spec_json={"waves": []},
            status="NOT_STARTED"
        )
        db.add(feature)
    
    with get_db() as db:
        f = db.query(Feature).filter_by(id="FEAT-TEST").first()
        assert f is not None
        assert f.title == "Test Feature"
        assert f.slug == "test"

def test_create_packet(test_db):
    """Test creating packet."""
    with get_db() as db:
        packet = Packet(
            id="FEAT-TEST-W01-P01-CREATE-TEST",
            feature_id="FEAT-TEST",
            wave_id="W01",
            slug="create-test",
            title="Create test",
            description="Test packet",
            spec_json={"scope": "src/test.py"},
            state=PacketState.DRAFT,
            acceptance_profile="NORMAL"
        )
        db.add(packet)
    
    with get_db() as db:
        p = db.query(Packet).filter_by(id="FEAT-TEST-W01-P01-CREATE-TEST").first()
        assert p is not None
        assert p.state == PacketState.DRAFT
        assert p.acceptance_profile == "NORMAL"

def test_packet_state_transitions(test_db):
    """Test packet state transitions."""
    with get_db() as db:
        packet = Packet(
            id="PKT-001",
            feature_id="FEAT-TEST",
            wave_id="W01",
            slug="test",
            title="Test",
            spec_json={},
            state=PacketState.DRAFT
        )
        db.add(packet)
    
    # DRAFT → READY
    with get_db() as db:
        packet = db.query(Packet).filter_by(id="PKT-001").first()
        packet.state = PacketState.READY
    
    # READY → RUNNING
    with get_db() as db:
        packet = db.query(Packet).filter_by(id="PKT-001").first()
        packet.state = PacketState.RUNNING
        assert packet.state == PacketState.RUNNING

def test_lease_mechanism(test_db):
    """Test lease creation and expiration."""
    with get_db() as db:
        # Create packet
        packet = Packet(
            id="PKT-001",
            feature_id="FEAT-TEST",
            wave_id="W01",
            slug="test",
            title="Test",
            spec_json={},
            state=PacketState.READY
        )
        db.add(packet)
        
        # Create worker
        worker = Worker(
            id="worker-1",
            status="active"
        )
        db.add(worker)
        
        # Create lease
        lease = Lease(
            packet_id="PKT-001",
            worker_id="worker-1",
            expires_at=datetime.utcnow() + timedelta(minutes=30)
        )
        db.add(lease)
    
    # Check lease exists
    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()
        assert lease is not None
        assert lease.worker_id == "worker-1"
        assert lease.expires_at > datetime.utcnow()

def test_worker_heartbeat(test_db):
    """Test worker heartbeat update."""
    with get_db() as db:
        worker = Worker(
            id="worker-1",
            status="active"
        )
        db.add(worker)
    
    # Update heartbeat
    with get_db() as db:
        worker = db.query(Worker).filter_by(id="worker-1").first()
        worker.last_heartbeat = datetime.utcnow()
        worker.status = "active"
    
    # Check updated
    with get_db() as db:
        worker = db.query(Worker).filter_by(id="worker-1").first()
        assert worker.status == "active"
        assert worker.last_heartbeat is not None
```

### Критерии готовности
- [ ] SQLAlchemy models созданы (7 таблиц)
- [ ] 8 canonical states определены
- [ ] Database helper работает (init_db, get_db)
- [ ] SQLite-safe (no FOR UPDATE SKIP LOCKED)
- [ ] Тесты проходят
- [ ] Можно создавать/читать entities из DB

---

## Task #11: Implement Packet State Machine

**Приоритет:** Критично
**Время:** 2 дня
**Зависимости:** Task #10

### Описание
Реализовать state machine с 8 canonical states и валидацией переходов.

### Что делать

#### 1. Создать state machine

**src/grace_control/core/state_machine.py:**
```python
"""
Packet state machine.

CANONICAL: 8 states, strict transitions.
See CANONICAL_DECISIONS.md for details.
"""
from grace_control.db.schema import PacketState
from typing import Optional

class StateTransitionError(Exception):
    """Invalid state transition."""
    pass

class PacketStateMachine:
    """
    Packet state machine with validation.
    
    Valid transitions:
    DRAFT → READY
    READY → RUNNING
    RUNNING → ACCEPTED | REJECTED | FAILED
    REJECTED → READY (retry)
    ACCEPTED → MERGED
    
    Any state → CANCELLED (manual cancellation)
    """
    
    VALID_TRANSITIONS = {
        PacketState.DRAFT: [PacketState.READY],
        PacketState.READY: [PacketState.RUNNING, PacketState.CANCELLED],
        PacketState.RUNNING: [
            PacketState.ACCEPTED,
            PacketState.REJECTED,
            PacketState.FAILED,
            PacketState.CANCELLED
        ],
        PacketState.REJECTED: [PacketState.READY, PacketState.CANCELLED],
        PacketState.ACCEPTED: [PacketState.MERGED],
        PacketState.MERGED: [],  # Terminal
        PacketState.FAILED: [],  # Terminal
        PacketState.CANCELLED: [],  # Terminal
    }
    
    TERMINAL_STATES = {
        PacketState.MERGED,
        PacketState.FAILED,
        PacketState.CANCELLED
    }
    
    def can_transition(self, from_state: PacketState, to_state: PacketState) -> bool:
        """Check if transition is valid."""
        return to_state in self.VALID_TRANSITIONS.get(from_state, [])
    
    def transition(self, packet, to_state: PacketState, reason: Optional[str] = None):
        """
        Transition packet to new state.
        
        Args:
            packet: Packet DB object
            to_state: Target state
            reason: Optional reason for transition
        
        Raises:
            StateTransitionError: If transition is invalid
        """
        if not self.can_transition(packet.state, to_state):
            raise StateTransitionError(
                f"Invalid transition: {packet.state.value} → {to_state.value}"
            )
        
        # Update state
        old_state = packet.state
        packet.state = to_state
        
        # Log transition
        from grace_control.logging import GraceLogger
        logger = GraceLogger("state_machine")
        logger.info(
            "State transition",
            packet_id=packet.id,
            from_state=old_state.value,
            to_state=to_state.value,
            reason=reason
        )
    
    def is_terminal(self, state: PacketState) -> bool:
        """Check if state is terminal."""
        return state in self.TERMINAL_STATES
```

#### 2. Интегрировать в DB operations

**src/grace_control/core/packet_operations.py:**
```python
"""
Packet operations with state machine validation.
"""
from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketState
from grace_control.core.state_machine import PacketStateMachine, StateTransitionError

state_machine = PacketStateMachine()

def transition_packet(packet_id: str, to_state: PacketState, reason: str = None):
    """
    Transition packet to new state.
    
    Args:
        packet_id: Packet ID
        to_state: Target state
        reason: Optional reason
    
    Raises:
        ValueError: If packet not found
        StateTransitionError: If transition invalid
    """
    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            raise ValueError(f"Packet {packet_id} not found")
        
        state_machine.transition(packet, to_state, reason)

def mark_ready(packet_id: str):
    """Mark packet as ready for execution."""
    transition_packet(packet_id, PacketState.READY, "Ready for execution")

def mark_running(packet_id: str, worker_id: str):
    """Mark packet as running."""
    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            raise ValueError(f"Packet {packet_id} not found")
        
        state_machine.transition(packet, PacketState.RUNNING, f"Claimed by {worker_id}")
        packet.attempt_count += 1

def mark_accepted(packet_id: str, evidence_path: str):
    """Mark packet as accepted."""
    transition_packet(packet_id, PacketState.ACCEPTED, f"Tests passed, evidence: {evidence_path}")

def mark_rejected(packet_id: str, reason: str):
    """Mark packet as rejected."""
    transition_packet(packet_id, PacketState.REJECTED, reason)

def mark_failed(packet_id: str, error: str):
    """Mark packet as failed."""
    transition_packet(packet_id, PacketState.FAILED, f"Execution error: {error}")

def mark_merged(packet_id: str, commit_sha: str):
    """Mark packet as merged."""
    transition_packet(packet_id, PacketState.MERGED, f"Merged: {commit_sha}")

def retry_packet(packet_id: str):
    """
    Retry rejected packet.
    
    Transitions REJECTED → READY if attempts remaining.
    """
    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            raise ValueError(f"Packet {packet_id} not found")
        
        if packet.state != PacketState.REJECTED:
            raise StateTransitionError(f"Can only retry REJECTED packets, got {packet.state.value}")
        
        if packet.attempt_count >= packet.max_attempts:
            raise StateTransitionError(f"Max attempts ({packet.max_attempts}) reached")
        
        state_machine.transition(packet, PacketState.READY, f"Retry attempt {packet.attempt_count + 1}")
```

#### 3. Создать тесты

**tests/test_state_machine.py:**
```python
"""Test state machine."""
import pytest
from grace_control.db import init_db, get_db
from grace_control.db.schema import Packet, PacketState
from grace_control.core.state_machine import PacketStateMachine, StateTransitionError
from grace_control.core.packet_operations import (
    mark_ready, mark_running, mark_accepted, mark_rejected, retry_packet
)

@pytest.fixture
def test_db():
    init_db("sqlite:///:memory:")
    yield

def test_valid_transitions(test_db):
    """Test valid state transitions."""
    sm = PacketStateMachine()
    
    assert sm.can_transition(PacketState.DRAFT, PacketState.READY)
    assert sm.can_transition(PacketState.READY, PacketState.RUNNING)
    assert sm.can_transition(PacketState.RUNNING, PacketState.ACCEPTED)
    assert sm.can_transition(PacketState.ACCEPTED, PacketState.MERGED)

def test_invalid_transitions(test_db):
    """Test invalid state transitions."""
    sm = PacketStateMachine()
    
    assert not sm.can_transition(PacketState.DRAFT, PacketState.RUNNING)
    assert not sm.can_transition(PacketState.READY, PacketState.ACCEPTED)
    assert not sm.can_transition(PacketState.MERGED, PacketState.READY)

def test_terminal_states(test_db):
    """Test terminal states."""
    sm = PacketStateMachine()
    
    assert sm.is_terminal(PacketState.MERGED)
    assert sm.is_terminal(PacketState.FAILED)
    assert sm.is_terminal(PacketState.CANCELLED)
    assert not sm.is_terminal(PacketState.RUNNING)

def test_packet_lifecycle(test_db):
    """Test full packet lifecycle."""
    # Create packet
    with get_db() as db:
        packet = Packet(
            id="PKT-001",
            feature_id="FEAT-TEST",
            wave_id="W01",
            slug="test",
            title="Test",
            spec_json={},
            state=PacketState.DRAFT
        )
        db.add(packet)
    
    # DRAFT → READY
    mark_ready("PKT-001")
    with get_db() as db:
        packet = db.query(Packet).filter_by(id="PKT-001").first()
        assert packet.state == PacketState.READY
    
    # READY → RUNNING
    mark_running("PKT-001", "worker-1")
    with get_db() as db:
        packet = db.query(Packet).filter_by(id="PKT-001").first()
        assert packet.state == PacketState.RUNNING
        assert packet.attempt_count == 1
    
    # RUNNING → ACCEPTED
    mark_accepted("PKT-001", ".grace/packets/PKT-001/runs/R01")
    with get_db() as db:
        packet = db.query(Packet).filter_by(id="PKT-001").first()
        assert packet.state == PacketState.ACCEPTED

def test_retry_rejected_packet(test_db):
    """Test retrying rejected packet."""
    # Create rejected packet
    with get_db() as db:
        packet = Packet(
            id="PKT-001",
            feature_id="FEAT-TEST",
            wave_id="W01",
            slug="test",
            title="Test",
            spec_json={},
            state=PacketState.REJECTED,
            attempt_count=1,
            max_attempts=3
        )
        db.add(packet)
    
    # Retry
    retry_packet("PKT-001")
    
    with get_db() as db:
        packet = db.query(Packet).filter_by(id="PKT-001").first()
        assert packet.state == PacketState.READY

def test_max_attempts_exceeded(test_db):
    """Test max attempts exceeded."""
    with get_db() as db:
        packet = Packet(
            id="PKT-001",
            feature_id="FEAT-TEST",
            wave_id="W01",
            slug="test",
            title="Test",
            spec_json={},
            state=PacketState.REJECTED,
            attempt_count=3,
            max_attempts=3
        )
        db.add(packet)
    
    # Should fail
    with pytest.raises(StateTransitionError, match="Max attempts"):
        retry_packet("PKT-001")
```

### Критерии готовности
- [ ] PacketStateMachine реализован
- [ ] 8 canonical states
- [ ] Valid transitions определены
- [ ] Terminal states определены
- [ ] packet_operations интегрированы
- [ ] Тесты проходят
- [ ] Invalid transitions блокируются

---

## Task #22: Implement PacketExecutionAdapter

**Приоритет:** Критично
**Время:** 2 дня
**Зависимости:** Task #11

### Описание
Создать adapter между DB packets и существующим `run_e2e_packet`.

**КРИТИЧНО:** Это bridge к legacy code. НЕ переписываем runner, только адаптируем.

### Что делать

#### 1. Создать adapter

**src/grace_control/adapters/packet_executor.py:**
```python
"""
PacketExecutionAdapter - bridge to legacy run_e2e_packet.

IMPORTANT: This adapter materializes DB packet → packet file,
calls existing run_e2e_packet, and normalizes result back to DB.
"""
from pathlib import Path
from typing import Optional
import yaml
import json
from datetime import datetime
from pydantic import BaseModel

from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketRun, PacketState
from grace_control.core.packet_operations import mark_running, mark_accepted, mark_rejected, mark_failed
from grace_control.logging import GraceLogger

logger = GraceLogger("packet_executor")

class ExecutionResult(BaseModel):
    """Execution result."""
    accepted: bool
    reason: Optional[str]
    evidence_path: str
    duration_ms: int
    tests: dict

class PacketExecutionAdapter:
    """
    Adapter between DB packets and legacy run_e2e_packet.
    
    Flow:
    1. Load packet from DB
    2. Materialize packet file (EXECUTION_PACKET.md)
    3. Call existing run_e2e_packet(...)
    4. Parse result
    5. Save evidence
    6. Update DB state
    """
    
    def __init__(
        self,
        project_root: Path,
        state_root: Path,
        worktree_root: Path
    ):
        self.project_root = project_root
        self.state_root = state_root
        self.worktree_root = worktree_root
    
    async def execute(self, packet_id: str, worker_id: str) -> ExecutionResult:
        """
        Execute packet.
        
        Args:
            packet_id: Packet ID
            worker_id: Worker ID
        
        Returns:
            ExecutionResult
        """
        logger.info("Starting packet execution", packet_id=packet_id, worker_id=worker_id)
        
        # 1. Load packet from DB
        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                raise ValueError(f"Packet {packet_id} not found")
            
            # Mark as running
            mark_running(packet_id, worker_id)
            
            # Create run record
            run_number = packet.attempt_count
            run_id = f"{packet_id}-R{run_number:02d}"
            
            packet_run = PacketRun(
                id=run_id,
                packet_id=packet_id,
                run_number=run_number,
                worker_id=worker_id,
                status="running",
                started_at=datetime.utcnow()
            )
            db.add(packet_run)
        
        try:
            # 2. Materialize packet file
            packet_path = self._materialize_packet(packet)
            
            # 3. Call existing runner
            result = await self._call_legacy_runner(packet_path)
            
            # 4. Parse result
            execution_result = self._parse_result(result)
            
            # 5. Save evidence
            evidence_path = self._save_evidence(packet_id, run_number, result)
            execution_result.evidence_path = evidence_path
            
            # 6. Update DB state
            with get_db() as db:
                packet_run = db.query(PacketRun).filter_by(id=run_id).first()
                packet_run.status = "accepted" if execution_result.accepted else "rejected"
                packet_run.result_json = execution_result.dict()
                packet_run.evidence_path = evidence_path
                packet_run.finished_at = datetime.utcnow()
                packet_run.duration_ms = execution_result.duration_ms
            
            # Update packet state
            if execution_result.accepted:
                mark_accepted(packet_id, evidence_path)
            else:
                mark_rejected(packet_id, execution_result.reason)
            
            logger.info(
                "Packet execution completed",
                packet_id=packet_id,
                accepted=execution_result.accepted,
                duration_ms=execution_result.duration_ms
            )
            
            return execution_result
        
        except Exception as e:
            logger.error("Packet execution failed", packet_id=packet_id, error=str(e))
            
            # Update run record
            with get_db() as db:
                packet_run = db.query(PacketRun).filter_by(id=run_id).first()
                packet_run.status = "failed"
                packet_run.finished_at = datetime.utcnow()
            
            # Mark packet as failed
            mark_failed(packet_id, str(e))
            
            raise
    
    def _materialize_packet(self, packet: Packet) -> Path:
        """
        Materialize packet file from DB spec.
        
        Creates EXECUTION_PACKET.md in state_root.
        """
        packet_dir = self.state_root / "packets" / packet.id
        packet_dir.mkdir(parents=True, exist_ok=True)
        
        packet_file = packet_dir / "EXECUTION_PACKET.md"
        
        # Convert spec_json to packet file format
        content = f"""# {packet.title}

**ID:** {packet.id}
**Feature:** {packet.feature_id}
**Wave:** {packet.wave_id}

## Description

{packet.description}

## Specification

```yaml
{yaml.dump(packet.spec_json, default_flow_style=False)}
```

## Acceptance Profile

{packet.acceptance_profile}
"""
        
        packet_file.write_text(content)
        logger.debug("Packet file materialized", packet_id=packet.id, path=str(packet_file))
        
        return packet_file
    
    async def _call_legacy_runner(self, packet_path: Path) -> dict:
        """
        Call existing run_e2e_packet.
        
        IMPORTANT: Existing runner is SYNCHRONOUS, so we run in executor.
        """
        import asyncio
        from functools import partial
        
        # Import legacy runner
        from prefect_grace.platform.e2e_packet_runner import run_e2e_packet
        
        # Run in executor (blocking call)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            partial(
                run_e2e_packet,
                project_root=self.project_root,
                packet_path=packet_path,
                state_root=self.state_root,
                worktree_root=self.worktree_root,
                dry_run=False,  # MVP: live execution
                # Note: existing runner may not have these flags yet
                # Will need to add them or handle via config
            )
        )
        
        return result
    
    def _parse_result(self, result: dict) -> ExecutionResult:
        """Parse legacy runner result."""
        # Legacy runner returns dict with:
        # - accepted: bool
        # - reason: str
        # - evidence_path: str
        # - duration_ms: int
        # - tests: dict
        
        return ExecutionResult(
            accepted=result.get("accepted", False),
            reason=result.get("reason"),
            evidence_path=result.get("evidence_path", ""),
            duration_ms=result.get("duration_ms", 0),
            tests=result.get("tests", {})
        )
    
    def _save_evidence(self, packet_id: str, run_number: int, result: dict) -> str:
        """
        Save evidence to .grace/packets/{packet_id}/runs/R{run_number}/.
        
        Evidence already saved by legacy runner, just return path.
        """
        evidence_path = self.state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"
        return str(evidence_path)
```

#### 2. Создать тесты

**tests/test_packet_executor.py:**
```python
"""Test PacketExecutionAdapter."""
import pytest
from pathlib import Path
from grace_control.db import init_db, get_db
from grace_control.db.schema import Packet, PacketState
from grace_control.adapters.packet_executor import PacketExecutionAdapter

@pytest.fixture
def test_db():
    init_db("sqlite:///:memory:")
    yield

@pytest.fixture
def test_dirs(tmp_path):
    project_root = tmp_path / "project"
    state_root = tmp_path / "state"
    worktree_root = tmp_path / "worktrees"
    
    project_root.mkdir()
    state_root.mkdir()
    worktree_root.mkdir()
    
    return project_root, state_root, worktree_root

@pytest.mark.asyncio
async def test_materialize_packet(test_db, test_dirs):
    """Test packet materialization."""
    project_root, state_root, worktree_root = test_dirs
    
    # Create packet
    with get_db() as db:
        packet = Packet(
            id="PKT-001",
            feature_id="FEAT-TEST",
            wave_id="W01",
            slug="test",
            title="Test Packet",
            description="Test description",
            spec_json={"scope": "src/test.py"},
            state=PacketState.READY
        )
        db.add(packet)
    
    # Materialize
    adapter = PacketExecutionAdapter(project_root, state_root, worktree_root)
    
    with get_db() as db:
        packet = db.query(Packet).filter_by(id="PKT-001").first()
        packet_file = adapter._materialize_packet(packet)
    
    # Check file created
    assert packet_file.exists()
    content = packet_file.read_text()
    assert "Test Packet" in content
    assert "PKT-001" in content
```

### Критерии готовности
- [ ] PacketExecutionAdapter реализован
- [ ] Materialize packet работает
- [ ] Call legacy runner работает (async wrapper)
- [ ] Parse result работает
- [ ] Save evidence работает
- [ ] DB state updates работают
- [ ] Тесты проходят

---

## Phase 1 Complete Checklist

### Все задачи Phase 1
- [ ] Task #10: DB Schema (7 таблиц, 8 states) ✅
- [ ] Task #11: State Machine (canonical transitions) ✅
- [ ] Task #22: PacketExecutionAdapter (bridge to legacy) ✅

### Deliverables
- ✅ SQLite DB с 7 таблицами
- ✅ State machine с 8 canonical states
- ✅ PacketExecutionAdapter для интеграции с legacy runner
- ✅ Все тесты проходят

### Готовность к Phase 2
После завершения Phase 1 можно начинать Phase 2: API & Worker
