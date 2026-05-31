# Task #32: Implement Test Execution Infrastructure

**Приоритет:** Высокий
**Время:** 2 дня
**Зависимости:** Task #10, #31

## Описание
Реализовать test execution infrastructure с touched scope resolver и parallel execution.

## Что делать

### 1. Создать test tier definitions

**src/grace_control/core/testing/tiers.py:**
```python
"""
Test tier definitions.
"""
from pydantic import BaseModel
from typing import List, Optional

class TestTier(BaseModel):
    """Test tier configuration."""
    name: str
    tier: str  # T0, T1, T2, T3
    timeout_seconds: int
    commands: List[str]
    required_for: List[str] = ["FAST", "NORMAL", "STRICT"]
    fail_fast: bool = True

# Default test tiers
DEFAULT_TIERS = [
    TestTier(
        name="Mechanical checks",
        tier="T0",
        timeout_seconds=60,
        commands=[
            "ruff check .",
            "ruff format --check .",
            "mypy src",
        ],
        required_for=["FAST", "NORMAL", "STRICT"],
        fail_fast=True
    ),
    TestTier(
        name="Touched scope tests",
        tier="T1",
        timeout_seconds=300,
        commands=[],  # Resolved dynamically
        required_for=["FAST", "NORMAL", "STRICT"],
        fail_fast=True
    ),
    TestTier(
        name="Full unit tests",
        tier="T2",
        timeout_seconds=600,
        commands=["pytest tests/unit -v --cov=src"],
        required_for=["NORMAL", "STRICT"],
        fail_fast=True
    ),
    TestTier(
        name="Integration tests",
        tier="T3",
        timeout_seconds=1200,
        commands=["pytest tests/integration -v"],
        required_for=["STRICT"],
        fail_fast=False
    ),
]
```

### 2. Создать touched scope resolver

**src/grace_control/core/testing/touched_scope.py:**
```python
"""
Touched scope test resolver.
"""
from pathlib import Path
from typing import List
import ast

class TouchedScopeResolver:
    """
    Resolve which tests to run based on changed files.
    
    Strategy:
    1. Direct mapping: src/auth/jwt.py → tests/auth/test_jwt.py
    2. Import analysis: find tests importing changed modules
    3. Fallback: run fast tests if no touched tests found
    """
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
    
    def resolve(self, changed_files: List[str]) -> List[str]:
        """
        Resolve touched tests.
        
        Args:
            changed_files: List of changed file paths
        
        Returns:
            List of test files to run
        """
        tests = set()
        
        for file in changed_files:
            # Direct mapping
            direct_test = self._find_direct_test(file)
            if direct_test:
                tests.add(direct_test)
            
            # Import analysis
            importing_tests = self._find_importing_tests(file)
            tests.update(importing_tests)
        
        # Fallback if no tests found
        if not tests:
            return self._get_fallback_tests()
        
        return list(tests)
    
    def _find_direct_test(self, file_path: str) -> Optional[str]:
        """Find direct test file."""
        if not file_path.startswith("src/"):
            return None
        
        # src/auth/jwt.py → tests/auth/test_jwt.py
        test_path = file_path.replace("src/", "tests/", 1)
        test_path = test_path.replace(".py", "_test.py")
        
        full_path = self.project_root / test_path
        if full_path.exists():
            return test_path
        
        # Try test_*.py pattern
        test_path = file_path.replace("src/", "tests/", 1)
        parts = test_path.rsplit("/", 1)
        if len(parts) == 2:
            test_path = f"{parts[0]}/test_{parts[1]}"
            full_path = self.project_root / test_path
            if full_path.exists():
                return test_path
        
        return None
    
    def _find_importing_tests(self, file_path: str) -> List[str]:
        """Find tests that import this module."""
        if not file_path.startswith("src/"):
            return []
        
        # Convert to module name: src/auth/jwt.py → auth.jwt
        module = file_path.replace("src/", "").replace(".py", "").replace("/", ".")
        
        # Search all test files
        tests_dir = self.project_root / "tests"
        if not tests_dir.exists():
            return []
        
        importing_tests = []
        for test_file in tests_dir.rglob("test_*.py"):
            if self._imports_module(test_file, module):
                rel_path = test_file.relative_to(self.project_root)
                importing_tests.append(str(rel_path))
        
        return importing_tests
    
    def _imports_module(self, test_file: Path, module: str) -> bool:
        """Check if test file imports module."""
        try:
            content = test_file.read_text()
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == module or alias.name.startswith(f"{module}."):
                            return True
                
                elif isinstance(node, ast.ImportFrom):
                    if node.module == module or (node.module and node.module.startswith(f"{module}.")):
                        return True
            
            return False
        except Exception:
            return False
    
    def _get_fallback_tests(self) -> List[str]:
        """Get fallback tests (fast tests)."""
        # Run tests marked as 'not slow'
        return ["pytest tests -k 'not slow' -x"]
```

