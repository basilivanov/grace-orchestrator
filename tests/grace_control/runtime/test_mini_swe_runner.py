# ############################################################################
# AI_HEADER: test_mini_swe_runner — contract tests for the mini-swe CLI wrapper
# ROLE: Verifies model routing, prompt construction, JSON extraction, and
#       timeout propagation used by GRACE runtime profiles.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Exercise mini_swe_runner behavior without launching real providers.
# inputs: Pytest fixtures, temporary worktrees, and monkeypatched subprocesses.
# returns: Pytest assertions for deterministic runner contracts.
# side_effects: Creates temporary files and mutates test-local environment state.
# emitted_logs: None.
# error_behavior: Fails assertions when runtime contracts regress.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_resolve_mini_binary_uses_source_virtualenv
#   - function: test_resolve_mini_binary_recovers_from_inaccessible_absolute_path
#   - function: test_build_prompt_includes_target_worktree_agents_md
#   - function: test_build_prompt_includes_result_file_contract_for_noncoder
#   - function: test_resolve_model_arg_supports_env_default
#   - function: test_configure_openai_compatible_env_defaults_to_local_proxy
#   - function: test_configure_openai_compatible_env_routes_openai_deepseek_direct
#   - function: test_build_mini_command_adds_reasoning_effort_for_gpt
#   - function: test_build_mini_command_skips_reasoning_effort_for_gemini
#   - function: test_extract_json_returns_last_valid_json
#   - function: test_extract_json_can_ignore_command_only_json
#   - function: test_parse_json_text_prefers_whole_payload_over_nested_arrays
#   - function: test_is_role_payload_accepts_canonical_architect_wave_plan
#   - function: test_extract_json_from_trajectory_uses_only_assistant_content
#   - function: test_extract_json_from_trajectory_ignores_assistant_command_json
#   - function: test_reviewer_main_prefers_result_file_json
#   - function: test_main_uses_configured_hard_timeout_above_profile_timeout
#   - function: test_reviewer_main_does_not_parse_stdout_prompt_examples
#   - function: test_coder_main_outputs_deterministic_json_when_mini_is_fake
# END_MODULE_MAP

from __future__ import annotations

import json
import os

from grace_control.core.structured_logger import GraceLogger
from grace_control.runtime import mini_swe_runner

_log = GraceLogger("test_mini_swe_runner")


# START_BLOCK_RUNNER_TESTS
# START_FUNCTION_CONTRACT
# name: test_resolve_mini_binary_uses_source_virtualenv
# purpose: Verify source-tree virtualenv binary discovery.
# inputs: monkeypatch and tmp_path pytest fixtures.
# returns: None; asserts the resolved executable path.
# side_effects: Creates a temporary executable and changes test environment.
# emitted_logs: None.
# error_behavior: Fails when source virtualenv discovery regresses.
# END_FUNCTION_CONTRACT
def test_resolve_mini_binary_uses_source_virtualenv(monkeypatch, tmp_path):
    binary = tmp_path / ".venv" / "bin" / "test-mini-from-source"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.setattr(mini_swe_runner.sys, "executable", "/usr/bin/python3")
    monkeypatch.setenv("GRACE_SOURCE_DIR", str(tmp_path))
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)

    resolved = mini_swe_runner.resolve_mini_binary(binary.name)

    assert resolved == str(binary)
    assert os.access(resolved, os.X_OK)


# START_FUNCTION_CONTRACT
# name: test_resolve_mini_binary_recovers_from_inaccessible_absolute_path
# purpose: Verify fallback from an inaccessible configured binary.
# inputs: monkeypatch and tmp_path pytest fixtures.
# returns: None; asserts the fallback path.
# side_effects: Creates a temporary executable and changes test environment.
# emitted_logs: None.
# error_behavior: Fails when inaccessible paths are not recovered.
# END_FUNCTION_CONTRACT
def test_resolve_mini_binary_recovers_from_inaccessible_absolute_path(monkeypatch, tmp_path):
    binary = tmp_path / ".venv" / "bin" / "mini"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.setattr(mini_swe_runner.sys, "executable", "/usr/bin/python3")
    monkeypatch.setenv("GRACE_SOURCE_DIR", str(tmp_path))

    assert mini_swe_runner.resolve_mini_binary("/home/other-user/.local/bin/mini") == str(binary)


