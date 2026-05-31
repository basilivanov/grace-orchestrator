# Phase 1: Core Infrastructure - Remaining Tasks

## Task #23: Implement GRACE Canon Checker

**Приоритет:** Высокий
**Время:** 2 дня
**Зависимости:** Task #10

### Описание
Реализовать проверки GRACE Canon (file/function limits, contracts, semantic blocks).

### Что делать

#### 1. Создать GRACE Canon checker

**src/grace_control/core/grace_canon.py:**
```python
"""
GRACE Canon compliance checker.
"""
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel
import ast

class CanonViolation(BaseModel):
    """Canon violation."""
    file: str
    line: Optional[int] = None
    rule: str
    message: str
    severity: str  # error, warning

class CanonResult(BaseModel):
    """Canon check result."""
    passed: bool
    violations: List[CanonViolation]

class GraceCanonChecker:
    """
    Check GRACE Canon compliance.
    
    Rules:
    - File size: max 1000 lines
    - Function size: max 4000 tokens (approx 1000 lines)
    - Contracts required: AI_HEADER, MODULE_CONTRACT, FUNCTION_CONTRACT
    - Semantic blocks: START/END pairs must match
    """
    
    MAX_FILE_LINES = 1000
    MAX_FUNCTION_LINES = 250  # Approx 1000 tokens
    
    def check_file(self, file_path: Path) -> CanonResult:
        """Check single file."""
        violations = []
        
        # Read file
        try:
            content = file_path.read_text()
            lines = content.split('\n')
        except Exception as e:
            return CanonResult(
                passed=False,
                violations=[CanonViolation(
                    file=str(file_path),
                    rule="file_readable",
                    message=f"Cannot read file: {e}",
                    severity="error"
                )]
            )
        
        # Check file size
        if len(lines) > self.MAX_FILE_LINES:
            violations.append(CanonViolation(
                file=str(file_path),
                rule="file_size",
                message=f"File too large: {len(lines)} lines (max {self.MAX_FILE_LINES})",
                severity="error"
            ))
        
        # Check contracts
        violations.extend(self._check_contracts(file_path, content))
        
        # Check function sizes
        violations.extend(self._check_function_sizes(file_path, content))
        
        # Check semantic blocks
        violations.extend(self._check_semantic_blocks(file_path, content))
        
        return CanonResult(
            passed=len(violations) == 0,
            violations=violations
        )
    
    def _check_contracts(self, file_path: Path, content: str) -> List[CanonViolation]:
        """Check for required contracts."""
        violations = []
        
        # Check AI_HEADER
        if "AI_HEADER:" not in content:
            violations.append(CanonViolation(
                file=str(file_path),
                rule="ai_header",
                message="Missing AI_HEADER",
                severity="error"
            ))
        
        # Check MODULE_CONTRACT
        if "START_MODULE_CONTRACT" not in content:
            violations.append(CanonViolation(
                file=str(file_path),
                rule="module_contract",
                message="Missing MODULE_CONTRACT",
                severity="error"
            ))
        
        return violations
    
    def _check_function_sizes(self, file_path: Path, content: str) -> List[CanonViolation]:
        """Check function sizes."""
        violations = []
        
        try:
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    func_lines = node.end_lineno - node.lineno + 1
                    
                    if func_lines > self.MAX_FUNCTION_LINES:
                        violations.append(CanonViolation(
                            file=str(file_path),
                            line=node.lineno,
                            rule="function_size",
                            message=f"Function '{node.name}' too large: {func_lines} lines (max {self.MAX_FUNCTION_LINES})",
                            severity="error"
                        ))
        except SyntaxError:
            pass  # Skip files with syntax errors
        
        return violations
    
    def _check_semantic_blocks(self, file_path: Path, content: str) -> List[CanonViolation]:
        """Check START/END block pairs."""
        violations = []
        lines = content.split('\n')
        
        stack = []
        for i, line in enumerate(lines, 1):
            if "START_BLOCK_" in line:
                block_name = line.split("START_BLOCK_")[1].split()[0]
                stack.append((block_name, i))
            elif "END_BLOCK_" in line:
                block_name = line.split("END_BLOCK_")[1].split()[0]
                
                if not stack:
                    violations.append(CanonViolation(
                        file=str(file_path),
                        line=i,
                        rule="semantic_blocks",
                        message=f"END_BLOCK_{block_name} without matching START",
                        severity="error"
                    ))
                else:
                    start_name, start_line = stack.pop()
                    if start_name != block_name:
                        violations.append(CanonViolation(
                            file=str(file_path),
                            line=i,
                            rule="semantic_blocks",
                            message=f"Mismatched blocks: START_{start_name} (line {start_line}) vs END_{block_name}",
                            severity="error"
                        ))
        
        # Check for unclosed blocks
        for block_name, line in stack:
            violations.append(CanonViolation(
                file=str(file_path),
                line=line,
                rule="semantic_blocks",
                message=f"Unclosed START_BLOCK_{block_name}",
                severity="error"
            ))
        
        return violations
```

