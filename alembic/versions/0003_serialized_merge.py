# ############################################################################
# AI_HEADER: 0003_serialized_merge — DB-backed serialized merge leases
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Add the durable fencing lease used to serialize mutations of one
#          logical target repository.
# inputs: Alembic migration context and SQLAlchemy schema types.
# returns: None from upgrade and downgrade.
# side_effects: Creates or removes the merge_leases table and expiry index.
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

_log = GraceLogger("alembic_serialized_merge")

revision: str = "0003_serialized_merge"
down_revision: str | None = "0002_safe_parallel_execution"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# START_BLOCK_SCHEMA
# START_FUNCTION_CONTRACT
# name: upgrade
# purpose: Create the target-repository merge lease and expiry index.
# inputs: None; Alembic supplies the active migration context.
# returns: None.
# side_effects: Creates merge_leases and its expiry lookup index.
# emitted_logs: upgrade_start, upgrade_done.
# error_behavior: Propagates database DDL errors.
# END_FUNCTION_CONTRACT
def upgrade() -> None:
    _log.info("upgrade_start", reason="serialized_merge")
    op.create_table(
        "merge_leases",
        sa.Column("target_repo_key", sa.String(), nullable=False),
        sa.Column("lease_token", sa.String(), nullable=False),
        sa.Column("packet_id", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("target_repo_key"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_merge_leases_packet_id",
        "merge_leases",
        ["packet_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_merge_leases_worker_id",
        "merge_leases",
        ["worker_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_merge_leases_expires_at",
        "merge_leases",
        ["expires_at"],
        if_not_exists=True,
    )
    _log.info("upgrade_done", reason="merge_leases_ready")


# START_FUNCTION_CONTRACT
# name: downgrade
# purpose: Remove the serialized merge lease schema.
# inputs: None; Alembic supplies the active migration context.
# returns: None.
# side_effects: Drops the merge lease expiry index and table.
# emitted_logs: downgrade_start, downgrade_done.
# error_behavior: Propagates database DDL errors.
# END_FUNCTION_CONTRACT
def downgrade() -> None:
    _log.info("downgrade_start", reason="serialized_merge")
    for index_name in (
        "ix_merge_leases_expires_at",
        "ix_merge_leases_worker_id",
        "ix_merge_leases_packet_id",
    ):
        op.drop_index(index_name, table_name="merge_leases", if_exists=True)
    op.drop_table("merge_leases", if_exists=True)
    _log.info("downgrade_done", reason="merge_leases_removed")
# END_BLOCK_SCHEMA
