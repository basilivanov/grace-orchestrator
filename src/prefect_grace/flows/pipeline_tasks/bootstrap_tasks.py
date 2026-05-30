# ############################################################################
# AI_HEADER: pipeline_tasks.bootstrap_tasks
# ROLE: Feature bootstrap and packet seeding Prefect tasks for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide decorated bootstrap tasks extracted from feature_pipeline without behavior changes.
# inputs: Feature identifiers, titles, summaries, verifier settings, planner contract settings, and agent hints.
# returns: Feature bootstrap records and seeded packet graph dictionaries.
# side_effects: Writes feature/packet state through existing feature_bootstrap task APIs.
# emitted_logs: Prefect task logs.
# error_behavior: Propagates existing bootstrap and seeding errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: bootstrap_task
#   - function: seed_feature_packets_task
# END_MODULE_MAP

from __future__ import annotations

from prefect_grace.prefect_compat import get_run_logger, task
from prefect_grace.tasks.feature_bootstrap import bootstrap_feature, seed_test_feature


# START_FUNCTION_CONTRACT
# name: bootstrap_task
# purpose: Bootstrap the feature record for a feature pipeline run.
# inputs:
#   feature_id: Feature identifier.
#   title: Feature title.
#   summary: Feature summary.
# returns: Feature record dictionary.
# side_effects: Writes feature state through bootstrap_feature.
# emitted_logs: Prefect task log line.
# error_behavior: Propagates bootstrap_feature errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="bootstrap:{feature_id}")
def bootstrap_task(feature_id: str, title: str, summary: str):
    logger = get_run_logger()
    record = bootstrap_feature(feature_id=feature_id, title=title, summary=summary)
    logger.info("Bootstrapped feature %s", feature_id)
    return record


# START_FUNCTION_CONTRACT
# name: seed_feature_packets_task
# purpose: Seed role packets for a feature pipeline run.
# inputs:
#   feature_id: Feature identifier and task seeding options.
# returns: Seeded feature packet graph dictionary.
# side_effects: Writes packet state and packet files through seed_test_feature.
# emitted_logs: Prefect task log line.
# error_behavior: Propagates seed_test_feature errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="seed-packets:{feature_id}")
def seed_feature_packets_task(
    feature_id: str,
    title: str,
    summary: str,
    implementation_title: str,
    implementation_summary: str,
    verifier_backend_profile: str | None,
    verifier_frontend_profile: str | None,
    verifier_frontend_commands: list[str] | None,
    verifier_observability_profile: str | None,
    verifier_observability_commands: list[str] | None,
    verifier_artifact_globs: list[str] | None,
    verifier_touches_frontend: bool,
    verifier_requires_frontend_visual: bool,
    verifier_include_day_live_canary: bool,
    agent_workdir: str | None,
    agent_sandbox: str | None,
    business_context: dict | None = None,
    planner_contract: dict | None = None,
    include_planner_packet: bool = False,
    materialize_execution_packets: bool = True,
):
    logger = get_run_logger()
    logger.info("Seeding role packets for %s", feature_id)
    return seed_test_feature(
        feature_id=feature_id,
        title=title,
        summary=summary,
        implementation_title=implementation_title,
        implementation_summary=implementation_summary,
        verifier_backend_profile=verifier_backend_profile,
        verifier_frontend_profile=verifier_frontend_profile,
        verifier_frontend_commands=verifier_frontend_commands,
        verifier_observability_profile=verifier_observability_profile,
        verifier_observability_commands=verifier_observability_commands,
        verifier_artifact_globs=verifier_artifact_globs,
        verifier_touches_frontend=verifier_touches_frontend,
        verifier_requires_frontend_visual=verifier_requires_frontend_visual,
        verifier_include_day_live_canary=verifier_include_day_live_canary,
        agent_workdir=agent_workdir,
        agent_sandbox=agent_sandbox,
        business_context=business_context,
        planner_contract=planner_contract,
        include_planner_packet=include_planner_packet,
        materialize_execution_packets=materialize_execution_packets,
    )
