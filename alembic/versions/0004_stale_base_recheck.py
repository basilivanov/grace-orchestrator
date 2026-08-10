# ############################################################################
# AI_HEADER: 0004_stale_base_recheck — PacketRun target-base snapshots
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Persist the target repository base and the validated integration
#          base for stale-base merge protection.
# inputs: Alembic migration context and SQLAlchemy schema types.
# returns: None from upgrade and downgrade.
# side_effects: Adds or removes two nullable packet_runs columns.
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

_log = GraceLogger("alembic_stale_base_recheck")

revision: str = "0004_stale_base_recheck"
down_revision: str | None = "0003_serialized_merge"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# START_BLOCK_SCHEMA
# START_FUNCTION_CONTRACT
# name: upgrade
# purpose: Add nullable target and integration base snapshots to PacketRun.
# inputs: None; Alembic supplies the active migration context.
# returns: None.
# side_effects: Adds packet_runs.base_sha and packet_runs.integration_base_sha.
# emitted_logs: upgrade_start, upgrade_done.
# error_behavior: Propagates database DDL errors.
# END_FUNCTION_CONTRACT
def upgrade() -> None:
    _log.info("upgrade_start", reason="stale_base_recheck")
    existing = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("packet_runs")
    }
    missing = {"base_sha", "integration_base_sha"} - existing
    if missing:
        with op.batch_alter_table("packet_runs", schema=None) as batch_op:
            if "base_sha" in missing:
                batch_op.add_column(sa.Column("base_sha", sa.String(), nullable=True))
            if "integration_base_sha" in missing:
                batch_op.add_column(sa.Column("integration_base_sha", sa.String(), nullable=True))
    _log.info("upgrade_done", reason="packet_run_base_snapshots_ready")


# START_FUNCTION_CONTRACT
# name: downgrade
# purpose: Remove stale-base target and integration snapshots from PacketRun.
# inputs: None; Alembic supplies the active migration context.
# returns: None.
# side_effects: Removes packet_runs.integration_base_sha and packet_runs.base_sha.
# emitted_logs: downgrade_start, downgrade_done.
# error_behavior: Propagates database DDL errors.
# END_FUNCTION_CONTRACT
def downgrade() -> None:
    _log.info("downgrade_start", reason="stale_base_recheck")
    existing = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("packet_runs")
    }
    removable = {"base_sha", "integration_base_sha"} & existing
    if removable:
        with op.batch_alter_table("packet_runs", schema=None) as batch_op:
            if "integration_base_sha" in removable:
                batch_op.drop_column("integration_base_sha")
            if "base_sha" in removable:
                batch_op.drop_column("base_sha")
    _log.info("downgrade_done", reason="packet_run_base_snapshots_removed")
# END_BLOCK_SCHEMA
