# ############################################################################
# AI_HEADER: test_mini_swe_profiles — verify mini-swe model and profile routing
# ROLE: Regression coverage for configured agent profiles, provider environments,
#       command rendering, and the deterministic coder fallback ladder.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify mini-swe profiles and executor selection without provider calls.
# inputs: Agent profile configuration and pytest monkeypatch fixtures.
# returns: Pytest assertions for profile, model, command, and ladder contracts.
# side_effects: Resets the in-process profile cache and mutates test-local env.
# emitted_logs: None.
# error_behavior: Fails assertions when routing or profile contracts regress.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_mini_swe_profiles_are_loadable_and_use_python_executable
#   - function: test_command_renderer_resolves_python_executable_for_mini_swe
#   - function: test_mini_swe_profiles_pass_runtime_validation
#   - function: test_deepseek_mini_swe_profiles_use_openai_compatible_deepseek_models
#   - function: test_mini_swe_profiles_have_expected_priorities_and_efforts
#   - function: test_primary_coder_uses_flash_36_through_local_cli_proxy
#   - function: test_deepseek_coder_uses_direct_provider_environment
#   - function: test_role_selection_prefers_mini_swe_profiles
#   - function: test_coder_selection_uses_profile_priority_without_override
#   - function: test_configured_coder_ladder_cycles_only_allowed_profiles
#   - function: test_supervisor_does_not_define_default_coder_ladder
#   - function: test_resolve_model_returns_mini_swe_executor_ids
# END_MODULE_MAP

from __future__ import annotations

import sys
from pathlib import Path

from grace_control.config.agent_profiles import get_agent_profile, reset_cache
from grace_control.core.executor_selector import resolve_model, select_executor
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.command_template_renderer import CommandTemplateRenderer
from grace_control.services.agent_profile_validator import AgentProfileValidator

_log = GraceLogger("test_mini_swe_profiles")


# START_BLOCK_PROFILE_TESTS
# START_FUNCTION_CONTRACT
# name: test_mini_swe_profiles_are_loadable_and_use_python_executable
# purpose: Verify every mini-swe role profile uses the Python wrapper contract.
# inputs: None.
# returns: None; asserts profile fields.
# side_effects: Resets the profile cache.
# emitted_logs: None.
# error_behavior: Fails when a profile cannot load or has an invalid command.
# END_FUNCTION_CONTRACT

def test_mini_swe_profiles_are_loadable_and_use_python_executable():
    reset_cache()
    for executor_id, role in [
        ("architect-mini-swe", "architect"),
        ("coder-mini-swe", "coder"),
        ("reviewer-mini-swe", "reviewer"),
        ("verifier-mini-swe", "verifier"),
        ("architect-mini-swe-deepseek", "architect"),
        ("coder-mini-swe-deepseek", "coder"),
        ("coder-mini-swe-gpt55", "coder"),
        ("reviewer-mini-swe-deepseek", "reviewer"),
        ("verifier-mini-swe-deepseek", "verifier"),
        ("context-json-flash", "context_collector"),
    ]:
        profile = get_agent_profile(executor_id)
        assert profile is not None
        data = profile.to_dict()
        assert data["command"][:3] == [
            "{python_executable}",
            "-m",
            "grace_control.runtime.mini_swe_runner",
        ]
        assert data["cwd"] == "{worktree_path}"
        assert data["inject_dir"] is False
        assert role in data["command"]
        assert "{packet_path}" in data["command"]
        assert "{worktree_path}" in data["command"]
        assert data["timeout_seconds"] == 600
        timeout_index = data["command"].index("--timeout-seconds")
        assert data["command"][timeout_index + 1] == "3600"


# START_FUNCTION_CONTRACT
# name: test_command_renderer_resolves_python_executable_for_mini_swe
# purpose: Verify command template rendering resolves the active Python binary.
# inputs: None.
# returns: None; asserts the rendered executable.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails when the placeholder is not resolved.
# END_FUNCTION_CONTRACT
def test_command_renderer_resolves_python_executable_for_mini_swe():
    rendered = CommandTemplateRenderer().render(
        ["{python_executable}", "-m", "grace_control.runtime.mini_swe_runner"],
        {"python_executable": sys.executable},
    )

    assert rendered[0] == sys.executable


