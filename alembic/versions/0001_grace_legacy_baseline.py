# ############################################################################
# AI_HEADER: grace_legacy_baseline — Current normalized GRACE database schema
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Create or remove the current normalized GRACE schema as the initial
#          Alembic revision used for fresh and pre-Alembic databases.
# inputs: Alembic migration context and SQLAlchemy schema types.
# returns: None from upgrade and downgrade.
# side_effects: Creates or drops GRACE tables and indexes in the active database.
# emitted_logs: upgrade_start, upgrade_done, downgrade_start, downgrade_done.
# error_behavior: Propagates Alembic and database DDL errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: upgrade
#   - function: downgrade
# END_MODULE_MAP

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("alembic_baseline")

revision: str = "0001_grace_legacy_baseline"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# START_BLOCK_SCHEMA
# START_FUNCTION_CONTRACT
# name: upgrade
# purpose: Create the current normalized GRACE schema on a fresh database and
#          complete absent baseline tables during the one-time legacy bridge.
# inputs: None; Alembic supplies the active migration context.
# returns: None.
# side_effects: Creates GRACE tables and indexes if they do not already exist.
# emitted_logs: upgrade_start, upgrade_done.
# error_behavior: Propagates database DDL errors.
# END_FUNCTION_CONTRACT
def upgrade() -> None:
    _log.info("upgrade_start", reason="grace_baseline")

    op.create_table(
        "features",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("spec_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("degraded_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_table(
        "waves",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("feature_id", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_table(
        "packets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("feature_id", sa.String(), nullable=False),
        sa.Column("wave_id", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("spec_json", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("acceptance_profile", sa.String(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_table(
        "packet_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("packet_id", sa.String(), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("executor_id", sa.String(), nullable=True),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("evidence_path", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("command_preview", sa.JSON(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_table(
        "workers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_packet_id", sa.String(), nullable=True),
        sa.Column("last_heartbeat", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_table(
        "leases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("packet_id", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("claimed_attempt", sa.Integer(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("packet_id"),
        if_not_exists=True,
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_table(
        "self_evolution_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("feature_id", sa.String(), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.Column("constraints_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("risk_class", sa.String(), nullable=True),
        sa.Column("requires_approval", sa.Boolean(), nullable=True),
        sa.Column("base_branch", sa.String(), nullable=True),
        sa.Column("rollback_plan", sa.JSON(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_table(
        "feature_planning_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("feature_id", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("last_heartbeat", sa.DateTime(), nullable=True),
        sa.Column("executor_id", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("stdout_path", sa.String(), nullable=True),
        sa.Column("stderr_path", sa.String(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("packet_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("executor_id", sa.String(), nullable=True),
        sa.Column("backend", sa.String(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("parent_session_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_table(
        "stage_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("packet_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("feature_id", sa.String(), nullable=False),
        sa.Column("wave_id", sa.String(), nullable=False),
        sa.Column("stage_key", sa.String(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("loop_round", sa.Integer(), nullable=False),
        sa.Column("parent_stage_run_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("last_heartbeat", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("executor_id", sa.String(), nullable=True),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("prompt_hash", sa.String(), nullable=True),
        sa.Column("command_preview", sa.JSON(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("stdout_path", sa.String(), nullable=True),
        sa.Column("stderr_path", sa.String(), nullable=True),
        sa.Column("result_path", sa.String(), nullable=True),
        sa.Column("artifacts_dir", sa.String(), nullable=True),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column("recovery_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_table(
        "stage_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stage_key", sa.String(), nullable=False),
        sa.Column("period_kind", sa.String(), nullable=False),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("p50_ms", sa.Integer(), nullable=True),
        sa.Column("p95_ms", sa.Integer(), nullable=True),
        sa.Column("avg_ms", sa.Integer(), nullable=True),
        sa.Column("max_ms", sa.Integer(), nullable=True),
        sa.Column("min_ms", sa.Integer(), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("success_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("avg_tokens_in", sa.Integer(), nullable=True),
        sa.Column("avg_tokens_out", sa.Integer(), nullable=True),
        sa.Column("avg_cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("total_cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("avg_idle_seconds", sa.Integer(), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stage_key", "period_kind", "period_start", name="uq_stage_metrics_period"),
        if_not_exists=True,
    )

    indexes = (
        ("ix_features_slug", "features", ("slug",), False),
        ("ix_waves_feature_id", "waves", ("feature_id",), False),
        ("ix_packets_feature_id", "packets", ("feature_id",), False),
        ("ix_packets_wave_id", "packets", ("wave_id",), False),
        ("ix_packets_state", "packets", ("state",), False),
        ("ix_packet_runs_packet_id", "packet_runs", ("packet_id",), False),
        ("ix_packet_runs_worker_id", "packet_runs", ("worker_id",), False),
        ("ix_workers_current_packet_id", "workers", ("current_packet_id",), False),
        ("ix_leases_packet_id", "leases", ("packet_id",), True),
        ("ix_leases_worker_id", "leases", ("worker_id",), False),
        ("ix_leases_expires_at", "leases", ("expires_at",), False),
        ("ix_events_timestamp", "events", ("timestamp",), False),
        ("ix_events_event_type", "events", ("event_type",), False),
        ("ix_events_entity_type", "events", ("entity_type",), False),
        ("ix_events_entity_id", "events", ("entity_id",), False),
        ("ix_events_trace_id", "events", ("trace_id",), False),
        ("ix_feature_planning_runs_feature_id", "feature_planning_runs", ("feature_id",), False),
        ("ix_feature_planning_runs_stage", "feature_planning_runs", ("stage",), False),
        ("ix_feature_planning_runs_status", "feature_planning_runs", ("status",), False),
        ("ix_feature_planning_runs_trace_id", "feature_planning_runs", ("trace_id",), False),
        ("ix_agent_sessions_external_id", "agent_sessions", ("external_id",), False),
        ("ix_agent_sessions_packet_id", "agent_sessions", ("packet_id",), False),
        ("ix_agent_sessions_run_id", "agent_sessions", ("run_id",), False),
        ("ix_stage_runs_packet_id", "stage_runs", ("packet_id",), False),
        ("ix_stage_runs_run_id", "stage_runs", ("run_id",), False),
        ("ix_stage_runs_feature_id", "stage_runs", ("feature_id",), False),
        ("ix_stage_runs_wave_id", "stage_runs", ("wave_id",), False),
        ("ix_stage_runs_stage_key", "stage_runs", ("stage_key",), False),
        ("ix_stage_runs_trace_id", "stage_runs", ("trace_id",), False),
        ("ix_stage_metrics_period_start", "stage_metrics", ("period_start",), False),
        ("ix_stage_metrics_stage_key", "stage_metrics", ("stage_key",), False),
    )
    for index_name, table_name, columns, unique in indexes:
        op.create_index(index_name, table_name, list(columns), unique=unique, if_not_exists=True)

    _log.info("upgrade_done", reason="grace_baseline")


# START_FUNCTION_CONTRACT
# name: downgrade
# purpose: Remove the complete baseline schema in reverse dependency order.
# inputs: None; Alembic supplies the active migration context.
# returns: None.
# side_effects: Drops GRACE indexes and tables.
# emitted_logs: downgrade_start, downgrade_done.
# error_behavior: Propagates database DDL errors.
# END_FUNCTION_CONTRACT
def downgrade() -> None:
    _log.info("downgrade_start", reason="grace_baseline")
    indexes = (
        ("ix_stage_metrics_stage_key", "stage_metrics"),
        ("ix_stage_metrics_period_start", "stage_metrics"),
        ("ix_stage_runs_trace_id", "stage_runs"),
        ("ix_stage_runs_stage_key", "stage_runs"),
        ("ix_stage_runs_wave_id", "stage_runs"),
        ("ix_stage_runs_feature_id", "stage_runs"),
        ("ix_stage_runs_run_id", "stage_runs"),
        ("ix_stage_runs_packet_id", "stage_runs"),
        ("ix_agent_sessions_run_id", "agent_sessions"),
        ("ix_agent_sessions_packet_id", "agent_sessions"),
        ("ix_agent_sessions_external_id", "agent_sessions"),
        ("ix_feature_planning_runs_trace_id", "feature_planning_runs"),
        ("ix_feature_planning_runs_status", "feature_planning_runs"),
        ("ix_feature_planning_runs_stage", "feature_planning_runs"),
        ("ix_feature_planning_runs_feature_id", "feature_planning_runs"),
        ("ix_events_trace_id", "events"),
        ("ix_events_entity_id", "events"),
        ("ix_events_entity_type", "events"),
        ("ix_events_event_type", "events"),
        ("ix_events_timestamp", "events"),
        ("ix_leases_expires_at", "leases"),
        ("ix_leases_worker_id", "leases"),
        ("ix_leases_packet_id", "leases"),
        ("ix_workers_current_packet_id", "workers"),
        ("ix_packet_runs_worker_id", "packet_runs"),
        ("ix_packet_runs_packet_id", "packet_runs"),
        ("ix_packets_state", "packets"),
        ("ix_packets_wave_id", "packets"),
        ("ix_packets_feature_id", "packets"),
        ("ix_waves_feature_id", "waves"),
        ("ix_features_slug", "features"),
    )
    for index_name, table_name in indexes:
        op.drop_index(index_name, table_name=table_name)

    for table_name in (
        "stage_metrics",
        "stage_runs",
        "agent_sessions",
        "feature_planning_runs",
        "self_evolution_sessions",
        "events",
        "leases",
        "workers",
        "packet_runs",
        "packets",
        "waves",
        "features",
    ):
        op.drop_table(table_name)
    _log.info("downgrade_done", reason="grace_baseline")


# END_BLOCK_SCHEMA
