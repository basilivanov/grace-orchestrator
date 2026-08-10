# ############################################################################
# AI_HEADER: safe_parallel_execution — Parallel scope/key lease schema
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Add the durable parallel lease snapshot used by atomic packet claims.
# inputs: Alembic migration context and SQLAlchemy schema types.
# returns: None from upgrade and downgrade.
# side_effects: Creates or removes the parallel_leases table and its indexes.
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

_log = GraceLogger("alembic_parallel")

revision: str = "0002_safe_parallel_execution"
down_revision: str | None = "0001_grace_legacy_baseline"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# START_BLOCK_SCHEMA
# START_FUNCTION_CONTRACT
# name: upgrade
# purpose: Create the parallel lease table and canonical lookup indexes.
# inputs: None; Alembic supplies the active migration context.
# returns: None.
# side_effects: Creates the parallel_leases table and indexes if absent.
# emitted_logs: upgrade_start, upgrade_done.
# error_behavior: Propagates database DDL errors.
# END_FUNCTION_CONTRACT
def upgrade() -> None:
    _log.info("upgrade_start", reason="safe_parallel_execution")
    op.create_table(
        "parallel_leases",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("packet_id", sa.String(), nullable=False),
        sa.Column("feature_id", sa.String(), nullable=False),
        sa.Column("wave_id", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("claimed_attempt", sa.Integer(), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("conflict_keys_json", sa.JSON(), nullable=False),
        sa.Column("base_sha", sa.String(), nullable=True),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("packet_id", name="uq_parallel_leases_packet_id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_parallel_leases_packet_id",
        "parallel_leases",
        ["packet_id"],
        unique=True,
        if_not_exists=True,
    )
    op.create_index(
        "ix_parallel_leases_feature_id",
        "parallel_leases",
        ["feature_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_parallel_leases_wave_id",
        "parallel_leases",
        ["wave_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_parallel_leases_feature_wave",
        "parallel_leases",
        ["feature_id", "wave_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_parallel_leases_worker_id",
        "parallel_leases",
        ["worker_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_parallel_leases_expires_at",
        "parallel_leases",
        ["expires_at"],
        if_not_exists=True,
    )
    _log.info("upgrade_done", reason="parallel_leases_ready")


# START_FUNCTION_CONTRACT
# name: downgrade
# purpose: Remove the parallel lease schema in reverse dependency order.
# inputs: None; Alembic supplies the active migration context.
# returns: None.
# side_effects: Drops parallel lease indexes and table.
# emitted_logs: downgrade_start, downgrade_done.
# error_behavior: Propagates database DDL errors.
# END_FUNCTION_CONTRACT
def downgrade() -> None:
    _log.info("downgrade_start", reason="safe_parallel_execution")
    for index_name in (
        "ix_parallel_leases_expires_at",
        "ix_parallel_leases_worker_id",
        "ix_parallel_leases_feature_wave",
        "ix_parallel_leases_wave_id",
        "ix_parallel_leases_feature_id",
        "ix_parallel_leases_packet_id",
    ):
        op.drop_index(index_name, table_name="parallel_leases", if_exists=True)
    op.drop_table("parallel_leases", if_exists=True)
    _log.info("downgrade_done", reason="parallel_leases_removed")
# END_BLOCK_SCHEMA
