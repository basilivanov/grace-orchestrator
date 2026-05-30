"""Tests for prefect_grace.resources module."""

import pytest
from prefect_grace.resources import (
    ResourceNotFoundError,
    list_policies,
    list_prompts,
    list_roles,
    list_templates,
    load_base_prompt,
    load_policy,
    load_role_contract,
    load_template,
)


def test_load_base_prompt_architect():
    """Test loading the architect prompt."""
    prompt = load_base_prompt("architect")
    assert isinstance(prompt, str)
    assert len(prompt) > 0
    assert "architect" in prompt.lower()


def test_load_base_prompt_planner():
    """Test loading the planner prompt."""
    prompt = load_base_prompt("planner")
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_load_base_prompt_coder():
    """Test loading the coder prompt."""
    prompt = load_base_prompt("coder")
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_load_base_prompt_not_found():
    """Test that loading a non-existent prompt raises ResourceNotFoundError."""
    with pytest.raises(ResourceNotFoundError) as exc_info:
        load_base_prompt("nonexistent_role")
    assert "nonexistent_role" in str(exc_info.value)


def test_load_role_contract_architect():
    """Test loading the architect role contract."""
    role = load_role_contract("architect")
    assert isinstance(role, str)
    assert len(role) > 0


def test_load_role_contract_planner():
    """Test loading the planner role contract."""
    role = load_role_contract("planner")
    assert isinstance(role, str)
    assert len(role) > 0


def test_load_role_contract_not_found():
    """Test that loading a non-existent role raises ResourceNotFoundError."""
    with pytest.raises(ResourceNotFoundError) as exc_info:
        load_role_contract("nonexistent_role")
    assert "nonexistent_role" in str(exc_info.value)


def test_load_template_with_extension():
    """Test loading a template with explicit extension."""
    template = load_template("packet.md")
    assert isinstance(template, str)
    assert len(template) > 0


def test_load_template_without_extension():
    """Test loading a template without extension (auto-detect)."""
    template = load_template("packet")
    assert isinstance(template, str)
    assert len(template) > 0


def test_load_template_yaml():
    """Test loading a YAML template."""
    template = load_template("business_feature_brief.yaml")
    assert isinstance(template, str)
    assert len(template) > 0


def test_load_template_not_found():
    """Test that loading a non-existent template raises ResourceNotFoundError."""
    with pytest.raises(ResourceNotFoundError) as exc_info:
        load_template("nonexistent_template")
    assert "nonexistent_template" in str(exc_info.value)


def test_load_policy_with_extension():
    """Test loading a policy with explicit extension."""
    policy = load_policy("verification.yaml")
    assert isinstance(policy, str)
    assert len(policy) > 0


def test_load_policy_without_extension():
    """Test loading a policy without extension (auto-detect)."""
    policy = load_policy("verification")
    assert isinstance(policy, str)
    assert len(policy) > 0


def test_load_policy_not_found():
    """Test that loading a non-existent policy raises ResourceNotFoundError."""
    with pytest.raises(ResourceNotFoundError) as exc_info:
        load_policy("nonexistent_policy")
    assert "nonexistent_policy" in str(exc_info.value)


def test_list_prompts():
    """Test listing all available prompts."""
    prompts = list_prompts()
    assert isinstance(prompts, list)
    assert len(prompts) > 0
    assert "architect" in prompts
    assert "planner" in prompts
    assert "coder" in prompts
    # Should not include the _prompt.md suffix
    assert "architect_prompt.md" not in prompts


def test_list_roles():
    """Test listing all available roles."""
    roles = list_roles()
    assert isinstance(roles, list)
    assert len(roles) > 0
    assert "architect" in roles
    assert "planner" in roles
    assert "coder" in roles
    # Should not include the .md suffix
    assert "architect.md" not in roles


def test_list_templates():
    """Test listing all available templates."""
    templates = list_templates()
    assert isinstance(templates, list)
    assert len(templates) > 0
    # Should include full filenames with extensions
    assert any("packet" in t for t in templates)
    assert any("feature_brief" in t for t in templates)


def test_list_policies():
    """Test listing all available policies."""
    policies = list_policies()
    assert isinstance(policies, list)
    assert len(policies) > 0
    # Should include full filenames with extensions
    assert any("verification" in p for p in policies)
