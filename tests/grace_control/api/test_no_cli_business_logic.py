"""W2 acceptance tests for source/codex/tz-api-first-cleanup-waves-w0-w11.md §W2.

Asserts:
1. pyproject.toml has no public `grace`, `grace-dev`, `prefect-grace`, `gracectl` scripts.
2. No runtime code under `src/grace_control/` imports `grace_control.cli`.
3. The CLI module itself is gone.
4. Makefile still supports `lint`, `docs-check`, `test` (CI/dev wrappers).
5. CI/dev scripts that replace the deleted CLI commands still exist.
"""
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = ROOT / "pyproject.toml"
SRC = ROOT / "src" / "grace_control"
SCRIPTS = ROOT / "scripts"
MAKEFILE = ROOT / "Makefile"


def _read(path: Path) -> str:
    return path.read_text()


# 1. No public runtime CLI scripts in pyproject.toml.
def test_no_grace_entrypoint_in_pyproject():
    text = _read(PYPROJECT)
    forbidden = ["grace-dev", "prefect-grace", "gracectl"]
    for name in forbidden:
        assert not re.search(rf'^\s*{re.escape(name)}\s*=', text, re.MULTILINE), (
            f"pyproject.toml still defines a `{name}` console script; W2 requires it gone."
        )
    # The `grace` script used to point at grace_control.cli.main:cli. The new
    # convention is: OpenAPI is the only runtime interface, so `grace` is removed.
    assert not re.search(r'^\s*grace\s*=\s*"grace_control\.cli', text, re.MULTILINE), (
        "pyproject.toml still defines `grace = grace_control.cli.*`; W2 requires it gone."
    )


# 2. The CLI module is deleted.
def test_grace_control_cli_module_removed():
    assert not (SRC / "cli").exists(), (
        f"src/grace_control/cli/ should be removed in W2; "
        f"found: {list((SRC / 'cli').iterdir()) if (SRC / 'cli').exists() else 'N/A'}"
    )


# 3. No runtime code imports grace_control.cli.
def test_no_grace_control_cli_imports_in_runtime():
    offenders = []
    for path in SRC.rglob("*.py"):
        text = path.read_text()
        for pat in ("from grace_control.cli", "import grace_control.cli",
                    "from grace_control import cli"):
            if pat in text:
                offenders.append((path.relative_to(ROOT), pat))
    assert not offenders, f"Runtime code still imports grace_control.cli: {offenders}"


# 4. Makefile keeps the CI/dev entrypoints.
def test_makefile_supports_lint_docs_check_test():
    text = _read(MAKEFILE)
    for target in ("lint:", "docs-check:", "test:"):
        assert target in text, f"Makefile lost the `{target}` target that W2 must preserve."


# 5. CI/dev replacement scripts exist.
def test_replacement_scripts_exist():
    """scripts/grace_lint.py and scripts/run_golden.py replace deleted CLI commands."""
    assert (SCRIPTS / "grace_lint.py").exists(), "scripts/grace_lint.py is the CI replacement for `grace lint`."
    assert (SCRIPTS / "run_golden.py").exists(), "scripts/run_golden.py is the CI replacement for `grace golden`/`fixture run-one`."
    assert (SCRIPTS / "live_worker.py").exists(), "scripts/live_worker.py is the deployment replacement for `grace worker start`."


# 6. CLI_DEPRECATION_INVENTORY.md is updated.
def test_cli_inventory_status_reflects_w2_completion():
    inv = _read(ROOT / "docs" / "grace" / "CLI_DEPRECATION_INVENTORY.md")
    # After W2, every `command` row in the migration-status table should be `done (W2)`.
    # The table at the bottom of the inventory file is the source of truth.
    for cmd in ("up", "init", "lint", "eval run", "worker start", "api start",
                "trace --packet/--feature/--wave"):
        pattern = rf"\|\s*`?{re.escape(cmd)}`?\s*\|\s*(done|TODO)\s*\|"
        m = re.search(pattern, inv)
        if m and m.group(1) == "TODO":
            pytest.fail(
                f"CLI inventory still lists `{cmd}` as TODO; W2 should have flipped it to done."
            )
