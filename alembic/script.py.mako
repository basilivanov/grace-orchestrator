# ############################################################################
# AI_HEADER: alembic_revision — Template for GRACE Alembic revisions
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Generate a GRACE-canon Alembic revision module.
# inputs: Alembic revision identifiers and generated migration body.
# returns: A Python Alembic revision source file.
# side_effects: None; consumed by Alembic revision generation.
# emitted_logs: None.
# error_behavior: Alembic reports template rendering errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: upgrade
#   - function: downgrade
# END_MODULE_MAP

"""${message}"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("alembic_revision")


revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


# START_BLOCK_MIGRATION
# START_FUNCTION_CONTRACT
# name: upgrade
# purpose: Apply this Alembic revision.
# inputs: None; Alembic supplies the active migration context.
# returns: None.
# side_effects: Changes database schema through Alembic operations.
# emitted_logs: upgrade_start, upgrade_done.
# error_behavior: Propagates migration errors.
# END_FUNCTION_CONTRACT
def upgrade() -> None:
    _log.info("upgrade_start")
${upgrades if upgrades else "    pass"}
    _log.info("upgrade_done")


# START_FUNCTION_CONTRACT
# name: downgrade
# purpose: Revert this Alembic revision.
# inputs: None; Alembic supplies the active migration context.
# returns: None.
# side_effects: Reverts database schema through Alembic operations.
# emitted_logs: downgrade_start, downgrade_done.
# error_behavior: Propagates migration errors.
# END_FUNCTION_CONTRACT
def downgrade() -> None:
    _log.info("downgrade_start")
${downgrades if downgrades else "    pass"}
    _log.info("downgrade_done")
# END_BLOCK_MIGRATION
