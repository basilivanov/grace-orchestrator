"""W6: no new `import subprocess` outside the approved legacy helper.

Only checks W6 new runtime files — pre-existing imports elsewhere are not
part of this enforcement wave.
"""

from __future__ import annotations

import ast
from pathlib import Path


# W6 new files that must NOT import subprocess directly
_W6_FILES = [
    "runtime_scope_enforcer.py",
    "runtime_diff_inspector.py",
    "runtime_diagnostics.py",
]

ALLOWED_HELPER = "packet_executor.py::_write_agent_patch"


class TestNoNewSubprocessImports:

    def test_no_subprocess_imports_in_w6_files(self):
        src_root = Path(__file__).resolve().parent.parent.parent.parent / "src" / "grace_control" / "runtime"
        violations: list[tuple[str, int]] = []

        for w6_file in _W6_FILES:
            py_path = src_root / w6_file
            if not py_path.exists():
                continue
            source = py_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "subprocess":
                            violations.append((w6_file, node.lineno))
                elif isinstance(node, ast.ImportFrom):
                    if node.module == "subprocess":
                        violations.append((w6_file, node.lineno))

        assert not violations, (
            f"W6 files must not import subprocess directly:\n"
            + "\n".join(f"  {f}:{l}" for f, l in violations)
        )
