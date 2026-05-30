# ############################################################################
# AI_HEADER: pipeline_tasks.canon_tasks
# ROLE: Canon digest recording Prefect task for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Record canon digest output for feature_pipeline.
# inputs: Feature id and canon digest run payload.
# returns: Updated feature record.
# side_effects: Reads agent output, writes canon-digest.md, and updates feature state.
# emitted_logs: Prefect task logs when available.
# error_behavior: Propagates state lookup, file write, and update errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: record_canon_digest_task
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from prefect_grace.prefect_compat import get_run_logger, task
from prefect_grace.tasks.agent_output_parser import read_agent_message
from prefect_grace.tasks.state_store import find_record, update_record


# START_FUNCTION_CONTRACT
# name: record_canon_digest_task
# purpose: Persist canon digest output for a feature and record its path.
# inputs:
#   feature_id: Feature identifier.
#   canon_digest_run: Agent run payload with message/stdout paths.
#   state_root: State root directory path.
# returns: Updated feature record.
# side_effects: Writes canon-digest.md and updates feature state.
# emitted_logs: Prefect task log line when logger is available.
# error_behavior: Propagates file and state update errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="canon-digest:record:{feature_id}")
def record_canon_digest_task(feature_id: str, canon_digest_run: dict, *, state_root: Path | str):
    try:
        logger = get_run_logger()
    except Exception:
        logger = None
    feature = find_record("features", "features", "feature_id", feature_id, state_root=state_root)
    feature_dir = Path(str(feature.get("feature_dir") or (Path("prefect_grace/packets") / feature_id)))
    output_path = feature_dir / "canon-digest.md"
    output_text = read_agent_message(canon_digest_run.get("last_message_path"), canon_digest_run.get("stdout_path")).strip()
    if not output_text:
        output_text = "# Canon Digest\n\nNo canon digest output was captured.\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_text + "\n", encoding="utf-8")
    if logger is not None:
        logger.info("Recorded canon digest for %s at %s", feature_id, output_path)
    return update_record("features", "features", "feature_id", feature_id, {"canon_digest_path": str(output_path)}, state_root=state_root)