# START_FUNCTION_CONTRACT
# name: test_build_prompt_includes_target_worktree_agents_md
# purpose: Verify project instructions and execution boundary enter the prompt.
# inputs: tmp_path pytest fixture.
# returns: None; asserts prompt content and ordering.
# side_effects: Writes a temporary AGENTS.md.
# emitted_logs: None.
# error_behavior: Fails when prompt context is incomplete.
# END_FUNCTION_CONTRACT
def test_build_prompt_includes_target_worktree_agents_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Use project-local instructions.\n")

    prompt = mini_swe_runner.build_prompt("coder", "TASK BODY", tmp_path)

    assert "PROJECT INSTRUCTIONS FROM TARGET WORKTREE AGENTS.md" in prompt
    assert "Use project-local instructions." in prompt
    assert "TASK BODY" in prompt
    assert "EXECUTION BOUNDARY (highest priority)" in prompt
    assert f"only writable repository for this run is the current worktree: {tmp_path}" in prompt
    assert prompt.index("TASK BODY") < prompt.index("EXECUTION BOUNDARY")


# START_FUNCTION_CONTRACT
# name: test_build_prompt_includes_result_file_contract_for_noncoder
# purpose: Verify non-coder prompts require an external result JSON file.
# inputs: tmp_path pytest fixture.
# returns: None; asserts result-file instructions.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails when the result contract is absent.
# END_FUNCTION_CONTRACT
def test_build_prompt_includes_result_file_contract_for_noncoder(tmp_path):
    result_path = tmp_path / "out" / mini_swe_runner.RESULT_JSON_FILENAME

    prompt = mini_swe_runner.build_prompt("reviewer", "TASK BODY", tmp_path, result_path=result_path)

    assert "MINI-SWE NON-INTERACTIVE OUTPUT CONTRACT" in prompt
    assert str(result_path) in prompt
    assert "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in prompt


# START_FUNCTION_CONTRACT
# name: test_resolve_model_arg_supports_env_default
# purpose: Verify shell-style model defaults and environment overrides.
# inputs: monkeypatch pytest fixture.
# returns: None; asserts resolved model identifiers.
# side_effects: Changes test-local environment variables.
# emitted_logs: None.
# error_behavior: Fails when model interpolation changes.
# END_FUNCTION_CONTRACT
def test_resolve_model_arg_supports_env_default(monkeypatch):
    monkeypatch.delenv("GRACE_MINI_SWE_CODER_MODEL", raising=False)
    assert (
        mini_swe_runner.resolve_model_arg(
            "${GRACE_MINI_SWE_CODER_MODEL:-anthropic/claude-sonnet-4-20250514}"
        )
        == "anthropic/claude-sonnet-4-20250514"
    )

    monkeypatch.setenv("GRACE_MINI_SWE_CODER_MODEL", "openai/gpt-4.1-mini")
    assert (
        mini_swe_runner.resolve_model_arg(
            "${GRACE_MINI_SWE_CODER_MODEL:-anthropic/claude-sonnet-4-20250514}"
        )
        == "openai/gpt-4.1-mini"
    )