### 3. Создать test executor

**src/grace_control/core/testing/executor.py:**
```python
"""
Test execution with parallel support.
"""
import asyncio
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

class TestResult(BaseModel):
    """Test result."""
    tier: str
    status: str  # passed, failed
    duration_ms: int
    command: str
    exit_code: int
    stdout: str
    stderr: str
    tests: Optional[List[dict]] = None

class TestExecutor:
    """
    Execute tests with parallel support.
    
    Uses pytest-xdist for parallelization.
    """
    
    def __init__(self, workdir: Path, parallel: bool = True, max_workers: int = 4):
        self.workdir = workdir
        self.parallel = parallel
        self.max_workers = max_workers
    
    async def execute_tier(
        self,
        tier: str,
        commands: List[str],
        timeout_seconds: int
    ) -> TestResult:
        """Execute test tier."""
        
        # Add parallel flags if enabled
        if self.parallel and "pytest" in commands[0]:
            commands = [f"{cmd} -n {self.max_workers}" for cmd in commands]
        
        # Combine commands
        full_command = " && ".join(commands)
        
        # Execute
        start = datetime.utcnow()
        
        process = await asyncio.create_subprocess_shell(
            full_command,
            cwd=self.workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds
            )
            
            duration_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
            
            return TestResult(
                tier=tier,
                status="passed" if process.returncode == 0 else "failed",
                duration_ms=duration_ms,
                command=full_command,
                exit_code=process.returncode,
                stdout=stdout.decode(),
                stderr=stderr.decode()
            )
        
        except asyncio.TimeoutError:
            process.kill()
            duration_ms = timeout_seconds * 1000
            
            return TestResult(
                tier=tier,
                status="failed",
                duration_ms=duration_ms,
                command=full_command,
                exit_code=-1,
                stdout="",
                stderr="Timeout"
            )
```

### 4. Создать тесты

**tests/test_touched_scope.py:**
```python
import pytest
from pathlib import Path
from grace_control.core.testing.touched_scope import TouchedScopeResolver

def test_direct_mapping(tmp_path):
    # Create structure
    (tmp_path / "src/auth").mkdir(parents=True)
    (tmp_path / "tests/auth").mkdir(parents=True)
    (tmp_path / "src/auth/jwt.py").write_text("def foo(): pass")
    (tmp_path / "tests/auth/test_jwt.py").write_text("def test_foo(): pass")
    
    resolver = TouchedScopeResolver(tmp_path)
    tests = resolver.resolve(["src/auth/jwt.py"])
    
    assert "tests/auth/test_jwt.py" in tests

def test_import_analysis(tmp_path):
    # Create structure
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    
    (tmp_path / "src/utils.py").write_text("def helper(): pass")
    (tmp_path / "tests/test_api.py").write_text("from src.utils import helper\ndef test_api(): pass")
    
    resolver = TouchedScopeResolver(tmp_path)
    tests = resolver.resolve(["src/utils.py"])
    
    assert "tests/test_api.py" in tests

def test_fallback(tmp_path):
    resolver = TouchedScopeResolver(tmp_path)
    tests = resolver.resolve(["src/new_file.py"])
    
    # Should return fallback
    assert len(tests) > 0
    assert "not slow" in tests[0]
```

### Критерии готовности
- [ ] Test tier definitions созданы
- [ ] TouchedScopeResolver реализован
- [ ] TestExecutor реализован
- [ ] Parallel execution работает (pytest-xdist)
- [ ] Fallback tests работают
- [ ] Тесты проходят

---

## Phase 1 Complete Checklist

### Все задачи Phase 1
- [ ] Task #10: DB Schema ✅
- [ ] Task #11: State Machine ✅
- [ ] Task #22: Executor Abstraction ✅
- [ ] Task #13: Complexity Router ✅
- [ ] Task #23: GRACE Canon Checker ✅
- [ ] Task #24: Acceptance Policy ✅
- [ ] Task #31: Logging Infrastructure ✅
- [ ] Task #32: Test Infrastructure ✅

### Deliverables
- ✅ SQLite DB с 8 таблицами
- ✅ State machine с ступенчатой приёмкой
- ✅ Executor abstraction (API + local)
- ✅ Complexity router
- ✅ GRACE Canon checker
- ✅ Acceptance policy
- ✅ Structured logging
- ✅ Test infrastructure

### Готовность к Phase 2
После завершения Phase 1 можно начинать Phase 2: API & Worker
