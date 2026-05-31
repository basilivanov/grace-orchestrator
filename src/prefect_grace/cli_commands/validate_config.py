"""Config validation command."""
from pathlib import Path
from prefect_grace.runtime_config import load_runtime_config
from prefect_grace.platform.project_adapter import load_project_adapter


def _cmd_validate_config(args):
    """Validate GRACE configuration."""
    print("Validating GRACE configuration...")

    try:
        # Load runtime config
        runtime = load_runtime_config()
        print(f"✓ Runtime config loaded")
        print(f"  API URL: {runtime.api_url}")
        print(f"  Work Pool: {runtime.work_pool_name}")
        print(f"  Working Dir: {runtime.working_directory}")

        # Load project config
        project = load_project_adapter()
        print(f"✓ Project config loaded")
        print(f"  Project Key: {project.project_key}")
        print(f"  Repo Root: {project.repo_root}")
        print(f"  State Root: {project.runtime_state_root}")

        # Validate paths exist
        repo_root = Path(project.repo_root)
        if not repo_root.exists():
            print(f"✗ Repo root does not exist: {repo_root}")
            return 1

        grace_dir = repo_root / project.grace_dir
        if not grace_dir.exists():
            print(f"⚠ Grace dir does not exist: {grace_dir}")

        print("\n✓ Configuration is valid!")
        return 0

    except Exception as e:
        print(f"✗ Configuration error: {e}")
        import traceback
        traceback.print_exc()
        return 1