# START_FUNCTION_CONTRACT
# name: test_configure_openai_compatible_env_defaults_to_local_proxy
# purpose: Verify the default OpenAI-compatible route uses the local proxy.
# inputs: monkeypatch pytest fixture.
# returns: None; asserts environment configuration.
# side_effects: Changes test-local environment variables.
# emitted_logs: None.
# error_behavior: Fails when proxy defaults regress.
# END_FUNCTION_CONTRACT
def test_configure_openai_compatible_env_defaults_to_local_proxy(monkeypatch):
    for key in [
        "GRACE_MINI_SWE_OPENAI_BASE_URL",
        "GRACE_MINI_SWE_OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
        "OPENAI_API_KEY",
        "LITELLM_MODE",
        "MSWEA_COST_TRACKING",
        "MSWEA_CONFIGURED",
    ]:
        monkeypatch.delenv(key, raising=False)

    mini_swe_runner.configure_openai_compatible_env()

    assert mini_swe_runner.os.environ["OPENAI_BASE_URL"] == "http://127.0.0.1:18317/v1"
    assert mini_swe_runner.os.environ["OPENAI_API_BASE"] == "http://127.0.0.1:18317/v1"
    assert mini_swe_runner.os.environ["OPENAI_API_KEY"] == "dummy"
    assert mini_swe_runner.os.environ["LITELLM_MODE"] == "PRODUCTION"
    assert mini_swe_runner.os.environ["MSWEA_COST_TRACKING"] == "ignore_errors"
    assert mini_swe_runner.os.environ["MSWEA_CONFIGURED"] == "true"


