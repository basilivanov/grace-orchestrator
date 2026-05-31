# ############################################################################
# AI_HEADER: init
# ROLE: Bootstrap new project workspaces with GRACE configuration.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Initialize a new project with GRACE directory structure and templates.
# inputs: CLI arguments (project_key, root directory).
# returns: None.
# side_effects: Creates grace/ directory structure and copies template files.
# emitted_logs: None.
# error_behavior: Exits with non-zero code on errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: _cmd_init
# END_MODULE_MAP

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from prefect_grace.resources import load_template, ResourceNotFoundError


def _cmd_init(args: argparse.Namespace) -> None:
    """Bootstrap a new project workspace with GRACE configuration.

    Creates the grace/ directory structure and populates it with template files
    for project configuration, requirements, technology stack, development plan,
    knowledge graph, and verification matrix.

    Args:
        args: Parsed command-line arguments containing:
            - project_key: Unique identifier for the project
            - root: Root directory for the project (defaults to current directory)
            - json: Whether to output JSON format
    """
    project_key = args.project_key
    root = Path(args.root).resolve() if args.root else Path.cwd()
    grace_dir = root / "grace"

    # Validate project key
    if not project_key or not project_key.strip():
        print("ERROR: project_key cannot be empty", file=sys.stderr)
        sys.exit(1)

    # Create grace directory
    try:
        grace_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"ERROR: Failed to create grace directory: {e}", file=sys.stderr)
        sys.exit(1)

    # Template files to copy
    templates = [
        "project.yaml",
        "requirements.xml",
        "technology.xml",
        "development-plan.xml",
        "knowledge-graph.xml",
        "verification-matrix.md",
    ]

    # Copy templates with project key substitution
    created_files = []
    skipped_files = []
    errors = []

    for template_name in templates:
        dst = grace_dir / template_name

        # Skip if file already exists (idempotent)
        if dst.exists():
            skipped_files.append(template_name)
            continue

        try:
            # Load template content
            template_content = load_template(template_name)

            # Substitute placeholders
            content = template_content.replace("{{PROJECT_KEY}}", project_key)
            content = content.replace("{{REPO_ROOT}}", str(root))

            # Write to destination
            dst.write_text(content, encoding="utf-8")
            created_files.append(template_name)

        except ResourceNotFoundError as e:
            errors.append(f"Template not found: {template_name}")
        except Exception as e:
            errors.append(f"Failed to create {template_name}: {e}")

    # Create override directories
    override_dirs = [
        "overrides/prompts",
        "overrides/policies",
        "packets",
    ]

    for subdir in override_dirs:
        dir_path = grace_dir / subdir
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            # Create .gitkeep to preserve empty directories in git
            gitkeep = dir_path / ".gitkeep"
            if not gitkeep.exists():
                gitkeep.touch()
        except Exception as e:
            errors.append(f"Failed to create directory {subdir}: {e}")

    # Output results
    if args.json:
        import json
        result = {
            "ok": len(errors) == 0,
            "command": "init",
            "project_key": project_key,
            "grace_dir": str(grace_dir),
            "created_files": created_files,
            "skipped_files": skipped_files,
            "errors": errors,
        }
        print(json.dumps(result, indent=2))
    else:
        print(f"Initialized GRACE workspace for project: {project_key}")
        print(f"Location: {grace_dir}")
        print()

        if created_files:
            print(f"Created {len(created_files)} files:")
            for f in created_files:
                print(f"  ✓ {f}")

        if skipped_files:
            print(f"\nSkipped {len(skipped_files)} existing files:")
            for f in skipped_files:
                print(f"  - {f}")

        print(f"\nCreated directory structure:")
        print(f"  ✓ overrides/prompts/")
        print(f"  ✓ overrides/policies/")
        print(f"  ✓ packets/")

        if errors:
            print(f"\nErrors encountered:", file=sys.stderr)
            for error in errors:
                print(f"  ✗ {error}", file=sys.stderr)

    # Exit with appropriate code
    sys.exit(0 if len(errors) == 0 else 1)
