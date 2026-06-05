"""Resource loading utilities for prefect_grace package data.

This module provides helper functions to load prompts, roles, templates,
and policies from the package using importlib.resources.
"""

from importlib import resources
from pathlib import Path
from typing import Optional


class ResourceNotFoundError(Exception):
    """Raised when a requested resource cannot be found."""
    pass


def load_base_prompt(role: str) -> str:
    """Load a base prompt for the specified role.

    Args:
        role: The role name (e.g., "architect", "planner", "coder")

    Returns:
        The prompt content as a string

    Raises:
        ResourceNotFoundError: If the prompt file does not exist
    """
    try:
        prompt_file = resources.files("prefect_grace.prompts").joinpath(f"{role}_prompt.md")
        return prompt_file.read_text(encoding="utf-8")
    except (FileNotFoundError, AttributeError) as e:
        raise ResourceNotFoundError(
            f"Prompt file for role '{role}' not found. "
            f"Expected: {role}_prompt.md"
        ) from e


def load_role_contract(role: str) -> str:
    """Load a role contract/definition for the specified role.

    Args:
        role: The role name (e.g., "architect", "planner", "coder")

    Returns:
        The role contract content as a string

    Raises:
        ResourceNotFoundError: If the role file does not exist
    """
    try:
        role_file = resources.files("prefect_grace.roles").joinpath(f"{role}.md")
        return role_file.read_text(encoding="utf-8")
    except (FileNotFoundError, AttributeError) as e:
        raise ResourceNotFoundError(
            f"Role contract for '{role}' not found. "
            f"Expected: {role}.md"
        ) from e


def load_template(name: str) -> str:
    """Load a template by name.

    Args:
        name: The template name (with or without extension)

    Returns:
        The template content as a string

    Raises:
        ResourceNotFoundError: If the template file does not exist
    """
    # Add extension if not provided
    if not any(name.endswith(ext) for ext in [".md", ".yaml", ".yml", ".xml"]):
        # Try .md first, then .yaml, then .xml
        for ext in [".md", ".yaml", ".xml"]:
            try:
                template_file = resources.files("prefect_grace.templates").joinpath(f"{name}{ext}")
                return template_file.read_text(encoding="utf-8")
            except (FileNotFoundError, AttributeError):
                continue
        raise ResourceNotFoundError(
            f"Template '{name}' not found with .md, .yaml, or .xml extension"
        )

    try:
        template_file = resources.files("prefect_grace.templates").joinpath(name)
        return template_file.read_text(encoding="utf-8")
    except (FileNotFoundError, AttributeError) as e:
        raise ResourceNotFoundError(
            f"Template '{name}' not found"
        ) from e


def load_policy(name: str) -> str:
    """Load a policy by name.

    Args:
        name: The policy name (with or without extension)

    Returns:
        The policy content as a string

    Raises:
        ResourceNotFoundError: If the policy file does not exist
    """
    # Add extension if not provided
    if not any(name.endswith(ext) for ext in [".yaml", ".yml", ".md"]):
        # Try .yaml first, then .md
        for ext in [".yaml", ".md"]:
            try:
                policy_file = resources.files("prefect_grace.policies").joinpath(f"{name}{ext}")
                return policy_file.read_text(encoding="utf-8")
            except (FileNotFoundError, AttributeError):
                continue
        raise ResourceNotFoundError(
            f"Policy '{name}' not found with .yaml or .md extension"
        )

    try:
        policy_file = resources.files("prefect_grace.policies").joinpath(name)
        return policy_file.read_text(encoding="utf-8")
    except (FileNotFoundError, AttributeError) as e:
        raise ResourceNotFoundError(
            f"Policy '{name}' not found"
        ) from e


def list_prompts() -> list[str]:
    """List all available prompt files.

    Returns:
        List of prompt role names (without _prompt.md suffix)
    """
    try:
        prompts_dir = resources.files("prefect_grace.prompts")
        return sorted([
            p.name.replace("_prompt.md", "")
            for p in prompts_dir.iterdir()
            if p.name.endswith("_prompt.md")
        ])
    except (FileNotFoundError, AttributeError):
        return []


def list_roles() -> list[str]:
    """List all available role contract files.

    Returns:
        List of role names (without .md suffix)
    """
    try:
        roles_dir = resources.files("prefect_grace.roles")
        return sorted([
            p.name.replace(".md", "")
            for p in roles_dir.iterdir()
            if p.name.endswith(".md")
        ])
    except (FileNotFoundError, AttributeError):
        return []


def list_templates() -> list[str]:
    """List all available template files.

    Returns:
        List of template filenames
    """
    try:
        templates_dir = resources.files("prefect_grace.templates")
        return sorted([
            p.name
            for p in templates_dir.iterdir()
            if p.name.endswith((".md", ".yaml", ".yml", ".xml"))
        ])
    except (FileNotFoundError, AttributeError):
        return []


def list_policies() -> list[str]:
    """List all available policy files.

    Returns:
        List of policy filenames
    """
    try:
        policies_dir = resources.files("prefect_grace.policies")
        return sorted([
            p.name
            for p in policies_dir.iterdir()
            if p.name.endswith((".yaml", ".yml", ".md"))
        ])
    except (FileNotFoundError, AttributeError):
        return []