#### 2. Интегрировать в acceptance pipeline

**Обновить src/grace_control/core/acceptance_pipeline.py:**
```python
async def _run_canon(self) -> tuple[Trigger, Optional[str]]:
    """Run GRACE Canon checks."""
    logger.info("Starting Canon check", packet_id=self.packet_id)
    
    from grace_control.core.grace_canon import GraceCanonChecker
    
    checker = GraceCanonChecker()
    
    # Get changed files
    changed_files = self._get_changed_files()
    
    all_violations = []
    for file_path in changed_files:
        result = checker.check_file(Path(file_path))
        if not result.passed:
            all_violations.extend(result.violations)
    
    if all_violations:
        reason = f"GRACE Canon violations: {len(all_violations)} issues"
        logger.warning("Canon check failed", violations=all_violations)
        return Trigger.CANON_FAILED, reason
    
    logger.info("Canon check passed")
    return Trigger.CANON_PASSED, None
```

#### 3. Создать тесты

**tests/test_grace_canon.py:**
```python
import pytest
from pathlib import Path
from grace_control.core.grace_canon import GraceCanonChecker

def test_file_too_large(tmp_path):
    checker = GraceCanonChecker()
    
    # Create file with 1001 lines
    file = tmp_path / "large.py"
    file.write_text('\n'.join(['x = 1'] * 1001))
    
    result = checker.check_file(file)
    assert not result.passed
    assert any(v.rule == "file_size" for v in result.violations)

def test_missing_ai_header(tmp_path):
    checker = GraceCanonChecker()
    
    file = tmp_path / "no_header.py"
    file.write_text("def foo(): pass")
    
    result = checker.check_file(file)
    assert not result.passed
    assert any(v.rule == "ai_header" for v in result.violations)

def test_function_too_large(tmp_path):
    checker = GraceCanonChecker()
    
    # Create function with 300 lines
    code = "def large_func():\n" + '\n'.join(['    x = 1'] * 300)
    file = tmp_path / "large_func.py"
    file.write_text(code)
    
    result = checker.check_file(file)
    assert not result.passed
    assert any(v.rule == "function_size" for v in result.violations)

def test_mismatched_blocks(tmp_path):
    checker = GraceCanonChecker()
    
    code = """
#START_BLOCK_A
x = 1
#END_BLOCK_B
"""
    file = tmp_path / "blocks.py"
    file.write_text(code)
    
    result = checker.check_file(file)
    assert not result.passed
    assert any(v.rule == "semantic_blocks" for v in result.violations)
```

### Критерии готовности
- [ ] GraceCanonChecker реализован
- [ ] File size check работает
- [ ] Function size check работает
- [ ] Contracts check работает
- [ ] Semantic blocks check работает
- [ ] Интегрирован в acceptance pipeline
- [ ] Тесты проходят

---

## Task #24: Implement Acceptance Policy Abstraction

**Приоритет:** Средний
**Время:** 1 день
**Зависимости:** Task #11

### Описание
Создать абстракцию для acceptance policies.

### Что делать

#### 1. Создать базовый интерфейс