# START_FUNCTION_CONTRACT
# name: test_configure_openai_compatible_env_routes_openai_deepseek_direct
# purpose: Verify DeepSeek models use their direct API configuration.
# inputs: monkeypatch pytest fixture.
# returns: None; asserts provider-specific environment routing.
# side_effects: Changes test-local environment variables.
# emitted_logs: None.
# error_behavior: Fails when DeepSeek routing regresses.
# END_FUNCTION_CONTRACT
def test_configure_openai_compatible_env_routes_openai_deepseek_direct(monkeypatch):
    for key in [
        "GRACE_MINI_SWE_DEEPSEEK_BASE_URL",
        "GRACE_MINI_SWE_DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
        "OPENAI_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:18317/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("GRACE_MINI_SWE_DEEPSEEK_API_KEY", "sk-deepseek")

    mini_swe_runner.configure_openai_compatible_env("openai/deepseek-v4-flash")

    assert mini_swe_runner.os.environ["OPENAI_BASE_URL"] == "https://api.deepseek.com/v1"
    assert mini_swe_runner.os.environ["OPENAI_API_BASE"] == "https://api.deepseek.com/v1"
    assert mini_swe_runner.os.environ["OPENAI_API_KEY"] == "sk-deepseek"
    assert mini_swe_runner.os.environ["DEEPSEEK_API_KEY"] == "sk-deepseek"


# START_FUNCTION_CONTRACT
# name: test_build_mini_command_adds_reasoning_effort_for_gpt
# purpose: Verify GPT commands receive configured reasoning effort.
# inputs: monkeypatch and tmp_path pytest fixtures.
# returns: None; asserts generated CLI arguments.
# side_effects: Changes test-local environment variables.
# emitted_logs: None.
# error_behavior: Fails when GPT command construction regresses.
# END_FUNCTION_CONTRACT
def test_build_mini_command_adds_reasoning_effort_for_gpt(monkeypatch, tmp_path):
    monkeypatch.setattr(mini_swe_runner, "mini_help", lambda binary: "-m -t -y -o -c --config")
    monkeypatch.delenv("GRACE_MINI_SWE_EXTRA_ARGS", raising=False)

    cmd = mini_swe_runner.build_mini_command(
        "mini",
        "openai/gpt-5.5",
        "task",
        tmp_path / "traj.json",
        "xhigh",
    )

    assert ["-c", "mini.yaml"] == cmd[-4:-2]
    assert cmd[-2:] == ["-c", "model.model_kwargs.reasoningEffort=xhigh"]


# START_FUNCTION_CONTRACT
# name: test_build_mini_command_skips_reasoning_effort_for_gemini
# purpose: Verify Gemini commands omit unsupported reasoning-effort arguments.
# inputs: monkeypatch and tmp_path pytest fixtures.
# returns: None; asserts generated CLI arguments.
# side_effects: Changes test-local environment variables.
# emitted_logs: None.
# error_behavior: Fails when Gemini command construction regresses.
# END_FUNCTION_CONTRACT
def test_build_mini_command_skips_reasoning_effort_for_gemini(monkeypatch, tmp_path):
    monkeypatch.setattr(mini_swe_runner, "mini_help", lambda binary: "-m -t -y -o -c --config")
    monkeypatch.delenv("GRACE_MINI_SWE_EXTRA_ARGS", raising=False)

    cmd = mini_swe_runner.build_mini_command(
        "mini",
        "openai/gemini-3-flash-agent",
        "task",
        tmp_path / "traj.json",
        "high",
    )

    assert "model.model_kwargs.reasoningEffort=high" not in cmd


# START_FUNCTION_CONTRACT
# name: test_extract_json_returns_last_valid_json
# purpose: Verify extraction selects the final valid role payload.
# inputs: None.
# returns: None; asserts parsed JSON content.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails when JSON selection changes.
# END_FUNCTION_CONTRACT
def test_extract_json_returns_last_valid_json():
    payload = mini_swe_runner.extract_json('progress\n{"a": 1}\nmore\n{"b": 2}')

    assert payload == {"b": 2}


# START_FUNCTION_CONTRACT
# name: test_extract_json_can_ignore_command_only_json
# purpose: Verify command examples are excluded from role-result extraction.
# inputs: None.
# returns: None; asserts parsed JSON content.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails when command JSON is mistaken for a result.
# END_FUNCTION_CONTRACT
def test_extract_json_can_ignore_command_only_json():
    payload = mini_swe_runner.extract_json(
        'prompt example {"command": "your_command_here"}\n{"verdict": "PASS"}',
        ignore_command_only=True,
    )

    assert payload == {"verdict": "PASS"}


# START_FUNCTION_CONTRACT
# name: test_parse_json_text_prefers_whole_payload_over_nested_arrays
# purpose: Verify whole role payloads win over nested JSON fragments.
# inputs: None.
# returns: None; asserts parsed JSON content.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails when nested arrays are selected incorrectly.
# END_FUNCTION_CONTRACT
def test_parse_json_text_prefers_whole_payload_over_nested_arrays():
    payload = mini_swe_runner.parse_json_text(
        '{"title":"Packet","scope":["src"],"description":"do it",'
        '"coder_instructions":["one"],"acceptance_criteria":["two"],'
        '"expected_evidence":["three"]}'
    )

    assert isinstance(payload, dict)
    assert payload["title"] == "Packet"
    assert payload["expected_evidence"] == ["three"]


# START_FUNCTION_CONTRACT
# name: test_is_role_payload_accepts_canonical_architect_wave_plan
# purpose: Verify canonical top-level architect wave plans are accepted.
# inputs: None.
# returns: None; asserts role-payload validation.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails when canonical plans are rejected.
# END_FUNCTION_CONTRACT
def test_is_role_payload_accepts_canonical_architect_wave_plan():
    payload = {
        "title": "Feature plan",
        "description": "Plan split into waves.",
        "waves": [
            {
                "title": "Wave 1",
                "packets": [
                    {
                        "title": "Packet 1",
                        "role": "coder",
                        "scope": ["app/example.py"],
                        "frozen_scope": [],
                        "acceptance_profile": "STRICT",
                        "depends_on": [],
                        "description": "Create the example module.",
                        "coder_instructions": ["Create the scoped file."],
                        "acceptance_criteria": ["The module exists."],
                        "verification": {"t0": [], "t1": [], "t2": []},
                        "expected_evidence": [],
                    }
                ],
            }
        ],
    }

    assert mini_swe_runner.is_role_payload("architect", payload) is True


# START_FUNCTION_CONTRACT
# name: test_extract_json_from_trajectory_uses_only_assistant_content
# purpose: Verify trajectory extraction ignores non-assistant messages.
# inputs: tmp_path pytest fixture.
# returns: None; asserts extracted assistant payload.
# side_effects: Writes a temporary trajectory file.
# emitted_logs: None.
# error_behavior: Fails when non-assistant content is parsed.
# END_FUNCTION_CONTRACT
def test_extract_json_from_trajectory_uses_only_assistant_content(tmp_path):
    trajectory = tmp_path / "mini-swe.traj.json"
    trajectory.write_text(json.dumps({
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": 'example {"command": "your_command_here"}'},
            {"role": "assistant", "content": 'I will inspect first, not final JSON.'},
            {"role": "tool", "content": '{"returncode": 0, "output": "ok"}'},
            {"role": "assistant", "content": '{"verdict": "PASS", "summary": "ok"}'},
        ]
    }))

    payload = mini_swe_runner.extract_json_from_trajectory(trajectory, "reviewer")

    assert payload == {"verdict": "PASS", "summary": "ok"}


