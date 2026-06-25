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

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text, Numeric, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# START_BLOCK_PACKET_STATE
class PacketState(enum.Enum):
    """Canonical packet states — 10 total. CANCELLED reserved for post-MVP.
    BLOCKED is deprecated alias kept for backward compat (reads as BLOCKED_FINAL).
    Use BLOCKED_RECOVERABLE when a blocked packet may retry; BLOCKED_FINAL is terminal.
    """

    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    ACCEPTED = "accepted"
    MERGED = "merged"
    REJECTED = "rejected"
    BLOCKED = "blocked"  # deprecated alias for BLOCKED_FINAL
    FAILED = "failed"
    CANCELLED = "cancelled"  # reserved, no endpoint creates this in MVP-0
    BLOCKED_RECOVERABLE = "blocked_recoverable"  # NEW: retryable, requires architect intervention
    BLOCKED_FINAL = "blocked_final"  # NEW: true terminal

# END_BLOCK_PACKET_STATE

# START_BLOCK_TABLES
class Feature(Base):
    """Feature table — top-level business feature.
    id = canonical generated UID (e.g. feat_K7F3P9Qx2L), not title-derived slug.
    slug = human-readable title-derived label, not a primary identifier.
    """

    __tablename__ = "features"

    id = Column(String, primary_key=True)
    slug = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    spec_json = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default="NOT_STARTED")
    degraded_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Wave(Base):
    """Wave table — sequential group of packets.
    id = canonical generated UID (e.g. wave_A9mP2qR7Vz), not order/slug-derived.
    slug = human-readable title-derived label.
    order = display/processing order within the feature.
    """

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
    """Packet table — self-contained work unit.
    id = canonical generated UID (e.g. pkt_T4V9K2mA1b), not feature/wave/action-derived.
    slug = human-readable title-derived label.
    """

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

    # Admin v2: which model / which command / which prompt was used.
    # Populated by packet_executor at run_started. Nullable for legacy rows.
    model = Column(String, nullable=True)
    command_preview = Column(JSON, nullable=True)
    prompt = Column(Text, nullable=True)
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    cost_usd = Column(Numeric(10, 6), nullable=True)


class Worker(Base):
    """Worker table — registered execution agent."""

    __tablename__ = "workers"

    id = Column(String, primary_key=True)
    status = Column(String, nullable=False, default="active")
    current_packet_id = Column(String, index=True)
    last_heartbeat = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    pid = Column(Integer, nullable=True)  # OS PID for signalling


class Lease(Base):
    """Lease table — exclusive packet claim with fencing token, SQLite-safe.

    W01: Added claimed_attempt column for lease fencing. A stale worker
    cannot release a packet after its lease has been reclaimed by another
    worker because the claimed_attempt won't match.
    """

    __tablename__ = "leases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    packet_id = Column(String, nullable=False, unique=True, index=True)
    worker_id = Column(String, nullable=False, index=True)
    claimed_attempt = Column(Integer, nullable=False, default=0)
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
    # W11: explicit fields for risk/approval/rollback
    risk_class = Column(String, nullable=True)
    requires_approval = Column(Boolean, default=True)
    base_branch = Column(String, default="main")
    rollback_plan = Column(JSON, nullable=True)
    prompt = Column(Text, nullable=True)