**src/grace_control/core/policies/base.py:**
```python
"""
Acceptance policy abstraction.
"""
from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel

class AcceptanceDecision(BaseModel):
    """Acceptance decision."""
    accepted: bool
    reason: Optional[str] = None
    profile: str  # FAST, NORMAL, STRICT

class AcceptancePolicyInterface(ABC):
    """Base interface for acceptance policies."""
    
    @abstractmethod
    async def decide(
        self,
        packet_id: str,
        test_results: dict,
        canon_result: dict,
        reviewer_result: Optional[dict] = None
    ) -> AcceptanceDecision:
        """
        Make acceptance decision.
        
        Args:
            packet_id: Packet ID
            test_results: Test results (T0, T1, T2)
            canon_result: GRACE Canon check result
            reviewer_result: Reviewer result (if STRICT)
        
        Returns:
            AcceptanceDecision
        """
        pass
```

#### 2. Реализовать simple policy

**src/grace_control/core/policies/simple_policy.py:**
```python
"""
Simple acceptance policy.
"""
from .base import AcceptancePolicyInterface, AcceptanceDecision
from typing import Optional

class SimplePolicy(AcceptancePolicyInterface):
    """
    Simple policy: all tests passed → accept.
    
    Rules:
    - T0 must pass (always)
    - T1 must pass (always)
    - T2 must pass (if NORMAL/STRICT)
    - Canon must pass (always)
    - Reviewer must accept (if STRICT)
    """
    
    async def decide(
        self,
        packet_id: str,
        test_results: dict,
        canon_result: dict,
        reviewer_result: Optional[dict] = None
    ) -> AcceptanceDecision:
        
        profile = test_results.get("profile", "NORMAL")
        
        # Check T0
        if not test_results.get("T0", {}).get("passed"):
            return AcceptanceDecision(
                accepted=False,
                reason="T0 (lint) failed",
                profile=profile
            )
        
        # Check T1
        if not test_results.get("T1", {}).get("passed"):
            return AcceptanceDecision(
                accepted=False,
                reason="T1 (touched tests) failed",
                profile=profile
            )
        
        # Check T2 (if NORMAL/STRICT)
        if profile in ["NORMAL", "STRICT"]:
            if not test_results.get("T2", {}).get("passed"):
                return AcceptanceDecision(
                    accepted=False,
                    reason="T2 (full tests) failed",
                    profile=profile
                )
        
        # Check Canon
        if not canon_result.get("passed"):
            return AcceptanceDecision(
                accepted=False,
                reason="GRACE Canon violations",
                profile=profile
            )
        
        # Check Reviewer (if STRICT)
        if profile == "STRICT":
            if not reviewer_result or not reviewer_result.get("accepted"):
                return AcceptanceDecision(
                    accepted=False,
                    reason="Reviewer rejected",
                    profile=profile
                )
        
        # All passed
        return AcceptanceDecision(
            accepted=True,
            reason="All checks passed",
            profile=profile
        )
```

#### 3. Создать тесты

**tests/test_acceptance_policy.py:**
```python
import pytest
from grace_control.core.policies import SimplePolicy

@pytest.mark.asyncio
async def test_all_passed_fast():
    policy = SimplePolicy()
    
    decision = await policy.decide(
        packet_id="PKT-001",
        test_results={
            "profile": "FAST",
            "T0": {"passed": True},
            "T1": {"passed": True},
        },
        canon_result={"passed": True}
    )
    
    assert decision.accepted is True

@pytest.mark.asyncio
async def test_t0_failed():
    policy = SimplePolicy()
    
    decision = await policy.decide(
        packet_id="PKT-001",
        test_results={
            "profile": "FAST",
            "T0": {"passed": False},
            "T1": {"passed": True},
        },
        canon_result={"passed": True}
    )
    
    assert decision.accepted is False
    assert "T0" in decision.reason

@pytest.mark.asyncio
async def test_strict_requires_reviewer():
    policy = SimplePolicy()
    
    decision = await policy.decide(
        packet_id="PKT-001",
        test_results={
            "profile": "STRICT",
            "T0": {"passed": True},
            "T1": {"passed": True},
            "T2": {"passed": True},
        },
        canon_result={"passed": True},
        reviewer_result={"accepted": False}
    )
    
    assert decision.accepted is False
    assert "Reviewer" in decision.reason
```