# START_FUNCTION_CONTRACT
# name: test_mini_swe_profiles_pass_runtime_validation
# purpose: Verify configured mini-swe profiles pass executable validation.
# inputs: None.
# returns: None; asserts validator results.
# side_effects: Resets the profile cache and probes the local executable.
# emitted_logs: None.
# error_behavior: Fails when a profile is not runnable.
# END_FUNCTION_CONTRACT
def test_mini_swe_profiles_pass_runtime_validation():
    reset_cache()
    validator = AgentProfileValidator()

    for executor_id in ("architect-mini-swe", "coder-mini-swe", "reviewer-mini-swe", "verifier-mini-swe"):
        result = validator.validate(get_agent_profile(executor_id), check_executable=True)

        assert result["ok"] is True, result
        assert result["rendered_command"][0] == sys.executable


# START_FUNCTION_CONTRACT
# name: test_deepseek_mini_swe_profiles_use_openai_compatible_deepseek_models
# purpose: Verify DeepSeek role profiles use direct OpenAI-compatible model IDs.
# inputs: None.
# returns: None; asserts model templates.
# side_effects: Resets the profile cache.
# emitted_logs: None.
# error_behavior: Fails when DeepSeek routing drifts.
# END_FUNCTION_CONTRACT
def test_deepseek_mini_swe_profiles_use_openai_compatible_deepseek_models():
    reset_cache()
    for executor_id in [
        "architect-mini-swe-deepseek",
        "coder-mini-swe-deepseek",
        "reviewer-mini-swe-deepseek",
        "verifier-mini-swe-deepseek",
    ]:
        profile = get_agent_profile(executor_id)
        assert profile is not None
        model = profile.to_dict()["model"]
        assert model.startswith("${GRACE_MINI_SWE_DEEPSEEK_")
        assert "openai/deepseek-v4-" in model


# START_FUNCTION_CONTRACT
# name: test_mini_swe_profiles_have_expected_priorities_and_efforts
# purpose: Verify role priorities, model defaults, and reasoning effort arguments.
# inputs: None.
# returns: None; asserts configured values.
# side_effects: Resets the profile cache.
# emitted_logs: None.
# error_behavior: Fails when profile ordering or effort changes unexpectedly.
# END_FUNCTION_CONTRACT
def test_mini_swe_profiles_have_expected_priorities_and_efforts():
    reset_cache()

    expected = {
        "architect-mini-swe": (400, "xhigh", "openai/gpt-5.5"),
        "reviewer-mini-swe": (400, "xhigh", "openai/gpt-5.6-sol"),
        "coder-mini-swe": (300, "medium", "openai/gemini-3.6-flash-high"),
        "coder-mini-swe-deepseek": (200, "medium", "openai/deepseek-v4-flash"),
        "coder-mini-swe-gpt55": (100, "high", "openai/gpt-5.5"),
        "verifier-mini-swe": (300, "medium", "openai/gpt-5.5"),
    }
    for executor_id, (priority, effort, model_default) in expected.items():
        data = get_agent_profile(executor_id).to_dict()
        assert data["priority"] == priority
        assert data["effort"] == effort
        assert model_default in data["model"]
        assert "--reasoning-effort" in data["command"]


# START_FUNCTION_CONTRACT
# name: test_primary_coder_uses_flash_36_through_local_cli_proxy
# purpose: Verify the primary coder routes Gemini Flash through localhost proxy.
# inputs: None.
# returns: None; asserts model and environment fields.
# side_effects: Resets the profile cache.
# emitted_logs: None.
# error_behavior: Fails when primary coder provider routing drifts.
# END_FUNCTION_CONTRACT
def test_primary_coder_uses_flash_36_through_local_cli_proxy():
    reset_cache()

    data = get_agent_profile("coder-mini-swe").to_dict()

    assert data["model"] == "${GRACE_MINI_SWE_CODER_MODEL:-openai/gemini-3.6-flash-high}"
    assert data["env"] == {
        "GRACE_MINI_SWE_OPENAI_BASE_URL": "http://127.0.0.1:18317/v1",
        "GRACE_MINI_SWE_OPENAI_API_KEY": "dummy",
    }


# START_FUNCTION_CONTRACT
# name: test_deepseek_coder_uses_direct_provider_environment
# purpose: Verify the DeepSeek coder does not inherit the local proxy environment.
# inputs: None.
# returns: None; asserts model and environment fields.
# side_effects: Resets the profile cache.
# emitted_logs: None.
# error_behavior: Fails when direct DeepSeek routing drifts.
# END_FUNCTION_CONTRACT
def test_deepseek_coder_uses_direct_provider_environment():
    reset_cache()

    data = get_agent_profile("coder-mini-swe-deepseek").to_dict()

    assert data["model"] == "${GRACE_MINI_SWE_DEEPSEEK_CODER_MODEL:-openai/deepseek-v4-flash}"
    assert data["env"] == {}