class FeaturePlanningRun(Base):
    """Observable planning run stage for a feature."""

    __tablename__ = "feature_planning_runs"

    id = Column(String, primary_key=True)
    feature_id = Column(String, nullable=False, index=True)
    stage = Column(String, nullable=False, index=True)
    # submit | context_builder | architect | materialize
    status = Column(String, nullable=False, index=True)
    # pending | running | done | failed | skipped
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    last_heartbeat = Column(DateTime, nullable=True)
    executor_id = Column(String, nullable=True)
    model = Column(String, nullable=True)
    prompt = Column(Text, nullable=True)
    stdout_path = Column(String, nullable=True)
    stderr_path = Column(String, nullable=True)
    result_json = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    trace_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AgentSession(Base):
    """Tracks LLM sessions for resume/fork across attempts.

    TZ_SESSION_RESUME.md Phase 1. Records every agent run (coder,
    architect, verifier, reviewer) so the operator can:
    - View session chain in admin UI (cross-reference packet ↔ session)
    - Recover from worktree cleanup (sessions survive in DB)
    - Audit which model ran which attempt
    """

    __tablename__ = "agent_sessions"

    id = Column(String, primary_key=True)            # internal UID (ses_XXXX)
    external_id = Column(String, nullable=True, index=True)  # session_id from opencode/agy
    packet_id = Column(String, nullable=False, index=True)
    run_id = Column(String, nullable=True, index=True)  # PacketRun.id
    role = Column(String, nullable=False)             # coder | architect | verifier | reviewer
    executor_id = Column(String, nullable=True)       # agent profile ID
    backend = Column(String, nullable=False)          # opencode | agy
    attempt_number = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="active")  # active | completed | failed | forked
    parent_session_id = Column(String, nullable=True) # for forks — points to original
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    # Forward-compat: if the table doesn't exist, callers should
    # detect via sqlite_master and skip silently.


class StageRun(Base):
    __tablename__ = "stage_runs"

    id = Column(String, primary_key=True)        # srun_XXXX
    packet_id = Column(String, nullable=False, index=True)
    run_id = Column(String, nullable=True, index=True)  # PacketRun.id
    feature_id = Column(String, nullable=False, index=True)
    wave_id = Column(String, nullable=False, index=True)

    # Stage identity
    stage_key = Column(String, nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False, default=1)
    loop_round = Column(Integer, nullable=False, default=1)
    parent_stage_run_id = Column(String, nullable=True)  # для возвратов

    # Timing
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    last_heartbeat = Column(DateTime, nullable=True)

    # Status
    status = Column(String, nullable=False, default="pending")
    error = Column(Text, nullable=True)

    # Executor info
    executor_id = Column(String, nullable=True)
    worker_id = Column(String, nullable=True)
    model = Column(String, nullable=True)
    prompt_hash = Column(String, nullable=True)  # sha256 of prompt
    command_preview = Column(JSON, nullable=True)

    # LLM cost (для LLM-стадий)
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    cost_usd = Column(Numeric(10, 6), nullable=True)

    # Artifacts
    stdout_path = Column(String, nullable=True)
    stderr_path = Column(String, nullable=True)
    result_path = Column(String, nullable=True)  # evidence/decision json
    artifacts_dir = Column(String, nullable=True)  # директория с артефактами

    # Trace и recovery
    trace_id = Column(String, nullable=True, index=True)
    recovery_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class StageMetric(Base):
    __tablename__ = "stage_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stage_key = Column(String, nullable=False, index=True)
    period_kind = Column(String, nullable=False)  # 24h|7d|30d
    period_start = Column(DateTime, nullable=False, index=True)
    period_end = Column(DateTime, nullable=False)

    count = Column(Integer, nullable=False)
    p50_ms = Column(Integer, nullable=True)
    p95_ms = Column(Integer, nullable=True)
    avg_ms = Column(Integer, nullable=True)
    max_ms = Column(Integer, nullable=True)
    min_ms = Column(Integer, nullable=True)

    success_count = Column(Integer, nullable=False, default=0)
    failure_count = Column(Integer, nullable=False, default=0)
    success_rate = Column(Numeric(5, 4), nullable=True)

    # LLM cost (для LLM-стадий)
    avg_tokens_in = Column(Integer, nullable=True)
    avg_tokens_out = Column(Integer, nullable=True)
    avg_cost_usd = Column(Numeric(10, 6), nullable=True)
    total_cost_usd = Column(Numeric(10, 6), nullable=True)

    # Idle time: claim → start, для executor/coder стадий
    avg_idle_seconds = Column(Integer, nullable=True)

    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("stage_key", "period_kind", "period_start",
                         name="uq_stage_metrics_period"),
    )

# END_BLOCK_TABLES
