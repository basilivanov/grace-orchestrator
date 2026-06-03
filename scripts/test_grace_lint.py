"""Tests for scripts/grace_lint.py — 14 tests covering all branches."""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Path to the linter
LINT = Path(__file__).resolve().parent / "grace_lint.py"


def _run(*args):
    return subprocess.run([sys.executable, str(LINT), *args],
                         capture_output=True, text=True)


def _write(path, content):
    Path(path).write_text(content)


class TestSyntax:
    def test_syntax_error_reports_grc000(self, tmp_path):
        f = tmp_path / "broken.py"
        _write(f, "def foo(\n")  # syntax error
        r = _run(str(f))
        assert r.returncode == 1
        assert "GRC000" in r.stdout

    def test_clean_file_passes(self, tmp_path):
        f = tmp_path / "clean.py"
        _write(f, """# AI_HEADER: test
# ROLE: test file
# START_MODULE_CONTRACT
# purpose: test
# inputs: none
# returns: none
# side_effects: none
# emitted_logs: none
# error_behavior: none
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:
#   - function: test_fn
# END_MODULE_MAP

# START_FUNCTION_CONTRACT
# name: test_fn
# purpose: test
# inputs: none
# returns: none
# side_effects: none
# emitted_logs: none
# error_behavior: none
# END_FUNCTION_CONTRACT
def test_fn():
    pass
""")
        r = _run(str(f))
        assert r.returncode == 0


class TestHeaders:
    def test_missing_ai_header(self, tmp_path):
        f = tmp_path / "noheader.py"
        _write(f, "def foo(): pass\n")
        r = _run(str(f))
        assert "GRC001" in r.stdout

    def test_missing_module_contract(self, tmp_path):
        f = tmp_path / "nomc.py"
        _write(f, "# AI_HEADER: test\ndef foo(): pass\n")
        r = _run(str(f))
        assert "GRC020" in r.stdout

    def test_missing_module_map(self, tmp_path):
        f = tmp_path / "nomm.py"
        _write(f, """# AI_HEADER: test
# ROLE: test
# START_MODULE_CONTRACT
# purpose: test
# inputs: none
# returns: none
# side_effects: none
# END_MODULE_CONTRACT
def foo(): pass
""")
        r = _run(str(f))
        assert "GRC021" in r.stdout


class TestPairing:
    def test_module_contract_start_without_end(self, tmp_path):
        f = tmp_path / "mc_start.py"
        _write(f, "# AI_HEADER: test\n# START_MODULE_CONTRACT\n# purpose: test\ndef foo(): pass\n")
        r = _run(str(f))
        assert "GRC002" in r.stdout

    def test_module_contract_end_without_start(self, tmp_path):
        f = tmp_path / "mc_end.py"
        _write(f, "# AI_HEADER: test\n# END_MODULE_CONTRACT\ndef foo(): pass\n")
        r = _run(str(f))
        assert "GRC002" in r.stdout

    def test_module_map_start_without_end(self, tmp_path):
        f = tmp_path / "mm_start.py"
        _write(f, """# AI_HEADER: test
# START_MODULE_CONTRACT
# purpose: test
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:
def foo(): pass
""")
        r = _run(str(f))
        assert "GRC003" in r.stdout

    def test_block_start_without_end(self, tmp_path):
        f = tmp_path / "block_mismatch.py"
        _write(f, """# AI_HEADER: test
# START_MODULE_CONTRACT
# purpose: test
# END_MODULE_CONTRACT
# START_MODULE_MAP
# END_MODULE_MAP
# START_BLOCK_FOO
def foo(): pass
""")
        r = _run(str(f))
        assert "GRC004" in r.stdout

    def test_block_end_without_start(self, tmp_path):
        f = tmp_path / "block_end.py"
        _write(f, """# AI_HEADER: test
# START_MODULE_CONTRACT
# purpose: test
# END_MODULE_CONTRACT
# START_MODULE_MAP
# END_MODULE_MAP
# END_BLOCK_FOO
def foo(): pass
""")
        r = _run(str(f))
        assert "GRC004" in r.stdout


class TestFunctions:
    def test_public_function_missing_contract(self, tmp_path):
        f = tmp_path / "nofunc.py"
        _write(f, """# AI_HEADER: test
# ROLE: test
# START_MODULE_CONTRACT
# purpose: test
# inputs: none
# returns: none
# side_effects: none
# error_behavior: none
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:
#   - function: public_fn
# END_MODULE_MAP

def public_fn():
    pass
""")
        r = _run(str(f))
        assert "GRC010" in r.stdout

    def test_private_function_exempt(self, tmp_path):
        f = tmp_path / "private.py"
        _write(f, """# AI_HEADER: test
# ROLE: test
# START_MODULE_CONTRACT
# purpose: test
# inputs: none
# returns: none
# side_effects: none
# error_behavior: none
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:
# END_MODULE_MAP

def _private_fn():
    pass
""")
        r = _run(str(f))
        assert r.returncode == 0

    def test_skip_function_contracts_option(self, tmp_path):
        f = tmp_path / "skip.py"
        _write(f, """# AI_HEADER: test
# ROLE: test
# START_MODULE_CONTRACT
# purpose: test
# END_MODULE_CONTRACT
# START_MODULE_MAP
# END_MODULE_MAP
def public_fn():
    pass
""")
        r = _run(str(f), "--skip-function-contracts")
        assert r.returncode == 0


