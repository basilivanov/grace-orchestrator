#!/usr/bin/env python3
"""Demonstration script for prefect_grace.resources module.

This script demonstrates loading prompts, roles, templates, and policies
using importlib.resources.
"""

import sys
from pathlib import Path

# Add src to path for demonstration
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from prefect_grace.resources import (
    list_policies,
    list_prompts,
    list_roles,
    list_templates,
    load_base_prompt,
    load_policy,
    load_role_contract,
    load_template,
)


def main():
    """Demonstrate resource loading functionality."""
    print("=" * 70)
    print("PREFECT GRACE RESOURCES DEMONSTRATION")
    print("=" * 70)
    print()

    # List available resources
    print("📋 Available Prompts:")
    for prompt in list_prompts():
        print(f"  - {prompt}")
    print()

    print("👤 Available Roles:")
    for role in list_roles():
        print(f"  - {role}")
    print()

    print("📄 Available Templates:")
    for template in list_templates():
        print(f"  - {template}")
    print()

    print("📜 Available Policies:")
    for policy in list_policies():
        print(f"  - {policy}")
    print()

    # Load and display sample content
    print("=" * 70)
    print("SAMPLE CONTENT")
    print("=" * 70)
    print()

    print("🔹 Architect Prompt (first 200 chars):")
    architect_prompt = load_base_prompt("architect")
    print(f"  {architect_prompt[:200]}...")
    print(f"  [Total length: {len(architect_prompt)} characters]")
    print()

    print("🔹 Planner Role Contract (first 200 chars):")
    planner_role = load_role_contract("planner")
    print(f"  {planner_role[:200]}...")
    print(f"  [Total length: {len(planner_role)} characters]")
    print()

    print("🔹 Packet Template (first 200 chars):")
    packet_template = load_template("packet")
    print(f"  {packet_template[:200]}...")
    print(f"  [Total length: {len(packet_template)} characters]")
    print()

    print("🔹 Verification Policy (first 200 chars):")
    verification_policy = load_policy("verification")
    print(f"  {verification_policy[:200]}...")
    print(f"  [Total length: {len(verification_policy)} characters]")
    print()

    print("=" * 70)
    print("✅ All resources loaded successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()