# START_FUNCTION_CONTRACT
# name: test_extract_json_from_trajectory_ignores_assistant_command_json
# purpose: Verify assistant shell-command JSON is not a role result.
# inputs: tmp_path pytest fixture.
# returns: None; asserts extracted role payload.
# side_effects: Writes a temporary trajectory file.
# emitted_logs: None.
# error_behavior: Fails when command JSON is selected.
# END_FUNCTION_CONTRACT
def test_extract_json_from_trajectory_ignores_assistant_command_json(tmp_path):
    trajectory = tmp_path / "mini-swe.traj.json"
    trajectory.write_text(json.dumps({
        "messages": [
            {"role": "assistant", "content": '{"command": "ls -la"}'},
            {"role": "assistant", "content": '{"verdict": "PASS", "summary": "ok"}'},
        ]
    }))

    payload = mini_swe_runner.extract_json_from_trajectory(trajectory, "reviewer")

    assert payload == {"verdict": "PASS", "summary": "ok"}


# START_FUNCTION_CONTRACT
# name: test_reviewer_main_prefers_result_file_json
# purpose: Verify reviewer main prefers the explicit result file.
# inputs: tmp_path, monkeypatch, and capsys pytest fixtures.
# returns: None; asserts emitted reviewer JSON.
# side_effects: Writes temporary files and patches the runner.
# emitted_logs: None.
# error_behavior: Fails when stdout overrides the result file.
# END_FUNCTION_CONTRACT
def test_reviewer_main_prefers_result_file_json(tmp_path, monkeypatch, capsys):
    (tmp_path / "AGENTS.md").write_text("Local rules.")
    (tmp_path / "task.md").write_text("Review demo")

    def fake_run_mini(**kwargs):
        result_path = kwargs["output_dir"] / mini_swe_runner.RESULT_JSON_FILENAME
        result_path.write_text('{"verdict":"PASS","summary":"from file"}')
        return mini_swe_runner.subprocess.CompletedProcess(
            args=["mini"],
            returncode=1,
            stdout='{"command":"your_command_here"}',
            stderr="RepeatedFormatError",
        )

    monkeypatch.setattr(mini_swe_runner, "run_mini", fake_run_mini)

    rc = mini_swe_runner.main([
        "--role", "reviewer",
        "--model", "openai/gpt-4.1-mini",
        "--task-file", str(tmp_path / "task.md"),
        "--worktree", str(tmp_path),
        "--output-dir", str(tmp_path / "out"),
    ])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {"verdict": "PASS", "summary": "from file"}