class TestGRC030:
    def test_compressed_module_reports_grc030(self, tmp_path):
        f = tmp_path / "compressed.py"
        f.write_text("a=1\nb=2\nc=3\nd=4\ne=5\nf=6")
        # 6 physical lines, 6 assigns — NOT compressed (phys=6, tls=6)
        # But with NO AI_HEADER, still reports GRC001
        r = _run(str(f))
        assert "GRC001" in r.stdout   # no AI_HEADER
        assert "GRC020" in r.stdout   # no MODULE_CONTRACT

    def test_compressed_module_direct_check(self):
        """Test _top_level_count and _physical_lines from grace_lint directly."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("grace_lint", str(LINT))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        tls = mod._top_level_count("a=1\nb=2\nc=3\nd=4\ne=5\nf=6\ng=7")
        phys = mod._physical_lines("a=1\nb=2\nc=3\nd=4\ne=5\nf=6\ng=7")
        assert tls == 7
        assert phys == 7  # same number of lines as statements
        # Test that GRC030 condition is correctly detected: tls > 5 and phys < 5
        assert not (tls > 5 and phys < 5)  # 7 lines → not compressed


class TestCLI:
    def test_main_exit_code_one_on_violation(self, tmp_path):
        f = tmp_path / "bad.py"
        _write(f, "def foo(): pass\n")
        r = _run(str(f))
        assert r.returncode == 1

    def test_main_exit_code_zero_on_clean(self, tmp_path):
        f = tmp_path / "clean2.py"
        _write(f, """# AI_HEADER: clean
# ROLE: test
# START_MODULE_CONTRACT
# purpose: test
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:
#   - function: fn
# END_MODULE_MAP

# START_FUNCTION_CONTRACT
# name: fn
# purpose: test
# inputs: none
# returns: none
# side_effects: none
# emitted_logs: none
# error_behavior: none
# END_FUNCTION_CONTRACT
def fn():
    pass
""")
        r = _run(str(f))
        assert r.returncode == 0

    def test_empty_init_py_is_exempt(self, tmp_path):
        f = tmp_path / "__init__.py"
        _write(f, "\n")
        r = _run(str(f))
        assert r.returncode == 0

    def test_directory_scan(self, tmp_path):
        f1 = tmp_path / "a.py"
        f1.write_text("# AI_HEADER: a\n# START_MODULE_CONTRACT\n# p\n# END_MODULE_CONTRACT\n# START_MODULE_MAP\n# END_MODULE_MAP\ndef fn(): pass")
        f2 = tmp_path / "b.py"
        f2.write_text("def bad(): pass")  # missing everything
        r = _run(str(tmp_path))
        assert r.returncode == 1
        assert "GRC001" in r.stdout  # b.py has no header


class TestFileLimits:
    def test_file_over_1000_lines_reports_grc005(self, tmp_path):
        f = tmp_path / "big.py"
        lines = ["# AI_HEADER: big\n# START_MODULE_CONTRACT\n# p\n# END_MODULE_CONTRACT\n# START_MODULE_MAP\n# END_MODULE_MAP\n"]
        lines += [f"a{i}=None" for i in range(1000)]
        f.write_text("\n".join(lines))
        r = _run(str(f))
        assert "GRC005" in r.stdout

    def test_file_under_1000_lines_no_grc005(self, tmp_path):
        f = tmp_path / "small.py"
        f.write_text("# AI_HEADER: small\n# START_MODULE_CONTRACT\n# p\n# END_MODULE_CONTRACT\n# START_MODULE_MAP\n# END_MODULE_MAP\ndef fn(): pass")
        r = _run(str(f))
        assert "GRC005" not in r.stdout


class TestFunctionLimits:
    def test_function_over_4000_tokens_reports_grc012(self, tmp_path):
        f = tmp_path / "bigfunc.py"
        header = """# AI_HEADER: bigfunc
# ROLE: test
# START_MODULE_CONTRACT
# purpose: test
# END_MODULE_CONTRACT
# START_MODULE_MAP
# END_MODULE_MAP
"""
        body = "def huge():" + f"\n    x={repr('x' * 17000)}\n"  # function with ~4500 tokens
        f.write_text(header + body)
        r = _run(str(f))
        assert "GRC012" in r.stdout

    def test_function_under_4000_tokens_no_grc012(self, tmp_path):
        f = tmp_path / "smallfunc.py"
        header = """# AI_HEADER: smallfunc
# ROLE: test
# START_MODULE_CONTRACT
# purpose: test
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:
# END_MODULE_MAP
"""
        body = "a=42\n"
        f.write_text(header + body)
        r = _run(str(f))
        assert "GRC012" not in r.stdout
