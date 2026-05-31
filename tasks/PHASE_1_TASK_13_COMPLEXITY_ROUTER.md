# Task #13: Implement Complexity Router

**Приоритет:** Средний
**Время:** 1 день
**Зависимости:** Task #10

## Описание
Создать complexity router для определения acceptance profile на основе изменённых файлов.

## Что делать

### 1. Создать базовый интерфейс

**src/grace_control/core/routers/base.py:**
```python
"""
Complexity router abstraction.
"""
from abc import ABC, abstractmethod
from typing import List
from pydantic import BaseModel

class ChangeSet(BaseModel):
    """Changed files information."""
    files: List[str]
    additions: int
    deletions: int
    diff_size: int

class ComplexityRouterInterface(ABC):
    """Base interface for complexity routers."""
    
    @abstractmethod
    def determine_profile(self, changeset: ChangeSet) -> str:
        """
        Determine acceptance profile based on changes.
        
        Args:
            changeset: Changed files and stats
        
        Returns:
            Profile: FAST, NORMAL, or STRICT
        """
        pass
```

### 2. Реализовать heuristic router

**src/grace_control/core/routers/heuristic_router.py:**
```python
"""
Heuristic-based complexity router.
"""
from .base import ComplexityRouterInterface, ChangeSet
from pathlib import Path

class HeuristicRouter(ComplexityRouterInterface):
    """
    Determine profile based on file patterns and diff size.
    
    Rules:
    - Critical files (auth, security, db) → STRICT
    - Large changes (>500 lines) → STRICT
    - Medium changes (100-500 lines) → NORMAL
    - Small changes (<100 lines) → FAST
    """
    
    CRITICAL_PATTERNS = [
        "auth",
        "security",
        "db/schema",
        "migrations",
        "payment",
        "billing",
    ]
    
    def determine_profile(self, changeset: ChangeSet) -> str:
        # Check for critical files
        for file in changeset.files:
            if self._is_critical(file):
                return "STRICT"
        
        # Check diff size
        total_changes = changeset.additions + changeset.deletions
        
        if total_changes > 500:
            return "STRICT"
        elif total_changes > 100:
            return "NORMAL"
        else:
            return "FAST"
    
    def _is_critical(self, file_path: str) -> bool:
        """Check if file is critical."""
        file_lower = file_path.lower()
        return any(pattern in file_lower for pattern in self.CRITICAL_PATTERNS)
```

### 3. Создать тесты

**tests/test_complexity_router.py:**
```python
import pytest
from grace_control.core.routers import HeuristicRouter, ChangeSet

def test_critical_file_strict():
    router = HeuristicRouter()
    
    changeset = ChangeSet(
        files=["src/auth/jwt.py"],
        additions=10,
        deletions=5,
        diff_size=15
    )
    
    profile = router.determine_profile(changeset)
    assert profile == "STRICT"

def test_large_changes_strict():
    router = HeuristicRouter()
    
    changeset = ChangeSet(
        files=["src/utils.py"],
        additions=600,
        deletions=100,
        diff_size=700
    )
    
    profile = router.determine_profile(changeset)
    assert profile == "STRICT"

def test_medium_changes_normal():
    router = HeuristicRouter()
    
    changeset = ChangeSet(
        files=["src/utils.py"],
        additions=150,
        deletions=50,
        diff_size=200
    )
    
    profile = router.determine_profile(changeset)
    assert profile == "NORMAL"

def test_small_changes_fast():
    router = HeuristicRouter()
    
    changeset = ChangeSet(
        files=["src/utils.py"],
        additions=50,
        deletions=20,
        diff_size=70
    )
    
    profile = router.determine_profile(changeset)
    assert profile == "FAST"
```

## Критерии готовности
- [ ] ComplexityRouterInterface определён
- [ ] HeuristicRouter реализован
- [ ] Critical files detection работает
- [ ] Diff size thresholds работают
- [ ] Тесты проходят