# START_FUNCTION_CONTRACT
# name: test_main_uses_configured_hard_timeout_above_profile_timeout
# purpose: Verify the process hard cap can exceed a profile timeout.
# inputs: tmp_path, monkeypatch, and capsys pytest fixtures.
# returns: None; asserts the timeout forwarded to the runner.
# side_effects: Writes temporary files and patches the runner.
# emitted_logs: None.
# error_behavior: Fails when the profile timeout truncates the hard cap.
# END_FUNCTION_CONTRACT
def test_main_uses_configured_hard_timeout_above_profile_timeout(
    tmp_path, monkeypatch, capsys,
):
    (tmp_path / "task.md").write_text("Review demo")
    observed: dict[str, int] = {}

    def fake_run_mini(**kwargs):
        observed["timeout_seconds"] = kwargs["timeout_seconds"]
        result_path = kwargs["output_dir"] / mini_swe_runner.RESULT_JSON_FILENAME
        result_path.write_text('{"verdict":"PASS","summary":"ok"}')
        return mini_swe_runner.subprocess.CompletedProcess(
            args=["mini"], returncode=0, stdout="", stderr="",
        )

    monkeypatch.setenv("GRACE_AGENT_MAX_TIMEOUT", "3600")
    monkeypatch.setattr(mini_swe_runner, "run_mini", fake_run_mini)

    rc = mini_swe_runner.main([
        "--role", "reviewer",
        "--model", "openai/gpt-4.1-mini",
        "--task-file", str(tmp_path / "task.md"),
        "--worktree", str(tmp_path),
        "--output-dir", str(tmp_path / "out"),
        "--timeout-seconds", "900",
    ])

    assert rc == 0
    assert observed["timeout_seconds"] == 3600
    assert json.loads(capsys.readouterr().out)["verdict"] == "PASS"


# START_FUNCTION_CONTRACT
# name: test_reviewer_main_does_not_parse_stdout_prompt_examples
# purpose: Verify reviewer main rejects prompt-example JSON on stdout.
# inputs: tmp_path, monkeypatch, and capsys pytest fixtures.
# returns: None; asserts fail-closed reviewer output.
# side_effects: Writes temporary files and patches the runner.
# emitted_logs: None.
# error_behavior: Fails when example JSON is accepted as a verdict.
# END_FUNCTION_CONTRACT
def test_reviewer_main_does_not_parse_stdout_prompt_examples(tmp_path, monkeypatch, capsys):
    (tmp_path / "task.md").write_text("Review demo")

    def fake_run_mini(**kwargs):
        return mini_swe_runner.subprocess.CompletedProcess(
            args=["mini"],
            returncode=1,
            stdout='mini prompt example {"command":"your_command_here"}',
            stderr="RepeatedFormatError",
        )

    monkeypatch.setattr(mini_swe_runner, "run_mini", fake_run_mini)

    rc = mini_swe_runner.main([
        "--role", "reviewer",
        "--model", "openai/gpt-4.1-mini",
        "--task-file", str(tmp_path / "task.md"),
        "--worktree", str(tmp_path),
        "--output-dir", str(tmp_path / "out"),
    ])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["verdict"] == "REWORK_TO_CODER"
    assert "command" not in data


# START_FUNCTION_CONTRACT
# name: test_coder_main_outputs_deterministic_json_when_mini_is_fake
# purpose: Verify coder main derives deterministic changed-file JSON.
# inputs: tmp_path, monkeypatch, and capsys pytest fixtures.
# returns: None; asserts coder result JSON.
# side_effects: Initializes temporary Git state and patches the runner.
# emitted_logs: None.
# error_behavior: Fails when coder output depends on model prose.
# END_FUNCTION_CONTRACT
def test_coder_main_outputs_deterministic_json_when_mini_is_fake(tmp_path, monkeypatch, capsys):
    (tmp_path / "AGENTS.md").write_text("Local rules.")
    (tmp_path / "task.md").write_text("Touch demo.txt")
    (tmp_path / ".git").mkdir()

    def fake_run_mini(**kwargs):
        (tmp_path / "demo.txt").write_text("done")
        return mini_swe_runner.subprocess.CompletedProcess(
            args=["mini"],
            returncode=0,
            stdout='{"status":"done"}',
            stderr="",
        )

    monkeypatch.setattr(mini_swe_runner, "run_mini", fake_run_mini)
    monkeypatch.setattr(mini_swe_runner, "changed_files", lambda worktree: ["demo.txt"])

    rc = mini_swe_runner.main([
        "--role", "coder",
        "--model", "openai/gpt-4.1-mini",
        "--task-file", str(tmp_path / "task.md"),
        "--worktree", str(tmp_path),
    ])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "done"
    assert data["changed_files"] == ["demo.txt"]
# END_BLOCK_RUNNER_TESTS
