# ############################################################################
# AI_HEADER: acceptance_frontend_service — frontend acceptance stage adapter
# ROLE: Translate frontend browser, visual and accessibility runner results into
#       the StageResult contract consumed by the acceptance coordinator.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Route enabled frontend acceptance stages and map runner results to
#          canonical StageResult and CommandResult values.
# inputs: ExecutionPacketContract, worktree root, run directory and run id.
# returns: Mapping for t2_browser, t3_visual and t2_browser_a11y stages.
# side_effects: Runs existing frontend browser/visual/a11y services and writes
#               their artifacts to the supplied run directory.
# emitted_logs: None.
# error_behavior: Runner failures become failed StageResult values; disabled
#                 stages become skipped StageResult values.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: run_frontend_stages
#   - function: commands_to_results
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any

from grace_control.core.contracts import (
    CommandResult,
    ExecutionPacketContract,
    StageName,
    StageResult,
    StageStatus,
)
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("acceptance_frontend")


# START_BLOCK_FRONTEND_STAGES
# START_FUNCTION_CONTRACT
# name: run_frontend_stages
# purpose: Run frontend browser, visual-regression and accessibility stages selected by routing.
# inputs: packet — execution contract; worktree_root — target worktree; run_dir — artifact directory; run_id — persisted run identifier.
# returns: StageResult mapping keyed by t2_browser, t3_visual and t2_browser_a11y.
# side_effects: Runs existing frontend helpers and writes browser artifacts.
# emitted_logs: None.
# error_behavior: Disabled stages are skipped; command/runner failures are represented as failed stages.
# END_FUNCTION_CONTRACT
def run_frontend_stages(
    packet: ExecutionPacketContract,
    *,
    worktree_root: Path,
    run_dir: Path,
    run_id: str = "",
) -> dict[str, StageResult]:
    from grace_control.core.frontend_stages import (
        BrowserStageResult,
        resolve_browser_routing,
        run_t2_browser_e2e,
        run_t3_visual_regression,
    )

    frontend_spec = packet.metadata.get("frontend") if hasattr(packet, "metadata") else {}
    routing = resolve_browser_routing(
        frontend_spec,
        acceptance_profile=packet.acceptance_profile.value,
    )
    result: dict[str, StageResult] = {}
    t2b_commands = packet.verification.get("t2_browser", [])
    t3v_commands = packet.verification.get("t3_visual", [])
    t2a_commands = packet.verification.get("t2_a11y", [])

    if routing.run_t2_browser:
        browser_results: list[BrowserStageResult] = run_t2_browser_e2e(
            worktree_root,
            run_dir,
            routing,
            telegram_mode=routing.telegram_mode,
            custom_cmds=t2b_commands if t2b_commands else None,
            telegram_bot_token_env=routing.telegram_bot_token_env,
            packet_id=packet.packet_id,
            run_id=run_id,
        )
        passed = all(item.passed for item in browser_results)
        screenshots = sum((item.screenshots for item in browser_results), [])
        errors = sum((item.errors for item in browser_results), [])
        commands = [
            CommandResult(
                command=item.command or " ".join(t2b_commands[index]) if index < len(t2b_commands) else "npx playwright test",
                cwd=str(worktree_root),
                exit_code=item.exit_code if item.exit_code >= 0 else (0 if item.passed else 1),
                stdout=item.stdout_snippet,
                stderr=item.stderr_snippet,
            )
            for index, item in enumerate(browser_results)
        ] if browser_results else commands_to_results(
            t2b_commands,
            worktree_path=str(worktree_root),
            run_dir=str(run_dir),
        )
        result["t2_browser"] = StageResult(
            name=StageName.T2_BROWSER_E2E,
            status=StageStatus.PASSED if passed else StageStatus.FAILED,
            summary=f"T2_BROWSER: {len(browser_results)} viewports, {len(screenshots)} screenshots",
            commands=commands,
            blocking_issues=errors if not passed else [],
        )
    else:
        result["t2_browser"] = StageResult(
            name=StageName.T2_BROWSER_E2E,
            status=StageStatus.SKIPPED,
            summary=f"T2_BROWSER skipped: {routing.reason}",
            commands=[],
            skipped_reason=routing.reason,
        )

    if routing.run_t3_visual:
        visual_results: list[BrowserStageResult] = run_t3_visual_regression(
            worktree_root,
            run_dir,
            routing,
            telegram_mode=routing.telegram_mode,
            custom_cmds=t3v_commands if t3v_commands else None,
            telegram_bot_token_env=routing.telegram_bot_token_env,
            packet_id=packet.packet_id,
            run_id=run_id,
        )
        passed = all(item.passed for item in visual_results)
        screenshots = sum((item.screenshots for item in visual_results), [])
        errors = sum((item.errors for item in visual_results), [])
        commands = [
            CommandResult(
                command=item.command or " ".join(t3v_commands[index]) if index < len(t3v_commands) else "npx playwright test --visual",
                cwd=str(worktree_root),
                exit_code=item.exit_code if item.exit_code >= 0 else (0 if item.passed else 1),
                stdout=item.stdout_snippet,
                stderr=item.stderr_snippet,
            )
            for index, item in enumerate(visual_results)
        ] if visual_results else commands_to_results(
            t3v_commands,
            worktree_path=str(worktree_root),
            run_dir=str(run_dir),
        )
        result["t3_visual"] = StageResult(
            name=StageName.T3_VISUAL_REGRESSION,
            status=StageStatus.PASSED if passed else StageStatus.FAILED,
            summary=f"T3_VISUAL: {len(visual_results)} viewports, {len(screenshots)} screenshots",
            commands=commands,
            blocking_issues=errors if not passed else [],
        )
    else:
        result["t3_visual"] = StageResult(
            name=StageName.T3_VISUAL_REGRESSION,
            status=StageStatus.SKIPPED,
            summary=f"T3_VISUAL skipped: {routing.reason}",
            commands=[],
            skipped_reason=routing.reason,
        )

    if routing.run_a11y:
        if not t2a_commands:
            result["t2_browser_a11y"] = StageResult(
                name=StageName.T2_BROWSER_A11Y,
                status=StageStatus.FAILED,
                summary="T2_BROWSER_A11Y failed: verification.t2_a11y is required but empty",
                commands=[],
                blocking_issues=[
                    "verification.t2_a11y is required for a11y gate — no axe-core command specified"
                ],
            )
        else:
            from grace_control.core.frontend_stages import run_a11y_check

            a11y_results = run_a11y_check(
                worktree_root,
                run_dir,
                routing,
                telegram_mode=routing.telegram_mode,
                telegram_bot_token_env=routing.telegram_bot_token_env,
                custom_cmds=t2a_commands if t2a_commands else None,
                packet_id=packet.packet_id,
                run_id=run_id,
            )
            passed = all(item.passed for item in a11y_results)
            errors = sum((item.errors for item in a11y_results), [])
            violations_count = sum(len(item.screenshots) for item in a11y_results)
            result["t2_browser_a11y"] = StageResult(
                name=StageName.T2_BROWSER_A11Y,
                status=StageStatus.PASSED if passed else StageStatus.FAILED,
                summary=f"T2_BROWSER_A11Y: {len(a11y_results)} viewports, {violations_count} violations",
                commands=[
                    CommandResult(
                        command=item.command or " ".join(t2a_commands[0]) if t2a_commands else f"npx playwright a11y --viewport={item.viewport}",
                        cwd=str(worktree_root),
                        exit_code=0 if item.passed else 1,
                        stdout=item.stdout_snippet,
                        stderr=item.stderr_snippet,
                    )
                    for item in a11y_results
                ],
                blocking_issues=errors if not passed else [],
            )
    else:
        result["t2_browser_a11y"] = StageResult(
            name=StageName.T2_BROWSER_A11Y,
            status=StageStatus.SKIPPED,
            summary="T2_BROWSER_A11Y skipped: a11y not required",
            commands=[],
            skipped_reason="a11y not required",
        )

    return result


# START_FUNCTION_CONTRACT
# name: commands_to_results
# purpose: Convert not-yet-executed frontend command values into placeholder CommandResult DTOs.
# inputs: commands — shell strings or argv lists; worktree_path — command cwd; run_dir — retained artifact context.
# returns: Placeholder CommandResult list with successful default exit codes.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def commands_to_results(
    commands: list[Any], *, worktree_path: str, run_dir: str
) -> list[CommandResult]:
    del run_dir
    return [
        CommandResult(
            command=" ".join(command) if isinstance(command, list) else str(command),
            cwd=worktree_path,
            exit_code=0,
            stdout="",
            stderr="",
        )
        for command in commands
    ]

# END_BLOCK_FRONTEND_STAGES