### Критерии готовности
- [ ] AcceptancePolicyInterface определён
- [ ] SimplePolicy реализован
- [ ] Profile-based logic работает
- [ ] Тесты проходят

---

## Task #31: Implement Structured Logging Infrastructure

**Приоритет:** Высокий
**Время:** 1 день
**Зависимости:** Task #10

### Описание
Реализовать structured logging с component-level config и trace ID propagation.

### Что делать

#### 1. Создать structured logger

**src/grace_control/logging.py:**
```python
"""
Structured logging infrastructure.
"""
import logging
import json
from datetime import datetime
from contextvars import ContextVar
from typing import Optional
from pathlib import Path

# Context var для trace_id
trace_id_var: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)

class JsonFormatter(logging.Formatter):
    """JSON formatter for structured logs."""
    
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname.lower(),
            "component": getattr(record, "component", None),
            "trace_id": getattr(record, "trace_id", None),
            "message": record.getMessage(),
        }
        
        # Add context
        if hasattr(record, "context"):
            log_data.update(record.context)
        
        # Add duration if present
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms
        
        return json.dumps(log_data)

class GraceLogger:
    """
    Structured logger with component-level config.
    
    Usage:
        logger = GraceLogger("worker", config)
        logger.info("Packet claimed", packet_id="PKT-001")
    """
    
    def __init__(self, component: str, config: Optional[dict] = None):
        self.component = component
        self.config = config or {}
        self.logger = logging.getLogger(f"grace.{component}")
        
        # Setup handler
        handler = logging.FileHandler(f"logs/{component}.jsonl")
        handler.setFormatter(JsonFormatter())
        self.logger.addHandler(handler)
        
        # Set level
        level = self.config.get("components", {}).get(component, "INFO")
        self.logger.setLevel(getattr(logging, level))
    
    def _log(self, level: str, message: str, **context):
        """Internal log method."""
        trace_id = trace_id_var.get()
        
        extra = {
            "component": self.component,
            "trace_id": trace_id,
            "context": context
        }
        
        getattr(self.logger, level)(message, extra=extra)
    
    def info(self, message: str, **context):
        self._log("info", message, **context)
    
    def debug(self, message: str, **context):
        self._log("debug", message, **context)
    
    def warning(self, message: str, **context):
        self._log("warning", message, **context)
    
    def error(self, message: str, **context):
        self._log("error", message, **context)

def set_trace_id(trace_id: str):
    """Set trace ID for current context."""
    trace_id_var.set(trace_id)

def get_trace_id() -> Optional[str]:
    """Get current trace ID."""
    return trace_id_var.get()
```

#### 2. Создать context manager

**Добавить в src/grace_control/logging.py:**
```python
from contextlib import contextmanager

@contextmanager
def trace_context(trace_id: str):
    """
    Set trace_id for all logs in this context.
    
    Usage:
        with trace_context(packet_id):
            logger.info("Starting execution")  # trace_id автоматически
    """
    token = trace_id_var.set(trace_id)
    try:
        yield
    finally:
        trace_id_var.reset(token)
```

#### 3. Создать тесты

**tests/test_logging.py:**
```python
import pytest
from grace_control.logging import GraceLogger, trace_context, get_trace_id

def test_logger_basic():
    logger = GraceLogger("test")
    logger.info("Test message", key="value")
    # Check log file created

def test_trace_context():
    with trace_context("TRACE-001"):
        assert get_trace_id() == "TRACE-001"
    
    assert get_trace_id() is None

def test_component_level():
    config = {
        "components": {
            "test": "DEBUG"
        }
    }
    logger = GraceLogger("test", config)
    assert logger.logger.level == logging.DEBUG
```

### Критерии готовности
- [ ] GraceLogger реализован
- [ ] JsonFormatter работает
- [ ] Trace ID propagation работает
- [ ] Component-level config работает
- [ ] trace_context работает
- [ ] Тесты проходят

---

Продолжить с Task #32 (Test Infrastructure)?
