"""Source-level audit: no production code should parse semantic meaning from ID strings.

Forbidden patterns:
  split("-W") / split('-W')  — wave marker
  split("-P") / split('-P')  — packet marker
  startswith("FEAT-") / startswith('FEAT-')  — legacy feature prefix

Historical docs in docs/codex/ and TZ documents are excluded.
"""

import subprocess
from pathlib import Path


def _check_dir(path: str, allowlist: list[str] | None = None) -> list[str]:
    """Grep for forbidden patterns, return list of offending lines."""
    cmd = [
        "grep", "-RInE",
        r'split\(["\']-W["\']\)|split\(["\']-P["\']\)|startswith\(["\']FEAT-["\']\)',
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        lines = [l for l in result.stdout.split("\n") if l.strip()]
        if allowlist:
            lines = [l for l in lines if not any(a in l for a in allowlist)]
        return lines
    except subprocess.TimeoutExpired:
        return ["TIMEOUT"]


def test_src_no_legacy_id_parsing():
    """Production source code must not parse W/P markers or check FEAT- prefix."""
    violations = _check_dir("src", allowlist=[
        "nightly_batch_execution_guard",  # legacy archive reference, not in active path
    ])
    assert not violations, f"Found legacy ID parsing in src/:\n" + "\n".join(violations[:10])


def test_tests_no_legacy_id_parsing():
    """Test files should not parse legacy ID formats in new code."""
    violations = _check_dir("tests", allowlist=[
        "test_no_legacy_id_assumptions",  # self-reference in comments excluded
        "test_wave_gate_flow",
        "test_worker_retry",
        "test_worker_blocked_routing",
    ])
    assert not violations, f"Found legacy ID parsing in tests/:\n" + "\n".join(violations[:10])


def test_scripts_no_legacy_id_parsing():
    """Script files should not parse legacy ID formats."""
    violations = _check_dir("scripts")
    assert not violations, f"Found legacy ID parsing in scripts/:\n" + "\n".join(violations[:10])


def test_grace_features_no_legacy_id_parsing():
    """Feature YAML files must not contain deterministic legacy IDs."""
    violations = _check_dir("grace")
    assert not violations, f"Found legacy ID patterns in grace/:\n" + "\n".join(violations[:10])