# START_FUNCTION_CONTRACT
# name: test_role_selection_prefers_mini_swe_profiles
# purpose: Verify architect, coder, reviewer, and verifier select mini-swe profiles.
# inputs: None.
# returns: None; asserts selected executor IDs.
# side_effects: Resets the profile cache.
# emitted_logs: None.
# error_behavior: Fails when default role routing changes.
# END_FUNCTION_CONTRACT
def test_role_selection_prefers_mini_swe_profiles():
    reset_cache()

    assert select_executor("architect")["executor_id"] == "architect-mini-swe"
    assert select_executor("coder")["executor_id"] == "coder-mini-swe"
    assert select_executor("reviewer")["executor_id"] == "reviewer-mini-swe"
    assert select_executor("verifier")["executor_id"] == "verifier-mini-swe"


# START_FUNCTION_CONTRACT
# name: test_coder_selection_uses_profile_priority_without_override
# purpose: Verify coder attempts follow descending profile priority by default.
# inputs: monkeypatch — pytest environment fixture.
# returns: None; asserts selected executor IDs.
# side_effects: Removes a test-local ladder override and resets the profile cache.
# emitted_logs: None.
# error_behavior: Fails when coder fallback order changes.
# END_FUNCTION_CONTRACT
def test_coder_selection_uses_profile_priority_without_override(monkeypatch):
    reset_cache()
    monkeypatch.delenv("GRACE_CODER_EXECUTOR_LADDER", raising=False)

    assert select_executor("coder", attempt=1)["executor_id"] == "coder-mini-swe"
    assert select_executor("coder", attempt=2)["executor_id"] == "coder-mini-swe-deepseek"
    assert select_executor("coder", attempt=3)["executor_id"] == "coder-mini-swe-gpt55"


# START_FUNCTION_CONTRACT
# name: test_configured_coder_ladder_cycles_only_allowed_profiles
# purpose: Verify an explicit coder ladder cycles only its configured profiles.
# inputs: monkeypatch — pytest environment fixture.
# returns: None; asserts selected executor IDs.
# side_effects: Sets a test-local environment variable and resets profile cache.
# emitted_logs: None.
# error_behavior: Fails when configured ladder cycling is ignored.
# END_FUNCTION_CONTRACT
def test_configured_coder_ladder_cycles_only_allowed_profiles(monkeypatch):
    reset_cache()
    monkeypatch.setenv(
        "GRACE_CODER_EXECUTOR_LADDER",
        "coder-mini-swe,coder-mini-swe-deepseek",
    )

    assert select_executor("coder", attempt=1)["executor_id"] == "coder-mini-swe"
    assert select_executor("coder", attempt=2)["executor_id"] == "coder-mini-swe-deepseek"
    assert select_executor("coder", attempt=3)["executor_id"] == "coder-mini-swe"
    assert select_executor("coder", attempt=4)["executor_id"] == "coder-mini-swe-deepseek"


# START_FUNCTION_CONTRACT
# name: test_supervisor_does_not_define_default_coder_ladder
# purpose: Verify supervisor startup does not bypass YAML profile priorities.
# inputs: None.
# returns: None; asserts the launch script has no implicit ladder default.
# side_effects: Reads scripts/live_supervisor.sh.
# emitted_logs: None.
# error_behavior: Fails when supervisor reintroduces a coder ladder default.
# END_FUNCTION_CONTRACT
def test_supervisor_does_not_define_default_coder_ladder():
    repository_root = Path(__file__).resolve().parents[3]
    source = (repository_root / "scripts" / "live_supervisor.sh").read_text()

    assert "GRACE_CODER_EXECUTOR_LADDER:-" not in source


# START_FUNCTION_CONTRACT
# name: test_resolve_model_returns_mini_swe_executor_ids
# purpose: Verify model resolution exposes mini-swe executor IDs and kind.
# inputs: None.
# returns: None; asserts resolved role metadata.
# side_effects: Resets the profile cache.
# emitted_logs: None.
# error_behavior: Fails when resolved model metadata drifts.
# END_FUNCTION_CONTRACT
def test_resolve_model_returns_mini_swe_executor_ids():
    reset_cache()

    for role, executor_id in [
        ("architect", "architect-mini-swe"),
        ("reviewer", "reviewer-mini-swe"),
        ("verifier", "verifier-mini-swe"),
    ]:
        resolved = resolve_model(role)
        assert resolved["executor_id"] == executor_id
        assert resolved["kind"] == "mini-swe"
# END_BLOCK_PROFILE_TESTS
