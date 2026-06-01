# ############################################################################
# AI_HEADER: db_schema
# ROLE: SQLAlchemy models for GRACE Control Plane — 8 tables, 8 states.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Define SQLAlchemy ORM models for GRACE Control Plane database.
# inputs: None (declarative models).
# returns: Base, model classes, PacketState enum.
# side_effects: None (pure declarative).
# emitted_logs: None.
# error_behavior: None at module level.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: Base
#   - enum: PacketState
#   - class: Feature
#   - class: Wave
#   - class: Packet
#   - class: PacketRun
#   - class: Worker
#   - class: Lease
#   - class: Event
#   - class: SelfEvolutionSession
# END_MODULE_MAP

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()

# START_BLOCK_PACKET_STATE
class PacketState(enum.Enum):
    """Canonical packet states — 8 total. CANCELLED reserved for post-MVP."""

    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    ACCEPTED = "accepted"
    MERGED = "merged"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"  # reserved, no endpoint creates this in MVP-0

# END_BLOCK_PACKET_STATE

# START_BLOCK_TABLES
class Feature(Base):
    """Feature table — top-level business feature."""

    __tablename__ = "features"

    id = Column(String, primary_key=True)
    slug = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    spec_json = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default="NOT_STARTED")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Wave(Base):
    """Wave table — sequential group of packets."""

    __tablename__ = "waves"

    id = Column(String, primary_key=True)
    feature_id = Column(String, nullable=False, index=True)
    slug = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    order = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="NOT_STARTED")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Packet(Base):
    """Packet table — self-contained work unit."""

    __tablename__ = "packets"

    id = Column(String, primary_key=True)
    feature_id = Column(String, nullable=False, index=True)
    wave_id = Column(String, nullable=False, index=True)
    slug = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    spec_json = Column(JSON, nullable=False)
    state = Column(String, nullable=False, default=PacketState.DRAFT.value, index=True)
    acceptance_profile = Column(String, nullable=False, default="NORMAL")
    attempt_count = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PacketRun(Base):
    """PacketRun table — one execution attempt."""

    __tablename__ = "packet_runs"

    id = Column(String, primary_key=True)
    packet_id = Column(String, nullable=False, index=True)
    run_number = Column(Integer, nullable=False)
    executor_id = Column(String)
    worker_id = Column(String, index=True)
    status = Column(String, nullable=False)
    result_json = Column(JSON)
    evidence_path = Column(String)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration_ms = Column(Integer)


class Worker(Base):
    """Worker table — registered execution agent."""

    __tablename__ = "workers"

    id = Column(String, primary_key=True)
    status = Column(String, nullable=False, default="active")
    current_packet_id = Column(String, index=True)
    last_heartbeat = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Lease(Base):
    """Lease table — exclusive packet claim, SQLite-safe."""

    __tablename__ = "leases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    packet_id = Column(String, nullable=False, unique=True, index=True)
    worker_id = Column(String, nullable=False, index=True)
    acquired_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    heartbeat_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Event(Base):
    """Event log table — audit trail."""

    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)
    payload_json = Column(JSON)
    trace_id = Column(String, index=True)


class SelfEvolutionSession(Base):
    """SelfEvolution session table — tracks self-modification runs."""

    __tablename__ = "self_evolution_sessions"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    status = Column(String, nullable=False, default="pending")
    feature_id = Column(String, nullable=True)
    context_json = Column(JSON, nullable=True)
    constraints_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)

# END_BLOCK_TABLES
